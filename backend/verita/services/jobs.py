"""A database job queue (PIVOT §8, M6.05): ``SELECT … FOR UPDATE SKIP LOCKED`` on PostgreSQL.

Narrative drafting calls an LLM and can take seconds, so the API enqueues a job and the client
polls ``GET /jobs/{id}``. Workers claim the oldest queued job with ``SKIP LOCKED``, so several
workers never take the same job and never block on each other. SQLite (dev) has no row locks;
there the claim is a single ``UPDATE … WHERE status = 'queued'`` that only one writer can win.

``VERITA_INLINE_JOBS`` (dev/demo) runs the job right after the request instead of waiting for
a separate ``verita worker`` process.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import CursorResult, select, update
from sqlalchemy.orm import Session, sessionmaker

from verita.core.errors import AppError
from verita.db.base import utcnow
from verita.db.case_models import Job, JobStatus
from verita.db.session import transaction

MAX_ATTEMPTS = 3
Handler = Callable[[Session, Job], dict[str, Any]]
HANDLERS: dict[str, Handler] = {}


def handler(kind: str) -> Callable[[Handler], Handler]:
    def register(fn: Handler) -> Handler:
        HANDLERS[kind] = fn
        return fn

    return register


def enqueue(db: Session, kind: str, payload: dict[str, Any], user_id: int | None) -> Job:
    job = Job(kind=kind, payload=payload, created_by=user_id, progress="queued")
    db.add(job)
    db.flush()
    return job


def get_job(db: Session, job_id: int) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise AppError(404, "job-not-found", "No such job")
    return job


def claim(db: Session, job_id: int | None = None) -> Job | None:
    """Take one queued job (a specific one, or the oldest) and mark it running."""
    stmt = select(Job).where(Job.status == JobStatus.QUEUED.value)
    if job_id is not None:
        stmt = stmt.where(Job.id == job_id)
    job = db.scalar(stmt.order_by(Job.id).limit(1).with_for_update(skip_locked=True))
    if job is None:
        return None
    result: CursorResult[Any] = db.execute(  # type: ignore[assignment]
        update(Job)
        .where(Job.id == job.id, Job.status == JobStatus.QUEUED.value)
        .values(
            status=JobStatus.RUNNING.value,
            attempts=Job.attempts + 1,
            progress="running",
            updated_at=utcnow(),
        )
    )
    if not result.rowcount:  # another worker got there first (SQLite path)
        return None
    db.refresh(job)
    return job


def run(factory: sessionmaker[Session], job_id: int | None = None) -> Job | None:
    """Claim and execute one job; the handler's work and the job's result commit together."""
    with transaction(factory) as db:
        job = claim(db, job_id)
        if job is None:
            return None
        claimed_id = job.id
    try:
        with transaction(factory) as db:
            job = db.get(Job, claimed_id)
            assert job is not None  # noqa: S101 - claimed in the previous transaction
            fn = HANDLERS.get(job.kind)
            if fn is None:
                msg = f"no handler for job kind {job.kind!r}"
                raise RuntimeError(msg)
            result = fn(db, job)
            job.status = JobStatus.DONE.value
            job.result = result
            job.progress = "done"
            job.updated_at = utcnow()
            return job
    except Exception as exc:  # noqa: BLE001 - a job failure is data, not a crash
        with transaction(factory) as db:
            job = db.get(Job, claimed_id)
            assert job is not None  # noqa: S101
            retry = job.attempts < MAX_ATTEMPTS and not isinstance(exc, AppError)
            job.status = JobStatus.QUEUED.value if retry else JobStatus.FAILED.value
            job.error = f"{type(exc).__name__}: {exc}"
            job.progress = "retrying" if retry else "failed"
            job.updated_at = utcnow()
            return job


def job_view(job: Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "attempts": job.attempts,
        "progress": job.progress,
        "result": job.result,
        "error": job.error,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
    }
