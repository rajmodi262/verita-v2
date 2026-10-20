"""Model governance: list models, read a validation report, validate, approve, reject, promote."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Request
from pydantic import BaseModel, Field

from verita.api.deps import DbDep, csrf_role, require_role
from verita.api.params import MAX_ID
from verita.db.models import Role
from verita.pipeline.config import get_dataset
from verita.services import models as svc
from verita.services.auth import SessionInfo

router = APIRouter(tags=["models"])
READERS = Depends(require_role(Role.ANALYST, Role.MLRO, Role.VALIDATOR, Role.REVIEWER))
ValidatorDep = Annotated[SessionInfo, Depends(csrf_role(Role.VALIDATOR))]
MlroDep = Annotated[SessionInfo, Depends(csrf_role(Role.MLRO))]

ModelId = Annotated[int, Path(ge=1, le=MAX_ID, description="Model version ID")]


class ValidationSummary(BaseModel):
    passed: bool
    sha256: str | None
    policy_version: int | None
    failed_gates: list[str]


class ModelOut(BaseModel):
    id: int
    name: str
    dataset: str
    status: str
    is_champion: bool
    champion_sha256: str
    git_revision: str
    threshold: float
    created_at: datetime
    proposed_by: str
    validation: ValidationSummary | None
    approved_by_id: int | None
    approved_at: datetime | None
    promoted_by_id: int | None
    promoted_at: datetime | None
    decision_note: str | None
    governance: str = Field(description="reviewed, bypassed, or not reviewed")
    bypass_reason: str | None


class ModelList(BaseModel):
    items: list[ModelOut]


class ModelDetail(ModelOut):
    report: dict[str, Any] | None = Field(description="The full validation report, if any")


class DecisionIn(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class RejectIn(BaseModel):
    note: str = Field(min_length=3, max_length=2000)


def _detail(version: Any) -> dict[str, Any]:
    return {**svc.view(version), "report": version.validation}


@router.get("/models", dependencies=[READERS], response_model=ModelList)
def list_models(db: DbDep) -> dict[str, Any]:
    return {"items": svc.list_models(db)}


@router.get("/models/{model_id}", dependencies=[READERS], response_model=ModelDetail)
def get_model(model_id: ModelId, db: DbDep) -> dict[str, Any]:
    return _detail(svc.get_model(db, model_id))


@router.post("/models/{model_id}/validate", response_model=ModelDetail)
def validate(model_id: ModelId, request: Request, db: DbDep, info: ValidatorDep) -> dict[str, Any]:
    settings = request.app.state.settings
    dataset = get_dataset(settings.dataset, root=settings.data_root)
    return _detail(svc.validate(db, dataset, model_id, info.user.id))


@router.post("/models/{model_id}/approve", response_model=ModelDetail)
def approve(
    model_id: ModelId, db: DbDep, info: ValidatorDep, body: DecisionIn | None = None
) -> dict[str, Any]:
    return _detail(svc.approve(db, info.user, model_id, body.note if body else None))


@router.post("/models/{model_id}/reject", response_model=ModelDetail)
def reject(model_id: ModelId, body: RejectIn, db: DbDep, info: ValidatorDep) -> dict[str, Any]:
    return _detail(svc.reject(db, info.user, model_id, body.note))


@router.post("/models/{model_id}/promote", response_model=ModelDetail)
def promote(
    model_id: ModelId, db: DbDep, info: MlroDep, body: DecisionIn | None = None
) -> dict[str, Any]:
    return _detail(svc.promote(db, info.user, model_id, body.note if body else None))
