"""Saved capacity plans (M4.19): an MLRO's staffing decision is part of the audit trail."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Date, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from verita.db.base import Base, UTCDateTime, utcnow


class CapacityPlan(Base):
    __tablename__ = "capacity_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_date: Mapped[date] = mapped_column(Date, index=True)
    analysts: Mapped[int] = mapped_column(Integer)
    alpha: Mapped[float] = mapped_column(Float)
    mode: Mapped[str] = mapped_column(String(16))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    result: Mapped[dict[str, Any]] = mapped_column(JSON)
    selected_alert_ids: Mapped[list[int]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
