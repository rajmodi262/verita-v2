"""Alert queue and analyst dispositions (M3.05–M3.07)."""

from __future__ import annotations

import base64
import json
import threading
import time
from dataclasses import astuple, dataclass
from datetime import date
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from verita.core.errors import AppError
from verita.db.detect_models import (
    DISMISS_REASONS,
    ESCALATE_REASONS,
    Alert,
    AlertStatus,
    Disposition,
    DispositionAction,
    ModelVersion,
)
from verita.db.models import User
from verita.repositories.identity import AuditRepository

MAX_PAGE = 200


@dataclass(frozen=True)
class AlertFilters:
    alert_date: date | None = None
    status: str | None = None
    typology: str | None = None
    min_score: float | None = None
    alert_ids: frozenset[int] | None = None


def champion(db: Session) -> ModelVersion:
    version = db.scalar(
        select(ModelVersion).where(ModelVersion.is_champion).order_by(ModelVersion.id.desc())
    )
    if version is None:
        raise AppError(
            503,
            "no-model",
            "No detector has been deployed yet",
            detail="Run `verita detect alerts` to load alerts.",
        )
    return version


def _encode_cursor(score: float, alert_id: int) -> str:
    raw = json.dumps([score, alert_id]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[float, int]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        score, alert_id = json.loads(base64.urlsafe_b64decode(padded))
        return float(score), int(alert_id)
    except (ValueError, TypeError) as exc:
        raise AppError(400, "bad-cursor", "Invalid pagination cursor") from exc


def _filtered(version_id: int, filters: AlertFilters) -> Any:
    clauses = [Alert.model_version_id == version_id]
    if filters.alert_date is not None:
        clauses.append(Alert.alert_date == filters.alert_date)
    if filters.status is not None:
        clauses.append(Alert.status == filters.status)
    if filters.typology is not None:
        clauses.append(Alert.typology_pred == filters.typology)
    if filters.min_score is not None:
        clauses.append(Alert.score >= filters.min_score)
    if filters.alert_ids is not None:
        clauses.append(Alert.id.in_(filters.alert_ids))
    return and_(*clauses)


COUNT_TTL_SECONDS = 5.0
_counts: dict[tuple[Any, ...], tuple[float, int]] = {}
_counts_lock = threading.Lock()


def _count(db: Session, version_id: int, filters: AlertFilters, where: Any) -> int:
    """Queue size for these filters, cached for a few seconds.

    COUNT(*) over ~200k alerts was the most expensive part of every queue request; the total is
    a "how many" hint next to a keyset-paged list, so being up to COUNT_TTL_SECONDS stale is
    acceptable. Dispositions clear the cache immediately.
    """
    key = (id(db.get_bind()), version_id, *astuple(filters))  # one cache per database
    now = time.monotonic()
    with _counts_lock:
        hit = _counts.get(key)
        if hit is not None and now - hit[0] < COUNT_TTL_SECONDS:
            return hit[1]
    total = int(db.scalar(select(func.count()).select_from(Alert).where(where)) or 0)
    with _counts_lock:
        _counts[key] = (now, total)
    return total


def clear_counts() -> None:
    with _counts_lock:
        _counts.clear()


def list_alerts(
    db: Session, filters: AlertFilters, cursor: str | None, limit: int
) -> dict[str, Any]:
    version = champion(db)
    limit = max(1, min(limit, MAX_PAGE))
    where = _filtered(version.id, filters)
    stmt = select(Alert).where(where)
    if cursor:
        score, alert_id = _decode_cursor(cursor)
        stmt = stmt.where(or_(Alert.score < score, and_(Alert.score == score, Alert.id > alert_id)))
    rows = list(db.scalars(stmt.order_by(Alert.score.desc(), Alert.id).limit(limit + 1)))
    total = _count(db, version.id, filters, where)
    next_cursor = (
        _encode_cursor(rows[limit - 1].score, rows[limit - 1].id) if len(rows) > limit else None
    )
    return {
        "items": [alert_summary(a) for a in rows[:limit]],
        "next_cursor": next_cursor,
        "total": int(total),
        "threshold": version.threshold,
    }


def queue_meta(db: Session) -> dict[str, Any]:
    version = champion(db)
    by_day = db.execute(
        select(Alert.alert_date, func.count())
        .where(Alert.model_version_id == version.id)
        .group_by(Alert.alert_date)
        .order_by(Alert.alert_date)
    ).all()
    by_status = dict(
        db.execute(
            select(Alert.status, func.count())
            .where(Alert.model_version_id == version.id)
            .group_by(Alert.status)
        ).all()
    )
    typologies = sorted(
        t
        for (t,) in db.execute(
            select(Alert.typology_pred).where(Alert.model_version_id == version.id).distinct()
        )
    )
    return {
        "model": {
            "id": version.id,
            "name": version.name,
            "dataset": version.dataset,
            "threshold": version.threshold,
            "alert_floor": version.metrics.get("alert_floor"),
        },
        "days": [{"date": d.isoformat(), "alerts": int(n)} for d, n in by_day],
        "by_status": {k: int(v) for k, v in by_status.items()},
        "typologies": typologies,
        "dismiss_reasons": DISMISS_REASONS,
        "escalate_reasons": ESCALATE_REASONS,
    }


def alert_summary(a: Alert) -> dict[str, Any]:
    return {
        "id": a.id,
        "account_id": a.account_id,
        "alert_date": a.alert_date.isoformat(),
        "score": round(a.score, 6),
        "score_top3_mean": round(a.score_top3_mean, 6),
        "calibrated_prob": a.calibrated_prob,
        "typology_pred": a.typology_pred,
        "typology_conf": round(a.typology_conf, 4),
        "top_txn_id": a.top_txn_id,
        "top_amount": round(a.top_amount, 2),
        "top_currency": a.top_currency,
        "n_transactions": a.n_transactions,
        "n_flagged": a.n_flagged,
        "status": a.status,
    }


def get_alert(db: Session, alert_id: int) -> Alert:
    alert = db.scalar(
        select(Alert).options(selectinload(Alert.reasons)).where(Alert.id == alert_id)
    )
    if alert is None:
        raise AppError(404, "alert-not-found", "Alert not found")
    return alert


def alert_detail(db: Session, alert_id: int) -> dict[str, Any]:
    alert = get_alert(db, alert_id)
    history = db.scalars(
        select(Disposition).where(Disposition.alert_id == alert_id).order_by(Disposition.id)
    ).all()
    return {
        **alert_summary(alert),
        "reasons": [
            {
                "rank": r.rank,
                "feature": r.feature,
                "value": r.value,
                "shap": round(r.shap, 6),
                "text": r.text,
                "evidence_id": f"EV-REASON-{alert.id}-{r.rank}",
            }
            for r in alert.reasons
        ],
        "dispositions": [
            {
                "id": d.id,
                "action": d.action,
                "reason_code": d.reason_code,
                "note": d.note,
                "user_id": d.user_id,
                "created_at": d.created_at.isoformat(),
            }
            for d in history
        ],
    }


_TRANSITIONS = {
    DispositionAction.ESCALATE: ({AlertStatus.OPEN}, AlertStatus.ESCALATED, ESCALATE_REASONS),
    DispositionAction.DISMISS: ({AlertStatus.OPEN}, AlertStatus.DISMISSED, DISMISS_REASONS),
    DispositionAction.REOPEN: (
        {AlertStatus.DISMISSED, AlertStatus.ESCALATED},
        AlertStatus.OPEN,
        {
            "reopen_error": "Disposition made in error",
            "new_information": "New information received",
        },
    ),
}


def dispose(
    db: Session,
    user: User,
    alert_id: int,
    action: DispositionAction,
    reason_code: str,
    note: str,
    ip: str | None,
) -> dict[str, Any]:
    alert = get_alert(db, alert_id)
    allowed_from, target, reasons = _TRANSITIONS[action]
    if AlertStatus(alert.status) not in allowed_from:
        raise AppError(
            409, "invalid-transition", f"Cannot {action.value} an alert that is {alert.status}"
        )
    if reason_code not in reasons:
        raise AppError(422, "invalid-reason", f"Reason must be one of: {', '.join(reasons)}")
    alert.status = target.value
    db.add(
        Disposition(
            alert_id=alert.id,
            user_id=user.id,
            action=action.value,
            reason_code=reason_code,
            note=note.strip(),
        )
    )
    AuditRepository(db).record(
        f"alert.{action.value}",
        actor_id=user.id,
        target=f"alert:{alert.id}",
        ip=ip,
        detail={"reason": reason_code},
    )
    db.flush()
    clear_counts()
    return alert_detail(db, alert.id)
