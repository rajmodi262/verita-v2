"""Model governance (model risk management): validate, approve, promote; separation of duties.

A detector reaches the live queue only one of two ways:

* **Reviewed:** the pipeline proposes a candidate; ``validate`` evaluates the policy gates
  (``configs/model_policy.yaml``) and stores the report and its SHA-256; a **validator**
  approves it (only if every gate passed); a different person, the **MLRO**, promotes it, which
  retires the previous champion. The database refuses a champion without two distinct reviewers
  (``ck_model_versions_champion_reviewed``).
* **Bypassed, visibly:** development pipelines and the synthetic demo pack put a model into
  service with a recorded ``bypass_reason``, which every API view of the model returns. Never in
  production by the pipeline: there, new models stay candidates and score in shadow.

Every transition is written to the audit log.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from verita.core.errors import AppError
from verita.db.base import utcnow
from verita.db.detect_models import ModelStatus, ModelVersion
from verita.db.models import Role, User
from verita.ml.validation import (
    ValidationError,
    build_report,
    load_policy,
    report_sha256,
)
from verita.pipeline.config import Dataset
from verita.repositories.identity import AuditRepository
from verita.services import alerts as alert_service

DEV_PIPELINE = "Development pipeline: put into service without model-risk review (non-production)."
DEMO_PACK = "Synthetic demo pack: put into service without model-risk review in this deployment."


def _get(db: Session, version_id: int) -> ModelVersion:
    version = db.get(ModelVersion, version_id)
    if version is None:
        raise AppError(404, "not-found", "Model version not found")
    return version


def _require(user: User, role: Role, action: str) -> None:
    if user.role != role.value:
        raise AppError(403, "forbidden", f"Only the {role.value} role may {action} a model")


def _audit(
    db: Session, action: str, version: ModelVersion, actor: int | None, **detail: Any
) -> None:
    AuditRepository(db).record(action, actor, f"model:{version.id}", None, detail)


def _governance(version: ModelVersion) -> str:
    """``bypassed`` (in service without review), ``reviewed`` (a validator approved it) or
    ``not reviewed``."""
    if version.bypass_reason:
        return "bypassed"
    return "reviewed" if version.approved_by_id is not None else "not reviewed"


def view(version: ModelVersion) -> dict[str, Any]:
    validation = version.validation or None
    return {
        "id": version.id,
        "name": version.name,
        "dataset": version.dataset,
        "status": version.status,
        "is_champion": version.is_champion,
        "champion_sha256": version.champion_sha256,
        "git_revision": version.git_revision,
        "threshold": version.threshold,
        "created_at": version.created_at,
        "proposed_by": version.proposed_by,
        "validation": None
        if validation is None
        else {
            "passed": bool(validation.get("passed")),
            "sha256": version.validation_sha256,
            "policy_version": validation.get("policy_version"),
            "failed_gates": [g["gate"] for g in validation.get("gates", []) if not g["passed"]],
        },
        "approved_by_id": version.approved_by_id,
        "approved_at": version.approved_at,
        "promoted_by_id": version.promoted_by_id,
        "promoted_at": version.promoted_at,
        "decision_note": version.decision_note,
        "governance": _governance(version),
        "bypass_reason": version.bypass_reason,
    }


def list_models(db: Session) -> list[dict[str, Any]]:
    return [view(v) for v in db.scalars(select(ModelVersion).order_by(ModelVersion.id.desc()))]


def get_model(db: Session, version_id: int) -> ModelVersion:
    return _get(db, version_id)


def validate(
    db: Session, dataset: Dataset, version_id: int, actor: int | None = None
) -> ModelVersion:
    """Evaluate the policy gates for a candidate and store the report on the version."""
    version = _get(db, version_id)
    if version.status not in (ModelStatus.CANDIDATE.value, ModelStatus.CHAMPION.value):
        raise AppError(409, "not-validatable", f"A {version.status} model cannot be re-validated")
    if version.dataset != dataset.name:
        raise AppError(409, "wrong-dataset", f"Model {version.id} belongs to {version.dataset}")
    try:
        report = build_report(dataset, version.champion_sha256, load_policy())
    except ValidationError as exc:
        raise AppError(409, "not-validatable", "The model cannot be validated", str(exc)) from exc
    version.validation = report
    version.validation_sha256 = report_sha256(report)
    db.flush()
    _audit(
        db,
        "model.validated",
        version,
        actor,
        passed=report["passed"],
        sha256=version.validation_sha256,
        failed=[g["gate"] for g in report["gates"] if not g["passed"]],
    )
    return version


def approve(db: Session, user: User, version_id: int, note: str | None) -> ModelVersion:
    _require(user, Role.VALIDATOR, "approve")
    version = _get(db, version_id)
    if version.status != ModelStatus.CANDIDATE.value:
        raise AppError(
            409, "not-candidate", f"Only a candidate can be approved (this is {version.status})"
        )
    report = version.validation
    if not report:
        raise AppError(409, "not-validated", "Validate the model before approving it")
    if not report.get("passed"):
        failed = [g["gate"] for g in report.get("gates", []) if not g["passed"]]
        raise AppError(
            409,
            "gates-failed",
            "The model failed policy gates and cannot be approved",
            "Failed: " + ", ".join(failed),
        )
    version.status = ModelStatus.APPROVED.value
    version.approved_by_id = user.id
    version.approved_at = utcnow()
    version.decision_note = note
    db.flush()
    _audit(db, "model.approved", version, user.id, validation_sha256=version.validation_sha256)
    return version


def reject(db: Session, user: User, version_id: int, note: str) -> ModelVersion:
    _require(user, Role.VALIDATOR, "reject")
    version = _get(db, version_id)
    if version.status not in (ModelStatus.CANDIDATE.value, ModelStatus.APPROVED.value):
        raise AppError(409, "not-rejectable", f"A {version.status} model cannot be rejected")
    version.status = ModelStatus.REJECTED.value
    version.decision_note = note
    db.flush()
    _audit(db, "model.rejected", version, user.id, note=note)
    return version


def _make_champion(db: Session, version: ModelVersion) -> int | None:
    """Retire the dataset's current champion and seat VERSION; returns the retired id."""
    previous = db.scalar(
        select(ModelVersion).where(
            ModelVersion.dataset == version.dataset,
            ModelVersion.is_champion,
            ModelVersion.id != version.id,
        )
    )
    db.execute(
        update(ModelVersion)
        .where(
            ModelVersion.dataset == version.dataset,
            ModelVersion.is_champion,
            ModelVersion.id != version.id,
        )
        .values(is_champion=False, status=ModelStatus.RETIRED.value)
    )
    version.status = ModelStatus.CHAMPION.value
    version.is_champion = True
    db.flush()
    alert_service.clear_counts()
    return previous.id if previous else None


