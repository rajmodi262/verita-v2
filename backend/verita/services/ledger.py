"""The case ledger: append-only, hash-chained events (PIVOT §8.5).

``hash = SHA-256(prev_hash ‖ JCS({case_id, seq, type, actor_id, payload, created_at}))``.
The first event of a case chains from 64 zeros. The database rejects UPDATE and DELETE (see
:mod:`verita.db.case_models`), and :func:`verify_chain` recomputes every hash, so a row edited
behind the application's back — or a deleted event — is detected.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from verita.db.base import utcnow
from verita.db.case_models import GENESIS_HASH, Case, CaseEvent
from verita.defend.canonical import canonicalize


def event_hash(
    prev_hash: str,
    case_id: int,
    seq: int,
    type_: str,
    actor_id: int | None,
    payload: dict[str, Any],
    created_at: datetime,
) -> str:
    body = canonicalize(
        {
            "case_id": case_id,
            "seq": seq,
            "type": type_,
            "actor_id": actor_id,
            "payload": payload,
            "created_at": created_at.isoformat(),
        }
    )
    return hashlib.sha256(prev_hash.encode("ascii") + body).hexdigest()


def append(
    db: Session, case_id: int, type_: str, actor_id: int | None, payload: dict[str, Any]
) -> CaseEvent:
    # Serialise appends per case by locking the case row, not the last event: it also covers a
    # case with no events yet, and the application's database role may not lock ledger rows
    # (row locks need UPDATE privilege, which it does not have on case_events).
    db.execute(select(Case.id).where(Case.id == case_id).with_for_update())
    last = db.scalar(
        select(CaseEvent)
        .where(CaseEvent.case_id == case_id)
        .order_by(CaseEvent.seq.desc())
        .limit(1)
    )
    seq = last.seq + 1 if last else 1
    prev = last.hash if last else GENESIS_HASH
    created = utcnow().replace(microsecond=0)
    ev = CaseEvent(
        case_id=case_id,
        seq=seq,
        type=type_,
        actor_id=actor_id,
        payload=payload,
        created_at=created,
        prev_hash=prev,
        hash=event_hash(prev, case_id, seq, type_, actor_id, payload, created),
    )
    db.add(ev)
    db.flush()
    return ev


def events(db: Session, case_id: int) -> list[CaseEvent]:
    return list(
        db.scalars(select(CaseEvent).where(CaseEvent.case_id == case_id).order_by(CaseEvent.seq))
    )


def verify_chain(chain: Sequence[CaseEvent]) -> dict[str, Any]:
    """Recompute the chain; report the first event whose link or hash does not hold."""
    prev = GENESIS_HASH
    for expected_seq, ev in enumerate(chain, start=1):
        if ev.seq != expected_seq:
            return {"valid": False, "broken_at": ev.seq, "reason": f"missing event {expected_seq}"}
        if ev.prev_hash != prev:
            return {"valid": False, "broken_at": ev.seq, "reason": "prev_hash does not link"}
        recomputed = event_hash(
            ev.prev_hash, ev.case_id, ev.seq, ev.type, ev.actor_id, ev.payload, ev.created_at
        )
        if recomputed != ev.hash:
            return {"valid": False, "broken_at": ev.seq, "reason": "event content was altered"}
        prev = ev.hash
    return {"valid": True, "broken_at": None, "reason": None, "head": prev, "length": len(chain)}
