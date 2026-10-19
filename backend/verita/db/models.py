"""ORM models for identity and the audit log (M0). Later milestones add their own modules."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from verita.db.base import Base, UTCDateTime, utcnow


class Role(StrEnum):
    ANALYST = "analyst"
    MLRO = "mlro"
    VALIDATOR = "validator"
    REVIEWER = "reviewer"


ROLE_CHECK = "role IN ('analyst', 'mlro', 'validator', 'reviewer')"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint(ROLE_CHECK, name="role_valid"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16))
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    sessions: Mapped[list[UserSession]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    @property
    def role_enum(self) -> Role:
        return Role(self.role)


class UserSession(Base):
    """A login session. ``id`` and ``csrf_digest`` are SHA-256 digests, never raw tokens."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    csrf_digest: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())

    user: Mapped[User] = relationship(back_populates="sessions")


class AuditLog(Base):
    """Append-only record of security-relevant actions."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None, index=True
    )
    action: Mapped[str] = mapped_column(String(64), index=True)
    target: Mapped[str | None] = mapped_column(String(255), default=None)
    ip: Mapped[str | None] = mapped_column(String(64), default=None)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
