"""Pure fixed income calculations: CDB, LCI and LCA.

Like portfolio.py, this module has no database, HTTP or I/O.

Unlike shares, these have no market price: the value comes from a formula.
- Post-fixed (% of CDI): each business day the investment earns that day's
  CDI times the percentage:  value = amount x prod(1 + CDI_day x pct)
- Pre-fixed (annual rate):  value = amount x (1 + rate) ^ (business days / 252)

Business days come from the CDI series itself: the Central Bank publishes
a rate only on business days, so it is the official calendar for free.
Each day's CDI is earned overnight, so a value at the close of day d
includes the rates of the days before d.

Taxes on redemption (CDB only; LCI and LCA are exempt for individuals):
- IOF, if redeemed within 30 days, on the gain (Decreto 6.306/2007);
- income tax on the gain minus IOF, by calendar days held (Lei 11.033/2004).
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from investtrack.portfolio import ONE, ZERO


class Product(StrEnum):
    CDB = "CDB"
    LCI = "LCI"
    LCA = "LCA"


class Indexer(StrEnum):
    CDI = "CDI"  # rate is a percentage of the CDI, e.g. 110
    PRE = "PRE"  # rate is a fixed annual percentage, e.g. 12.5


TAX_EXEMPT = {Product.LCI, Product.LCA}

# Income tax on the gain, by calendar days held: (up to N days, rate).
IR_TABLE = [(180, Decimal("0.225")), (360, Decimal("0.20")), (720, Decimal("0.175"))]
IR_LONG_TERM = Decimal("0.15")

# IOF on the gain for redemptions on day 1..29; from day 30 on there is none.
IOF_TABLE = [
    96, 93, 90, 86, 83, 80, 76, 73, 70, 66, 63, 60, 56, 53, 50,
    46, 43, 40, 36, 33, 30, 26, 23, 20, 16, 13, 10, 6, 3,
]  # fmt: skip


def ir_rate(days_held: int) -> Decimal:
    for limit, rate in IR_TABLE:
        if days_held <= limit:
            return rate
    return IR_LONG_TERM


def iof_rate(days_held: int) -> Decimal:
    if days_held <= 0:
        return ONE  # redeemed the same day: the whole gain
    if days_held >= 30:
        return ZERO
    return Decimal(IOF_TABLE[days_held - 1]) / 100


@dataclass(frozen=True)
class FixedIncome:
    name: str  # e.g. "CDB Banco X"
    product: Product
    indexer: Indexer
    rate: Decimal  # % of CDI (110) or % per year (12.5)
    start: date
    maturity: date
    amount: Decimal
    redeemed_on: date | None = None  # early redemption; None = held until maturity

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("name must not be empty")
        object.__setattr__(self, "name", self.name.strip())
        object.__setattr__(self, "product", Product(self.product))
        object.__setattr__(self, "indexer", Indexer(self.indexer))
        for field in ("rate", "amount"):
            if not isinstance(getattr(self, field), Decimal):
                raise TypeError(f"{field} must be a Decimal, never a float")
        if self.amount <= 0:
            raise ValueError("amount must be greater than zero")
        if self.rate <= 0:
            raise ValueError("rate must be greater than zero")
        if self.maturity <= self.start:
            raise ValueError("maturity must be after the start date")
        if self.redeemed_on is not None and not self.start <= self.redeemed_on <= self.maturity:
            raise ValueError("redemption must be between the start and the maturity")

    @property
    def end(self) -> date:
        """Last day the money is invested: redemption or maturity."""
        return self.redeemed_on or self.maturity


@dataclass(frozen=True)
class Valuation:
    day: date
    gross: Decimal
    iof: Decimal
    ir: Decimal

    @property
    def net(self) -> Decimal:
        return self.gross - self.iof - self.ir


def gross_values(
    investment: FixedIncome, business_days: list[date], cdi: dict[date, Decimal]
) -> dict[date, Decimal]:
    """Gross value at the close of each business day while invested.

    Stops at the end (redemption or maturity) or at the last day with data.
    For post-fixed, a day without a published CDI ends the series, since the
    value can't be known past it.
    """
    pct = investment.rate / 100
    days = sorted(d for d in business_days if investment.start <= d <= investment.end)
    values: dict[date, Decimal] = {}
    value = investment.amount
    elapsed = 0
    previous: date | None = None
    for day in days:
        if previous is not None:
            if investment.indexer is Indexer.CDI:
                if previous not in cdi:
                    break
                value *= 1 + cdi[previous] / 100 * pct
            else:
                elapsed += 1
                value = investment.amount * (1 + pct) ** (Decimal(elapsed) / 252)
        values[day] = value
        previous = day
    return values


def taxes(investment: FixedIncome, day: date, gross: Decimal) -> Valuation:
    """IOF and income tax if redeemed on `day` with this gross value."""
    gain = max(gross - investment.amount, ZERO)
    if investment.product in TAX_EXEMPT:
        return Valuation(day, gross, ZERO, ZERO)
    held = (day - investment.start).days
    iof = gain * iof_rate(held)
    ir = (gain - iof) * ir_rate(held)
    return Valuation(day, gross, iof, ir)


def value_on(
    investment: FixedIncome, day: date, business_days: list[date], cdi: dict[date, Decimal]
) -> Valuation | None:
    """Value on `day` (or the last day with data before it), with taxes."""
    values = gross_values(investment, business_days, cdi)
    known = [d for d in values if d <= day]
    if not known:
        return None
    last = max(known)
    return taxes(investment, last, values[last])


def daily_series(
    investments: list[FixedIncome], business_days: list[date], cdi: dict[date, Decimal]
) -> tuple[dict[date, Decimal], dict[date, Decimal]]:
    """Values and flows of all investments, ready to join the TWR.

    Applying is money in on the first day; redeeming (or maturing) is money
    out at the gross value on the last day, which then no longer counts in
    the value. Investments still running count until the last day with data.
    """
    values: dict[date, Decimal] = defaultdict(lambda: ZERO)
    flows: dict[date, Decimal] = defaultdict(lambda: ZERO)
    last_known = max(business_days, default=None)
    for investment in investments:
        gross = gross_values(investment, business_days, cdi)
        if not gross:
            continue
        flows[min(gross)] += investment.amount
        ended = last_known is not None and investment.end <= last_known
        last = max(gross)
        for day, value in gross.items():
            if ended and day == last:
                flows[day] -= value
            else:
                values[day] += value
    return dict(values), dict(flows)
