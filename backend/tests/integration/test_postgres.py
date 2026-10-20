"""Runs the migrations against real Postgres. Skipped when no Postgres is available."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect

from verita.cli import alembic_config

pytestmark = pytest.mark.postgres


@pytest.fixture(scope="module")
def pg_url() -> Iterator[str]:
    url = os.environ.get("VERITA_TEST_DATABASE_URL")
    if url:
        yield url
        return
    try:
        from testcontainers.postgres import PostgresContainer

        container = PostgresContainer("postgres:16-alpine", driver="psycopg")
        container.start()
    except Exception as exc:  # noqa: BLE001 - any Docker failure means "skip", stated in output
        pytest.skip(f"Postgres unavailable: {exc}")
    try:
        yield container.get_connection_url()
    finally:
        container.stop()


def test_migrations_on_postgres(pg_url):
    cfg = alembic_config(pg_url)
    command.upgrade(cfg, "head")
    command.check(cfg)
    tables = set(inspect(create_engine(pg_url)).get_table_names())
    assert {"users", "sessions", "audit_log"} <= tables
    command.downgrade(cfg, "base")


@pytest.fixture
def pg_migrated(pg_url):
    cfg = alembic_config(pg_url)
    command.upgrade(cfg, "head")
    try:
        yield pg_url
    finally:
        command.downgrade(cfg, "base")


def test_ledger_is_append_only_on_postgres(pg_migrated):
    from datetime import UTC, datetime

    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    engine = create_engine(pg_migrated)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (username, password_hash, role, failed_logins, created_at) "
                "VALUES ('u', 'x', 'analyst', 0, :t)"
            ),
            {"t": datetime.now(UTC)},
        )
        conn.execute(
            text(
                "INSERT INTO cases (title, state, created_by, created_at, updated_at) "
                "VALUES ('c', 'draft', 1, :t, :t)"
            ),
            {"t": datetime.now(UTC)},
        )
        conn.execute(
            text(
                "INSERT INTO case_events"
                " (case_id, seq, type, payload, created_at, prev_hash, hash) "
                "VALUES (1, 1, 'case.created', '{}', :t, :p, :h)"
            ),
            {"t": datetime.now(UTC), "p": "0" * 64, "h": "a" * 64},
        )
    for sql in ("UPDATE case_events SET type = 'x'", "DELETE FROM case_events"):
        with pytest.raises(DBAPIError, match="append-only"), engine.begin() as conn:
            conn.execute(text(sql))
    engine.dispose()


def test_job_claims_skip_locked_rows_on_postgres(pg_migrated):
    from sqlalchemy.orm import sessionmaker

    from verita.services import jobs

    engine = create_engine(pg_migrated)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as db:
        first = jobs.enqueue(db, "k", {}, None).id
        second = jobs.enqueue(db, "k", {}, None).id
    # a first worker holds a claim open; a second worker must take the next job, not wait
    a = factory()
    b = factory()
    try:
        got_a = jobs.claim(a)
        got_b = jobs.claim(b)
        assert got_a is not None and got_b is not None
        assert {got_a.id, got_b.id} == {first, second}
        a.commit()
        b.commit()
    finally:
        a.close()
        b.close()
        engine.dispose()
