"""Pure fixed income calculations: CDB, LCI and LCA.

Like portfolio.py, this module has no database, HTTP or I/O.

Unlike shares, these have no market price: the value comes from a formula.
- Post-fixed (% of CDI): each business day the investment earns that day's
  CDI times the percentage:  value = amount x prod(1 + CDI_day x pct)
- Pre-fixed (annual rate):  value = amount x (1 + rate) ^ (business days / 252)
- IPCA+ (real annual rate): the pre-fixed formula times the inflation since
  the start. Each month's IPCA is spread over its calendar days, so the
  value grows a little every day instead of jumping once a month. The IPCA
  of a month only comes out around the 10th of the next one: until then,
  the last published month is repeated, and the value is an estimate.
  (Banks and the Tesouro use an anniversary date and business days instead;
  over whole months the result is the same, within a month it differs a little.)

Business days come from the CDI series itself: the Central Bank publishes
a rate only on business days, so it is the official calendar for free.
Each day's CDI is earned overnight, so a value at the close of day d
includes the rates of the days before d.

Partial redemptions: the value grows in proportion to the money invested,
so withdrawing R from a value V leaves (1 - R/V) of everything: of the
value from then on, and of the principal. Each withdrawal is taxed on its
own share of the gain, by the days held since the start (the whole
investment has one start, so it has one IR bracket on each day).

Taxes on redemption (CDB only; LCI and LCA are exempt for individuals):
- IOF, if redeemed within 30 days, on the gain (Decreto 6.306/2007);
- income tax on the gain minus IOF, by calendar days held (Lei 11.033/2004).
"""

import calendar
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
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
    IPCA = "IPCA"  # rate is the annual percentage above inflation, e.g. 6.5


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
class PartialRedemption:
    day: date
    gross: Decimal  # amount withdrawn, before taxes

    def __post_init__(self) -> None:
        if not isinstance(self.gross, Decimal):
            raise TypeError("gross must be a Decimal, never a float")
        if self.gross <= 0:
            raise ValueError("redemption amount must be greater than zero")


class RedemptionTooLargeError(ValueError):
    """Withdrawing as much as (or more than) the value left on that day."""

    def __init__(self, day: date, requested: Decimal, available: Decimal):
        self.day = day
        self.requested = requested
        self.available = available
        super().__init__(
            f"cannot withdraw {requested} on {day}: the value then is {available}"
            " (redeem the whole investment instead)"
        )


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
    partial: tuple[PartialRedemption, ...] = ()

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
        # Strictly inside: on the start there is no gain yet, and taking money
        # on the last day is the full redemption itself.
        for p in self.partial:
            if not self.start < p.day < self.end:
                raise ValueError("a partial redemption must be after the start and before the end")
        object.__setattr__(self, "partial", tuple(sorted(self.partial, key=lambda p: p.day)))

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
    principal: Decimal  # money invested in what is valued (after withdrawals)

    @property
    def net(self) -> Decimal:
        return self.gross - self.iof - self.ir

    @property
    def gross_return(self) -> Decimal:
        """Gross return since the start, %. Withdrawals don't change it."""
        return (self.gross / self.principal - 1) * 100


def _month(day: date) -> date:
    return day.replace(day=1)


def _ipca_growth(start: date, end: date, ipca: dict[date, Decimal]) -> Decimal | None:
    """Inflation factor from the start of `start` to the start of `end`.

    Each calendar day earns its month's IPCA ^ (1 / days in the month). A
    month not published yet uses the last one before it; None if there is
    none at all.
    """
    growth = ONE
    day = start
    while day < end:
        month = _month(day)
        known = [m for m in ipca if m <= month]
        if not known:
            return None
        rate = ipca[max(known)]
        days_in_month = calendar.monthrange(day.year, day.month)[1]
        next_month = (month + timedelta(days=days_in_month)).replace(day=1)
        days = (min(end, next_month) - day).days
        growth *= (1 + rate / 100) ** (Decimal(days) / days_in_month)
        day = min(end, next_month)
    return growth


