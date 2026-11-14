"""Pure income (proventos) calculations: dividends, JCP and FII distributions.

Like portfolio.py, this module has no database, HTTP or I/O.

Income comes from two places:
- B3 events (the normal case): the company announces a value per share and
  a record date (data com). What you receive is computed, never typed:
  shares held at the end of the record date x value per share. Like
  positions, it is recalculated from the trades, so fixing an old trade
  fixes the income too.
- Manual entries: for what B3 doesn't publish (e.g. BDRs, or events older
  than the history B3 shows). These are totals from the broker statement.

Design rules:
- Income never changes the average price. Brazilian tax rules keep the
  cost basis of a share unchanged when it pays dividends or JCP, so income
  is tracked as a separate result, not as a discount on the cost.
- Only JCP has income tax withheld at source. Its rate is set by law, so it
  lives in one constant (JCP_TAX_RATE) used only for computed income;
  manual entries record the tax exactly as the statement shows.
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from investtrack.portfolio import ZERO, Operation, OpType, StockEvent, calculate_position

# Income tax withheld on JCP for individuals (Lei 9.249/95, art. 9).
JCP_TAX_RATE = Decimal("0.15")


class IncomeType(StrEnum):
    DIVIDEND = "DIVIDEND"
    JCP = "JCP"  # juros sobre capital próprio
    DISTRIBUTION = "DISTRIBUTION"  # FII rendimento


class IncomeSource(StrEnum):
    B3 = "B3"  # computed from an event published by B3
    MANUAL = "MANUAL"  # typed by the user


class IncomeWithoutPositionError(ValueError):
    """Raised when income is paid before the ticker was ever bought.

    Usually a typo in the ticker (PETR3 instead of PETR4) or in the date.
    """

    def __init__(self, ticker: str, payment_date: date, first_buy: date | None):
        self.ticker = ticker
        self.date = payment_date
        self.first_buy = first_buy
        since = f"first bought on {first_buy}" if first_buy else "never bought"
        super().__init__(f"Income from {ticker} on {payment_date}, but {ticker} was {since}")


@dataclass(frozen=True)
class Income:
    ticker: str
    income_type: IncomeType
    date: date  # payment date: when the money reached the account
    amount: Decimal  # gross total, before withholding tax
    tax: Decimal = ZERO  # withheld at source (usually only JCP)
    source: IncomeSource = IncomeSource.MANUAL
    # Only for computed income: how the amount was obtained.
    record_date: date | None = None
    quantity: Decimal | None = None
    rate: Decimal | None = None

    def __post_init__(self) -> None:
        ticker = self.ticker.strip().upper()
        if not ticker:
            raise ValueError("ticker must not be empty")
        object.__setattr__(self, "ticker", ticker)
        object.__setattr__(self, "income_type", IncomeType(self.income_type))
        object.__setattr__(self, "source", IncomeSource(self.source))

        for field in ("amount", "tax"):
            if not isinstance(getattr(self, field), Decimal):
                raise TypeError(f"{field} must be a Decimal, never a float")

        if self.amount <= 0:
            raise ValueError("amount must be greater than zero")
        if self.tax < 0:
            raise ValueError("tax must not be negative")
        if self.tax > self.amount:
            raise ValueError("tax cannot be larger than the amount")

    @property
    def net(self) -> Decimal:
        return self.amount - self.tax


@dataclass(frozen=True)
class IncomeEvent:
    """A payment announced by a company or fund, per share."""

    ticker: str
    income_type: IncomeType
    record_date: date  # data com: owning the share at the end of this day gives the right
    payment_date: date | None  # None while the company hasn't set it
    rate: Decimal  # value per share, gross

    def __post_init__(self) -> None:
        object.__setattr__(self, "ticker", self.ticker.strip().upper())
        object.__setattr__(self, "income_type", IncomeType(self.income_type))
        if not isinstance(self.rate, Decimal):
            raise TypeError("rate must be a Decimal, never a float")


@dataclass(frozen=True)
class TickerEvents:
    """Everything B3 publishes about one ticker that affects a holder."""

    income: list[IncomeEvent]
    stock: list[StockEvent]


def quantity_on(
    operations: list[Operation], day: date, stock_events: Iterable[StockEvent] = ()
) -> Decimal:
    """Shares held at the end of `day`: trades on that day count.

    Stock events count only if their record date is before `day`. When a
    split and a dividend share the same record date, the dividend is
    announced per share as they were before the split.

    Reuses calculate_position instead of a second implementation of the
    trade rules, so the two can never disagree.
    """
    until_then = [op for op in operations if op.date <= day]
    if not until_then:
        return ZERO
    events = [e for e in stock_events if e.record_date < day]
    return calculate_position(until_then, events).quantity


def incomes_from_events(
    operations: list[Operation],
    events: list[IncomeEvent],
    jcp_tax_rate: Decimal = JCP_TAX_RATE,
    stock_events: Iterable[StockEvent] = (),
) -> list[Income]:
    """What each event paid you, given your trades.

    Events you weren't entitled to (no shares on the record date) produce
    nothing. Events without a payment date yet are left out until B3
    publishes one, since the income can't be placed in a month.
    """
    by_ticker: dict[str, list[Operation]] = defaultdict(list)
    for op in operations:
        by_ticker[op.ticker].append(op)

    stock_events = list(stock_events)
    incomes = []
    for event in events:
        if event.payment_date is None or event.rate <= 0:
            continue
        quantity = quantity_on(by_ticker[event.ticker], event.record_date, stock_events)
        if quantity == 0:
            continue
        amount = quantity * event.rate
        tax = amount * jcp_tax_rate if event.income_type is IncomeType.JCP else ZERO
        incomes.append(
            Income(
                ticker=event.ticker,
                income_type=event.income_type,
                date=event.payment_date,
                amount=amount,
                tax=tax,
                source=IncomeSource.B3,
                record_date=event.record_date,
                quantity=quantity,
                rate=event.rate,
            )
        )
    return incomes


def check_incomes(operations: list[Operation], incomes: list[Income]) -> None:
    """Every income must be paid on or after the first buy of its ticker.

    The rule is deliberately loose: income may arrive after the position was
    sold, because what matters is holding the shares on the record date,
    which can be weeks before the payment.
    """
    first_buy: dict[str, date] = {}
    for op in operations:
        if op.op_type is OpType.BUY and (
            op.ticker not in first_buy or op.date < first_buy[op.ticker]
        ):
            first_buy[op.ticker] = op.date

    for income in incomes:
        since = first_buy.get(income.ticker)
        if since is None or income.date < since:
            raise IncomeWithoutPositionError(income.ticker, income.date, since)


def net_income_by_ticker(incomes: list[Income]) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for income in incomes:
        totals[income.ticker] += income.net
    return dict(totals)


@dataclass(frozen=True)
class MonthlyIncome:
    year: int
    month: int
    dividend: Decimal  # net values per type
    jcp: Decimal
    distribution: Decimal
    tax: Decimal
    net: Decimal


def monthly_income(incomes: list[Income]) -> list[MonthlyIncome]:
    """Net income per month and type, oldest month first. Empty months are omitted."""
    net: dict[tuple[int, int], dict[IncomeType, Decimal]] = {}
    tax: dict[tuple[int, int], Decimal] = defaultdict(lambda: ZERO)
    for income in incomes:
        key = (income.date.year, income.date.month)
        by_type = net.setdefault(key, dict.fromkeys(IncomeType, ZERO))
        by_type[income.income_type] += income.net
        tax[key] += income.tax

    return [
        MonthlyIncome(
            year=year,
            month=month,
            dividend=by_type[IncomeType.DIVIDEND],
            jcp=by_type[IncomeType.JCP],
            distribution=by_type[IncomeType.DISTRIBUTION],
            tax=tax[(year, month)],
            net=sum(by_type.values(), ZERO),
        )
        for (year, month), by_type in sorted(net.items())
    ]
