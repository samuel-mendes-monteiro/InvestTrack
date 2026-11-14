"""Database tables.

These classes describe how data is stored. They are separate from the
dataclasses in portfolio.py, which describe how data is calculated.
Note there is no "positions" table: positions are always recalculated
from the operations.
"""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from investtrack.db import Base, SafeDecimal
from investtrack.income import IncomeType
from investtrack.portfolio import OpType


class AssetType(StrEnum):
    STOCK = "STOCK"
    FII = "FII"
    ETF = "ETF"
    BDR = "BDR"


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


class IncomeEventSync(Base):
    """When each ticker's events were last fetched from B3."""

    __tablename__ = "income_event_sync"

    ticker: Mapped[str] = mapped_column(String(12), primary_key=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
