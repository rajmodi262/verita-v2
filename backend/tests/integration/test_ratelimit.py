"""Rate limiting: per IP, stricter on login, per session on mutations; 429 problem+json."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.conftest import PASSWORD
from verita.api.app import create_app
from verita.api.ratelimit import SlidingWindow
from verita.core.config import Settings
from verita.db.base import Base
from verita.db.models import Role
from verita.services.auth import AuthService


def make_app(**limits):
    settings = Settings(
        env="test",
        database_url="sqlite+pysqlite:///:memory:",
        rate_limit_enabled=True,
        _env_file=None,
        **limits,
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)
    with app.state.session_factory() as db:
        AuthService(db, settings).create_user("priya", PASSWORD, Role.ANALYST)
        db.commit()
    return app


def test_sliding_window_forgets_old_hits():
    w = SlidingWindow(limit=2, window=10)
    assert w.check("a", 0) is None
    assert w.check("a", 1) is None
    assert w.check("a", 2) == pytest.approx(8)
    assert w.check("b", 2) is None  # keys are independent
    assert w.check("a", 10.5) is None  # the first hit has left the window


def test_login_is_limited_per_ip_with_a_problem_response():
    client = TestClient(make_app(rate_limit_login_per_ip=3))
    bad = {"username": "nobody", "password": "x" * 12}
    statuses = [client.post("/api/v1/auth/login", json=bad).status_code for _ in range(4)]
    assert statuses == [401, 401, 401, 429]
    r = client.post("/api/v1/auth/login", json=bad)
    assert r.headers["content-type"] == "application/problem+json"
    assert int(r.headers["retry-after"]) >= 1
    assert r.json()["type"].endswith("/rate-limited")
    assert "x-request-id" in r.headers  # still inside the request-context middleware


def test_all_api_traffic_is_limited_per_ip_except_liveness():
    client = TestClient(make_app(rate_limit_per_ip=5))
    codes = [client.get("/api/v1/me").status_code for _ in range(6)]
    assert codes[:5] == [401] * 5 and codes[5] == 429
    assert client.get("/api/v1/health/live").status_code == 200


def test_mutations_are_limited_per_session():
    client = TestClient(make_app(rate_limit_mutations_per_session=2))
    login = client.post("/api/v1/auth/login", json={"username": "priya", "password": PASSWORD})
    csrf = {"X-CSRF-Token": login.json()["csrf_token"]}
    codes = [
        client.post(
            "/api/v1/alerts/1/disposition",
            json={"action": "dismiss", "reason_code": "x"},
            headers=csrf,
        ).status_code
        for _ in range(3)
    ]
    assert 429 not in codes[:2] and codes[2] == 429
    assert client.get("/api/v1/me").status_code == 200  # reads are not mutations


def test_limiter_is_off_by_default_in_tests_and_on_elsewhere():
    assert Settings(env="test", _env_file=None).rate_limits_on is False
    assert Settings(env="dev", _env_file=None).rate_limits_on is True
