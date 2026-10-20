"""Prometheus metrics endpoint and the tracing switch."""

from __future__ import annotations

from fastapi.testclient import TestClient

from verita.api.app import create_app
from verita.api.observability import setup_tracing
from verita.core.config import Settings


def _app(**kw):
    return create_app(
        Settings(env="test", database_url="sqlite+pysqlite:///:memory:", _env_file=None, **kw)
    )


def test_requests_are_counted_by_route_template_not_raw_path():
    client = TestClient(_app())
    client.get("/api/v1/alerts/12345")  # 401, but routed
    client.get("/api/v1/health/live")
    body = client.get("/api/metrics").text
    assert 'route="/alerts/{alert_id}"' in body
    assert "/alerts/12345" not in body  # a raw-path label (durations may contain the digits)
    assert "verita_http_request_duration_seconds_bucket" in body
    assert "verita_case_signatures_total" in body


def test_metrics_can_require_a_bearer_token():
    client = TestClient(_app(metrics_token="s3cret-scrape-token"))
    assert client.get("/api/metrics").status_code == 401
    ok = client.get("/api/metrics", headers={"Authorization": "Bearer s3cret-scrape-token"})
    assert ok.status_code == 200 and ok.headers["content-type"].startswith("text/plain")


def test_tracing_is_off_without_an_endpoint():
    assert setup_tracing(_app(), None) is False


def test_tracing_instruments_the_app_when_configured():
    app = _app()
    assert setup_tracing(app, "http://127.0.0.1:4318/v1/traces") is True
    assert TestClient(app).get("/api/v1/health/live").status_code == 200
