"""Database tables.

These classes describe how data is stored. They are separate from the
dataclasses in portfolio.py, which describe how data is calculated.
Note there is no "positions" table: positions are always recalculated
from the operations.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from investtrack.core.fixed_income import Indexer, Product
from investtrack.core.income import IncomeType
from investtrack.core.portfolio import AssetType, OpType, StockEventType
from investtrack.storage.db import Base, SafeDecimal


class User(Base):
    """An account. The password itself is never stored, only its Argon2 hash."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)  # always lowercase
    password_hash: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuthSession(Base):
    """A logged-in session. Only the SHA-256 of the token is stored: whoever
    reads the database can't use it to log in, and logging out deletes the row."""

    __tablename__ = "auth_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# Every table with the user's own data has an owner. The column is nullable
# only for rows created before v0.5, which the first account adopts; the
# application always sets it.
def owner_column() -> Mapped[int | None]:
    return mapped_column(ForeignKey("users.id"), index=True)


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(12), unique=True)
    asset_type: Mapped[AssetType] = mapped_column(Enum(AssetType, native_enum=False, length=10))
    name: Mapped[str | None] = mapped_column(String(100))

    operations: Mapped[list["OperationRecord"]] = relationship(back_populates="asset")
    incomes: Mapped[list["IncomeRecord"]] = relationship(back_populates="asset")

    def __repr__(self) -> str:
        return f"Asset({self.ticker})"


class OperationRecord(Base):
    __tablename__ = "operations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = owner_column()
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"))
    op_type: Mapped[OpType] = mapped_column(Enum(OpType, native_enum=False, length=10))
    date: Mapped[date] = mapped_column(Date)
    quantity: Mapped[Decimal] = mapped_column(SafeDecimal)
    price: Mapped[Decimal] = mapped_column(SafeDecimal)
    fees: Mapped[Decimal] = mapped_column(SafeDecimal, default=Decimal("0"))

    asset: Mapped[Asset] = relationship(back_populates="operations")

    # Positions are always rebuilt by reading one asset's operations in date order.
    __table_args__ = (Index("ix_operations_asset_date", "asset_id", "date"),)

    def __repr__(self) -> str:
        return f"OperationRecord(id={self.id}, {self.op_type} {self.quantity} @ {self.price})"


class IncomeRecord(Base):
    """Dividends, JCP and FII distributions received.

    A separate table instead of new op_types in "operations": income has no
    quantity or price, and mixing both would force every position
    calculation to skip rows that aren't trades. Adding a table is also the
    safest schema change: create_all creates it in existing databases and
    no existing row or column changes.
    """

    __tablename__ = "incomes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = owner_column()
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"))
    income_type: Mapped[IncomeType] = mapped_column(Enum(IncomeType, native_enum=False, length=20))
    date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(SafeDecimal)
    tax: Mapped[Decimal] = mapped_column(SafeDecimal, default=Decimal("0"))

    asset: Mapped[Asset] = relationship(back_populates="incomes")

    __table_args__ = (Index("ix_incomes_asset_date", "asset_id", "date"),)

    def __repr__(self) -> str:
        return f"IncomeRecord(id={self.id}, {self.income_type} {self.amount})"


class PriceCache(Base):
    """Last known quote for each ticker (used in stage 4)."""

    __tablename__ = "price_cache"

    ticker: Mapped[str] = mapped_column(String(12), primary_key=True)
    price: Mapped[Decimal] = mapped_column(SafeDecimal)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IncomeEventRecord(Base):
    """Income events published by B3 (value per share, record date).

    This is market data, like price_cache: it is keyed by ticker and does
    not depend on what you own. What you received is never stored; it is
    computed from these events and your operations.

    Unlike the price cache, events are kept for good: B3 only shows about
    the last 12 months, so older events would otherwise be lost.
    """

    __tablename__ = "income_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(12))
    income_type: Mapped[IncomeType] = mapped_column(Enum(IncomeType, native_enum=False, length=20))
    record_date: Mapped[date] = mapped_column(Date)
    payment_date: Mapped[date | None] = mapped_column(Date)
    rate: Mapped[Decimal] = mapped_column(SafeDecimal)

    __table_args__ = (Index("ix_income_events_ticker_record_date", "ticker", "record_date"),)


