from fastapi.testclient import TestClient

from tests.conftest import PASSWORD
from verita.db.models import Role

PROBLEM = "application/problem+json"


def test_login_sets_hardened_cookies(client, make_user):
    make_user()
    r = client.post("/api/v1/auth/login", json={"username": "priya", "password": PASSWORD})
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["username"] == "priya" and body["user"]["role"] == "analyst"
    cookies = r.headers.get_list("set-cookie")
    session = next(c for c in cookies if c.startswith("verita_session="))
    csrf = next(c for c in cookies if c.startswith("verita_csrf="))
    assert "HttpOnly" in session and "Path=/api" in session and "SameSite=lax" in session
    assert "HttpOnly" not in csrf


def test_bad_login_is_problem_json(client, make_user):
    make_user()
    r = client.post("/api/v1/auth/login", json={"username": "priya", "password": "nope-nope-x"})
    assert r.status_code == 401
    assert r.headers["content-type"] == PROBLEM
    assert r.json()["type"].endswith("/invalid-credentials")
    assert "request_id" in r.json()


def test_me_requires_session(client):
    r = client.get("/api/v1/me")
    assert r.status_code == 401 and r.headers["content-type"] == PROBLEM


def test_me_returns_current_user(client, make_user, login):
    make_user(role=Role.MLRO)
    login()
    r = client.get("/api/v1/me")
    assert r.status_code == 200 and r.json()["role"] == "mlro"


def test_logout_requires_csrf(client, make_user, login):
    make_user()
    login()
    r = client.post("/api/v1/auth/logout")
    assert r.status_code == 403 and r.json()["type"].endswith("/csrf-failed")
    r = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": "forged"})
    assert r.status_code == 403


def test_logout_with_csrf_ends_session(client, make_user, login):
    make_user()
    csrf = login()
    r = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 204
    assert client.get("/api/v1/me").status_code == 401


def test_csrf_token_is_bound_to_its_session(app, make_user):
    """A CSRF token from one session must not work for another."""
    make_user("priya")
    make_user("marcus", Role.MLRO)
    with TestClient(app) as a, TestClient(app) as b:
        token_a = a.post(
            "/api/v1/auth/login", json={"username": "priya", "password": PASSWORD}
        ).json()["csrf_token"]
        b.post("/api/v1/auth/login", json={"username": "marcus", "password": PASSWORD})
        assert b.post("/api/v1/auth/logout", headers={"X-CSRF-Token": token_a}).status_code == 403


def test_validation_errors_are_structured(client):
    r = client.post("/api/v1/auth/login", json={"username": ""})
    assert r.status_code == 422 and r.headers["content-type"] == PROBLEM
    locs = {tuple(e["loc"]) for e in r.json()["errors"]}
    assert ("body", "password") in locs
