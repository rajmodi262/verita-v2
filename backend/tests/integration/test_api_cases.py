"""Defend end to end over HTTP on the fixture: create → draft → verify → submit → sign → export."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from typer.testing import CliRunner

from tests.conftest import PASSWORD
from tests.pipeline.conftest import fx_dataset, fx_root, fx_run  # noqa: F401
from verita.api.app import create_app
from verita.core.config import Settings
from verita.db.base import Base
from verita.db.models import Role
from verita.defend.verify_cli import app as verify_cli
from verita.ml import stages
from verita.ml.detect import DetectConfig, run_detect
from verita.services.auth import AuthService

USERS = {
    "priya": Role.ANALYST,
    "omar": Role.ANALYST,
    "marcus": Role.MLRO,
    "maria": Role.MLRO,
    "rev": Role.REVIEWER,
}


@pytest.fixture(scope="module")
def env(fx_run, fx_dataset, fx_root, tmp_path_factory):  # noqa: F811
    stages.stage_features(fx_dataset)
    run_detect(fx_dataset, DetectConfig.quick())
    keys = tmp_path_factory.mktemp("keys")
    settings = Settings(
        env="test",
        database_url="sqlite+pysqlite:///:memory:",
        data_root=fx_root,
        dataset="fixture",
        signing_key_path=keys / "signing.pem",
        public_key_path=keys / "pub.pem",
        llm_providers=[],
        _env_file=None,
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)
    with app.state.session_factory() as db:
        stages.stage_alerts(fx_dataset, db)
        auth = AuthService(db, settings)
        for name, role in USERS.items():
            auth.create_user(name, PASSWORD, role)
        db.commit()
    return app, keys


class Api:
    def __init__(self, app, username: str):
        self.client = TestClient(app)
        r = self.client.post(
            "/api/v1/auth/login", json={"username": username, "password": PASSWORD}
        )
        assert r.status_code == 200
        self.headers = {"X-CSRF-Token": r.json()["csrf_token"]}

    def get(self, path, **kw):
        return self.client.get(f"/api/v1{path}", **kw)

    def post(self, path, body=None):
        return self.client.post(f"/api/v1{path}", json=body or {}, headers=self.headers)

    def put(self, path, body):
        return self.client.put(f"/api/v1{path}", json=body, headers=self.headers)


def top_alerts(api: Api, n: int) -> list[int]:
    items = api.get("/alerts", params={"limit": 50}).json()["items"]
    return [a["id"] for a in items[:n]]


def fresh_alert(api: Api) -> int:
    """A different open alert for each case (an alert belongs to one case at a time)."""
    items = api.get("/alerts", params={"limit": 200, "status": "open"}).json()["items"]
    return items[0]["id"]


def drafted_case(maker: Api) -> dict:
    case = maker.post("/cases", {"alert_ids": [fresh_alert(maker)]})
    assert case.status_code == 201, case.text
    case_id = case.json()["id"]
    job = maker.post(f"/cases/{case_id}/narrative", {"mode": "offline"})
    assert job.status_code == 202
    status = maker.get(f"/jobs/{job.json()['id']}").json()
    assert status["status"] == "done", status
    return maker.get(f"/cases/{case_id}").json()


def test_create_freezes_evidence_and_starts_the_ledger(env):
    app, _ = env
    priya = Api(app, "priya")
    alert_id = fresh_alert(priya)
    r = priya.post("/cases", {"alert_ids": [alert_id]})
    assert r.status_code == 201
    case = r.json()
    kinds = {e["kind"] for e in case["evidence"]}
    assert {"alert", "case", "motif"} <= kinds
    assert case["state"] == "draft" and case["narrative"] is None
    assert case["ledger"]["valid"] and case["events"][0]["type"] == "case.created"
    assert case["events"][0]["prev_hash"] == "0" * 64
    again = priya.post("/cases", {"alert_ids": [alert_id]})
    assert again.status_code == 409 and again.json()["type"].endswith("/alert-in-case")
    alert = priya.get(f"/alerts/{alert_id}").json()
    assert alert["status"] == "in_case"


def test_offline_draft_verifies_and_full_signing_path(env):
    app, keys = env
    priya, marcus = Api(app, "priya"), Api(app, "marcus")
    case = drafted_case(priya)
    case_id = case["id"]
    assert case["narrative"]["mode"] == "offline"
    assert case["verification"]["passed"], case["verification"]["report"]
    assert case["state"] == "verified"
    assert case["permissions"]["submit"] and not case["permissions"]["approve"]

    assert priya.post(f"/cases/{case_id}/approve").status_code == 403  # analysts never sign
    submitted = priya.post(f"/cases/{case_id}/submit").json()
    assert submitted["state"] == "submitted"

    view = marcus.get(f"/cases/{case_id}").json()
    assert view["permissions"]["approve"] and view["permissions"]["approve_blockers"] == []
    signed = marcus.post(f"/cases/{case_id}/approve")
    assert signed.status_code == 200, signed.text
    body = signed.json()
    assert body["state"] == "signed" and body["signature"]["signed_by"] == "marcus"
    assert [e["type"] for e in body["events"]][-1] == "case.signed"
    assert body["ledger"]["valid"]

    check = marcus.get(f"/cases/{case_id}/verify-signature").json()
    assert check["valid"] and check["changed_leaves"] == [] and check["ledger"]["valid"]

    # the export verifies offline with only the file and the published key
    export = priya.get(f"/cases/{case_id}/export.json")
    assert export.status_code == 200
    (keys / "case.json").write_bytes(export.content)
    pub = priya.client.get("/api/v1/keys").json()["keys"][0]
    (keys / "pub-from-api.pem").write_text(pub["public_key_pem"])
    runner = CliRunner()
    ok = runner.invoke(
        verify_cli, [str(keys / "case.json"), "--pubkey", str(keys / "pub-from-api.pem")]
    )
    assert ok.exit_code == 0, ok.output
    assert "VALID" in ok.output

    tampered = priya.get(f"/cases/{case_id}/export-tampered.json")
    (keys / "bad.json").write_bytes(tampered.content)
    bad = runner.invoke(
        verify_cli, [str(keys / "bad.json"), "--pubkey", str(keys / "pub-from-api.pem")]
    )
    assert bad.exit_code == 1
    assert "changed     EV-TXN-" in bad.output and "MISMATCH" in bad.output

    pdf = priya.get(f"/cases/{case_id}/export.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    # a signed case is frozen
    assert (
        priya.put(
            f"/cases/{case_id}/narrative", {"sentences": case["narrative"]["sentences"]}
        ).status_code
        == 409
    )


def test_maker_checker_blocks_self_approval(env):
    app, _ = env
    marcus = Api(app, "marcus")
    case = drafted_case(marcus)
    marcus.post(f"/cases/{case['id']}/submit")
    view = marcus.get(f"/cases/{case['id']}").json()
    assert not view["permissions"]["approve"]
    assert any("Maker-checker" in b for b in view["permissions"]["approve_blockers"])
    r = marcus.post(f"/cases/{case['id']}/approve")
    assert r.status_code == 403 and "Maker-checker" in r.json()["detail"]
    assert Api(app, "maria").post(f"/cases/{case['id']}/approve").status_code == 200


def test_edits_are_reverified_and_failures_block_submission(env):
    app, _ = env
    priya = Api(app, "priya")
    case = drafted_case(priya)
    sentences = case["narrative"]["sentences"]
    broken = json.loads(json.dumps(sentences))
    target = next(s for s in broken if "US Dollar" in s["text"])
    target["text"] = target["text"].replace("US Dollar", "Euro", 1)
    edited = priya.put(f"/cases/{case['id']}/narrative", {"sentences": broken}).json()
    assert edited["state"] == "draft"
    assert edited["narrative"]["mode"] == "edit" and edited["narrative"]["version"] == 2
    report = edited["verification"]["report"]
    assert not report["passed"] and report["failed_sentences"]
    failing = report["sentences"][report["failed_sentences"][0]]
    assert any(not c["passed"] for c in failing["claims"])
    blocked = priya.post(f"/cases/{case['id']}/submit")
    assert blocked.status_code == 409
    fixed = priya.put(f"/cases/{case['id']}/narrative", {"sentences": sentences}).json()
    assert fixed["state"] == "verified" and fixed["narrative"]["version"] == 3


def test_return_and_close(env):
    app, _ = env
    priya, marcus = Api(app, "priya"), Api(app, "marcus")
    case = drafted_case(priya)
    priya.post(f"/cases/{case['id']}/submit")
    assert marcus.post(f"/cases/{case['id']}/return", {"reason": "nope"}).status_code == 422
    returned = marcus.post(
        f"/cases/{case['id']}/return", {"reason": "narrative_unclear", "note": "tighten"}
    ).json()
    assert returned["state"] == "returned"
    assert returned["events"][-1]["payload"] == {"reason": "narrative_unclear", "note": "tighten"}
    redone = priya.post(f"/cases/{case['id']}/verify").json()
    assert redone["state"] == "verified"
    closed = priya.post(f"/cases/{case['id']}/close", {"reason": "no_suspicion"}).json()
    assert closed["state"] == "closed" and not closed["permissions"]["edit"]
    alert = priya.get(f"/alerts/{closed['alert_ids'][0]}").json()
    assert alert["status"] == "escalated"


def test_roles_and_meta(env):
    app, _ = env
    rev = Api(app, "rev")
    assert rev.post("/cases", {"alert_ids": top_alerts(rev, 1)}).status_code == 403
    meta = rev.get("/cases/meta").json()
    assert meta["offline_only"] is True and "narrative_unclear" in meta["return_reasons"]
    listing = rev.get("/cases").json()["items"]
    assert listing and {"id", "state", "alerts"} <= set(listing[0])
    assert rev.get("/cases/99999").status_code == 404
    assert TestClient(app).get("/api/v1/keys").status_code == 200  # public, no login
    assert TestClient(app).get("/api/v1/cases").status_code == 401


def test_ledger_rejects_update_and_delete(env):
    app, _ = env
    with app.state.engine.connect() as conn:
        for sql in ("UPDATE case_events SET type = 'x'", "DELETE FROM case_events"):
            with pytest.raises(DBAPIError, match="append-only"):
                conn.execute(text(sql))
            conn.rollback()
