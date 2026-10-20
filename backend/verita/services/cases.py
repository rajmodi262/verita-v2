"""Case files (PIVOT §8): create, draft, edit, verify, submit, return, approve-and-sign, close.

State machine::

    draft ──verify ok──▶ verified ──submit──▶ submitted ──approve (MLRO ≠ maker)──▶ signed
      ▲  ◀──edit/redraft──┘                       │
      └──────────edit/redraft── returned ◀──return┘
    any unsigned state ──close (reason)──▶ closed

Every transition appends a hash-chained ledger event. Approval is maker-checker: the MLRO who
signs can be neither the case's creator nor whoever submitted it. Signing freezes the case
file — evidence, narrative, verification report and approval — as Merkle leaves, signs the root
with Ed25519 and stores the exact signed document, so the export is reproducible byte for byte.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from verita.core.config import Settings
from verita.core.errors import AppError
from verita.db.base import utcnow
from verita.db.case_models import (
    CLOSE_REASONS,
    RETURN_REASONS,
    Case,
    CaseAlert,
    CaseEvidence,
    CaseState,
    EventType,
    Job,
    Narrative,
    Signature,
    Verification,
)
from verita.db.detect_models import Alert, AlertStatus
from verita.db.models import Role, User
from verita.defend import narrative as narr
from verita.defend.canonical import canonicalize
from verita.defend.evidence import AlertInput, build_case_evidence
from verita.defend.merkle import MerkleTree, changed_leaves, leaf_hash
from verita.defend.signing import Signer, load_public_pem, verify_signature
from verita.defend.verifier import verify
from verita.services import jobs, ledger
from verita.services.alerts import champion, get_alert
from verita.services.evidence import AlertRef, SubgraphSource

MAX_ALERTS_PER_CASE = 10
EXPORT_FORMAT = "verita-case-file/1"
NARRATIVE_JOB = "narrative.draft"
EDITABLE = {CaseState.DRAFT, CaseState.VERIFIED, CaseState.RETURNED}


@dataclass
class Runtime:
    """Process-wide dependencies the job handler needs (set by the app factory and the CLI)."""

    settings: Settings | None = None
    signer: Signer | None = None


RUNTIME = Runtime()


def configure(settings: Settings) -> None:
    """Remember the settings; the signing key is loaded (or created, in dev) on first use."""
    RUNTIME.settings = settings
    RUNTIME.signer = None


def signer() -> Signer:
    if RUNTIME.signer is None:
        if RUNTIME.settings is None:
            raise AppError(503, "no-signing-key", "Signing is not configured")
        s = RUNTIME.settings
        RUNTIME.signer = Signer.load_or_create(s.signing_key_path, s.public_key_path)
    return RUNTIME.signer


# ── helpers ──────────────────────────────────────────────────────────────────


def get_case(db: Session, case_id: int, *, lock: bool = False) -> Case:
    stmt = select(Case).where(Case.id == case_id)
    if lock:
        stmt = stmt.with_for_update()
    case = db.scalar(stmt)
    if case is None:
        raise AppError(404, "case-not-found", "No such case")
    return case


def _require(case: Case, *states: CaseState) -> None:
    if CaseState(case.state) not in states:
        allowed = ", ".join(s.value for s in states)
        raise AppError(
            409,
            "invalid-transition",
            f"The case is {case.state}",
            detail=f"This action needs the case to be: {allowed}.",
        )


def _set_state(case: Case, state: CaseState) -> None:
    case.state = state.value
    case.updated_at = utcnow()


def evidence_items(db: Session, case_id: int) -> dict[str, dict[str, Any]]:
    rows = db.scalars(select(CaseEvidence).where(CaseEvidence.case_id == case_id)).all()
    return {
        r.evidence_id: {"id": r.evidence_id, "kind": r.kind, "payload": r.payload} for r in rows
    }


def _current_narrative(db: Session, case: Case) -> Narrative | None:
    return db.get(Narrative, case.current_narrative_id) if case.current_narrative_id else None


def _latest_verification(db: Session, narrative_id: int | None) -> Verification | None:
    if narrative_id is None:
        return None
    return db.scalar(
        select(Verification)
        .where(Verification.narrative_id == narrative_id)
        .order_by(Verification.id.desc())
        .limit(1)
    )


def _sha(data: Any) -> str:
    return hashlib.sha256(canonicalize(data)).hexdigest()


# ── create ───────────────────────────────────────────────────────────────────


def _alert_input(db: Session, store: SubgraphSource, alert: Alert, threshold: float) -> AlertInput:
    ref = AlertRef(alert.id, alert.account_id, alert.alert_date, alert.top_txn_id, threshold)
    return AlertInput(
        id=alert.id,
        account_id=alert.account_id,
        alert_date=alert.alert_date.isoformat(),
        score=alert.score,
        typology_pred=alert.typology_pred,
        typology_conf=alert.typology_conf,
        n_transactions=alert.n_transactions,
        n_flagged=alert.n_flagged,
        top_txn_id=alert.top_txn_id,
        reasons=[
            {"rank": r.rank, "feature": r.feature, "value": r.value, "text": r.text}
            for r in alert.reasons
        ],
        subgraph=store.subgraph(ref),
    )


def create_case(
    db: Session, user: User, store: SubgraphSource, alert_ids: list[int], title: str | None = None
) -> Case:
    ids = sorted(set(alert_ids))
    if not 1 <= len(ids) <= MAX_ALERTS_PER_CASE:
        raise AppError(422, "bad-alerts", f"A case groups 1 to {MAX_ALERTS_PER_CASE} alerts")
    alerts = [get_alert(db, i) for i in ids]
    taken = [a.id for a in alerts if a.status == AlertStatus.IN_CASE.value]
    if taken:
        raise AppError(
            409, "alert-in-case", "Alert already belongs to a case", detail=f"Alerts: {taken}"
        )
    version = champion(db)
    inputs = [_alert_input(db, store, a, version.threshold) for a in alerts]
    first = alerts[0]
    case = Case(
        title=title or f"{first.typology_pred.title()} activity around {first.account_id}",
        created_by=user.id,
    )
    db.add(case)
    db.flush()
    items = build_case_evidence(case.id, inputs).items
    for ev_id, item in items.items():
        db.add(
            CaseEvidence(
                case_id=case.id,
                evidence_id=ev_id,
                kind=item["kind"],
                payload=item["payload"],
                leaf_hash=leaf_hash(ev_id, item).hex(),
            )
        )
    for a in alerts:
        db.add(CaseAlert(case_id=case.id, alert_id=a.id))
        a.status = AlertStatus.IN_CASE.value
    ledger.append(
        db,
        case.id,
        EventType.CREATED,
        user.id,
        {
            "alert_ids": ids,
            "evidence_count": len(items),
            "evidence_root": MerkleTree.build(items).root,
        },
    )
    return case


# ── narrative ────────────────────────────────────────────────────────────────


def _new_version(db: Session, case_id: int) -> int:
    current = db.scalar(select(func.max(Narrative.version)).where(Narrative.case_id == case_id))
    return int(current or 0) + 1


def _record_verification(db: Session, case: Case, nar: Narrative, user_id: int) -> Verification:
    report = verify(nar.sentences, evidence_items(db, case.id)).to_dict()
    ver = Verification(
        case_id=case.id,
        narrative_id=nar.id,
        passed=report["passed"],
        report=report,
        verifier_version=report["verifier_version"],
    )
    db.add(ver)
    db.flush()
    _set_state(case, CaseState.VERIFIED if ver.passed else CaseState.DRAFT)
    ledger.append(
        db,
        case.id,
        EventType.VERIFIED,
        user_id,
        {
            "narrative_id": nar.id,
            "verification_id": ver.id,
            "passed": ver.passed,
            "failed_sentences": report["failed_sentences"],
            "report_sha256": _sha(report),
        },
    )
    return ver


def request_draft(db: Session, case_id: int, user: User, mode: str) -> Job:
    case = get_case(db, case_id, lock=True)
    _require(case, *EDITABLE)
    return jobs.enqueue(
        db, NARRATIVE_JOB, {"case_id": case.id, "mode": mode, "user_id": user.id}, user.id
    )


@jobs.handler(NARRATIVE_JOB)
def _draft_job(db: Session, job: Job) -> dict[str, Any]:
    case = get_case(db, int(job.payload["case_id"]), lock=True)
    _require(case, *EDITABLE)
    job.progress = "drafting"
    settings = RUNTIME.settings
    providers = narr.providers_from_settings(settings) if settings else []
    draft = narr.draft(evidence_items(db, case.id), providers, str(job.payload.get("mode", "auto")))
    user_id = int(job.payload["user_id"])
    nar = Narrative(
        case_id=case.id,
        version=_new_version(db, case.id),
        mode=draft.mode,
        provider=draft.provider,
        model_id=draft.model,
        prompt_hash=draft.prompt_hash,
        sentences=draft.sentences,
        created_by=user_id,
    )
    db.add(nar)
    db.flush()
    case.current_narrative_id = nar.id
    ledger.append(
        db,
        case.id,
        EventType.NARRATIVE_DRAFTED,
        user_id,
        {
            "narrative_id": nar.id,
            "version": nar.version,
            "mode": nar.mode,
            "provider": nar.provider,
            "model": nar.model_id,
            "prompt_sha256": nar.prompt_hash,
            "sentences_sha256": _sha(nar.sentences),
            "provider_failures": len(draft.attempts),
        },
    )
    job.progress = "verifying"
    ver = _record_verification(db, case, nar, user_id)
    return {
        "case_id": case.id,
        "narrative_id": nar.id,
        "mode": nar.mode,
        "provider": nar.provider,
        "passed": ver.passed,
        "seconds": draft.seconds,
    }


def save_edit(db: Session, case_id: int, user: User, sentences: list[dict[str, Any]]) -> Case:
    case = get_case(db, case_id, lock=True)
    _require(case, *EDITABLE)
    try:
        clean = [narr.SentenceModel.model_validate(s).model_dump() for s in sentences]
    except ValueError as exc:
        raise AppError(
            422, "bad-narrative", "Sentences must have section, text and evidence_ids"
        ) from exc
    base = _current_narrative(db, case)
    nar = Narrative(
        case_id=case.id,
        version=_new_version(db, case.id),
        mode="edit",
        provider="analyst",
        model_id=base.model_id if base else "analyst",
        prompt_hash=base.prompt_hash if base else "",
        sentences=clean,
        created_by=user.id,
    )
    db.add(nar)
    db.flush()
    case.current_narrative_id = nar.id
    ledger.append(
        db,
        case.id,
        EventType.NARRATIVE_EDITED,
        user.id,
        {
            "narrative_id": nar.id,
            "version": nar.version,
            "based_on": base.id if base else None,
            "sentences_sha256": _sha(clean),
        },
    )
    _record_verification(db, case, nar, user.id)
    return case


def run_verification(db: Session, case_id: int, user: User) -> Verification:
    case = get_case(db, case_id, lock=True)
    _require(case, *EDITABLE)
    nar = _current_narrative(db, case)
    if nar is None:
        raise AppError(409, "no-narrative", "Draft a narrative first")
    return _record_verification(db, case, nar, user.id)


# ── review and sign ──────────────────────────────────────────────────────────


def submit(db: Session, case_id: int, user: User) -> Case:
    case = get_case(db, case_id, lock=True)
    _require(case, CaseState.VERIFIED)
    nar = _current_narrative(db, case)
    ver = _latest_verification(db, nar.id if nar else None)
    if nar is None or ver is None or not ver.passed:
        raise AppError(409, "not-verified", "The current narrative has not passed verification")
    _set_state(case, CaseState.SUBMITTED)
    ledger.append(
        db,
        case.id,
        EventType.SUBMITTED,
        user.id,
        {"narrative_id": nar.id, "verification_id": ver.id},
    )
    return case


def _submitter(db: Session, case_id: int) -> int | None:
    subs = [e for e in ledger.events(db, case_id) if e.type == EventType.SUBMITTED]
    return subs[-1].actor_id if subs else None


def return_case(db: Session, case_id: int, user: User, reason: str, note: str) -> Case:
    if reason not in RETURN_REASONS:
        raise AppError(422, "bad-reason", "Unknown return reason")
    case = get_case(db, case_id, lock=True)
    _require(case, CaseState.SUBMITTED)
    _set_state(case, CaseState.RETURNED)
    ledger.append(db, case.id, EventType.RETURNED, user.id, {"reason": reason, "note": note})
    return case


def close_case(db: Session, case_id: int, user: User, reason: str, note: str) -> Case:
    if reason not in CLOSE_REASONS:
        raise AppError(422, "bad-reason", "Unknown close reason")
    case = get_case(db, case_id, lock=True)
    _require(case, CaseState.DRAFT, CaseState.VERIFIED, CaseState.RETURNED, CaseState.SUBMITTED)
    _set_state(case, CaseState.CLOSED)
    for link in db.scalars(select(CaseAlert).where(CaseAlert.case_id == case.id)):
        alert = db.get(Alert, link.alert_id)
        if alert is not None:
            alert.status = AlertStatus.ESCALATED.value
    ledger.append(db, case.id, EventType.CLOSED, user.id, {"reason": reason, "note": note})
    return case


def approval_blockers(db: Session, case: Case, user: User) -> list[str]:
    """Why ``user`` may not approve this case (empty when they may)."""
    reasons = []
    if user.role != Role.MLRO:
        reasons.append("Only the MLRO approves case files.")
    if user.id == case.created_by:
        reasons.append("Maker-checker: you created this case, so someone else must approve it.")
    if user.id == _submitter(db, case.id):
        reasons.append("Maker-checker: you submitted this case, so someone else must approve it.")
    if case.state != CaseState.SUBMITTED:
        reasons.append(f"The case is {case.state}; only submitted cases can be approved.")
    return reasons


def _document(db: Session, case: Case, approver: User, signed_at: str) -> dict[str, Any]:
    nar = _current_narrative(db, case)
    ver = _latest_verification(db, nar.id if nar else None)
    if nar is None or ver is None:
        raise AppError(409, "not-verified", "Nothing verified to sign")
    head = ledger.events(db, case.id)[-1]
    items: dict[str, Any] = dict(evidence_items(db, case.id))
    items["narrative"] = {
        "narrative_id": nar.id,
        "version": nar.version,
        "mode": nar.mode,
        "provider": nar.provider,
        "model": nar.model_id,
        "prompt_sha256": nar.prompt_hash,
        "sentences": nar.sentences,
    }
    items["verification"] = ver.report
    items["approval"] = {
        "case_id": case.id,
        "title": case.title,
        "approved_by": approver.username,
        "approver_role": approver.role,
        "approved_at": signed_at,
        "ledger_head": {"seq": head.seq, "hash": head.hash},
    }
    return items


def approve(db: Session, case_id: int, user: User) -> Signature:
    case = get_case(db, case_id, lock=True)
    blockers = approval_blockers(db, case, user)
    if blockers:
        raise AppError(
            403, "approval-blocked", "You cannot approve this case", detail=" ".join(blockers)
        )
    signed_at = utcnow().replace(microsecond=0).astimezone(UTC).isoformat()
    items = _document(db, case, user, signed_at)
    tree = MerkleTree.build(items)
    key = signer()
    sig = Signature(
        case_id=case.id,
        merkle_root=tree.root,
        key_id=key.key_id,
        signature=key.sign(case.id, tree.root),
        signed_by=user.id,
        document=items,
    )
    db.add(sig)
    _set_state(case, CaseState.SIGNED)
    db.flush()
    ledger.append(
        db,
        case.id,
        EventType.SIGNED,
        user.id,
        {"merkle_root": tree.root, "key_id": key.key_id, "leaves": len(items)},
    )
    return sig


# ── export and verification ──────────────────────────────────────────────────


def export_document(db: Session, case_id: int) -> dict[str, Any]:
    case = get_case(db, case_id)
    sig = db.get(Signature, case.id)
    if sig is None:
        raise AppError(409, "not-signed", "Only signed cases can be exported")
    tree = MerkleTree.build(sig.document)
    key = signer()
    return {
        "format": EXPORT_FORMAT,
        "case_id": case.id,
        "title": case.title,
        "items": sig.document,
        "leaves": tree.leaf_hex(),
        "merkle_root": sig.merkle_root,
        "signature": {
            "algorithm": "Ed25519",
            "key_id": sig.key_id,
            "value": sig.signature,
            "message": f"verita-case-v1:{case.id}:{sig.merkle_root}",
            "signed_at": sig.signed_at.isoformat(),
        },
        "public_key_pem": key.describe()["public_key_pem"] if key.key_id == sig.key_id else None,
        "how_to_verify": (
            "Recompute each leaf as SHA-256(0x00 || JCS({name, value})) over `items`, build the "
            "RFC 6962 tree, compare with `merkle_root`, then check the Ed25519 signature over "
            "`signature.message` with the published key: `verita-verify <file> --pubkey <pem>`."
        ),
    }


def verify_export(export: dict[str, Any], public_pem: str | None = None) -> dict[str, Any]:
    """Recompute leaves and root and check the signature; name any leaf that changed."""
    items = export.get("items", {})
    tree = MerkleTree.build(items)
    changed = changed_leaves(export.get("leaves", {}), items)
    pem = public_pem or export.get("public_key_pem")
    signature_ok = False
    if pem:
        sig = export.get("signature", {})
        signature_ok = verify_signature(
            load_public_pem(pem),
            int(export.get("case_id", -1)),
            str(export.get("merkle_root")),
            str(sig.get("value", "")),
        )
    root_ok = tree.root == export.get("merkle_root")
    return {
        "valid": bool(signature_ok and root_ok and not changed),
        "signature_valid": signature_ok,
        "root_matches": root_ok,
        "recomputed_root": tree.root,
        "changed_leaves": changed,
    }


# ── read model ───────────────────────────────────────────────────────────────


def case_view(db: Session, case_id: int, viewer: User) -> dict[str, Any]:
    case = get_case(db, case_id)
    nar = _current_narrative(db, case)
    ver = _latest_verification(db, nar.id if nar else None)
    chain = ledger.events(db, case.id)
    sig = db.get(Signature, case.id)
    users = {u.id: u.username for u in db.scalars(select(User))}
    alert_ids = list(db.scalars(select(CaseAlert.alert_id).where(CaseAlert.case_id == case.id)))
    editable = CaseState(case.state) in EDITABLE
    return {
        "id": case.id,
        "title": case.title,
        "state": case.state,
        "created_by": users.get(case.created_by, "?"),
        "created_at": case.created_at.isoformat(),
        "updated_at": case.updated_at.isoformat(),
        "alert_ids": alert_ids,
        "evidence": sorted(evidence_items(db, case.id).values(), key=lambda e: e["id"]),
        "narrative": None
        if nar is None
        else {
            "id": nar.id,
            "version": nar.version,
            "mode": nar.mode,
            "provider": nar.provider,
            "model": nar.model_id,
            "prompt_hash": nar.prompt_hash,
            "sentences": nar.sentences,
            "created_by": users.get(nar.created_by, "?"),
            "created_at": nar.created_at.isoformat(),
        },
        "verification": None
        if ver is None
        else {
            "id": ver.id,
            "passed": ver.passed,
            "report": ver.report,
            "created_at": ver.created_at.isoformat(),
        },
        "events": [
            {
                "seq": e.seq,
                "type": e.type,
                "actor": users.get(e.actor_id) if e.actor_id else None,
                "payload": e.payload,
                "created_at": e.created_at.isoformat(),
                "hash": e.hash,
                "prev_hash": e.prev_hash,
            }
            for e in chain
        ],
        "ledger": ledger.verify_chain(chain),
        "signature": None
        if sig is None
        else {
            "merkle_root": sig.merkle_root,
            "key_id": sig.key_id,
            "signed_by": users.get(sig.signed_by, "?"),
            "signed_at": sig.signed_at.isoformat(),
        },
        "permissions": {
            "edit": editable and viewer.role in (Role.ANALYST, Role.MLRO),
            "submit": case.state == CaseState.VERIFIED and viewer.role in (Role.ANALYST, Role.MLRO),
            "approve": not approval_blockers(db, case, viewer),
            "approve_blockers": approval_blockers(db, case, viewer),
            "return": case.state == CaseState.SUBMITTED and viewer.role == Role.MLRO,
            "close": case.state not in (CaseState.SIGNED, CaseState.CLOSED)
            and viewer.role in (Role.ANALYST, Role.MLRO),
        },
    }


def list_cases(db: Session) -> list[dict[str, Any]]:
    users = {u.id: u.username for u in db.scalars(select(User))}
    grouped = db.execute(select(CaseAlert.case_id, func.count()).group_by(CaseAlert.case_id))
    counts = {int(case_id): int(n) for case_id, n in grouped}
    rows = db.scalars(select(Case).order_by(Case.updated_at.desc(), Case.id.desc())).all()
    return [
        {
            "id": c.id,
            "title": c.title,
            "state": c.state,
            "created_by": users.get(c.created_by, "?"),
            "updated_at": c.updated_at.isoformat(),
            "alerts": int(counts.get(c.id, 0)),
        }
        for c in rows
    ]
