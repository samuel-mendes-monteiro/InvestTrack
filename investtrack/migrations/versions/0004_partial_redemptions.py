"""Partial redemptions of fixed income.

A new table, so no existing row changes.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import investtrack.db

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "partial_redemptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("fixed_income_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("gross", investtrack.db.SafeDecimal(), nullable=False),
        sa.ForeignKeyConstraint(
            ["fixed_income_id"],
            ["fixed_income.id"],
            name="fk_partial_redemptions_fixed_income_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_partial_redemptions_fixed_income_id", "partial_redemptions", ["fixed_income_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_partial_redemptions_fixed_income_id", table_name="partial_redemptions")
    op.drop_table("partial_redemptions")
