"""Authentication: login with lockout, opaque cookie sessions, CSRF tokens, logout.

Every failure path returns the same error so the API never reveals whether a username exists or
an account is locked.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from verita.core.config import Settings
from verita.core.errors import AppError
from verita.core.security import hash_password, new_token, token_digest, verify_password
from verita.db.base import utcnow
from verita.db.models import Role, User
from verita.repositories.identity import AuditRepository, SessionRepository, UserRepository


def invalid_credentials() -> AppError:
    return AppError(401, "invalid-credentials", "Invalid username or password")


@dataclass(frozen=True)
class LoginResult:
    user: User
    session_token: str
    csrf_token: str
    expires_at: datetime


@dataclass(frozen=True)
class SessionInfo:
    user: User
    csrf_digest: str
    session_digest: str


class AuthService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self._db = db
        self._settings = settings
        self._users = UserRepository(db)
        self._sessions = SessionRepository(db)
        self._audit = AuditRepository(db)

    def create_user(self, username: str, password: str, role: Role) -> User:
        username = username.strip()
        if not username or len(username) > 64:  # noqa: PLR2004 - column width
            raise AppError(422, "invalid-username", "Username must be 1-64 characters")
        if self._users.get_by_username(username) is not None:
            raise AppError(409, "username-taken", "Username already exists")
        user = self._users.add(username, hash_password(password), role)
        self._audit.record(
            "user.created", actor_id=None, target=f"user:{user.id}", detail={"role": role.value}
        )
        return user

    def reset_password(self, username: str, password: str) -> bool:
        """Set a new password, clear any lockout and end the user's sessions. False if unknown."""
        user = self._users.get_by_username(username)
        if user is None:
            return False
        user.password_hash = hash_password(password)
        user.failed_logins = 0
        user.locked_until = None
        user.sessions.clear()
        self._audit.record("user.password_reset", actor_id=None, target=f"user:{user.id}")
        return True

    def login(
        self, username: str, password: str, ip: str | None, now: datetime | None = None
    ) -> LoginResult:
        now = now or utcnow()
        user = self._users.get_by_username(username.strip())

        if user is not None and user.locked_until is not None and user.locked_until > now:
            verify_password(None, password)  # keep timing uniform
            self._audit.record("auth.login_locked", actor_id=user.id, ip=ip)
            self._db.commit()  # persist the audit record; the request will fail
            raise invalid_credentials()

        if not verify_password(user.password_hash if user else None, password) or user is None:
            if user is not None:
                self._register_failure(user, now)
            self._audit.record(
                "auth.login_failed",
                actor_id=user.id if user else None,
                ip=ip,
                detail={"username": username[:64]},
            )
            self._db.commit()  # persist the failure count before the request fails
            raise invalid_credentials()

        user.failed_logins = 0
        user.locked_until = None
        session_token, csrf_token = new_token(), new_token()
        expires_at = now + timedelta(minutes=self._settings.session_ttl_minutes)
        self._sessions.add(
            token_digest(session_token), user.id, token_digest(csrf_token), expires_at
        )
        self._sessions.delete_expired(now)
        self._audit.record("auth.login", actor_id=user.id, ip=ip)
        return LoginResult(user, session_token, csrf_token, expires_at)

    def _register_failure(self, user: User, now: datetime) -> None:
        user.failed_logins += 1
        if user.failed_logins >= self._settings.login_max_failures:
            user.locked_until = now + timedelta(minutes=self._settings.login_lockout_minutes)
            user.failed_logins = 0
            self._audit.record("auth.locked", actor_id=user.id)

    def resolve(self, session_token: str | None, now: datetime | None = None) -> SessionInfo | None:
        if not session_token:
            return None
        now = now or utcnow()
        digest = token_digest(session_token)
        record = self._sessions.get(digest)
        if record is None:
            return None
        if record.expires_at <= now:
            self._sessions.delete(digest)
            return None
        return SessionInfo(record.user, record.csrf_digest, digest)

    def logout(self, info: SessionInfo, ip: str | None) -> None:
        self._sessions.delete(info.session_digest)
        self._audit.record("auth.logout", actor_id=info.user.id, ip=ip)
