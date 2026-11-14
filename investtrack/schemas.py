"""Shapes of the JSON that goes in and out of the API (Pydantic).

Decimals are sent as JSON strings ("35.10"), not numbers, so a client
never has to parse money into a float.
"""

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated

from pydantic import BaseModel, Field, PlainSerializer, field_validator

from investtrack.models import AssetType
from investtrack.portfolio import OpType


def _round2(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# Calculations keep full precision; values are rounded only when sent out.
Money = Annotated[Decimal, PlainSerializer(_round2, return_type=str, when_used="json")]


class OperationCreate(BaseModel):
    ticker: str = Field(min_length=1, max_length=12, examples=["PETR4"])
    op_type: OpType
    date: date
    quantity: Decimal = Field(gt=0, examples=["100"])
    price: Decimal = Field(ge=0, examples=["30.50"])
    fees: Decimal = Field(default=Decimal("0"), ge=0, examples=["4.90"])
    asset_type: AssetType = Field(
        default=AssetType.STOCK, description="Only used the first time a ticker appears"
    )

    @field_validator("date")
    @classmethod
    def not_in_the_future(cls, value: date) -> date:
        if value > date.today():
            raise ValueError("operation date cannot be in the future")
        return value


class OperationOut(BaseModel):
    id: int
    ticker: str
    op_type: OpType
    date: date
    quantity: Decimal
    price: Decimal
    fees: Decimal


class PositionOut(BaseModel):
    ticker: str
    quantity: Decimal
    avg_price: Money
    realized_profit: Money
    current_price: Money | None
    price_as_of: datetime | None = Field(description="When the price was fetched")
    price_stale: bool = Field(
        description="True if the quote source failed and an old price is shown"
    )
    invested: Money
    current_value: Money | None
    result: Money | None
    result_pct: Money | None


class PortfolioTotals(BaseModel):
    invested: Money
    current_value: Money | None  # None if some open position has no price
    result: Money | None
    result_pct: Money | None
    realized_profit: Money


class PortfolioOut(BaseModel):
    positions: list[PositionOut]
    totals: PortfolioTotals


class ErrorDetail(BaseModel):
    code: str = Field(examples=["INSUFFICIENT_POSITION"])
    message: str = Field(description="English fallback text")
    ticker: str | None = None
    available: Decimal | None = None
    requested: Decimal | None = None


class ErrorOut(BaseModel):
    detail: ErrorDetail
