"""Users, sessions, and an owner for every row of the user's own data.

Existing rows get user_id NULL; the first account created adopts them
(see auth.adopt_legacy_data), so nothing a single-user install already has
is lost.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import investtrack.db

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OWNED = ("operations", "incomes", "fixed_income")


def upgrade() -> None:
    # A server running the new models with the old create_all (e.g. with
    # auto-reload during an update) may have created the two new tables,
    # empty. They are only created here if missing.
    inspector = sa.inspect(op.get_bind())
    existing = set(inspector.get_table_names())

    if "users" not in existing:
        _create_users()
    if "auth_sessions" not in existing:
        _create_auth_sessions()
    elif "ix_auth_sessions_user_id" not in {
        i["name"] for i in inspector.get_indexes("auth_sessions")
    }:
        op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])

    _add_owners()


def _create_users() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )


def _create_auth_sessions() -> None:
    op.create_table(
        "auth_sessions",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_auth_sessions_user_id", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("token_hash"),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])


def _add_owners() -> None:
    # Adding a nullable column keeps the existing rows; SQLite needs batch
    # mode (a table rebuild) only for the foreign key.
    for table in OWNED:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
            batch.create_index(f"ix_{table}_user_id", ["user_id"])
            batch.create_foreign_key(f"fk_{table}_user_id", "users", ["user_id"], ["id"])

    # bonus_costs changes its primary key from (ticker, record_date) to an id,
    # which autogenerate doesn't detect: rebuild it by hand and copy the rows.
    op.create_table(
        "bonus_costs_new",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("ticker", sa.String(length=12), nullable=False),
        sa.Column("record_date", sa.Date(), nullable=False),
        sa.Column("unit_cost", investtrack.db.SafeDecimal(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_bonus_costs_user_id"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "ticker", "record_date", name="uq_bonus_costs_user_ticker_date"
        ),
    )
    op.execute(
        "INSERT INTO bonus_costs_new (ticker, record_date, unit_cost) "
        "SELECT ticker, record_date, unit_cost FROM bonus_costs"
    )
    op.drop_table("bonus_costs")
    op.rename_table("bonus_costs_new", "bonus_costs")
    op.create_index("ix_bonus_costs_user_id", "bonus_costs", ["user_id"])


def downgrade() -> None:
    op.create_table(
        "bonus_costs_old",
        sa.Column("ticker", sa.String(length=12), nullable=False),
        sa.Column("record_date", sa.Date(), nullable=False),
        sa.Column("unit_cost", investtrack.db.SafeDecimal(), nullable=False),
        sa.PrimaryKeyConstraint("ticker", "record_date"),
    )
    # With several users, the same bonus may have several costs: keep one.
    op.execute(
        "INSERT INTO bonus_costs_old (ticker, record_date, unit_cost) "
        "SELECT ticker, record_date, MIN(unit_cost) FROM bonus_costs GROUP BY ticker, record_date"
    )
    op.drop_index("ix_bonus_costs_user_id", table_name="bonus_costs")
    op.drop_table("bonus_costs")
    op.rename_table("bonus_costs_old", "bonus_costs")

    for table in OWNED:
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(f"fk_{table}_user_id", type_="foreignkey")
            batch.drop_index(f"ix_{table}_user_id")
            batch.drop_column("user_id")

    op.drop_index("ix_auth_sessions_user_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_table("users")
