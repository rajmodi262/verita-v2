"""Alert queue, alert detail, evidence subgraph, dispositions."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from verita.api.deps import CsrfSessionDep, DbDep, require_role
from verita.api.params import AlertId
from verita.api.schemas import AlertDetail, AlertList, QueueMeta, Subgraph
from verita.api.state import evidence_store
from verita.db.detect_models import DispositionAction
from verita.db.models import Role
from verita.services import alerts as svc
from verita.services.evidence import AlertRef

router = APIRouter(prefix="/alerts", tags=["alerts"])

READERS = Depends(require_role(Role.ANALYST, Role.MLRO, Role.VALIDATOR, Role.REVIEWER))
DECIDERS = require_role(Role.ANALYST, Role.MLRO)


@router.get("", dependencies=[READERS], response_model=AlertList, response_model_by_alias=True)
def list_alerts(
    db: DbDep,
    alert_date: Annotated[date | None, Query(alias="date")] = None,
    status: Annotated[str | None, Query(pattern="^(open|escalated|dismissed|in_case)$")] = None,
    typology: Annotated[str | None, Query(max_length=32)] = None,
    min_score: Annotated[float | None, Query(ge=0, le=1)] = None,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=svc.MAX_PAGE)] = 50,
) -> dict[str, Any]:
    filters = svc.AlertFilters(
        alert_date=alert_date, status=status, typology=typology, min_score=min_score
    )
    return svc.list_alerts(db, filters, cursor, limit)


@router.get("/meta", dependencies=[READERS], response_model=QueueMeta)
def meta(db: DbDep) -> dict[str, Any]:
    return svc.queue_meta(db)


@router.get("/{alert_id}", dependencies=[READERS], response_model=AlertDetail)
def detail(alert_id: AlertId, db: DbDep) -> dict[str, Any]:
    return svc.alert_detail(db, alert_id)


@router.get(
    "/{alert_id}/subgraph",
    dependencies=[READERS],
    response_model=Subgraph,
    response_model_by_alias=True,
)
def subgraph(alert_id: AlertId, db: DbDep, request: Request) -> dict[str, Any]:
    alert = svc.get_alert(db, alert_id)
    version = svc.champion(db)
    ref = AlertRef(
        alert.id, alert.account_id, alert.alert_date, alert.top_txn_id, version.threshold
    )
    return evidence_store(request).subgraph(ref)


class DispositionIn(BaseModel):
    action: DispositionAction
    reason_code: str = Field(min_length=1, max_length=32)
    note: str = Field(default="", max_length=2000)


@router.post("/{alert_id}/disposition", response_model=AlertDetail)
def disposition(
    alert_id: AlertId, body: DispositionIn, db: DbDep, info: CsrfSessionDep, request: Request
) -> dict[str, Any]:
    DECIDERS(info)
    ip = request.client.host if request.client else None
    return svc.dispose(db, info.user, alert_id, body.action, body.reason_code, body.note, ip)