def is_estimated(investment: FixedIncome, day: date, ipca: dict[date, Decimal]) -> bool:
    """True if the value on `day` uses an IPCA not published yet."""
    if investment.indexer is not Indexer.IPCA or day <= investment.start:
        return False
    last_accrued = _month(day - timedelta(days=1))
    return not ipca or max(ipca) < last_accrued


@dataclass(frozen=True)
class DayValue:
    gross: Decimal  # value left after that day's withdrawals
    share: Decimal  # fraction of the investment still held (1 until a withdrawal)


def _trajectory(
    investment: FixedIncome,
    business_days: list[date],
    cdi: dict[date, Decimal],
    ipca: dict[date, Decimal] | None = None,
) -> dict[date, DayValue]:
    """Value at the close of each business day while invested.

    Stops at the end (redemption or maturity) or at the last day with data.
    For post-fixed, a day without a published CDI ends the series, since the
    value can't be known past it.

    `whole` is the value as if nothing had been withdrawn; the real value is
    whole x share. Keeping both apart is what makes partial redemptions exact.
    """
    pct = investment.rate / 100
    withdrawn: dict[date, Decimal] = defaultdict(lambda: ZERO)
    for p in investment.partial:
        withdrawn[p.day] += p.gross

    days = sorted(d for d in business_days if investment.start <= d <= investment.end)
    values: dict[date, DayValue] = {}
    whole = investment.amount
    share = ONE
    inflation = ONE  # IPCA since the start, for IPCA+
    elapsed = 0
    previous: date | None = None
    for day in days:
        if previous is not None:
            if investment.indexer is Indexer.CDI:
                if previous not in cdi:
                    break
                whole *= 1 + cdi[previous] / 100 * pct
            else:
                elapsed += 1
                whole = investment.amount * (1 + pct) ** (Decimal(elapsed) / 252)
                if investment.indexer is Indexer.IPCA:
                    growth = _ipca_growth(previous, day, ipca or {})
                    if growth is None:
                        break
                    inflation *= growth
                    whole *= inflation
        if day in withdrawn:
            before = whole * share
            if withdrawn[day] >= before:
                raise RedemptionTooLargeError(day, withdrawn[day], before)
            share *= 1 - withdrawn[day] / before
        values[day] = DayValue(whole * share, share)
        previous = day
    return values


def gross_values(
    investment: FixedIncome,
    business_days: list[date],
    cdi: dict[date, Decimal],
    ipca: dict[date, Decimal] | None = None,
) -> dict[date, Decimal]:
    """Gross value at the close of each business day while invested."""
    return {d: v.gross for d, v in _trajectory(investment, business_days, cdi, ipca).items()}


def _taxes(product: Product, start: date, day: date, gross: Decimal, principal: Decimal):
    gain = max(gross - principal, ZERO)
    if product in TAX_EXEMPT:
        return Valuation(day, gross, ZERO, ZERO, principal)
    held = (day - start).days
    iof = gain * iof_rate(held)
    ir = (gain - iof) * ir_rate(held)
    return Valuation(day, gross, iof, ir, principal)


def taxes(investment: FixedIncome, day: date, gross: Decimal, share: Decimal = ONE) -> Valuation:
    """IOF and income tax if redeemed on `day` with this gross value.

    `share` is the fraction still held: after partial redemptions, only that
    fraction of the money invested is left to be deducted from the value.
    """
    principal = investment.amount * share
    return _taxes(investment.product, investment.start, day, gross, principal)


def value_on(
    investment: FixedIncome,
    day: date,
    business_days: list[date],
    cdi: dict[date, Decimal],
    ipca: dict[date, Decimal] | None = None,
) -> Valuation | None:
    """Value on `day` (or the last day with data before it), with taxes."""
    values = _trajectory(investment, business_days, cdi, ipca)
    known = [d for d in values if d <= day]
    if not known:
        return None
    last = max(known)
    return taxes(investment, last, values[last].gross, values[last].share)


