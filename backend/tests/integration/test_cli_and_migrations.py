from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect
from typer.testing import CliRunner

from verita.cli import alembic_config, app
from verita.core.config import get_settings

runner = CliRunner()


@pytest.fixture
def db_url(tmp_path: Path, monkeypatch):
    url = f"sqlite+pysqlite:///{tmp_path.as_posix()}/cli.sqlite"
    monkeypatch.setenv("VERITA_DATABASE_URL", url)
    monkeypatch.delenv("VERITA_DEMO_PASSWORD", raising=False)
    get_settings.cache_clear()
    yield url
    get_settings.cache_clear()


def test_upgrade_creates_tables_and_matches_models(db_url):
    result = runner.invoke(app, ["db", "upgrade"])
    assert result.exit_code == 0, result.output
    tables = set(inspect(create_engine(db_url)).get_table_names())
    assert {"users", "sessions", "audit_log", "alembic_version"} <= tables
    command.check(alembic_config(db_url))  # raises if models and migrations disagree


def test_downgrade_is_clean(db_url):
    runner.invoke(app, ["db", "upgrade"])
    command.downgrade(alembic_config(db_url), "base")
    assert set(inspect(create_engine(db_url)).get_table_names()) == {"alembic_version"}


def test_users_create_and_duplicate(db_url):
    runner.invoke(app, ["db", "upgrade"])
    args = [
        "users",
        "create",
        "--username",
        "marcus",
        "--role",
        "mlro",
        "--password",
        "a-long-enough-password",
    ]
    ok = runner.invoke(app, args)
    assert ok.exit_code == 0 and "Created marcus" in ok.output
    dup = runner.invoke(app, args)
    assert dup.exit_code == 1 and "already exists" in dup.output


def test_seed_demo_is_idempotent(db_url):
    runner.invoke(app, ["db", "upgrade"])
    first = runner.invoke(app, ["users", "seed-demo"])
    assert first.exit_code == 0 and "Generated password" in first.output
    second = runner.invoke(app, ["users", "seed-demo"])
    assert "nothing changed" in second.output


def test_seed_demo_uses_configured_password(db_url, monkeypatch):
    monkeypatch.setenv("VERITA_DEMO_PASSWORD", "demo-password-1234")
    runner.invoke(app, ["db", "upgrade"])
    out = runner.invoke(app, ["users", "seed-demo"])
    assert out.exit_code == 0 and "Generated password" not in out.output
