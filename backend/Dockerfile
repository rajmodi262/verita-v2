# syntax=docker/dockerfile:1.7
# Verita API. Build from the repository root (it needs configs/, prompts/ and reports/):
#   docker build -f backend/Dockerfile .
# Multi-stage: build the locked virtualenv, ship it on a slim non-root image. Run data (alerts,
# Decide artifacts, evidence) comes from a verified demo pack mounted at /srv/verita/demo-pack.

FROM python:3.11-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock backend/README.md ./
RUN uv sync --frozen --no-install-project --no-dev
COPY backend/alembic.ini ./
COPY backend/migrations ./migrations
COPY backend/verita ./verita
RUN uv sync --frozen --no-dev

FROM python:3.11-slim AS runtime
# Security updates at build time; the app runs from /app/.venv, so the interpreter's own pip,
# setuptools and wheel (and their vendored packages) are removed rather than patched.
RUN apt-get update && apt-get upgrade -y --no-install-recommends     && rm -rf /var/lib/apt/lists/*     && python -m pip uninstall -y pip setuptools wheel     && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin verita
WORKDIR /app
COPY --from=build --chown=10001:10001 /app /app
COPY --chown=10001:10001 configs /srv/verita/configs
COPY --chown=10001:10001 prompts /srv/verita/prompts
COPY --chown=10001:10001 reports /srv/verita/reports
COPY --chown=10001:10001 keys/verita-pub.pem /srv/verita/keys/verita-pub.pem
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VERITA_ENV=prod \
    VERITA_REPO_ROOT=/srv/verita \
    VERITA_DATA_ROOT=/srv/verita     PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live', timeout=2)"]
# Two worker processes by default (VERITA_WORKERS): one Python process saturates near 110 req/s.
# Per-process caches (rate limits, plans) are independent; see docs/RUNBOOK.md.
CMD ["sh", "-c", "exec uvicorn verita.api.app:create_app --factory --host 0.0.0.0 --port 8000 --workers ${VERITA_WORKERS:-2} --proxy-headers --forwarded-allow-ips '*'"]
