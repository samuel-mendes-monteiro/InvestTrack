"""Shapes of the JSON that goes in and out of the API (Pydantic).

Decimals are sent as JSON strings ("35.10"), not numbers, so a client
never has to parse money into a float.
"""

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    Field,
    PlainSerializer,
    ValidationInfo,
    field_validator,
)

from investtrack.fixed_income import Indexer, Product
from investtrack.income import IncomeSource, IncomeType
from investtrack.models import AssetType
from investtrack.portfolio import OpType, StockEventType

# For classes with a field named "date": inside them that name means the
# field's default, not the type, once annotations are evaluated.
Day = date


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


class Credentials(BaseModel):
    email: str = Field(max_length=254, examples=["ana@example.com"])
    password: str = Field(max_length=256)  # the length rules live in auth.py


class UserOut(BaseModel):
    id: int
    email: str
    created_at: datetime = Field(description="When the account was created")


class AccountDeletion(BaseModel):
    password: str = Field(max_length=256)


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)  # the length rules live in auth.py


class SessionOut(BaseModel):
    # The token itself goes only in the HttpOnly cookie, never in the body:
    # a script that can read responses still can't read the session.
    expires_at: datetime


class StockEventOut(BaseModel):
    ticker: str
    event_type: StockEventType
    record_date: date = Field(description="Applied at the end of this day")
    multiplier: Decimal = Field(description="Shares after = shares before x multiplier")
    quantity_before: Decimal
    quantity_after: Decimal
    unit_cost: Decimal | None = Field(
        description="Attributed cost per bonus share, None if not informed (counts as zero)"
    )


class BonusCostIn(BaseModel):
    unit_cost: Decimal = Field(ge=0, description="From the company's notice", examples=["7.82"])


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
    fixed_income: Money | None = Field(
        description="Net value of fixed income still invested; None while some value is unknown"
    )


class PriceOut(BaseModel):
    ticker: str
    date: date  # the day the price is from: a close may be from before the day asked
    price: Money
    source: Literal["QUOTE", "CLOSE"] = Field(
        description="QUOTE: current price (brapi); CLOSE: official B3 close of that day"
    )


class PortfolioOut(BaseModel):
    positions: list[PositionOut]
    totals: PortfolioTotals
    syncing: bool = Field(
        description="CDI history is being downloaded; fixed income values may change or be unknown"
    )


class FixedIncomeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100, examples=["CDB Banco X"])
    product: Product
    indexer: Indexer
    rate: Decimal = Field(
        gt=0,
        description="% of CDI (110), % per year (12.5), or % per year above IPCA (6.5)",
        examples=["110"],
    )
    start: PastDate
    maturity: date
    amount: Decimal = Field(gt=0, examples=["5000"])


class RedeemIn(BaseModel):
    redeemed_on: PastDate | None = Field(description="None undoes an early redemption")


class PartialRedemptionIn(BaseModel):
    date: PastDate = Field(description="A business day after the start")
    gross: Decimal = Field(gt=0, description="Amount withdrawn, before taxes", examples=["1000"])


class PartialRedemptionOut(BaseModel):
    id: int
    date: date
    gross: Money
    iof: Money | None = Field(description="None until that day's CDI is known")
    ir: Money | None
    net: Money | None


class FixedIncomeOut(BaseModel):
    id: int
    name: str
    product: Product
    indexer: Indexer
    rate: Decimal
    start: date
    maturity: date
    amount: Money
    redeemed_on: date | None
    partial_redemptions: list[PartialRedemptionOut]
    principal: Money = Field(description="Amount invested still held, after partial redemptions")
    status: Literal["ACTIVE", "REDEEMED", "MATURED"]
    as_of: date | None = Field(description="Day of the values below; None until the CDI is known")
    estimated: bool = Field(
        description="IPCA+ only: uses the last published IPCA for months not out yet"
    )
    gross: Money | None
    iof: Money | None
    ir: Money | None
    net: Money | None
    gross_return: Money | None = Field(description="Gross return since the start, %")


class PerformancePoint(BaseModel):
    date: date
    value: Money = Field(description="Portfolio value at the close")
    net_worth: Money = Field(
        description="Value at the close with fixed income net of taxes, as the portfolio shows it"
    )
    invested: Money = Field(
        description="Money put in minus taken out until this close, fees included"
    )
    twr: Money = Field(description="Cumulative time-weighted return, %")
    twr_price: Money = Field(description="The same without income: prices (and fees) only, %")
    cdi: Money | None = Field(description="CDI accumulated over the same period, %")
    ibovespa: Money | None = Field(description="Ibovespa return over the same period, %")


class PerformanceOut(BaseModel):
    syncing: bool = Field(description="Historical data is being downloaded; numbers may change")
    start: date | None = Field(
        description="First trading day with a position, or the close a period starts from"
    )
    as_of: date | None = Field(description="Last day with official closing prices")
    twr: Money | None
    twr_price: Money | None = Field(
        None, description="The same return without income: from prices (and fees) only, %"
    )
    cdi: Money | None
    ibovespa: Money | None
    pct_of_cdi: Money | None = Field(description="TWR as a percentage of the CDI")
    pct_of_cdi_price: Money | None = Field(
        None, description="The price-only return as a percentage of the CDI"
    )
    points: list[PerformancePoint]
    invested_now: Money | None = Field(
        None,
        description="Money put in minus taken out until today, after the last close too; "
        "None while a redemption's value is unknown",
    )


class ErrorDetail(BaseModel):
    code: str = Field(examples=["INSUFFICIENT_POSITION"])
    message: str = Field(description="English fallback text")
    ticker: str | None = None
    available: Decimal | None = None
    requested: Decimal | None = None
    income_date: Day | None = None
    first_buy: Day | None = None
    date: Day | None = Field(None, description="REDEMPTION_TOO_LARGE: the day asked for")
    retry_after: int | None = Field(None, description="TOO_MANY_ATTEMPTS: seconds to wait")


class ErrorOut(BaseModel):
    detail: ErrorDetail


class ImportRowOut(BaseModel):
    line: int = Field(description="Row in the spreadsheet")
    status: Literal["NEW", "DUPLICATE", "REJECTED", "IMPORTED"] = Field(
        description="IMPORTED replaces NEW once the import is saved"
    )
    date: date
    op_type: OpType
    ticker: str
    quantity: Decimal
    price: Decimal
    error: ErrorDetail | None = Field(description="Why a REJECTED row can't be imported")


class SkippedRowOut(BaseModel):
    line: int
    reason: Literal["UNSUPPORTED_MARKET", "UNKNOWN_TYPE", "UNREADABLE_ROW"]
    detail: str


class ImportOut(BaseModel):
    imported: bool = Field(description="False for a preview: nothing was saved")
    new: int
    duplicates: int
    rejected: int
    skipped: int
    rows: list[ImportRowOut]
    skipped_rows: list[SkippedRowOut]
