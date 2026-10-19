"""Alert queue, detail, subgraph and dispositions over HTTP, on the fixture's real model."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.conftest import PASSWORD
from tests.pipeline.conftest import fx_dataset, fx_root, fx_run  # noqa: F401
from verita.api.app import create_app
from verita.core.config import Settings
from verita.db.base import Base
from verita.db.detect_models import Alert
from verita.db.models import Role
from verita.ml import stages
from verita.ml.detect import DetectConfig, run_detect
from verita.pipeline.config import PipelineError
from verita.services.auth import AuthService


@pytest.fixture(scope="module")
def loaded(fx_run, fx_dataset, fx_root):  # noqa: F811
    stages.stage_features(fx_dataset)
    run_detect(fx_dataset, DetectConfig.quick())
    settings = Settings(
        env="test",
        database_url="sqlite+pysqlite:///:memory:",
        data_root=fx_root,
        dataset="fixture",
        _env_file=None,
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)
    with app.state.session_factory() as db:
        report = stages.stage_alerts(fx_dataset, db)
        auth = AuthService(db, settings)
        for name, role in (
            ("priya", Role.ANALYST),
            ("marcus", Role.MLRO),
            ("elena", Role.VALIDATOR),
            ("rev", Role.REVIEWER),
        ):
            auth.create_user(name, PASSWORD, role)
        db.commit()
    return app, report


def client_for(app, username: str) -> tuple[TestClient, str]:
    client = TestClient(app)
    r = client.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD})
    assert r.status_code == 200
    return client, r.json()["csrf_token"]


def test_alerts_were_generated(loaded):
    _, report = loaded
    assert report["alerts"] > 0
    assert 0 < report["positive_alerts"] <= report["alerts"]


def test_queue_is_sorted_paginated_and_hides_truth(loaded):
    app, report = loaded
    client, _ = client_for(app, "priya")
    first = client.get("/api/v1/alerts", params={"limit": 5}).json()
    assert len(first["items"]) == 5 and first["total"] == report["alerts"]
    scores = [a["score"] for a in first["items"]]
    assert scores == sorted(scores, reverse=True)
    assert "truth_label" not in first["items"][0]
    second = client.get("/api/v1/alerts", params={"limit": 5, "cursor": first["next_cursor"]})
    ids = {a["id"] for a in first["items"]} & {a["id"] for a in second.json()["items"]}
    assert not ids  # pages don't overlap


def test_walking_every_page_returns_every_alert_once(loaded):
    app, report = loaded
    client, _ = client_for(app, "rev")
    seen, cursor = [], None
    while True:
        params = {"limit": 200, **({"cursor": cursor} if cursor else {})}
        page = client.get("/api/v1/alerts", params=params).json()
        seen += [a["id"] for a in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == len(set(seen)) == report["alerts"]


def test_filters_and_meta(loaded):
    app, _ = loaded
    client, _ = client_for(app, "elena")
    meta = client.get("/api/v1/alerts/meta").json()
    day = meta["days"][0]["date"]
    by_day = client.get("/api/v1/alerts", params={"date": day, "limit": 200}).json()
    assert by_day["total"] == meta["days"][0]["alerts"]
    assert all(a["alert_date"] == day for a in by_day["items"])
    high = client.get("/api/v1/alerts", params={"min_score": 0.9}).json()
    assert all(a["score"] >= 0.9 for a in high["items"])
    assert "dismiss_reasons" in meta and meta["model"]["threshold"] > 0


def test_bad_cursor_is_rejected(loaded):
    app, _ = loaded
    client, _ = client_for(app, "priya")
    r = client.get("/api/v1/alerts", params={"cursor": "not-base64!!"})
    assert r.status_code == 400 and r.json()["type"].endswith("/bad-cursor")


def test_detail_has_reasons_with_evidence_ids(loaded):
    app, _ = loaded
    client, _ = client_for(app, "priya")
    alert_id = client.get("/api/v1/alerts", params={"limit": 1}).json()["items"][0]["id"]
    detail = client.get(f"/api/v1/alerts/{alert_id}").json()
    assert 1 <= len(detail["reasons"]) <= 5
    assert detail["reasons"][0]["evidence_id"] == f"EV-REASON-{alert_id}-1"
    assert "risk score" in detail["reasons"][0]["text"]
    assert client.get("/api/v1/alerts/999999").status_code == 404


def test_subgraph_contains_the_alert_payment_and_a_path(loaded):
    app, _ = loaded
    client, _ = client_for(app, "priya")
    alert = client.get("/api/v1/alerts", params={"limit": 1}).json()["items"][0]
    graph = client.get(f"/api/v1/alerts/{alert['id']}/subgraph").json()
    txn_ids = {e["txn_id"] for e in graph["edges"]}
    assert alert["top_txn_id"] in txn_ids
    assert alert["top_txn_id"] in graph["dominant_path"]["txn_ids"]
    assert graph["center"] == alert["account_id"]
    assert any(n["is_center"] for n in graph["nodes"])
    assert len(graph["nodes"]) <= 60 and len(graph["edges"]) <= 200
    nodes = {n["id"] for n in graph["nodes"]}
    assert all(e["from"] in nodes and e["to"] in nodes for e in graph["edges"])
    assert all(e["ts"] < graph["window"]["to"] for e in graph["edges"])  # nothing after the day
    assert graph["motif"]["evidence_id"].startswith("EV-MOTIF-")


def test_disposition_rules(loaded):
    app, _ = loaded
    analyst, csrf = client_for(app, "priya")
    alert_id = analyst.get("/api/v1/alerts", params={"limit": 1, "status": "open"}).json()["items"][
        0
    ]["id"]
    url = f"/api/v1/alerts/{alert_id}/disposition"
    assert analyst.post(url, json={"action": "dismiss", "reason_code": "x"}).status_code == 403
    bad = analyst.post(
        url, json={"action": "dismiss", "reason_code": "nope"}, headers={"X-CSRF-Token": csrf}
    )
    assert bad.status_code == 422 and bad.json()["type"].endswith("/invalid-reason")
    ok = analyst.post(
        url,
        json={"action": "dismiss", "reason_code": "known_counterparty", "note": "Payroll account"},
        headers={"X-CSRF-Token": csrf},
    )
    assert ok.status_code == 200 and ok.json()["status"] == "dismissed"
    assert ok.json()["dispositions"][-1]["note"] == "Payroll account"
    again = analyst.post(
        url,
        json={"action": "escalate", "reason_code": "typology_match"},
        headers={"X-CSRF-Token": csrf},
    )
    assert again.status_code == 409
    reopened = analyst.post(
        url,
        json={"action": "reopen", "reason_code": "reopen_error"},
        headers={"X-CSRF-Token": csrf},
    )
    assert reopened.json()["status"] == "open" and len(reopened.json()["dispositions"]) == 2


def test_only_analysts_and_mlro_can_decide(loaded):
    app, _ = loaded
    for user, expected in (("elena", 403), ("rev", 403)):
        client, csrf = client_for(app, user)
        alert_id = client.get("/api/v1/alerts", params={"limit": 1}).json()["items"][0]["id"]
        r = client.post(
            f"/api/v1/alerts/{alert_id}/disposition",
            json={"action": "escalate", "reason_code": "typology_match"},
            headers={"X-CSRF-Token": csrf},
        )
        assert r.status_code == expected


def test_reloading_never_erases_worked_alerts(loaded, fx_dataset):  # noqa: F811
    app, _ = loaded
    with app.state.session_factory() as db, pytest.raises(PipelineError, match="analyst"):
        stages.stage_alerts(fx_dataset, db)


def test_reloading_unworked_alerts_replaces_them(fx_dataset):  # noqa: F811
    settings = Settings(env="test", database_url="sqlite+pysqlite:///:memory:", _env_file=None)
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)
    with app.state.session_factory() as db:
        first = stages.stage_alerts(fx_dataset, db)
        again = stages.stage_alerts(fx_dataset, db)
        assert again["model_version_id"] == first["model_version_id"]
        assert db.query(Alert).count() == again["alerts"]


def test_no_model_means_503(app, client, make_user, login):
    make_user()
    login()
    r = client.get("/api/v1/alerts")
    assert r.status_code == 503 and r.json()["type"].endswith("/no-model")
