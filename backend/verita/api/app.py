"""Application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from verita import __version__
from verita.api.deps import CSRF_HEADER
from verita.api.middleware import RequestContextMiddleware
from verita.api.routers import auth, health
from verita.core.config import Settings, get_settings
from verita.core.errors import install_error_handlers
from verita.core.logging import configure_logging, get_logger
from verita.db.session import make_engine, make_session_factory

API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    log = get_logger("verita.app")

    engine = make_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        log.info("startup", env=settings.env, version=__version__)
        yield
        engine.dispose()
        log.info("shutdown")

    show_docs = not settings.is_prod
    app = FastAPI(
        title="Verita API",
        version=__version__,
        lifespan=lifespan,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url="/api/docs" if show_docs else None,
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)

    install_error_handlers(app)
    # Order matters: the last middleware added is the outermost. CORS must be outermost so
    # preflight requests and error responses always carry CORS headers.
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type", CSRF_HEADER, "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )

    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(auth.router, prefix=API_PREFIX)
    return app
