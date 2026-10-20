"""ORM models for Detect (M3): model registry, alerts, reasons and analyst dispositions."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from verita.db.base import Base, UTCDateTime, utcnow


class AlertStatus(StrEnum):
    OPEN = "open"
    ESCALATED = "escalated"
    DISMISSED = "dismissed"
    IN_CASE = "in_case"


class DispositionAction(StrEnum):
    ESCALATE = "escalate"
    DISMISS = "dismiss"
    REOPEN = "reopen"


# Mandatory, closed set: free-text-only dismissals are not auditable.
DISMISS_REASONS = {
    "known_counterparty": "Known, verified counterparty relationship",
    "business_pattern": "Consistent with the customer's documented business",
    "duplicate_alert": "Duplicate of an alert already worked",
    "data_error": "Alert caused by a data quality problem",
    "below_risk_appetite": "Below the documented risk appetite",
}
ESCALATE_REASONS = {
    "typology_match": "Matches a known laundering typology",
    "unexplained_flow": "Funds flow has no evident business purpose",
    "rapid_movement": "Funds moved on unusually quickly",
    "network_link": "Linked to other suspicious accounts",
}


class ModelStatus(StrEnum):
    """Model lifecycle (verita.services.models): only a champion scores the live queue."""

    CANDIDATE = "candidate"  # trained and scored in shadow; awaiting validation
    APPROVED = "approved"  # passed the policy gates and an independent validator signed off
    CHAMPION = "champion"  # put into service by the MLRO
    REJECTED = "rejected"
    RETIRED = "retired"  # replaced by a newer champion


MODEL_STATUS_CHECK = "status IN ('candidate', 'approved', 'champion', 'rejected', 'retired')"
# A champion is either reviewed by two different people, or carries an explicit, displayed
# bypass reason (development pipelines, the synthetic demo pack). There is no third way.
CHAMPION_REVIEWED_CHECK = (
    "status <> 'champion' OR bypass_reason IS NOT NULL OR "
    "(approved_by_id IS NOT NULL AND promoted_by_id IS NOT NULL "
    "AND approved_by_id <> promoted_by_id)"
)


CHAMPION_FLAG_CHECK = "is_champion = (status = 'champion')"


class ModelVersion(Base):
    __tablename__ = "model_versions"
    __table_args__ = (
        CheckConstraint(MODEL_STATUS_CHECK, name="status_valid"),
        CheckConstraint(CHAMPION_REVIEWED_CHECK, name="champion_reviewed"),
        CheckConstraint(CHAMPION_FLAG_CHECK, name="champion_flag"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    dataset: Mapped[str] = mapped_column(String(32))
    git_revision: Mapped[str] = mapped_column(String(64))
    champion_sha256: Mapped[str] = mapped_column(String(64), unique=True)
    features_sha256: Mapped[str] = mapped_column(String(64))
    threshold: Mapped[float] = mapped_column(Float)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    is_champion: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    # Governance (migration 0005). The proposer is the pipeline run that trained the model.
    status: Mapped[str] = mapped_column(String(16), default=ModelStatus.CANDIDATE.value)
    proposed_by: Mapped[str] = mapped_column(String(128), default="pipeline")
    validation: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    validation_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    promoted_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    promoted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    bypass_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class Alert(Base):
    """One account-day whose riskiest transaction scored above the alert floor."""

    __tablename__ = "alerts"
    __table_args__ = (
        UniqueConstraint("model_version_id", "account_id", "alert_date", name="one_per_day"),
        CheckConstraint(
            "status IN ('open', 'escalated', 'dismissed', 'in_case')", name="status_valid"
        ),
        Index("ix_alerts_queue", "model_version_id", "alert_date", "score"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_version_id: Mapped[int] = mapped_column(ForeignKey("model_versions.id"), index=True)
    account_id: Mapped[str] = mapped_column(String(64), index=True)
    alert_date: Mapped[date] = mapped_column(Date)
    score: Mapped[float] = mapped_column(Float)
    score_top3_mean: Mapped[float] = mapped_column(Float)
    calibrated_prob: Mapped[float | None] = mapped_column(Float, default=None)
    typology_pred: Mapped[str] = mapped_column(String(32))
    typology_conf: Mapped[float] = mapped_column(Float)
    top_txn_id: Mapped[int] = mapped_column(Integer)
    top_amount: Mapped[float] = mapped_column(Float)
    top_currency: Mapped[str] = mapped_column(String(32))
    n_transactions: Mapped[int] = mapped_column(Integer)
    n_flagged: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default=AlertStatus.OPEN.value)
    # Ground truth, for model validation only. Never sent to the analyst queue.
    truth_label: Mapped[bool] = mapped_column(Boolean)
    truth_typologies: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    reasons: Mapped[list[AlertReason]] = relationship(
        back_populates="alert", cascade="all, delete-orphan", order_by="AlertReason.rank"
    )


class AlertReason(Base):
    __tablename__ = "alert_reasons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("alerts.id", ondelete="CASCADE"), index=True)
    rank: Mapped[int] = mapped_column(Integer)
    feature: Mapped[str] = mapped_column(String(64))
    value: Mapped[float] = mapped_column(Float)
    shap: Mapped[float] = mapped_column(Float)
    text: Mapped[str] = mapped_column(Text)

    alert: Mapped[Alert] = relationship(back_populates="reasons")


class Disposition(Base):
    """Append-only analyst decisions on alerts."""

    __tablename__ = "dispositions"
    __table_args__ = (
        CheckConstraint("action IN ('escalate', 'dismiss', 'reopen')", name="action_valid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("alerts.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(16))
    reason_code: Mapped[str] = mapped_column(String(32))
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
