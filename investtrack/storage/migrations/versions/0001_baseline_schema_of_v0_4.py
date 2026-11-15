"""Baseline: the schema of v0.4, the last version before migrations.

Revision ID: 0001
Revises:
Create Date: 2026-11-14 12:43:55.928336
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import investtrack.storage.db

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Databases from before migrations existed (v0.1 to v0.4) were created with
    # create_all: their tables already exist. Creating only the missing ones lets
    # old and new databases follow the same path, with no special case.
    existing = set(sa.inspect(op.get_bind()).get_table_names())

    if "assets" not in existing:
        op.create_table(
            "assets",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("ticker", sa.String(length=12), nullable=False),
            sa.Column(
                "asset_type",
                sa.Enum(
                    "STOCK", "FII", "ETF", "BDR", name="assettype", native_enum=False, length=10
                ),
                nullable=False,
            ),
            sa.Column("name", sa.String(length=100), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("ticker"),
        )

    if "benchmark_values" not in existing:
        op.create_table(
            "benchmark_values",
            sa.Column("series", sa.String(length=10), nullable=False),
            sa.Column("date", sa.Date(), nullable=False),
            sa.Column("value", investtrack.storage.db.SafeDecimal(), nullable=False),
            sa.PrimaryKeyConstraint("series", "date"),
        )

    if "bonus_costs" not in existing:
        op.create_table(
            "bonus_costs",
            sa.Column("ticker", sa.String(length=12), nullable=False),
            sa.Column("record_date", sa.Date(), nullable=False),
            sa.Column("unit_cost", investtrack.storage.db.SafeDecimal(), nullable=False),
            sa.PrimaryKeyConstraint("ticker", "record_date"),
        )

    if "daily_prices" not in existing:
        op.create_table(
            "daily_prices",
            sa.Column("ticker", sa.String(length=12), nullable=False),
            sa.Column("date", sa.Date(), nullable=False),
            sa.Column("close", investtrack.storage.db.SafeDecimal(), nullable=False),
            sa.PrimaryKeyConstraint("ticker", "date"),
        )
        with op.batch_alter_table("daily_prices", schema=None) as batch_op:
            batch_op.create_index("ix_daily_prices_date", ["date"], unique=False)

    if "event_sync" not in existing:
        op.create_table(
            "event_sync",
            sa.Column("ticker", sa.String(length=12), nullable=False),
            sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("ticker"),
        )

    if "fixed_income" not in existing:
        op.create_table(
            "fixed_income",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column(
                "product",
                sa.Enum("CDB", "LCI", "LCA", name="product", native_enum=False, length=10),
                nullable=False,
            ),
            sa.Column(
                "indexer",
                sa.Enum("CDI", "PRE", name="indexer", native_enum=False, length=10),
                nullable=False,
            ),
            sa.Column("rate", investtrack.storage.db.SafeDecimal(), nullable=False),
            sa.Column("start", sa.Date(), nullable=False),
            sa.Column("maturity", sa.Date(), nullable=False),
            sa.Column("amount", investtrack.storage.db.SafeDecimal(), nullable=False),
            sa.Column("redeemed_on", sa.Date(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )

    if "history_loads" not in existing:
        op.create_table(
            "history_loads",
            sa.Column("period", sa.String(length=30), nullable=False),
            sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("period"),
        )

    if "income_events" not in existing:
        op.create_table(
            "income_events",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("ticker", sa.String(length=12), nullable=False),
            sa.Column(
                "income_type",
                sa.Enum(
                    "DIVIDEND",
                    "JCP",
                    "DISTRIBUTION",
                    name="incometype",
                    native_enum=False,
                    length=20,
                ),
                nullable=False,
            ),
            sa.Column("record_date", sa.Date(), nullable=False),
            sa.Column("payment_date", sa.Date(), nullable=True),
            sa.Column("rate", investtrack.storage.db.SafeDecimal(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("income_events", schema=None) as batch_op:
            batch_op.create_index(
                "ix_income_events_ticker_record_date", ["ticker", "record_date"], unique=False
            )

    if "price_cache" not in existing:
        op.create_table(
            "price_cache",
            sa.Column("ticker", sa.String(length=12), nullable=False),
            sa.Column("price", investtrack.storage.db.SafeDecimal(), nullable=False),
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("ticker"),
        )

    if "stock_events" not in existing:
        op.create_table(
            "stock_events",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("ticker", sa.String(length=12), nullable=False),
            sa.Column(
                "event_type",
                sa.Enum(
                    "SPLIT",
                    "REVERSE_SPLIT",
                    "BONUS",
                    name="stockeventtype",
                    native_enum=False,
                    length=20,
                ),
                nullable=False,
            ),
            sa.Column("record_date", sa.Date(), nullable=False),
            sa.Column("multiplier", investtrack.storage.db.SafeDecimal(), nullable=False),
            sa.Column("unit_cost", investtrack.storage.db.SafeDecimal(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("stock_events", schema=None) as batch_op:
            batch_op.create_index(
                "ix_stock_events_ticker_record_date", ["ticker", "record_date"], unique=False
            )

    if "incomes" not in existing:
        op.create_table(
            "incomes",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("asset_id", sa.Integer(), nullable=False),
            sa.Column(
                "income_type",
                sa.Enum(
                    "DIVIDEND",
                    "JCP",
                    "DISTRIBUTION",
                    name="incometype",
                    native_enum=False,
                    length=20,
                ),
                nullable=False,
            ),
            sa.Column("date", sa.Date(), nullable=False),
            sa.Column("amount", investtrack.storage.db.SafeDecimal(), nullable=False),
            sa.Column("tax", investtrack.storage.db.SafeDecimal(), nullable=False),
            sa.ForeignKeyConstraint(
                ["asset_id"],
                ["assets.id"],
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("incomes", schema=None) as batch_op:
            batch_op.create_index("ix_incomes_asset_date", ["asset_id", "date"], unique=False)

    if "operations" not in existing:
        op.create_table(
            "operations",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("asset_id", sa.Integer(), nullable=False),
            sa.Column(
                "op_type",
                sa.Enum("BUY", "SELL", name="optype", native_enum=False, length=10),
                nullable=False,
            ),
            sa.Column("date", sa.Date(), nullable=False),
            sa.Column("quantity", investtrack.storage.db.SafeDecimal(), nullable=False),
            sa.Column("price", investtrack.storage.db.SafeDecimal(), nullable=False),
            sa.Column("fees", investtrack.storage.db.SafeDecimal(), nullable=False),
            sa.ForeignKeyConstraint(
                ["asset_id"],
                ["assets.id"],
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("operations", schema=None) as batch_op:
            batch_op.create_index("ix_operations_asset_date", ["asset_id", "date"], unique=False)


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table("operations", schema=None) as batch_op:
        batch_op.drop_index("ix_operations_asset_date")

    op.drop_table("operations")
    with op.batch_alter_table("incomes", schema=None) as batch_op:
        batch_op.drop_index("ix_incomes_asset_date")

    op.drop_table("incomes")
    with op.batch_alter_table("stock_events", schema=None) as batch_op:
        batch_op.drop_index("ix_stock_events_ticker_record_date")

    op.drop_table("stock_events")
    op.drop_table("price_cache")
    with op.batch_alter_table("income_events", schema=None) as batch_op:
        batch_op.drop_index("ix_income_events_ticker_record_date")

    op.drop_table("income_events")
    op.drop_table("history_loads")
    op.drop_table("fixed_income")
    op.drop_table("event_sync")
    with op.batch_alter_table("daily_prices", schema=None) as batch_op:
        batch_op.drop_index("ix_daily_prices_date")

    op.drop_table("daily_prices")
    op.drop_table("bonus_costs")
    op.drop_table("benchmark_values")
    op.drop_table("assets")
    # ### end Alembic commands ###
