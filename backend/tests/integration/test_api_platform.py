import pytest
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from tests.conftest import PASSWORD
from verita.api.app import create_app
from verita.api.deps import require_role
from verita.core.config import Settings
from verita.db.models import Role


def test_live(client):
    r = client.get("/api/v1/health/live")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_ready(client):
    r = client.get("/api/v1/health/ready")
    assert r.status_code == 200
    assert r.json() == {"status": "ready", "checks": {"database": "ok"}}


def test_ready_reports_db_outage(app, client, monkeypatch):
    class Broken:
        def __enter__(self):
            raise OperationalError("SELECT 1", {}, Exception("down"))

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(app.state, "session_factory", Broken)
    r = client.get("/api/v1/health/ready")
    assert r.status_code == 503 and r.json()["type"].endswith("/not-ready")


def test_security_headers_and_request_id(client):
    r = client.get("/api/v1/health/live")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["content-security-policy"].startswith("default-src 'none'")
    assert len(r.headers["x-request-id"]) == 32


def test_safe_inbound_request_id_is_kept_and_unsafe_replaced(client):
    kept = client.get("/api/v1/health/live", headers={"X-Request-ID": "trace-12345678"})
    assert kept.headers["x-request-id"] == "trace-12345678"
    replaced = client.get("/api/v1/health/live", headers={"X-Request-ID": "<script>"})
    assert replaced.headers["x-request-id"] != "<script>"


def test_docs_are_not_given_the_api_csp(client):
    r = client.get("/api/docs")
    assert r.status_code == 200 and "content-security-policy" not in r.headers


def test_unknown_route_is_problem_json(client):
    r = client.get("/api/v1/nope")
    assert r.status_code == 404 and r.json()["type"].endswith("/not-found")


def test_cors_preflight_is_answered_before_auth(client):
    r = client.options(
        "/api/v1/auth/logout",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-csrf-token,content-type",
        },
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert r.headers["access-control-allow-credentials"] == "true"


def test_error_responses_carry_cors_headers(client):
    r = client.get("/api/v1/me", headers={"Origin": "http://localhost:5173"})
    assert r.status_code == 401
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_unknown_origin_gets_no_cors_grant(client):
    r = client.get("/api/v1/health/live", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers


def test_unhandled_errors_do_not_leak(app):
    router = APIRouter()

    @router.get("/api/v1/_boom")
    def boom() -> None:
        raise RuntimeError("secret internal detail")

    app.include_router(router)
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/api/v1/_boom")
    assert r.status_code == 500
    assert "secret" not in r.text
    assert r.json()["type"].endswith("/internal-error")


def test_prod_hides_docs():
    prod = create_app(
        Settings(env="prod", database_url="postgresql+psycopg://u:p@localhost/x", _env_file=None)
    )
    assert prod.docs_url is None


@pytest.mark.parametrize("role", list(Role))
def test_require_role_is_default_deny(app, make_user, role):
    router = APIRouter()

    @router.get("/api/v1/_mlro_only", dependencies=[Depends(require_role(Role.MLRO))])
    def mlro_only() -> dict[str, str]:
        return {"ok": "yes"}

    app.include_router(router)
    make_user(f"user-{role.value}", role)
    with TestClient(app) as c:
        assert c.get("/api/v1/_mlro_only").status_code == 401
        c.post("/api/v1/auth/login", json={"username": f"user-{role.value}", "password": PASSWORD})
        expected = 200 if role is Role.MLRO else 403
        assert c.get("/api/v1/_mlro_only").status_code == expected


def test_evidence_room_serves_the_metrics_file_with_its_hash(tmp_path):
    import hashlib

    from fastapi.testclient import TestClient

    from tests.conftest import PASSWORD
    from verita.api.app import create_app
    from verita.core.config import Settings
    from verita.db.base import Base
    from verita.db.models import Role
    from verita.services.auth import AuthService

    settings = Settings(
        env="test", database_url="sqlite+pysqlite:///:memory:", data_root=tmp_path, _env_file=None
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)
    with app.state.session_factory() as db:
        AuthService(db, settings).create_user("val", PASSWORD, Role.VALIDATOR)
        db.commit()
    client = TestClient(app)
    client.post("/api/v1/auth/login", json={"username": "val", "password": PASSWORD})
    missing = client.get("/api/v1/evidence-room/metrics")
    assert missing.status_code == 503 and missing.json()["type"].endswith("/no-metrics")
    (tmp_path / "reports").mkdir()
    raw = b'{"schema_version": 1, "headline": []}'
    (tmp_path / "reports" / "metrics.json").write_bytes(raw)
    public = TestClient(app).get("/api/v1/evidence-room/headline").json()
    assert public["headline"] == [] and public["sha256"] == hashlib.sha256(raw).hexdigest()
    body = client.get("/api/v1/evidence-room/metrics").json()
    assert body == {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "metrics": {"schema_version": 1, "headline": []},
    }
