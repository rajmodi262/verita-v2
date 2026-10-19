"""Login, logout and the current user."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, Field

from verita.api.deps import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    CsrfSessionDep,
    DbDep,
    SessionDep,
    SettingsDep,
    client_ip,
)
from verita.db.models import Role, User
from verita.services.auth import AuthService

router = APIRouter(tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    id: int
    username: str
    role: Role

    @classmethod
    def of(cls, user: User) -> UserOut:
        return cls(id=user.id, username=user.username, role=user.role_enum)


class LoginResponse(BaseModel):
    user: UserOut
    csrf_token: str
    expires_at: datetime


@router.post("/auth/login", response_model=LoginResponse)
def login(
    body: LoginRequest, request: Request, response: Response, db: DbDep, settings: SettingsDep
) -> LoginResponse:
    result = AuthService(db, settings).login(body.username, body.password, client_ip(request))
    max_age = settings.session_ttl_minutes * 60
    response.set_cookie(
        SESSION_COOKIE,
        result.session_token,
        max_age=max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/api",
    )
    response.set_cookie(
        CSRF_COOKIE,
        result.csrf_token,
        max_age=max_age,
        httponly=False,  # the SPA reads it and echoes it in X-CSRF-Token
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return LoginResponse(
        user=UserOut.of(result.user), csrf_token=result.csrf_token, expires_at=result.expires_at
    )


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request, response: Response, info: CsrfSessionDep, db: DbDep, settings: SettingsDep
) -> Response:
    AuthService(db, settings).logout(info, client_ip(request))
    response.status_code = status.HTTP_204_NO_CONTENT
    response.delete_cookie(SESSION_COOKIE, path="/api")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return response


@router.get("/me", response_model=UserOut)
def me(info: SessionDep) -> UserOut:
    return UserOut.of(info.user)