def promote(db: Session, user: User, version_id: int, note: str | None) -> ModelVersion:
    _require(user, Role.MLRO, "promote")
    version = _get(db, version_id)
    if version.status != ModelStatus.APPROVED.value:
        raise AppError(
            409,
            "not-approved",
            f"Only an approved model can be promoted (this is {version.status})",
        )
    if version.approved_by_id == user.id:
        raise AppError(
            409,
            "separation-of-duties",
            "The person who approved a model cannot also put it into service",
        )
    version.promoted_by_id = user.id
    version.promoted_at = utcnow()
    if note:
        version.decision_note = note
    retired = _make_champion(db, version)
    _audit(db, "model.promoted", version, user.id, retired=retired)
    return version


def bypass(db: Session, version: ModelVersion, reason: str, env: str) -> ModelVersion:
    """Put VERSION into service without review, recording why. Refused in production unless the
    caller is the demo-pack loader (synthetic data, reason ``DEMO_PACK``)."""
    if env == "prod" and reason != DEMO_PACK:
        raise AppError(
            409,
            "review-required",
            "In production a model reaches service only through validation, approval and promotion",
        )
    version.bypass_reason = reason
    retired = _make_champion(db, version)
    _audit(db, "model.governance_bypassed", version, None, reason=reason, retired=retired)
    return version
