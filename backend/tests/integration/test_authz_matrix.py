"""Authorization matrix (M7.11): every API route × every role, default deny.

The matrix below is the policy. The test enumerates the live OpenAPI document, so adding a
route without deciding who may call it fails here. Authorization runs before any lookup, so an
empty database is enough: a permitted call may 404/409/422/503, but never 401/403; a forbidden
one is always 403; an anonymous one is always 401 (except the public routes).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.conftest import PASSWORD
from verita.api.app import create_app
from verita.core.config import Settings
from verita.db.base import Base
from verita.db.models import Role
from verita.services.auth import AuthService

ALL = {"analyst", "mlro", "validator", "reviewer"}
MAKERS = {"analyst", "mlro"}
MLRO = {"mlro"}
PUBLIC = "public"

# (method, path) -> roles allowed, or PUBLIC
POLICY: dict[tuple[str, str], set[str] | str] = {
    ("GET", "/api/v1/health/live"): PUBLIC,
    ("GET", "/api/v1/health/ready"): PUBLIC,
    ("POST", "/api/v1/auth/login"): PUBLIC,
    ("GET", "/api/v1/keys"): PUBLIC,
    ("POST", "/api/v1/auth/logout"): ALL,
    ("GET", "/api/v1/me"): ALL,
    ("GET", "/api/v1/alerts"): ALL,
    ("GET", "/api/v1/alerts/meta"): ALL,
    ("GET", "/api/v1/alerts/{alert_id}"): ALL,
    ("GET", "/api/v1/alerts/{alert_id}/subgraph"): ALL,
    ("POST", "/api/v1/alerts/{alert_id}/disposition"): MAKERS,
    ("GET", "/api/v1/capacity/meta"): ALL,
    ("GET", "/api/v1/capacity/staffing"): ALL,
    ("GET", "/api/v1/capacity/frontier"): ALL,
    ("GET", "/api/v1/capacity/plan"): ALL,
    ("POST", "/api/v1/capacity/plans"): MLRO,
    ("GET", "/api/v1/capacity/plans/latest"): ALL,
    ("GET", "/api/v1/capacity/forecast"): ALL,
    ("GET", "/api/v1/capacity/coverage"): ALL,
    ("GET", "/api/v1/capacity/calibration"): ALL,
    ("GET", "/api/v1/capacity/drift"): ALL,
    ("GET", "/api/v1/cases/meta"): ALL,
    ("GET", "/api/v1/cases"): ALL,
    ("POST", "/api/v1/cases"): MAKERS,
    ("GET", "/api/v1/cases/{case_id}"): ALL,
    ("POST", "/api/v1/cases/{case_id}/narrative"): MAKERS,
    ("PUT", "/api/v1/cases/{case_id}/narrative"): MAKERS,
    ("POST", "/api/v1/cases/{case_id}/verify"): MAKERS,
    ("POST", "/api/v1/cases/{case_id}/submit"): MAKERS,
    ("POST", "/api/v1/cases/{case_id}/approve"): MLRO,
    ("POST", "/api/v1/cases/{case_id}/return"): MLRO,
    ("POST", "/api/v1/cases/{case_id}/close"): MAKERS,
    ("GET", "/api/v1/cases/{case_id}/verify-signature"): ALL,
    ("GET", "/api/v1/cases/{case_id}/export.json"): ALL,
    ("GET", "/api/v1/cases/{case_id}/export-tampered.json"): ALL,
    ("GET", "/api/v1/cases/{case_id}/export.pdf"): ALL,
    ("GET", "/api/v1/jobs/{job_id}"): ALL,
    ("GET", "/api/v1/evidence-room/metrics"): ALL,
    ("GET", "/api/v1/evidence-room/headline"): PUBLIC,
}

BODIES = {
    "/api/v1/auth/login": {"username": "nobody", "password": "x" * 12},
    "/api/v1/alerts/{alert_id}/disposition": {"action": "dismiss", "reason_code": "x"},
    "/api/v1/capacity/plans": {
        "date": "2022-09-08",
        "analysts": 2,
        "alpha": 0.05,
        "mode": "pooled",
    },
    "/api/v1/cases": {"alert_ids": [1]},
    "/api/v1/cases/{case_id}/narrative": {"mode": "offline"},
    "/api/v1/cases/{case_id}/return": {"reason": "narrative_unclear"},
    "/api/v1/cases/{case_id}/close": {"reason": "no_suspicion"},
}
QUERY = {
    "/api/v1/capacity/frontier": {"date": "2022-09-08"},
    "/api/v1/capacity/plan": {"date": "2022-09-08", "analysts": 2},
    "/api/v1/capacity/plans/latest": {"date": "2022-09-08"},
}


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    keys = tmp_path_factory.mktemp("keys")
    settings = Settings(
        env="test",
        database_url="sqlite+pysqlite:///:memory:",
        data_root=tmp_path_factory.mktemp("data"),
        signing_key_path=keys / "k.pem",
        public_key_path=keys / "pub.pem",
        llm_providers=[],
        _env_file=None,
    )
    application = create_app(settings)
    Base.metadata.create_all(application.state.engine)
    with application.state.session_factory() as db:
        auth = AuthService(db, settings)
        for role in Role:
            auth.create_user(role.value, PASSWORD, role)
        db.commit()
    return application


def _call(client: TestClient, method: str, path: str, csrf: str | None):
    url = path.replace("{alert_id}", "1").replace("{case_id}", "1").replace("{job_id}", "1")
    body = BODIES.get(path)
    if path.endswith("/narrative") and method == "PUT":
        body = {"sentences": [{"section": "who", "text": "x", "evidence_ids": ["EV-CASE-1"]}]}
    headers = {"X-CSRF-Token": csrf} if csrf else {}
    return client.request(method, url, json=body, params=QUERY.get(path), headers=headers)


def test_every_route_has_a_policy(app):
    live = {(m.upper(), p) for p, item in app.openapi()["paths"].items() for m in item}
    assert live == set(POLICY), {"unlisted": live - set(POLICY), "stale": set(POLICY) - live}


@pytest.mark.parametrize(("method", "path"), sorted(POLICY))
def test_anonymous_is_rejected_except_public_routes(app, method, path):
    response = _call(TestClient(app), method, path, None)
    status = response.status_code
    if path == "/api/v1/auth/login":  # reachable; the made-up credentials are what fail
        assert status == 401 and response.json()["type"].endswith("/invalid-credentials")
    elif POLICY[(method, path)] == PUBLIC:
        assert status not in (401, 403), status
    else:
        assert status == 401, status


@pytest.mark.parametrize("role", sorted(ALL))
def test_each_role_gets_exactly_its_policy(app, role):
    client = TestClient(app)
    login = client.post("/api/v1/auth/login", json={"username": role, "password": PASSWORD})
    csrf = login.json()["csrf_token"]
    wrong = []
    for (method, path), allowed in sorted(POLICY.items()):
        if allowed == PUBLIC or path == "/api/v1/auth/logout":
            continue  # logout would end this session mid-matrix; covered by the auth tests
        status = _call(client, method, path, csrf).status_code
        permitted = role in allowed
        if permitted and status in (401, 403):
            wrong.append(f"{method} {path}: {role} should be allowed, got {status}")
        if not permitted and status != 403:
            wrong.append(f"{method} {path}: {role} should be forbidden, got {status}")
    assert not wrong, "\n".join(wrong)


def test_mutations_need_csrf(app):
    client = TestClient(app)
    client.post("/api/v1/auth/login", json={"username": "mlro", "password": PASSWORD})
    for (method, path), allowed in POLICY.items():
        if method != "GET" and allowed != PUBLIC:
            assert _call(client, method, path, None).status_code == 403, path
