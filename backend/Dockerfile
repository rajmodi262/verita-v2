# syntax=docker/dockerfile:1.7
# Verita API. Multi-stage: build the locked virtualenv, ship it on a slim non-root image.
# Base images are pinned to digests in M9 (TRACKER M9.06).

FROM python:3.11-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project
COPY alembic.ini ./
COPY migrations ./migrations
COPY verita ./verita
RUN uv sync --frozen

FROM python:3.11-slim AS runtime
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin verita
WORKDIR /app
COPY --from=build --chown=10001:10001 /app /app
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VERITA_ENV=prod
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live', timeout=2)"]
CMD ["uvicorn", "verita.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
