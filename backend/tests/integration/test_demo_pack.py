"""Demo pack: build → verify (and catch tampering) → load into a fresh DB → serve from the pack."""

from __future__ import annotations

import json
import shutil

import pytest
from fastapi.testclient import TestClient

from tests.conftest import PASSWORD
from tests.pipeline.conftest import fx_dataset, fx_root, fx_run  # noqa: F401
from verita.api.app import create_app
from verita.core.config import Settings
from verita.db.base import Base
from verita.db.models import Role
from verita.demo.pack import build_pack, load_pack, verify_pack
from verita.ml import stages
from verita.ml.detect import DetectConfig, run_detect
from verita.services.auth import AuthService


@pytest.fixture(scope="module")
def pack(fx_run, fx_dataset, fx_root, tmp_path_factory):  # noqa: F811
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
    out = tmp_path_factory.mktemp("pack") / "demo-pack"
    with app.state.session_factory() as db:
        stages.stage_alerts(fx_dataset, db)
        stages.stage_decide(fx_dataset, db)
        db.commit()
        manifest = build_pack(fx_dataset, db, out, subgraphs_per_day=5)
    return out, manifest


def test_pack_has_a_manifest_covering_every_file(pack):
    out, manifest = pack
    assert manifest["counts"]["alerts"] > 0 and manifest["counts"]["subgraphs"] > 0
    assert "alerts.parquet" in manifest["files"] and "subgraphs.jsonl.gz" in manifest["files"]
    assert "artifacts/fixture/decide/isotonic.joblib" in manifest["files"]
    assert verify_pack(out) == []


def test_tampering_is_detected(pack, tmp_path):
    out, _ = pack
    bad = tmp_path / "bad"
    shutil.copytree(out, bad)
    (bad / "artifacts/fixture/decide/thresholds.json").write_text("{}", encoding="utf-8")
    (bad / "extra.txt").write_text("hi", encoding="utf-8")
    (bad / "reasons.parquet").unlink()
    problems = verify_pack(bad)
    assert any("thresholds.json: SHA-256" in p for p in problems)
    assert any("reasons.parquet: missing" in p for p in problems)
    assert any("extra.txt: not in the manifest" in p for p in problems)
    with pytest.raises(RuntimeError, match="failed verification"):
        create_app(
            Settings(
                env="test",
                database_url="sqlite+pysqlite:///:memory:",
                demo_pack=bad,
                _env_file=None,
            )
        )
    assert verify_pack(tmp_path / "nowhere") == ["manifest.json is missing"]


def test_a_fresh_deployment_serves_everything_from_the_pack(pack, tmp_path):
    out, manifest = pack
    settings = Settings(
        env="test",
        database_url="sqlite+pysqlite:///:memory:",
        data_root=tmp_path,  # nothing on disk but the pack
        dataset="fixture",
        demo_pack=out,
        signing_key_path=tmp_path / "k.pem",
        public_key_path=tmp_path / "pub.pem",
        _env_file=None,
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)
    with app.state.session_factory() as db:
        result = load_pack(db, out)
        again = load_pack(db, out)
        AuthService(db, settings).create_user("priya", PASSWORD, Role.ANALYST)
        db.commit()
    assert result["loaded"] and result["alerts"] == manifest["counts"]["alerts"]
    assert again["loaded"] is False  # idempotent

    client = TestClient(app)
    client.post("/api/v1/auth/login", json={"username": "priya", "password": PASSWORD})
    queue = client.get("/api/v1/alerts", params={"limit": 5}).json()
    assert queue["total"] == manifest["counts"]["alerts"]
    top = queue["items"][0]["id"]
    graph = client.get(f"/api/v1/alerts/{top}/subgraph")
    assert graph.status_code == 200 and graph.json()["edges"]
    lowest = client.get("/api/v1/alerts", params={"limit": 200}).json()["items"][-1]["id"]
    missing = client.get(f"/api/v1/alerts/{lowest}/subgraph")
    assert missing.status_code in (200, 404)
    if missing.status_code == 404:
        assert missing.json()["type"].endswith("/evidence-not-in-pack")
    meta = client.get("/api/v1/capacity/meta")
    assert meta.status_code == 200 and meta.json()["days"]
    case = client.post(
        "/api/v1/cases",
        json={"alert_ids": [top]},
        headers={"X-CSRF-Token": client.cookies.get("verita_csrf") or ""},
    )
    assert case.status_code == 201, case.text


def test_load_refuses_an_unverified_pack(pack, tmp_path):
    out, _ = pack
    bad = tmp_path / "bad2"
    shutil.copytree(out, bad)
    manifest = json.loads((bad / "manifest.json").read_text(encoding="utf-8"))
    manifest["files"]["alerts.parquet"] = "0" * 64
    (bad / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    from verita.db.session import make_engine, make_session_factory

    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with (
        make_session_factory(engine)() as db,
        pytest.raises(ValueError, match="failed verification"),
    ):
        load_pack(db, bad)
