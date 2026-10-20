"""Property-based contract fuzzing of the whole API (M9.02): no input produces a 5xx.

schemathesis generates requests from the live OpenAPI document — valid and invalid bodies,
parameters and IDs — and sends them in-process to a fully populated stack (the fixture
dataset's detector, alerts and Decide artifacts) with a signed-in MLRO session (the broadest
role) and its CSRF token. A populated stack matters: on an empty one most routes correctly
answer 503 "not deployed yet" and the interesting code is never reached.

Findings it produced (fixed): path IDs beyond 32 bits crashed the database driver.
"""

from __future__ import annotations

import pytest
import schemathesis
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, settings
from schemathesis.checks import not_a_server_error

from tests.conftest import PASSWORD
from tests.pipeline.conftest import fx_dataset, fx_root, fx_run  # noqa: F401
from verita.api.app import create_app
from verita.core.config import Settings
from verita.db.base import Base
from verita.db.models import Role
from verita.ml import stages
from verita.ml.detect import DetectConfig, run_detect
from verita.services.auth import AuthService


@pytest.fixture(scope="module")
def stack(fx_run, fx_dataset, fx_root, tmp_path_factory):  # noqa: F811
    stages.stage_features(fx_dataset)
    run_detect(fx_dataset, DetectConfig.quick())
    work = tmp_path_factory.mktemp("fuzz")
    # A file database: schemathesis runs the app's lifespan, whose shutdown disposes the engine
    # (and with it any in-memory SQLite database).
    settings_ = Settings(
        env="test",
        database_url=f"sqlite+pysqlite:///{(work / 'fuzz.sqlite').as_posix()}",
        data_root=fx_root,
        dataset="fixture",
        signing_key_path=work / "k.pem",
        public_key_path=work / "pub.pem",
        llm_providers=[],
        _env_file=None,
    )
    (fx_root / "reports").mkdir(exist_ok=True)  # the Evidence Room answers 503 without a report
    (fx_root / "reports" / "metrics.json").write_text(
        '{"schema_version": 1, "headline": [], "datasets": {}}', encoding="utf-8"
    )
    app = create_app(settings_)
    Base.metadata.create_all(app.state.engine)
    with app.state.session_factory() as db:
        stages.stage_alerts(fx_dataset, db)
        stages.stage_decide(fx_dataset, db)
        AuthService(db, settings_).create_user("marcus", PASSWORD, Role.MLRO)
        db.commit()
    login = TestClient(app).post(
        "/api/v1/auth/login", json={"username": "marcus", "password": PASSWORD}
    )
    auth = {
        "Cookie": "; ".join(f"{k}={v}" for k, v in login.cookies.items()),
        "X-CSRF-Token": login.json()["csrf_token"],
    }
    return app, auth


@pytest.fixture(scope="module")
def api_schema(stack):
    app, _ = stack
    # Signing out would end the shared session mid-run; the auth tests cover it.
    return schemathesis.openapi.from_asgi("/api/v1/openapi.json", app).exclude(
        path="/api/v1/auth/logout"
    )


schema = schemathesis.pytest.from_fixture("api_schema")


@schema.parametrize()
@settings(max_examples=20, deadline=None, suppress_health_check=list(HealthCheck))
@pytest.mark.filterwarnings("ignore")
def test_no_input_produces_a_server_error(case, stack):
    _, auth = stack
    response = case.call(headers=auth)
    case.validate_response(response, checks=(not_a_server_error,))
