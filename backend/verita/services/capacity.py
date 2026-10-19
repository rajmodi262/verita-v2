"""Capacity planning service (M4.19–M4.20): serves Decide artifacts and computes exact plans."""

from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from verita.core.errors import AppError
from verita.db.capacity_models import CapacityPlan
from verita.db.detect_models import Alert
from verita.db.models import User
from verita.ml.conformal import DEFAULT_ALPHA, Thresholds, apply_thresholds
from verita.optimize.planner import OBJECTIVES, Operations, plan_day, prepare
from verita.repositories.identity import AuditRepository
from verita.services.alerts import champion

MODES = ("pooled", "mondrian")
MAX_CACHED_DAYS = 16


class DecideArtifacts:
    """Read-only view over ``artifacts/<dataset>/decide``; files are loaded once."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._cache: dict[str, Any] = {}
        self._frames: dict[str, Any] = {}

    def json(self, name: str) -> Any:
        if name not in self._cache:
            path = self.root / f"{name}.json"
            if not path.exists():
                raise AppError(
                    503,
                    "no-decide",
                    "Capacity analysis has not been run",
                    detail="Run `verita decide run` first.",
                )
            self._cache[name] = json.loads(path.read_text(encoding="utf-8"))
        return self._cache[name]

    def cached(self, key: str) -> Any:
        return self._frames.get(key)

    def store(self, key: str, value: Any) -> None:
        if len(self._frames) >= MAX_CACHED_DAYS:
            self._frames.pop(next(iter(self._frames)))  # oldest first
        self._frames[key] = value

    def isotonic(self) -> Any:
        if "isotonic" not in self._cache:
            path = self.root / "isotonic.joblib"
            if not path.exists():
                raise AppError(503, "no-decide", "Capacity analysis has not been run")
            self._cache["isotonic"] = joblib.load(path)  # our own artifact, written by decide
        return self._cache["isotonic"]

    def thresholds(self, alpha: float) -> Thresholds:
        table = self.json("thresholds")
        key = _alpha_key(alpha, table)
        t = table[key]
        return Thresholds(
            alpha=float(key),
            pooled=-math.inf if t["pooled"] is None else float(t["pooled"]),
            by_group={k: (-math.inf if v is None else float(v)) for k, v in t["by_group"].items()},
            group_sizes=t["group_sizes"],
            fallback_groups=t["fallback_groups"],
        )


def _alpha_key(alpha: float, table: dict[str, Any]) -> str:
    for key in table:
        if math.isclose(float(key), alpha):
            return key
    raise AppError(422, "unsupported-alpha", f"alpha must be one of {sorted(table)}")


def meta(art: DecideArtifacts) -> dict[str, Any]:
    frontier = art.json("frontier")
    days = sorted({day for per_mode in frontier.values() for day in per_mode})
    return {
        "days": days,
        "alphas": sorted(float(a) for a in art.json("thresholds")),
        "frontier_alphas": sorted({float(k.split("|")[0]) for k in frontier}),
        "modes": list(MODES),
        "objectives": list(OBJECTIVES),
        "default_alpha": DEFAULT_ALPHA,
        "operations": art.json("operations"),
    }


def _frontier_days(
    art: DecideArtifacts, alpha: float, mode: str, objective: str = "cases"
) -> dict[str, Any]:
    frontier = art.json("frontier")
    for key, days in frontier.items():
        a, m, o = key.split("|")
        if math.isclose(float(a), alpha) and (m, o) == (mode, objective):
            result: dict[str, Any] = days
            return result
    raise AppError(404, "no-frontier", "No frontier for that alpha, mode and objective")


def get_frontier(
    art: DecideArtifacts, day: str, alpha: float, mode: str, objective: str
) -> dict[str, Any]:
    days = _frontier_days(art, alpha, mode, objective)
    if day not in days:
        raise AppError(404, "no-frontier", "No frontier for that day")
    return {
        "day": day,
        "alpha": alpha,
        "mode": mode,
        "objective": objective,
        "solver": "greedy",
        "points": days[day],
    }


def staffing(art: DecideArtifacts, alpha: float, mode: str) -> dict[str, Any]:
    """Analysts each replay day needs for the guarantee (from the precomputed frontier)."""
    days = _frontier_days(art, alpha, mode)
    rows = []
    for day in sorted(days):
        first = days[day][0]
        rows.append(
            {
                "day": day,
                "alerts": first["alerts"],
                "required_alerts": first["guarantee"]["required_alerts"],
                "analysts_needed": first["guarantee"]["analysts_needed"],
            }
        )
    return {"alpha": alpha, "mode": mode, "days": rows}


_COLUMNS = ["id", "score", "calibrated_prob", "typology_pred", "top_amount", "top_currency"]


def _day_alerts(db: Session, art: DecideArtifacts, day: date) -> pd.DataFrame:
    """A day's alerts for the planner, cached per model version (alerts never change in place:
    a reload is a new model version)."""
    version = champion(db)
    key = f"alerts:{version.id}:{day.isoformat()}"
    cached: pd.DataFrame | None = art.cached(key)
    if cached is not None:
        return cached
    stmt = select(
        Alert.id,
        Alert.score,
        Alert.calibrated_prob,
        Alert.typology_pred,
        Alert.top_amount,
        Alert.top_currency,
    ).where(Alert.model_version_id == version.id, Alert.alert_date == day)
    frame = pd.DataFrame([tuple(r) for r in db.execute(stmt)], columns=_COLUMNS)
    art.store(key, frame)
    return frame


def compute_plan(
    db: Session,
    art: DecideArtifacts,
    day: date,
    analysts: int,
    alpha: float,
    mode: str,
    overrides: dict[str, float | None] | None = None,
    objective: str = "cases",
) -> dict[str, Any]:
    ops, overridden = Operations.load().with_overrides(**(overrides or {}))
    if not ops.min_analysts <= analysts <= ops.max_analysts:
        raise AppError(
            422,
            "bad-analysts",
            f"analysts must be between {ops.min_analysts} and {ops.max_analysts}",
        )
    alerts = _day_alerts(db, art, day).copy()
    if alerts.empty:
        raise AppError(404, "no-alerts", "No alerts on that day")
    if alerts["calibrated_prob"].isna().any():
        alerts["calibrated_prob"] = np.asarray(
            art.isotonic().predict(alerts["score"].to_numpy(dtype=float)), dtype=float
        )
    th = art.thresholds(alpha)
    prepared = prepare(alerts, ops)
    mask = apply_thresholds(
        prepared["score"].to_numpy(dtype=float), prepared["typology_pred"].to_numpy(), th, mode
    )
    day_info = art.json("queue")["by_day"].get(day.isoformat(), {})
    outside = float(day_info.get("outside_expected", 0.0))
    plan = plan_day(prepared, analysts, mask, ops, True, outside, objective)
    selected = plan.pop("selected")
    chosen = prepared.loc[selected].sort_values("expected_value", ascending=False)
    plan.update(
        {
            "day": day.isoformat(),
            "alpha": alpha,
            "mode": mode,
            "target_recall": 1 - alpha,
            "selected_alert_ids": chosen["id"].astype(int).tolist(),
            # Only when feasible (then they are all selected); an infeasible day can require
            # 10⁵ alerts, and their count is already in guarantee.required_alerts.
            "guaranteed_alert_ids": prepared.loc[mask, "id"].astype(int).tolist()
            if plan["guarantee"]["feasible"]
            else [],
            "assumptions": {**ops.to_dict(), "overridden": overridden},
            "threshold": th.pooled if mode == "pooled" else None,
            "outside_expected": outside,
        }
    )
    if plan["threshold"] is not None and math.isinf(plan["threshold"]):
        plan["threshold"] = None
    return plan


def save_plan(db: Session, user: User, plan: dict[str, Any], ip: str | None) -> CapacityPlan:
    record = CapacityPlan(
        plan_date=date.fromisoformat(plan["day"]),
        analysts=plan["analysts"],
        alpha=plan["alpha"],
        mode=plan["mode"],
        created_by=user.id,
        result={k: v for k, v in plan.items() if k != "selected_alert_ids"},
        selected_alert_ids=plan["selected_alert_ids"],
    )
    db.add(record)
    db.flush()
    AuditRepository(db).record(
        "capacity.plan_saved",
        actor_id=user.id,
        target=f"capacity_plan:{record.id}",
        ip=ip,
        detail={
            "day": plan["day"],
            "analysts": plan["analysts"],
            "alpha": plan["alpha"],
            "mode": plan["mode"],
        },
    )
    return record


def latest_plan(db: Session, day: date) -> CapacityPlan | None:
    return db.scalar(
        select(CapacityPlan).where(CapacityPlan.plan_date == day).order_by(CapacityPlan.id.desc())
    )
