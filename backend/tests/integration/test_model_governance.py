"""Model governance end to end: a production-loaded model is a candidate that serves nothing until
it is validated against the policy gates, approved by a validator and promoted by the MLRO."""

from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from tests.conftest import PASSWORD
from tests.pipeline.conftest import fx_dataset, fx_root, fx_run  # noqa: F401
from verita.api.app import create_app
from verita.core import config as config_module
from verita.core.config import Settings
from verita.db.base import Base
from verita.db.detect_models import ModelVersion
from verita.db.models import AuditLog, Role
from verita.ml import stages, validation
from verita.ml.detect import DetectConfig, run_detect
from verita.services import models as governance
from verita.services.auth import AuthService

USERS = {"priya": Role.ANALYST, "vera": Role.VALIDATOR, "marcus": Role.MLRO}
LENIENT = {
    "version": 99,
    "gates": {
        "min_f1_ci_low": 0.0,
        "beats_incumbent": False,
        "max_f1_std_over_seeds": 1.0,
        "max_ece_after_calibration": 1.0,
        "max_shuffled_pr_auc_over_base_rate": 1e9,
        "max_major_drift_share": 1.0,
        "min_rows_for_drift": 1,
        "min_typology_support_reported": 10**9,
    },
}


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


@pytest.fixture(scope="module")
def stack(fx_run, fx_dataset, fx_root, tmp_path_factory):  # noqa: F811
    stages.stage_features(fx_dataset)
    run_detect(fx_dataset, DetectConfig.quick())
    work = tmp_path_factory.mktemp("gov")
    settings = Settings(
        env="test",
        database_url=f"sqlite+pysqlite:///{(work / 'gov.sqlite').as_posix()}",
        data_root=fx_root,
        dataset="fixture",
        signing_key_path=work / "k.pem",
        public_key_path=work / "pub.pem",
        llm_providers=[],
        _env_file=None,
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)
    prod = SimpleNamespace(env="prod")  # the pipeline only reads `env`
    original = config_module.get_settings
    config_module.get_settings = lambda: prod  # the pipeline loads this model as production would
    try:
        with app.state.session_factory() as db:
            stages.stage_alerts(fx_dataset, db)
            stages.stage_decide(fx_dataset, db)
            auth = AuthService(db, settings)
            for name, role in USERS.items():
                auth.create_user(name, PASSWORD, role)
            db.commit()
    finally:
        config_module.get_settings = original
    with app.state.session_factory() as db:
        version_id = db.scalar(select(ModelVersion.id))
    return app, version_id, fx_dataset


def test_a_production_load_is_a_candidate_that_serves_nothing(stack):
    app, version_id, _ = stack
    analyst = Api(app, "priya")
    model = analyst.get(f"/models/{version_id}").json()
    assert model["status"] == "candidate" and model["governance"] == "not reviewed"
    assert not model["is_champion"] and model["bypass_reason"] is None
    queue = analyst.get("/alerts")
    assert queue.status_code == 503 and queue.json()["type"].endswith("no-model")


def test_only_a_validator_validates_approves_or_rejects(stack):
    app, version_id, _ = stack
    for user in ("priya", "marcus"):
        api = Api(app, user)
        for action in ("validate", "approve"):
            assert api.post(f"/models/{version_id}/{action}").status_code == 403
        assert api.post(f"/models/{version_id}/reject", {"note": "no"}).status_code == 403
    assert Api(app, "vera").post(f"/models/{version_id}/promote").status_code == 403


def test_approval_needs_a_validation_that_passed(stack, monkeypatch):
    app, version_id, _ = stack
    vera = Api(app, "vera")
    first = vera.post(f"/models/{version_id}/approve")
    assert first.status_code == 409 and first.json()["type"].endswith("not-validated")

    strict = copy.deepcopy(LENIENT)
    strict["gates"]["min_f1_ci_low"] = 1.01  # unreachable
    monkeypatch.setattr(governance, "load_policy", lambda: strict)
    report = vera.post(f"/models/{version_id}/validate").json()
    assert report["validation"]["passed"] is False
    assert "f1_ci_low" in report["validation"]["failed_gates"]
    blocked = vera.post(f"/models/{version_id}/approve")
    assert blocked.status_code == 409 and "f1_ci_low" in blocked.json()["detail"]


