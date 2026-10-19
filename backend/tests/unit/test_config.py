import pytest
from pydantic import ValidationError

from verita.core.config import Settings, get_settings


def test_defaults_are_safe_for_dev():
    s = Settings(_env_file=None)
    assert s.env == "dev"
    assert not s.cookie_secure
    assert s.login_max_failures == 5


def test_prod_requires_postgres():
    with pytest.raises(ValidationError, match="PostgreSQL"):
        Settings(env="prod", database_url="sqlite+pysqlite:///x.sqlite", _env_file=None)


def test_prod_with_postgres_sets_secure_cookies():
    s = Settings(env="prod", database_url="postgresql+psycopg://u:p@h/db", _env_file=None)
    assert s.is_prod and s.cookie_secure


def test_env_variables_are_read(monkeypatch):
    monkeypatch.setenv("VERITA_SESSION_TTL_MINUTES", "60")
    get_settings.cache_clear()
    try:
        assert get_settings().session_ttl_minutes == 60
    finally:
        get_settings.cache_clear()


def test_bounds_are_enforced():
    with pytest.raises(ValidationError):
        Settings(session_ttl_minutes=1, _env_file=None)
