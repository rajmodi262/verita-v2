"""Case files (Defend): create from alerts, draft, edit, verify, submit, return, approve, export."""

from __future__ import annotations

import copy
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response

from verita.api import case_schemas as cs
from verita.api.deps import DbDep, SessionDep, csrf_role, require_role
from verita.api.params import CaseId, JobId
from verita.api.state import evidence_store
from verita.db.case_models import CLOSE_REASONS, RETURN_REASONS
from verita.db.models import Role
from verita.defend.pdf import render_pdf
from verita.repositories.identity import AuditRepository
from verita.services import cases as svc
from verita.services import jobs, ledger
from verita.services.auth import SessionInfo

router = APIRouter(tags=["cases"])
READERS = Depends(require_role(Role.ANALYST, Role.MLRO, Role.VALIDATOR, Role.REVIEWER))
MakerDep = Annotated[SessionInfo, Depends(csrf_role(Role.ANALYST, Role.MLRO))]
CheckerDep = Annotated[SessionInfo, Depends(csrf_role(Role.MLRO))]


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _audit(
    db: DbDep, request: Request, actor: int, action: str, case_id: int, **detail: Any
) -> None:
    AuditRepository(db).record(action, actor, f"case:{case_id}", _ip(request), detail)


@router.get("/cases/meta", dependencies=[READERS], response_model=cs.CaseMeta)
def meta(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    keyed = [p for p in settings.llm_providers if settings.llm_keys(p)]
    return {
        "return_reasons": RETURN_REASONS,
        "close_reasons": CLOSE_REASONS,
        "llm_providers": keyed,
        "offline_only": not keyed,
    }


@router.get("/cases", dependencies=[READERS], response_model=cs.CaseList)
def list_cases(db: DbDep) -> dict[str, Any]:
    return {"items": svc.list_cases(db)}


@router.post("/cases", response_model=cs.CaseDetail, response_model_by_alias=True, status_code=201)
def create(body: cs.CreateCaseIn, request: Request, db: DbDep, info: MakerDep) -> dict[str, Any]:
    case = svc.create_case(db, info.user, evidence_store(request), body.alert_ids, body.title)
    _audit(db, request, info.user.id, "case.created", case.id, alert_ids=body.alert_ids)
    return svc.case_view(db, case.id, info.user)


@router.get(
    "/cases/{case_id}",
    dependencies=[READERS],
    response_model=cs.CaseDetail,
    response_model_by_alias=True,
)
def detail(case_id: CaseId, db: DbDep, info: SessionDep) -> dict[str, Any]:
    return svc.case_view(db, case_id, info.user)


@router.post("/cases/{case_id}/narrative", response_model=cs.JobOut, status_code=202)
def draft(
    case_id: CaseId,
    body: cs.DraftIn,
    request: Request,
    background: BackgroundTasks,
    db: DbDep,
    info: MakerDep,
) -> dict[str, Any]:
    """Queue a narrative draft; poll ``GET /jobs/{id}``."""
    job = svc.request_draft(db, case_id, info.user, body.mode)
    view = jobs.job_view(job)
    db.commit()  # the job must exist before a worker (or the inline task) looks for it
    if request.app.state.settings.inline_jobs:
        background.add_task(jobs.run, request.app.state.session_factory, job.id)
    return view


@router.put(
    "/cases/{case_id}/narrative", response_model=cs.CaseDetail, response_model_by_alias=True
)
def edit(
    case_id: CaseId, body: cs.EditIn, request: Request, db: DbDep, info: MakerDep
) -> dict[str, Any]:
    svc.save_edit(db, case_id, info.user, [s.model_dump() for s in body.sentences])
    _audit(db, request, info.user.id, "case.narrative_edited", case_id)
    return svc.case_view(db, case_id, info.user)


@router.post("/cases/{case_id}/verify", response_model=cs.CaseDetail, response_model_by_alias=True)
def run_verify(case_id: CaseId, db: DbDep, info: MakerDep) -> dict[str, Any]:
    svc.run_verification(db, case_id, info.user)
    return svc.case_view(db, case_id, info.user)


@router.post("/cases/{case_id}/submit", response_model=cs.CaseDetail, response_model_by_alias=True)
def submit(case_id: CaseId, request: Request, db: DbDep, info: MakerDep) -> dict[str, Any]:
    svc.submit(db, case_id, info.user)
    _audit(db, request, info.user.id, "case.submitted", case_id)
    return svc.case_view(db, case_id, info.user)


@router.post("/cases/{case_id}/approve", response_model=cs.CaseDetail, response_model_by_alias=True)
def approve(case_id: CaseId, request: Request, db: DbDep, info: CheckerDep) -> dict[str, Any]:
    sig = svc.approve(db, case_id, info.user)
    _audit(db, request, info.user.id, "case.signed", case_id, merkle_root=sig.merkle_root)
    return svc.case_view(db, case_id, info.user)


@router.post("/cases/{case_id}/return", response_model=cs.CaseDetail, response_model_by_alias=True)
def return_case(
    case_id: CaseId, body: cs.ReasonIn, request: Request, db: DbDep, info: CheckerDep
) -> dict[str, Any]:
    svc.return_case(db, case_id, info.user, body.reason, body.note)
    _audit(db, request, info.user.id, "case.returned", case_id, reason=body.reason)
    return svc.case_view(db, case_id, info.user)


@router.post("/cases/{case_id}/close", response_model=cs.CaseDetail, response_model_by_alias=True)
def close(
    case_id: CaseId, body: cs.ReasonIn, request: Request, db: DbDep, info: MakerDep
) -> dict[str, Any]:
    svc.close_case(db, case_id, info.user, body.reason, body.note)
    _audit(db, request, info.user.id, "case.closed", case_id, reason=body.reason)
    return svc.case_view(db, case_id, info.user)


@router.get(
    "/cases/{case_id}/verify-signature", dependencies=[READERS], response_model=cs.SignatureCheck
)
def verify_signature(case_id: CaseId, db: DbDep) -> dict[str, Any]:
    """Server-side check of the signed export and the ledger (the CLI does the same offline)."""
    result = svc.verify_export(svc.export_document(db, case_id))
    return {**result, "ledger": ledger.verify_chain(ledger.events(db, case_id))}


@router.get("/cases/{case_id}/export.json", dependencies=[READERS])
def export_json(case_id: CaseId, db: DbDep) -> Response:
    from verita.defend.canonical import canonicalize  # noqa: PLC0415

    body = canonicalize(svc.export_document(db, case_id))
    return Response(
        body,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="case-{case_id}.json"'},
    )


@router.get("/cases/{case_id}/export-tampered.json", dependencies=[READERS])
def export_tampered(case_id: CaseId, db: DbDep) -> Response:
    """Demo: the signed export with one payment amount changed, to show verification failing."""
    from verita.defend.canonical import canonicalize  # noqa: PLC0415

    doc = copy.deepcopy(svc.export_document(db, case_id))
    txn = next((k for k in sorted(doc["items"]) if k.startswith("EV-TXN-")), None)
    if txn is not None:
        doc["items"][txn]["payload"]["amount_paid"] = round(
            float(doc["items"][txn]["payload"]["amount_paid"]) + 1000.0, 2
        )
    return Response(
        canonicalize(doc),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="case-{case_id}-TAMPERED.json"'},
    )


@router.get("/cases/{case_id}/export.goaml.xml", dependencies=[READERS])
def export_goaml(case_id: CaseId, db: DbDep) -> Response:
    """The goAML suspicious transaction report, exactly as signed (a leaf of the case file)."""
    return Response(
        svc.goaml_report(db, case_id),
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="case-{case_id}-goaml.xml"'},
    )


@router.get("/cases/{case_id}/export.pdf", dependencies=[READERS])
def export_pdf(case_id: CaseId, db: DbDep) -> Response:
    return Response(
        render_pdf(svc.export_document(db, case_id)),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="case-{case_id}.pdf"'},
    )


@router.get("/jobs/{job_id}", dependencies=[READERS], response_model=cs.JobOut)
def job(job_id: JobId, db: DbDep) -> dict[str, Any]:
    return jobs.job_view(jobs.get_job(db, job_id))


@router.get("/keys", response_model=cs.Keys)
def keys() -> dict[str, Any]:
    """Public signing keys — no login needed: anyone holding an export can verify it."""
    return {"keys": [svc.signer().describe()]}
