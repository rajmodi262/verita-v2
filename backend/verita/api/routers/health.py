"""Liveness and readiness probes."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from verita import __version__
from verita.core.errors import AppError

router = APIRouter(prefix="/health", tags=["health"])


class LiveResponse(BaseModel):
    status: Literal["ok"]
    version: str


class ReadyResponse(BaseModel):
    status: Literal["ready"]
    checks: dict[str, Literal["ok"]]


@router.get("/live", response_model=LiveResponse)
def live() -> LiveResponse:
    """The process is up. Never touches dependencies."""
    return LiveResponse(status="ok", version=__version__)


@router.get("/ready", response_model=ReadyResponse)
def ready(request: Request) -> ReadyResponse:
    """The process can serve traffic: the database answers."""
    factory: sessionmaker[Session] = request.app.state.session_factory
    try:
        with factory() as db:
            db.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise AppError(
            503, "not-ready", "Service not ready", detail="database unavailable"
        ) from exc
    return ReadyResponse(status="ready", checks={"database": "ok"})
