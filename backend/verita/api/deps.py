"""Request-scoped dependencies: settings, DB session, authentication, roles, CSRF."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session, sessionmaker

from verita.core.config import Settings
from verita.core.errors import AppError
from verita.core.security import tokens_match
from verita.db.models import Role
from verita.db.session import session_scope
from verita.services.auth import AuthService, SessionInfo

SESSION_COOKIE = "verita_session"
CSRF_COOKIE = "verita_csrf"
CSRF_HEADER = "X-CSRF-Token"


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_db(request: Request) -> Iterator[Session]:
    factory: sessionmaker[Session] = request.app.state.session_factory
    yield from session_scope(factory)


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
# scope="function": commit (or roll back) before the response is sent. With the default
# request scope the commit ran after the client already had its 200, so an immediate next
# request (sign in, then act) could miss the new session row on PostgreSQL.
DbDep = Annotated[Session, Depends(get_db, scope="function")]


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def current_session(request: Request, db: DbDep, settings: SettingsDep) -> SessionInfo:
    info = AuthService(db, settings).resolve(request.cookies.get(SESSION_COOKIE))
    if info is None:
        raise AppError(401, "unauthenticated", "Authentication required")
    return info


SessionDep = Annotated[SessionInfo, Depends(current_session)]


def csrf_protected(request: Request, info: SessionDep) -> SessionInfo:
    """Mutating requests must echo the session's CSRF token in a header."""
    if not tokens_match(request.headers.get(CSRF_HEADER), info.csrf_digest):
        raise AppError(403, "csrf-failed", "Missing or invalid CSRF token")
    return info


CsrfSessionDep = Annotated[SessionInfo, Depends(csrf_protected)]


def csrf_role(*allowed: Role) -> Callable[[SessionInfo], SessionInfo]:
    """CSRF check and role check as one dependency for mutating routes.

    Dependencies resolve before FastAPI validates the request body, so an unauthorized caller
    always gets 403 — never a 422 that describes the endpoint's input to someone who may not
    call it (found by the authorization matrix).
    """
    allowed_values = {role.value for role in allowed}

    def _check(info: CsrfSessionDep) -> SessionInfo:
        if info.user.role not in allowed_values:
            raise AppError(403, "forbidden", "Your role cannot perform this action")
        return info

    return _check


def require_role(*allowed: Role) -> Callable[[SessionInfo], SessionInfo]:
    """Default deny: the route is reachable only by the listed roles."""
    allowed_values = {role.value for role in allowed}

    def _check(info: SessionDep) -> SessionInfo:
        if info.user.role not in allowed_values:
            raise AppError(403, "forbidden", "Your role cannot perform this action")
        return info

    return _check