def partial_valuations(
    investment: FixedIncome,
    business_days: list[date],
    cdi: dict[date, Decimal],
    ipca: dict[date, Decimal] | None = None,
) -> list[Valuation | None]:
    """Taxes on each partial redemption, in the order of investment.partial.

    The principal of a withdrawal is the share of the investment it took:
    from 1.0 to 0.75 held is a quarter of the money invested. None for a
    redemption whose day has no data yet.
    """
    values = _trajectory(investment, business_days, cdi, ipca)
    days = sorted(values)
    result: list[Valuation | None] = []
    for p in investment.partial:
        if p.day not in values:
            result.append(None)
            continue
        i = days.index(p.day)
        share_before = values[days[i - 1]].share if i > 0 else ONE
        # Withdrawals on the same day split that day's share drop by amount.
        same_day = sum((q.gross for q in investment.partial if q.day == p.day), ZERO)
        dropped = (share_before - values[p.day].share) * p.gross / same_day
        principal = investment.amount * dropped
        result.append(_taxes(investment.product, investment.start, p.day, p.gross, principal))
    return result


def daily_series(
    investments: list[FixedIncome],
    business_days: list[date],
    cdi: dict[date, Decimal],
    ipca: dict[date, Decimal] | None = None,
) -> tuple[dict[date, Decimal], dict[date, Decimal]]:
    """Values and flows of all investments, ready to join the TWR.

    Applying is money in on the first day; redeeming (or maturing) is money
    out at the gross value on the last day, which then no longer counts in
    the value. A partial redemption is money out on its day, and the value
    that day is what is left. Investments still running count until the
    last day with data.
    """
    values: dict[date, Decimal] = defaultdict(lambda: ZERO)
    flows: dict[date, Decimal] = defaultdict(lambda: ZERO)
    last_known = max(business_days, default=None)
    for investment in investments:
        gross = gross_values(investment, business_days, cdi, ipca)
        if not gross:
            continue
        flows[min(gross)] += investment.amount
        for p in investment.partial:
            if p.day in gross:
                flows[p.day] -= p.gross
        ended = last_known is not None and investment.end <= last_known
        last = max(gross)
        for day, value in gross.items():
            if ended and day == last:
                flows[day] -= value
            else:
                values[day] += value
    return dict(values), dict(flows)


def daily_net_values(
    investments: list[FixedIncome],
    business_days: list[date],
    cdi: dict[date, Decimal],
    ipca: dict[date, Decimal] | None = None,
) -> dict[date, Decimal]:
    """Net value (after IOF and income tax) of all investments at each close.

    The same days as daily_series' values, but what the money is worth if
    redeemed that day, as the portfolio's net worth shows it. The return
    (TWR) keeps using the gross values: the tax is only paid on redemption.
    """
    values: dict[date, Decimal] = defaultdict(lambda: ZERO)
    last_known = max(business_days, default=None)
    for investment in investments:
        trajectory = _trajectory(investment, business_days, cdi, ipca)
        if not trajectory:
            continue
        ended = last_known is not None and investment.end <= last_known
        last = max(trajectory)
        for day, v in trajectory.items():
            if not (ended and day == last):  # gone that day, as in daily_series
                values[day] += taxes(investment, day, v.gross, v.share).net
    return dict(values)


def money_in(
    investments: list[FixedIncome],
    business_days: list[date],
    cdi: dict[date, Decimal],
    ipca: dict[date, Decimal] | None,
    today: date,
) -> Decimal | None:
    """Money put into fixed income minus what came out, until `today`.

    The same flows as daily_series (applied amount in, partial and full
    redemptions out at their gross value), but counting a redemption made
    after the last day with data too. None while such a value is unknown.
    """
    total = ZERO
    for investment in investments:
        if investment.start > today:
            continue
        total += investment.amount
        total -= sum((p.gross for p in investment.partial if p.day <= today), ZERO)
        if investment.end <= today:
            gross = gross_values(investment, business_days, cdi, ipca)
            known = [d for d in gross if d <= investment.end]
            if not known:
                return None
            total -= gross[max(known)]
    return total
