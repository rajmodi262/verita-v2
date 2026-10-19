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
