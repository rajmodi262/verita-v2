"""Decide end to end on the fixture: run_decide artifacts, then the capacity API."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from tests.conftest import PASSWORD
from tests.pipeline.conftest import fx_dataset, fx_root, fx_run  # noqa: F401
from verita.api.app import create_app
from verita.core.config import Settings
from verita.db.base import Base
from verita.db.detect_models import Alert
from verita.db.models import AuditLog, Role
from verita.ml import stages
from verita.ml.detect import DetectConfig, run_detect
from verita.services.auth import AuthService


@pytest.fixture(scope="module")
def decided(fx_run, fx_dataset, fx_root):  # noqa: F811
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
        stages.stage_alerts(fx_dataset, db)
        report = stages.stage_decide(fx_dataset, db)
        auth = AuthService(db, settings)
        auth.create_user("priya", PASSWORD, Role.ANALYST)
        auth.create_user("marcus", PASSWORD, Role.MLRO)
        db.commit()
    return app, report, fx_dataset


def login(app, username: str) -> tuple[TestClient, str]:
    client = TestClient(app)
    r = client.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD})
    assert r.status_code == 200
    return client, r.json()["csrf_token"]


def test_decide_writes_every_artifact(decided):
    _, report, dataset = decided
    out = dataset.artifacts_dir / "decide"
    for name in ("calibration", "thresholds", "coverage", "forecast", "drift", "frontier"):
        assert (out / f"{name}.json").exists(), name
    assert (out / "isotonic.joblib").exists()
    assert report["headline"]["target_recall"] == pytest.approx(0.95)
    thresholds = json.loads((out / "thresholds.json").read_text())
    assert set(thresholds) == {"0.01", "0.05", "0.1", "0.2"}


def test_alerts_get_calibrated_probabilities(decided):
    app, _, _ = decided
    with app.state.session_factory() as db:
        probs = [p for (p,) in db.query(Alert.calibrated_prob).all()]
    assert probs and all(p is not None and 0 <= p <= 1 for p in probs)


def test_meta_frontier_and_artifact_endpoints(decided):
    app, _, _ = decided
    client, _ = login(app, "priya")
    meta = client.get("/api/v1/capacity/meta").json()
    assert meta["days"] and meta["modes"] == ["pooled", "mondrian"]
    day = meta["days"][0]
    front = client.get("/api/v1/capacity/frontier", params={"date": day, "alpha": 0.05}).json()
    analysts = [p["analysts"] for p in front["points"]]
    assert analysts == sorted(analysts)
    for path in ("forecast", "calibration", "drift"):
        assert client.get(f"/api/v1/capacity/{path}").status_code == 200
    cov = client.get("/api/v1/capacity/coverage", params={"alpha": 0.1}).json()
    assert {"static_pooled", "static_mondrian", "aci_pooled"} <= set(cov["runs"])
    bad = client.get("/api/v1/capacity/coverage", params={"alpha": 0.3})
    assert bad.status_code == 422


def test_plan_is_exact_and_respects_the_guarantee(decided):
    app, _, _ = decided
    client, _ = login(app, "priya")
    day = client.get("/api/v1/alerts/meta").json()["days"][0]["date"]
    plan = client.get(
        "/api/v1/capacity/plan", params={"date": day, "analysts": 3, "alpha": 0.05}
    ).json()
    assert plan["reviewed"] == len(plan["selected_alert_ids"])
    assert plan["review_minutes"] <= plan["capacity_minutes"]
    if plan["guarantee"]["feasible"]:
        assert set(plan["guaranteed_alert_ids"]) <= set(plan["selected_alert_ids"])
    assert plan["optimality_gap"] >= 0
    mondrian = client.get(
        "/api/v1/capacity/plan",
        params={"date": day, "analysts": 3, "alpha": 0.05, "mode": "mondrian"},
    )
    assert mondrian.status_code == 200 and mondrian.json()["threshold"] is None


def test_plan_validation(decided):
    app, _, _ = decided
    client, _ = login(app, "priya")
    r = client.get("/api/v1/capacity/plan", params={"date": "2001-01-01", "analysts": 3})
    assert r.status_code == 404
    r = client.get("/api/v1/capacity/plan", params={"date": "2022-09-01", "analysts": 0})
    assert r.status_code == 422
    r = client.get(
        "/api/v1/capacity/plan", params={"date": "2022-09-01", "analysts": 3, "mode": "x"}
    )
    assert r.status_code == 422


def test_only_mlro_saves_plans_and_saving_is_audited(decided):
    app, _, _ = decided
    analyst, csrf = login(app, "priya")
    day = analyst.get("/api/v1/alerts/meta").json()["days"][0]["date"]
    body = {"date": day, "analysts": 2, "alpha": 0.05, "mode": "pooled"}
    denied = analyst.post("/api/v1/capacity/plans", json=body, headers={"X-CSRF-Token": csrf})
    assert denied.status_code == 403
    mlro, csrf = login(app, "marcus")
    assert mlro.post("/api/v1/capacity/plans", json=body).status_code == 403  # no CSRF
    saved = mlro.post("/api/v1/capacity/plans", json=body, headers={"X-CSRF-Token": csrf})
    assert saved.status_code == 200
    latest = analyst.get("/api/v1/capacity/plans/latest", params={"date": day}).json()
    assert latest["id"] == saved.json()["id"] and latest["analysts"] == 2
    missing = analyst.get("/api/v1/capacity/plans/latest", params={"date": "2001-01-01"})
    assert missing.status_code == 404
    with app.state.session_factory() as db:
        actions = [a for (a,) in db.query(AuditLog.action).all()]
    assert "capacity.plan_saved" in actions


def test_staffing_and_what_if(decided):
    app, _, _ = decided
    client, _ = login(app, "priya")
    staffing = client.get("/api/v1/capacity/staffing", params={"alpha": 0.05}).json()
    assert staffing["days"] and all(d["analysts_needed"] >= 1 for d in staffing["days"])
    day = client.get("/api/v1/alerts/meta").json()["days"][0]["date"]
    base = {"date": day, "analysts": 2, "alpha": 0.05}
    plain = client.get("/api/v1/capacity/plan", params=base).json()
    slower = client.get("/api/v1/capacity/plan", params={**base, "median_minutes": 120}).json()
    assert slower["assumptions"]["overridden"] == ["median_minutes"]
    assert slower["assumptions"]["median_minutes"] == 120
    assert slower["reviewed"] <= plain["reviewed"]
    bad = client.get("/api/v1/capacity/plan", params={**base, "productive_hours": 30})
    assert bad.status_code == 422


def test_objective_parameter(decided):
    app, _, _ = decided
    client, _ = login(app, "priya")
    meta = client.get("/api/v1/capacity/meta").json()
    assert meta["objectives"] == ["cases", "value"]
    day = meta["days"][0]
    params = {"date": day, "alpha": 0.05, "objective": "value"}
    front = client.get("/api/v1/capacity/frontier", params=params).json()
    assert front["objective"] == "value" and front["points"][0]["objective"] == "value"
    plan = client.get("/api/v1/capacity/plan", params={**params, "analysts": 2}).json()
    assert plan["objective"] == "value"
    bad = client.get("/api/v1/capacity/plan", params={**params, "objective": "x", "analysts": 2})
    assert bad.status_code == 422


def test_bench_reports_latency_percentiles(decided):
    from verita.ml.bench import run_bench

    app, _, dataset = decided
    with app.state.session_factory() as db:
        result = run_bench(dataset, db)
    assert result["subgraph"]["n"] > 0
    assert result["subgraph"]["p50_ms"] <= result["subgraph"]["p95_ms"]
    assert result["plan"]["days"] >= 1 and result["plan"]["warm"]["n"] > 0
    assert (dataset.artifacts_dir / "bench.json").exists()
