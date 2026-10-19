"""Data access for users, sessions and the audit log. Services never write SQL directly."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from verita.db.models import AuditLog, Role, User, UserSession


class UserRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_by_username(self, username: str) -> User | None:
        return self._db.scalar(select(User).where(User.username == username))

    def get(self, user_id: int) -> User | None:
        return self._db.get(User, user_id)

    def add(self, username: str, password_hash: str, role: Role) -> User:
        user = User(username=username, password_hash=password_hash, role=role.value)
        self._db.add(user)
        self._db.flush()
        return user


class SessionRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def add(self, digest: str, user_id: int, csrf_digest: str, expires_at: datetime) -> None:
        self._db.add(
            UserSession(id=digest, user_id=user_id, csrf_digest=csrf_digest, expires_at=expires_at)
        )
        self._db.flush()

    def get(self, digest: str) -> UserSession | None:
        return self._db.get(UserSession, digest)

    def delete(self, digest: str) -> None:
        self._db.execute(delete(UserSession).where(UserSession.id == digest))

    def delete_expired(self, now: datetime) -> int:
        result = self._db.execute(delete(UserSession).where(UserSession.expires_at <= now))
        return int(getattr(result, "rowcount", 0) or 0)


class AuditRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def record(
        self,
        action: str,
        actor_id: int | None = None,
        target: str | None = None,
        ip: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self._db.add(
            AuditLog(action=action, actor_id=actor_id, target=target, ip=ip, detail=detail or {})
        )
        self._db.flush()

    def recent(self, limit: int = 50) -> list[AuditLog]:
        return list(self._db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)))
