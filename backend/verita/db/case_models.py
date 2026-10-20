"""ORM models for Defend (M6): cases, evidence, narratives, verifications, ledger, signatures, jobs.

``case_events`` is the ledger. It is append-only in the database itself — a trigger rejects
UPDATE and DELETE on both PostgreSQL and SQLite — and every row carries the previous row's hash,
so rewriting history needs both write access *and* recomputing every later hash. Corrections are
new events that supersede old ones.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    DDL,
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column

from verita.db.base import Base, UTCDateTime, utcnow


class CaseState(StrEnum):
    DRAFT = "draft"
    VERIFIED = "verified"
    SUBMITTED = "submitted"
    SIGNED = "signed"
    RETURNED = "returned"
    CLOSED = "closed"


class EventType(StrEnum):
    CREATED = "case.created"
    NARRATIVE_DRAFTED = "narrative.drafted"
    NARRATIVE_EDITED = "narrative.edited"
    VERIFIED = "narrative.verified"
    SUBMITTED = "case.submitted"
    RETURNED = "case.returned"
    SIGNED = "case.signed"
    CLOSED = "case.closed"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


RETURN_REASONS = {
    "insufficient_evidence": "The evidence does not support filing yet",
    "narrative_unclear": "The narrative needs rewriting",
    "wrong_subject": "The case is about the wrong subject",
    "needs_more_alerts": "Related alerts should be added",
}
CLOSE_REASONS = {
    "no_suspicion": "Reviewed: no suspicion after investigation",
    "duplicate": "Duplicate of another case",
    "data_error": "Alerts were caused by a data error",
}

GENESIS_HASH = "0" * 64


def _check(column: str, values: type[StrEnum]) -> str:
    return f"{column} IN ({', '.join(repr(v.value) for v in values)})"


class Case(Base):
    __tablename__ = "cases"
    __table_args__ = (CheckConstraint(_check("state", CaseState), name="state_valid"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    state: Mapped[str] = mapped_column(String(16), default=CaseState.DRAFT.value, index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    current_narrative_id: Mapped[int | None] = mapped_column(Integer, default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class CaseAlert(Base):
    __tablename__ = "case_alerts"

    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("alerts.id"), primary_key=True, index=True)


class CaseEvidence(Base):
    """Immutable once written: the case's Merkle leaves are computed from these rows."""

    __tablename__ = "case_evidence"

    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), primary_key=True)
    evidence_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    leaf_hash: Mapped[str] = mapped_column(String(64))


class Narrative(Base):
    __tablename__ = "narratives"
    __table_args__ = (
        UniqueConstraint("case_id", "version", name="one_version"),
        CheckConstraint("mode IN ('llm', 'offline', 'edit')", name="mode_valid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    mode: Mapped[str] = mapped_column(String(8))
    provider: Mapped[str] = mapped_column(String(32))
    model_id: Mapped[str] = mapped_column(String(80))
    prompt_hash: Mapped[str] = mapped_column(String(64))
    sentences: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Verification(Base):
    __tablename__ = "verifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    narrative_id: Mapped[int] = mapped_column(ForeignKey("narratives.id"), index=True)
    passed: Mapped[bool] = mapped_column(Boolean)
    report: Mapped[dict[str, Any]] = mapped_column(JSON)
    verifier_version: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class CaseEvent(Base):
    """The append-only, hash-chained ledger."""

    __tablename__ = "case_events"
    __table_args__ = (UniqueConstraint("case_id", "seq", name="one_seq"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(32))
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), unique=True)


class Signature(Base):
    __tablename__ = "signatures"

    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"), primary_key=True)
    merkle_root: Mapped[str] = mapped_column(String(64))
    key_id: Mapped[str] = mapped_column(String(16))
    signature: Mapped[str] = mapped_column(String(128))
    signed_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    signed_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    # The exact items that were signed, so the export is byte-identical forever.
    document: Mapped[dict[str, Any]] = mapped_column(JSON)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(_check("status", JobStatus), name="status_valid"),
        Index("ix_jobs_claim", "status", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default=JobStatus.QUEUED.value)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    progress: Mapped[str] = mapped_column(Text, default="")
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


# ── append-only enforcement, in the database ─────────────────────────────────

SQLITE_APPEND_ONLY = [
    """CREATE TRIGGER case_events_no_update BEFORE UPDATE ON case_events
       BEGIN SELECT RAISE(ABORT, 'case_events is append-only'); END""",
    """CREATE TRIGGER case_events_no_delete BEFORE DELETE ON case_events
       BEGIN SELECT RAISE(ABORT, 'case_events is append-only'); END""",
]
POSTGRES_APPEND_ONLY = [
    """CREATE OR REPLACE FUNCTION case_events_append_only() RETURNS trigger AS $$
       BEGIN RAISE EXCEPTION 'case_events is append-only'; END; $$ LANGUAGE plpgsql""",
    """CREATE TRIGGER case_events_append_only BEFORE UPDATE OR DELETE ON case_events
       FOR EACH ROW EXECUTE FUNCTION case_events_append_only()""",
]

for _sql in SQLITE_APPEND_ONLY:
    event.listen(CaseEvent.__table__, "after_create", DDL(_sql).execute_if(dialect="sqlite"))  # type: ignore[no-untyped-call]
for _sql in POSTGRES_APPEND_ONLY:
    event.listen(CaseEvent.__table__, "after_create", DDL(_sql).execute_if(dialect="postgresql"))  # type: ignore[no-untyped-call]
