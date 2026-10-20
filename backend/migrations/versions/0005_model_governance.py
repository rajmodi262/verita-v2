"""model governance: lifecycle, validation, maker-checker promotion

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-20 20:10:00

Existing rows are back-filled honestly: the serving champion becomes a champion with a recorded
bypass reason (it predates review), every other version is retired. Nothing is marked approved
that nobody approved.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from verita.db.detect_models import (
    CHAMPION_FLAG_CHECK,
    CHAMPION_REVIEWED_CHECK,
    MODEL_STATUS_CHECK,
)

revision: str = "0005"
down_revision: Union[str, Sequence[str], None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PRE_GOVERNANCE = (
    "Put into service before model governance existed (migration 0005); "
    "validate it with `verita models validate` and re-promote through review."
)


def upgrade() -> None:
    with op.batch_alter_table("model_versions", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("status", sa.String(length=16), nullable=False, server_default="candidate")
        )
        batch_op.add_column(
            sa.Column(
                "proposed_by", sa.String(length=128), nullable=False, server_default="pipeline"
            )
        )
        batch_op.add_column(sa.Column("validation", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("validation_sha256", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("approved_by_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("promoted_by_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("decision_note", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("bypass_reason", sa.Text(), nullable=True))
        batch_op.create_foreign_key(
            op.f("fk_model_versions_approved_by_id_users"), "users", ["approved_by_id"], ["id"]
        )
        batch_op.create_foreign_key(
            op.f("fk_model_versions_promoted_by_id_users"), "users", ["promoted_by_id"], ["id"]
        )

    model_versions = sa.table(
        "model_versions",
        sa.column("is_champion", sa.Boolean()),
        sa.column("status", sa.String()),
        sa.column("bypass_reason", sa.Text()),
    )
    op.execute(
        model_versions.update()
        .where(model_versions.c.is_champion == sa.true())
        .values(status="champion", bypass_reason=PRE_GOVERNANCE)
    )
    op.execute(
        model_versions.update()
        .where(model_versions.c.is_champion == sa.false())
        .values(status="retired")
    )

    with op.batch_alter_table("model_versions", schema=None) as batch_op:
        batch_op.create_check_constraint(op.f("ck_model_versions_status_valid"), MODEL_STATUS_CHECK)
        batch_op.create_check_constraint(
            op.f("ck_model_versions_champion_reviewed"), CHAMPION_REVIEWED_CHECK
        )
        batch_op.create_check_constraint(
            op.f("ck_model_versions_champion_flag"), CHAMPION_FLAG_CHECK
        )


def downgrade() -> None:
    with op.batch_alter_table("model_versions", schema=None) as batch_op:
        batch_op.drop_constraint(op.f("ck_model_versions_champion_flag"), type_="check")
        batch_op.drop_constraint(op.f("ck_model_versions_champion_reviewed"), type_="check")
        batch_op.drop_constraint(op.f("ck_model_versions_status_valid"), type_="check")
        batch_op.drop_constraint(op.f("fk_model_versions_promoted_by_id_users"), type_="foreignkey")
        batch_op.drop_constraint(op.f("fk_model_versions_approved_by_id_users"), type_="foreignkey")
        for column in (
            "bypass_reason",
            "decision_note",
            "promoted_at",
            "promoted_by_id",
            "approved_at",
            "approved_by_id",
            "validation_sha256",
            "validation",
            "proposed_by",
            "status",
        ):
            batch_op.drop_column(column)