class StockEventRecord(Base):
    """Splits, reverse splits and bonus shares published by B3.

    Market data like income_events: keyed by ticker, kept for good. Positions
    are never stored; they are computed from operations and these events.
    """

    __tablename__ = "stock_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(12))
    event_type: Mapped[StockEventType] = mapped_column(
        Enum(StockEventType, native_enum=False, length=20)
    )
    record_date: Mapped[date] = mapped_column(Date)
    multiplier: Mapped[Decimal] = mapped_column(SafeDecimal)
    unit_cost: Mapped[Decimal] = mapped_column(SafeDecimal, default=Decimal("0"))

    __table_args__ = (Index("ix_stock_events_ticker_record_date", "ticker", "record_date"),)


class EventSync(Base):
    """When each ticker's events (income and stock) were last fetched from B3.

    Replaces the v0.2 table income_event_sync, which only covered income:
    a new table makes every ticker sync again, so stock events are fetched
    right away. The old table is no longer used.
    """

    __tablename__ = "event_sync"

    ticker: Mapped[str] = mapped_column(String(12), primary_key=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BonusCost(Base):
    """Attributed cost (custo atribuído) of the shares of one bonus event.

    Typed by the user: the company discloses it in its notice to
    shareholders, but B3 doesn't publish it in the data used here. Kept
    apart from stock_events because a sync replaces those rows.
    """

    __tablename__ = "bonus_costs"

    # Per user, although the value is the same for everyone: one person's
    # typo must never change another person's average price.
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = owner_column()
    ticker: Mapped[str] = mapped_column(String(12))
    record_date: Mapped[date] = mapped_column(Date)
    unit_cost: Mapped[Decimal] = mapped_column(SafeDecimal)

    __table_args__ = (UniqueConstraint("user_id", "ticker", "record_date"),)


class DailyPrice(Base):
    """Official closing price of each B3 spot-market ticker, from COTAHIST.

    Every ticker of each downloaded day is kept, not only the ones you own:
    a ticker added later already has its history, without downloading again.
    """

    __tablename__ = "daily_prices"

    ticker: Mapped[str] = mapped_column(String(12), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    close: Mapped[Decimal] = mapped_column(SafeDecimal)

    __table_args__ = (Index("ix_daily_prices_date", "date"),)


class BenchmarkValue(Base):
    """Daily benchmark data: "IBOV" (index points) and "CDI" (% per day)."""

    __tablename__ = "benchmark_values"

    series: Mapped[str] = mapped_column(String(10), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    value: Mapped[Decimal] = mapped_column(SafeDecimal)


class HistoryLoad(Base):
    """Which periods of historical data were already downloaded.

    period examples: "COTAHIST:M102026" (a month), "COTAHIST:D13112026"
    (a day, also recorded for holidays, which have no file), "IBOV:2026", "CDI".
    """

    __tablename__ = "history_loads"

    period: Mapped[str] = mapped_column(String(30), primary_key=True)
    loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class FixedIncomeRecord(Base):
    """A CDB, LCI or LCA. Its value is never stored: it comes from the CDI."""

    __tablename__ = "fixed_income"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = owner_column()
    name: Mapped[str] = mapped_column(String(100))
    product: Mapped[Product] = mapped_column(Enum(Product, native_enum=False, length=10))
    indexer: Mapped[Indexer] = mapped_column(Enum(Indexer, native_enum=False, length=10))
    rate: Mapped[Decimal] = mapped_column(SafeDecimal)
    start: Mapped[date] = mapped_column(Date)
    maturity: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(SafeDecimal)
    redeemed_on: Mapped[date | None] = mapped_column(Date)

    # Loaded with the investment (selectin: one query for all of them) and
    # deleted with it: a withdrawal means nothing without its investment.
    partial_redemptions: Mapped[list["PartialRedemptionRecord"]] = relationship(
        back_populates="investment",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="PartialRedemptionRecord.date, PartialRedemptionRecord.id",
    )


class PartialRedemptionRecord(Base):
    """Money withdrawn from a fixed income investment that keeps running.

    No user_id: the owner is the investment's, and every access goes
    through the investment, which is already checked.
    """

    __tablename__ = "partial_redemptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    fixed_income_id: Mapped[int] = mapped_column(
        ForeignKey("fixed_income.id", ondelete="CASCADE"), index=True
    )
    date: Mapped[date] = mapped_column(Date)
    gross: Mapped[Decimal] = mapped_column(SafeDecimal)

    investment: Mapped[FixedIncomeRecord] = relationship(back_populates="partial_redemptions")