def test_validate_approve_promote_puts_the_model_into_service(stack, monkeypatch):
    app, version_id, _ = stack
    vera, marcus, priya = Api(app, "vera"), Api(app, "marcus"), Api(app, "priya")
    monkeypatch.setattr(governance, "load_policy", lambda: LENIENT)

    validated = vera.post(f"/models/{version_id}/validate").json()
    assert validated["validation"]["passed"] is True
    assert len(validated["validation"]["sha256"]) == 64
    assert {g["gate"] for g in validated["report"]["gates"]} >= {
        "f1_ci_low",
        "beats_incumbent",
        "calibration",
        "leakage_label_shuffle",
        "drift",
    }
    early = marcus.post(f"/models/{version_id}/promote")
    assert early.status_code == 409 and early.json()["type"].endswith("not-approved")

    approved = vera.post(f"/models/{version_id}/approve", {"note": "gates pass"}).json()
    assert approved["status"] == "approved" and approved["governance"] == "reviewed"
    promoted = marcus.post(f"/models/{version_id}/promote", {"note": "go live"}).json()
    assert promoted["status"] == "champion" and promoted["is_champion"]
    assert promoted["approved_by_id"] != promoted["promoted_by_id"]

    assert priya.get("/alerts").status_code == 200
    with app.state.session_factory() as db:
        actions = set(
            db.scalars(select(AuditLog.action).where(AuditLog.target == f"model:{version_id}"))
        )
    assert {"model.validated", "model.approved", "model.promoted"} <= actions


def test_the_database_refuses_an_unreviewed_champion(stack):
    app, _, _ = stack
    with app.state.session_factory() as db:
        db.add(
            ModelVersion(
                name="rogue",
                dataset="fixture",
                git_revision="x",
                champion_sha256="f" * 64,
                features_sha256="f" * 64,
                threshold=0.5,
                status="champion",
                is_champion=True,
            )
        )
        with pytest.raises(IntegrityError, match="champion_reviewed"):
            db.flush()


def test_status_and_champion_flag_cannot_disagree(stack):
    app, _, _ = stack
    with app.state.session_factory() as db:
        db.add(
            ModelVersion(
                name="flag",
                dataset="fixture",
                git_revision="x",
                champion_sha256="e" * 64,
                features_sha256="e" * 64,
                threshold=0.5,
                status="candidate",
                is_champion=True,  # serving, yet not a champion: refused
            )
        )
        with pytest.raises(IntegrityError, match="champion_flag"):
            db.flush()


def test_validation_refuses_artifacts_of_another_model(stack):
    _, _, dataset = stack
    with pytest.raises(validation.ValidationError, match="different model"):
        validation.build_report(dataset, "0" * 64, LENIENT)


def test_rejection_needs_a_reason_and_is_final(stack):
    app, _, _ = stack
    with app.state.session_factory() as db:
        candidate = ModelVersion(
            name="challenger",
            dataset="fixture",
            git_revision="x",
            champion_sha256="c" * 64,
            features_sha256="c" * 64,
            threshold=0.5,
        )
        db.add(candidate)
        db.commit()
        candidate_id = candidate.id
    vera = Api(app, "vera")
    assert vera.post(f"/models/{candidate_id}/reject", {"note": ""}).status_code == 422
    rejected = vera.post(f"/models/{candidate_id}/reject", {"note": "unstable seeds"}).json()
    assert rejected["status"] == "rejected" and rejected["decision_note"] == "unstable seeds"
    again = vera.post(f"/models/{candidate_id}/approve")
    assert again.status_code == 409


def test_the_pipeline_never_bypasses_review_in_production(stack):
    app, _, _ = stack
    with app.state.session_factory() as db:
        version = ModelVersion(
            name="x",
            dataset="fixture",
            git_revision="x",
            champion_sha256="d" * 64,
            features_sha256="d" * 64,
            threshold=0.5,
        )
        db.add(version)
        db.flush()
        with pytest.raises(Exception, match="only through validation"):
            governance.bypass(db, version, governance.DEV_PIPELINE, "prod")
        db.rollback()
