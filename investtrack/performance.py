"""Pure performance calculations: time-weighted return (TWR) and benchmarks.

Like portfolio.py, this module has no database, HTTP or I/O.

Why TWR: the portfolio's value grows when you invest more money, but that
is not return. TWR measures each day's return net of the money that came
in or out, and chains the days together:

    r_d = (V_d + I_d - F_d) / V_{d-1} - 1        TWR = (1 + r_1)(1 + r_2)... - 1

V_d: value at the close of day d (shares x closing price)
F_d: net flow of day d (buys add money, sells take it out, fees included)
I_d: income paid on day d (counted as return: it is money the assets produced)

Flows are assumed at the end of the day, so a buy's first-day return is
measured from the trade price to that day's close. This is the usual
daily approximation and is the same rule for every day.
"""

import calendar
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from investtrack.income import Income, quantity_on
from investtrack.portfolio import ONE, ZERO, Operation, OpType, StockEvent


@dataclass(frozen=True)
class DailyValue:
    date: date
    value: Decimal  # portfolio value at the close
    flow: Decimal  # money put in (positive) or taken out (negative) that day
    income: Decimal
    twr: Decimal  # cumulative return since the start, as a fraction (0.05 = 5%)


def _next_trading_day(day: date, trading_days: list[date]) -> date | None:
    """Trades and payments on a weekend or holiday count on the next trading day."""
    return next((d for d in trading_days if d >= day), None)


def _flow(op: Operation) -> Decimal:
    if op.op_type is OpType.BUY:
        return op.quantity * op.price + op.fees
    return -(op.quantity * op.price - op.fees)


def portfolio_history(
    operations: list[Operation],
    trading_days: list[date],
    closes: dict[str, dict[date, Decimal]],
    stock_events: Iterable[StockEvent] = (),
    incomes: Iterable[Income] = (),
    other_values: dict[date, Decimal] | None = None,
    other_flows: dict[date, Decimal] | None = None,
) -> list[DailyValue]:
    """Value and cumulative TWR at the close of every trading day.

    other_values and other_flows add assets valued elsewhere, such as fixed
    income: their value at each close and the money put in or taken out.

    Missing closes (a day without trades in that asset) use the last known
    close, and before the first known close, the last trade price: an
    illiquid asset keeps its value instead of dropping to zero.
    """
    other_values = other_values or {}
    other_flows = other_flows or {}
    if not (operations or other_flows) or not trading_days:
        return []
    trading_days = sorted(trading_days)
    stock_events = list(stock_events)

    ops_by_ticker: dict[str, list[Operation]] = defaultdict(list)
    flows: dict[date, Decimal] = defaultdict(lambda: ZERO)
    for op in operations:
        ops_by_ticker[op.ticker].append(op)
        day = _next_trading_day(op.date, trading_days)
        if day is not None:
            flows[day] += _flow(op)

    paid: dict[date, Decimal] = defaultdict(lambda: ZERO)
    for income in incomes:
        day = _next_trading_day(income.date, trading_days)
        if day is not None:
            paid[day] += income.net

    for day, flow in other_flows.items():
        flows[day] += flow
    starts = [op.date for op in operations] + list(other_flows)
    first_day = _next_trading_day(min(starts), trading_days)
    last_price: dict[str, Decimal] = {}
    has_close: set[str] = set()
    previous_value = ZERO
    index = ONE
    history = []

    for day in trading_days:
        if first_day is None or day < first_day:
            continue
        for ticker, ops in ops_by_ticker.items():
            close = closes.get(ticker, {}).get(day)
            if close is not None:
                last_price[ticker] = close
                has_close.add(ticker)
            elif ticker not in has_close:
                traded = [op for op in ops if op.date <= day]
                if traded:
                    last_price[ticker] = max(traded, key=lambda o: o.date).price

        value = sum(
            (
                quantity_on(ops, day, stock_events) * last_price.get(ticker, ZERO)
                for ticker, ops in ops_by_ticker.items()
            ),
            other_values.get(day, ZERO),
        )
        flow, income = flows[day], paid[day]

        if previous_value > 0:
            daily_return = (value + income - flow) / previous_value - 1
        elif flow > 0:  # first money in, or back in after selling everything
            daily_return = (value + income) / flow - 1
        else:
            daily_return = ZERO
        index *= 1 + daily_return

        history.append(DailyValue(day, value, flow, income, index - 1))
        previous_value = value
    return history


def cdi_accumulated(
    rates: dict[date, Decimal], days: list[date], start: date
) -> dict[date, Decimal]:
    """CDI accumulated from `start` until each day, as a fraction.

    Each rate (% per day) is earned overnight, from its date to the next
    business day, so the rate of the day itself is not yet earned at its
    close.
    """
    result = {}
    factor = ONE
    ordered = sorted(d for d in rates if d >= start)
    earned = iter(ordered)
    pending = next(earned, None)
    for day in sorted(d for d in days if d >= start):
        while pending is not None and pending < day:
            factor *= 1 + rates[pending] / 100
            pending = next(earned, None)
        result[day] = factor - 1
    return result


def index_return(values: dict[date, Decimal], days: list[date], start: date) -> dict[date, Decimal]:
    """Return of an index (e.g. Ibovespa) from the close before `start`.

    The base is the previous close, so the start day's own move counts, just
    like the portfolio's first day counts from the trade price.
    """
    before = [d for d in values if d < start]
    base_day = max(before) if before else min((d for d in values if d >= start), default=None)
    if base_day is None:
        return {}
    base = values[base_day]
    result = {}
    last = base
    for day in sorted(d for d in days if d >= start):
        last = values.get(day, last)
        result[day] = last / base - 1
    return result


# --- periods -------------------------------------------------------------------


class Period(StrEnum):
    MONTH = "1M"
    SEMESTER = "6M"
    YEAR = "1Y"
    ALL = "ALL"


_MONTHS = {Period.MONTH: 1, Period.SEMESTER: 6, Period.YEAR: 12}


def months_before(day: date, months: int) -> date:
    """The same day `months` earlier, clamped to the month's end (31/03 - 1 month = 28/02)."""
    total = day.year * 12 + day.month - 1 - months
    year, month = divmod(total, 12)
    month += 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def window_base(days: list[date], period: Period) -> date | None:
    """The close a period is measured from: the last day on or before
    (last day - period). None for the whole history, or when the history is
    shorter than the period, which then shows everything."""
    if period is Period.ALL or not days:
        return None
    cutoff = months_before(max(days), _MONTHS[period])
    before = [d for d in days if d <= cutoff]
    return max(before) if before else None


def rebase(cumulative: Decimal, base: Decimal) -> Decimal:
    """A cumulative return (as a fraction) measured from another day instead.

    TWR, accumulated CDI and an index return are all chained products of
    daily factors, so the return between two days is the ratio of their
    factors, exactly: (1 + R_end) / (1 + R_base) - 1.
    """
    return (1 + cumulative) / (1 + base) - 1
