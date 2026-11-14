"""Drop income_event_sync, replaced by event_sync in v0.2.1.

It only recorded when each ticker's income events were last fetched, so
nothing is lost: event_sync has the same information for income and stock
events. Databases created after v0.4 never had it, hence the check.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if "income_event_sync" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("income_event_sync")


def downgrade() -> None:
    # Back empty: the timestamps were a cache, and an empty table only means
    # "never synced", which the old code handled by syncing again.
    op.create_table(
        "income_event_sync",
        sa.Column("ticker", sa.String(length=12), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("ticker"),
    )
