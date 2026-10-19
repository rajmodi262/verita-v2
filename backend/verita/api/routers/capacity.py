"""Capacity planner (Decide): frontier, exact plan, saved plans, forecast, coverage, drift."""

from __future__ import annotations

import math
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from verita.api import capacity_schemas as cs
from verita.api.deps import CsrfSessionDep, DbDep, require_role
from verita.api.state import decide_artifacts
from verita.core.errors import AppError
from verita.db.models import Role
from verita.services import capacity as svc

router = APIRouter(prefix="/capacity", tags=["capacity"])
READERS = Depends(require_role(Role.ANALYST, Role.MLRO, Role.VALIDATOR, Role.REVIEWER))
PLANNERS = require_role(Role.MLRO)

Alpha = Annotated[float, Query(gt=0, lt=1)]
Mode = Annotated[str, Query(pattern="^(pooled|mondrian)$")]
Objective = Annotated[str, Query(pattern="^(cases|value)$")]


Minutes = Annotated[float | None, Query(gt=0, le=600)]
Hours = Annotated[float | None, Query(gt=0, le=12)]
Rate = Annotated[float | None, Query(ge=0, le=1000)]


@router.get("/meta", dependencies=[READERS], response_model=cs.CapacityMeta)
def meta(request: Request) -> dict[str, Any]:
    return svc.meta(decide_artifacts(request))


@router.get("/staffing", dependencies=[READERS], response_model=cs.Staffing)
def staffing(request: Request, alpha: Alpha = 0.05, mode: Mode = "pooled") -> dict[str, Any]:
    return svc.staffing(decide_artifacts(request), alpha, mode)


@router.get("/frontier", dependencies=[READERS], response_model=cs.Frontier)
def frontier(
    request: Request,
    day: Annotated[date, Query(alias="date")],
    alpha: Alpha = 0.05,
    mode: Mode = "pooled",
    objective: Objective = "cases",
) -> dict[str, Any]:
    return svc.get_frontier(decide_artifacts(request), day.isoformat(), alpha, mode, objective)


@router.get("/plan", dependencies=[READERS], response_model=cs.Plan)
def plan(
    request: Request,
    db: DbDep,
    day: Annotated[date, Query(alias="date")],
    analysts: Annotated[int, Query(ge=1, le=50)],
    alpha: Alpha = 0.05,
    mode: Mode = "pooled",
    objective: Objective = "cases",
    median_minutes: Minutes = None,
    productive_hours: Hours = None,
    analyst_hourly_rate: Rate = None,
) -> dict[str, Any]:
    """Exact plan; the optional assumption overrides are a what-if and are never saved."""
    overrides = {
        "median_minutes": median_minutes,
        "productive_hours": productive_hours,
        "analyst_hourly_rate": analyst_hourly_rate,
    }
    art = decide_artifacts(request)
    return svc.compute_plan(db, art, day, analysts, alpha, mode, overrides, objective)


class SavePlanIn(BaseModel):
    date: date
    analysts: int = Field(ge=1, le=50)
    alpha: float = Field(gt=0, lt=1)
    mode: str = Field(pattern="^(pooled|mondrian)$")
    objective: str = Field(default="cases", pattern="^(cases|value)$")


@router.post("/plans", response_model=cs.SavedPlanOut)
def save(body: SavePlanIn, request: Request, db: DbDep, info: CsrfSessionDep) -> dict[str, Any]:
    PLANNERS(info)
    result = svc.compute_plan(
        db,
        decide_artifacts(request),
        body.date,
        body.analysts,
        body.alpha,
        body.mode,
        objective=body.objective,
    )
    ip = request.client.host if request.client else None
    record = svc.save_plan(db, info.user, result, ip)
    return {"id": record.id, "plan": result}


@router.get("/plans/latest", dependencies=[READERS], response_model=cs.SavedPlan)
def latest(db: DbDep, day: Annotated[date, Query(alias="date")]) -> dict[str, Any]:
    record = svc.latest_plan(db, day)
    if record is None:
        raise AppError(404, "no-plan", "No plan saved for that day")
    return {
        "id": record.id,
        "date": record.plan_date.isoformat(),
        "analysts": record.analysts,
        "alpha": record.alpha,
        "mode": record.mode,
        "created_by": record.created_by,
        "created_at": record.created_at.isoformat(),
        "result": record.result,
        "selected_alert_ids": record.selected_alert_ids,
    }


@router.get("/forecast", dependencies=[READERS], response_model=cs.ForecastOut)
def forecast(request: Request) -> dict[str, Any]:
    data: dict[str, Any] = decide_artifacts(request).json("forecast")
    return data


@router.get("/coverage", dependencies=[READERS], response_model=cs.Coverage)
def coverage(request: Request, alpha: Alpha = 0.05) -> dict[str, Any]:
    data = decide_artifacts(request).json("coverage")
    key = next((k for k in data["by_alpha"] if math.isclose(float(k), alpha)), None)
    if key is None:
        raise AppError(422, "unsupported-alpha", "No coverage replay for that alpha")
    return {
        "alpha": alpha,
        "runs": data["by_alpha"][key],
        "tail_days": data["tail_days"],
        "label_delay_sensitivity": data["label_delay_sensitivity"],
        "gamma": data["gamma"],
    }


@router.get("/calibration", dependencies=[READERS], response_model=cs.Calibration)
def calibration(request: Request) -> dict[str, Any]:
    data: dict[str, Any] = decide_artifacts(request).json("calibration")
    return data


@router.get("/drift", dependencies=[READERS], response_model=cs.Drift)
def drift(request: Request) -> dict[str, Any]:
    data: dict[str, Any] = decide_artifacts(request).json("drift")
    return data
