"""Metrics and tracing (M9.07–M9.08).

Prometheus
    ``verita_http_requests_total`` and ``verita_http_request_duration_seconds`` by method, route
    template (never the raw path, so IDs do not explode the label space) and status, plus
    business counters: signatures, verifier verdicts, narrative jobs. With several Uvicorn
    workers set ``PROMETHEUS_MULTIPROC_DIR`` (the image does) and the scrape aggregates them.
    ``GET /api/metrics`` is for the internal scraper: nginx refuses it on the public origin,
    and ``VERITA_METRICS_TOKEN`` (bearer) protects it if the port is exposed.

OpenTelemetry
    When ``VERITA_OTEL_ENDPOINT`` is set, FastAPI requests are traced and exported over
    OTLP/HTTP; every log line then carries the current ``trace_id``.
"""

from __future__ import annotations

import hmac
import os
import time
from collections.abc import MutableMapping
from typing import Any

from fastapi import APIRouter, FastAPI, Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
    multiprocess,
)
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from verita.core.errors import AppError

# Multi-process mode stores values in this directory; every process that imports the metrics
# (API workers, the job worker, one-off CLI commands) must find it, whatever its entrypoint.
if _dir := os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
    os.makedirs(_dir, exist_ok=True)

REQUESTS = Counter("verita_http_requests_total", "HTTP requests", ["method", "route", "status"])
LATENCY = Histogram(
    "verita_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)
SIGNATURES = Counter("verita_case_signatures_total", "Case files approved and signed")
VERIFICATIONS = Counter("verita_verifier_runs_total", "Verifier runs", ["passed"])
JOBS = Counter("verita_jobs_total", "Background jobs finished", ["kind", "status"])


class MetricsMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") == "/api/metrics":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status = {"code": 500}

        async def wrapped(message: Message) -> None:
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, wrapped)
        finally:
            route = scope.get("route")
            template = getattr(route, "path", None) or "unmatched"
            method = scope.get("method", "GET")
            REQUESTS.labels(method, template, str(status["code"])).inc()
            LATENCY.labels(method, template).observe(time.perf_counter() - started)


router = APIRouter()


@router.get("/api/metrics", include_in_schema=False)
def metrics(request: Request) -> Response:
    token = request.app.state.settings.metrics_token
    if token is not None:
        given = request.headers.get("authorization", "").removeprefix("Bearer ")
        if not hmac.compare_digest(given, token.get_secret_value()):
            raise AppError(401, "unauthenticated", "Metrics need the scrape token")
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)  # type: ignore[no-untyped-call]
        body = generate_latest(registry)
    else:
        body = generate_latest()
    return Response(body, media_type=CONTENT_TYPE_LATEST)


def setup_tracing(app: FastAPI, endpoint: str | None, service: str = "verita-api") -> bool:
    """Instrument the app with OpenTelemetry when an OTLP endpoint is configured."""
    if not endpoint:
        return False
    from opentelemetry import trace  # noqa: PLC0415 - only when tracing is on
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # noqa: PLC0415
        OTLPSpanExporter,
    )
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor  # noqa: PLC0415
    from opentelemetry.sdk.resources import Resource  # noqa: PLC0415
    from opentelemetry.sdk.trace import TracerProvider  # noqa: PLC0415
    from opentelemetry.sdk.trace.export import BatchSpanProcessor  # noqa: PLC0415

    provider = TracerProvider(resource=Resource.create({"service.name": service}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(
        app, tracer_provider=provider, excluded_urls="health/live,api/metrics"
    )
    return True


def add_trace_id(
    _logger: Any, _name: str, event: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """structlog processor: attach the current OpenTelemetry trace id, when there is one."""
    try:
        from opentelemetry import trace  # noqa: PLC0415
    except ImportError:  # pragma: no cover
        return event
    ctx = trace.get_current_span().get_span_context()
    if ctx.is_valid:
        event["trace_id"] = format(ctx.trace_id, "032x")
    return event
