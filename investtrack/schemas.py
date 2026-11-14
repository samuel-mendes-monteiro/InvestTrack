"""Shapes of the JSON that goes in and out of the API (Pydantic).

Decimals are sent as JSON strings ("35.10"), not numbers, so a client
never has to parse money into a float.
"""

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    Field,
    PlainSerializer,
    ValidationInfo,
    field_validator,
)

from investtrack.income import IncomeSource, IncomeType
from investtrack.models import AssetType
from investtrack.portfolio import OpType


def _round2(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# Calculations keep full precision; values are rounded only when sent out.
Money = Annotated[Decimal, PlainSerializer(_round2, return_type=str, when_used="json")]


def _not_in_the_future(value: date) -> date:
    if value > date.today():
        raise ValueError("date cannot be in the future")
    return value


# Shared by operations and income: a reusable type instead of a copied validator.
PastDate = Annotated[date, AfterValidator(_not_in_the_future)]


class OperationCreate(BaseModel):
    ticker: str = Field(min_length=1, max_length=12, examples=["PETR4"])
    op_type: OpType
    date: PastDate
    quantity: Decimal = Field(gt=0, examples=["100"])
    price: Decimal = Field(ge=0, examples=["30.50"])
    fees: Decimal = Field(default=Decimal("0"), ge=0, examples=["4.90"])
    asset_type: AssetType = Field(
        default=AssetType.STOCK, description="Only used the first time a ticker appears"
    )


class IncomeCreate(BaseModel):
    ticker: str = Field(min_length=1, max_length=12, examples=["ITSA4"])
    income_type: IncomeType
    date: PastDate = Field(description="Payment date")
    amount: Decimal = Field(gt=0, description="Gross total received", examples=["120.50"])
    tax: Decimal = Field(
        default=Decimal("0"), ge=0, description="Withheld at source", examples=["18.08"]
    )

    @field_validator("tax")
    @classmethod
    def tax_not_above_amount(cls, value: Decimal, info: ValidationInfo) -> Decimal:
        # "amount" is missing from info.data if it failed its own validation.
        amount = info.data.get("amount")
        if amount is not None and value > amount:
            raise ValueError("tax cannot be larger than the amount")
        return value


class IncomeOut(BaseModel):
    id: int | None = Field(description="Only manual entries have an id (and can be deleted)")
    source: IncomeSource
    ticker: str
    income_type: IncomeType
    # No Field() here: "date = Field(...)" would shadow the type for the fields below.
    date: date  # payment date
    pending: bool = Field(description="True if the payment date hasn't arrived yet")
    amount: Decimal
    tax: Decimal
    net: Decimal
    record_date: date | None = Field(description="Data com (computed income only)")
    quantity: Decimal | None = Field(description="Shares held on the record date")
    rate: Decimal | None = Field(description="Gross value per share")


class MonthlyIncomeOut(BaseModel):
    year: int
    month: int
    dividend: Money
    jcp: Money
    distribution: Money
    tax: Money
    net: Money


class OperationOut(BaseModel):
    id: int
    ticker: str
    op_type: OpType
    date: PastDate
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
    income: Money = Field(description="Net income already received (dividends, JCP, distributions)")


class PortfolioTotals(BaseModel):
    invested: Money
    current_value: Money | None  # None if some open position has no price
    result: Money | None
    result_pct: Money | None
    realized_profit: Money
    income: Money
    income_pending: Money = Field(description="Announced income not paid yet")


class PortfolioOut(BaseModel):
    positions: list[PositionOut]
    totals: PortfolioTotals


class ErrorDetail(BaseModel):
    code: str = Field(examples=["INSUFFICIENT_POSITION"])
    message: str = Field(description="English fallback text")
    ticker: str | None = None
    available: Decimal | None = None
    requested: Decimal | None = None
    income_date: date | None = None
    first_buy: date | None = None


class ErrorOut(BaseModel):
    detail: ErrorDetail
