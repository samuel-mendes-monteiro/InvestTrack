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
    asset_type: Mapped[AssetType] = mapped_column(
        Enum(AssetType, native_enum=False, length=10)
    )
    name: Mapped[str | None] = mapped_column(String(100))

    operations: Mapped[list["OperationRecord"]] = relationship(
        back_populates="asset"
    )

    def __repr__(self) -> str:
        return f"Asset({self.ticker})"


class OperationRecord(Base):
    __tablename__ = "operations"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"))
    op_type: Mapped[OpType] = mapped_column(
        Enum(OpType, native_enum=False, length=10)
    )
    date: Mapped[date] = mapped_column(Date)
    quantity: Mapped[Decimal] = mapped_column(SafeDecimal)
    price: Mapped[Decimal] = mapped_column(SafeDecimal)
    fees: Mapped[Decimal] = mapped_column(SafeDecimal, default=Decimal("0"))

    asset: Mapped[Asset] = relationship(back_populates="operations")

    # Positions are always rebuilt by reading one asset's operations in date order.
    __table_args__ = (Index("ix_operations_asset_date", "asset_id", "date"),)

    def __repr__(self) -> str:
        return f"OperationRecord(id={self.id}, {self.op_type} {self.quantity} @ {self.price})"


class PriceCache(Base):
    """Last known quote for each ticker (used in stage 4)."""

    __tablename__ = "price_cache"

    ticker: Mapped[str] = mapped_column(String(12), primary_key=True)
    price: Mapped[Decimal] = mapped_column(SafeDecimal)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
