"""Pure portfolio calculations.

This module has no database, HTTP or I/O. It receives a list of operations
and returns positions. Money and quantities are always Decimal, never float.
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_FLOOR, Decimal
from enum import StrEnum

ZERO = Decimal("0")
ONE = Decimal("1")


class OpType(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class InsufficientPositionError(ValueError):
    """Raised when a sale is larger than the current position."""

    def __init__(self, ticker: str, available: Decimal, requested: Decimal):
        self.ticker = ticker
        self.available = available
        self.requested = requested
        super().__init__(f"Cannot sell {requested} {ticker}: only {available} available")


@dataclass(frozen=True)
class Operation:
    ticker: str
    op_type: OpType
    date: date
    quantity: Decimal
    price: Decimal
    fees: Decimal = ZERO

    def __post_init__(self) -> None:
        # The dataclass is frozen, so normalizing fields needs object.__setattr__.
        ticker = self.ticker.strip().upper()
        if not ticker:
            raise ValueError("ticker must not be empty")
        object.__setattr__(self, "ticker", ticker)
        # Accepts "BUY"/"SELL" strings too; raises ValueError for anything else.
        object.__setattr__(self, "op_type", OpType(self.op_type))

        for field in ("quantity", "price", "fees"):
            if not isinstance(getattr(self, field), Decimal):
                raise TypeError(f"{field} must be a Decimal, never a float")

        if self.quantity <= 0:
            raise ValueError("quantity must be greater than zero")
        if self.price < 0:
            raise ValueError("price must not be negative")
        if self.fees < 0:
            raise ValueError("fees must not be negative")


class StockEventType(StrEnum):
    SPLIT = "SPLIT"  # desdobramento
    REVERSE_SPLIT = "REVERSE_SPLIT"  # grupamento
    BONUS = "BONUS"  # bonificação


@dataclass(frozen=True)
class StockEvent:
    """A change in the number of shares decided by the company.

    multiplier: shares after = shares before x multiplier
    (a 1:2 split is 2, a 10:1 reverse split is 0.1, a 10% bonus is 1.1).
    """

    ticker: str
    event_type: StockEventType
    record_date: date  # applies at the end of this day, after its trades
    multiplier: Decimal
    # Cost of each new bonus share for tax purposes (custo atribuído). Splits
    # create no new value, so they never have one.
    unit_cost: Decimal = ZERO

    def __post_init__(self) -> None:
        object.__setattr__(self, "ticker", self.ticker.strip().upper())
        object.__setattr__(self, "event_type", StockEventType(self.event_type))
        for field in ("multiplier", "unit_cost"):
            if not isinstance(getattr(self, field), Decimal):
                raise TypeError(f"{field} must be a Decimal, never a float")
        if self.multiplier <= 0:
            raise ValueError("multiplier must be greater than zero")


@dataclass(frozen=True)
class Position:
    ticker: str
    quantity: Decimal
    avg_price: Decimal
    realized_profit: Decimal


def apply_stock_event(
    quantity: Decimal, avg_price: Decimal, event: StockEvent
) -> tuple[Decimal, Decimal]:
    """New (quantity, average price) after a split, reverse split or bonus.

    - Split and reverse split don't change the total cost, only spread it
      over a different number of shares: 100 at R$ 30 become 200 at R$ 15.
    - Bonus shares add their attributed cost (zero if unknown).
    - Fractions are dropped: B3 sells them in an auction and pays the
      holder in cash. The fraction's share of the cost leaves with it, so
      the average price is the same as without rounding.
    """
    if quantity == 0:
        return quantity, avg_price
    exact = quantity * event.multiplier
    total_cost = quantity * avg_price + (exact - quantity) * event.unit_cost
    new_avg = total_cost / exact
    new_quantity = exact.to_integral_value(rounding=ROUND_FLOOR)
    if new_quantity == 0:
        return ZERO, ZERO
    return new_quantity, new_avg


def calculate_position(
    operations: list[Operation], stock_events: Iterable[StockEvent] = ()
) -> Position:
    """Compute the position of a single ticker.

    Operations are processed in date order. The sort is stable, so operations
    on the same date keep the order in which they were given. Stock events
    of the same ticker are applied at the end of their record date, after
    that day's operations; events of other tickers are ignored.

    Rules:
    - BUY: fees are added to the cost, and the average price is recalculated.
    - SELL: the average price does not change; the difference (minus fees)
      becomes realized profit. Selling everything resets the average price,
      so a later buy starts from zero.

    No rounding happens here: values keep full precision and are only
    rounded when displayed.
    """
    if not operations:
        raise ValueError("at least one operation is required")
    tickers = {op.ticker for op in operations}
    if len(tickers) != 1:
        raise ValueError(f"expected a single ticker, got {sorted(tickers)}")
    ticker = tickers.pop()

    quantity = ZERO
    avg_price = ZERO
    realized_profit = ZERO

    # (day, 0, operation) sorts before (day, 1, event): trades first, then events.
    timeline = [(op.date, 0, op) for op in operations] + [
        (e.record_date, 1, e) for e in stock_events if e.ticker == ticker
    ]
    for _, _, op in sorted(timeline, key=lambda t: (t[0], t[1])):
        if isinstance(op, StockEvent):
            quantity, avg_price = apply_stock_event(quantity, avg_price, op)
        elif op.op_type is OpType.BUY:
            new_quantity = quantity + op.quantity
            total_cost = quantity * avg_price + op.quantity * op.price + op.fees
            avg_price = total_cost / new_quantity
            quantity = new_quantity
        else:
            if op.quantity > quantity:
                raise InsufficientPositionError(ticker, quantity, op.quantity)
            realized_profit += op.quantity * (op.price - avg_price) - op.fees
            quantity -= op.quantity
            if quantity == 0:
                avg_price = ZERO

    return Position(ticker, quantity, avg_price, realized_profit)


@dataclass(frozen=True)
class Valuation:
    """Unrealized result of a position at a given market price."""

    invested: Decimal
    current_value: Decimal
    result: Decimal
    result_pct: Decimal | None  # None when nothing is invested (closed position)


def value_position(position: Position, price: Decimal) -> Valuation:
    invested = position.quantity * position.avg_price
    current_value = position.quantity * price
    result = current_value - invested
    result_pct = result / invested * 100 if invested else None
    return Valuation(invested, current_value, result, result_pct)


@dataclass(frozen=True)
class AppliedStockEvent:
    """A stock event that changed one of your positions."""

    event: StockEvent
    quantity_before: Decimal
    quantity_after: Decimal


def applied_stock_events(
    operations: list[Operation], stock_events: Iterable[StockEvent]
) -> list[AppliedStockEvent]:
    """The events that hit a position, with the quantity before and after.

    Only for showing: the calculation itself is in calculate_position.
    """
    ticker_ops: dict[str, list[Operation]] = defaultdict(list)
    for op in operations:
        ticker_ops[op.ticker].append(op)
    events = sorted(stock_events, key=lambda e: e.record_date)

    applied = []
    for event in events:
        ops = [op for op in ticker_ops.get(event.ticker, []) if op.date <= event.record_date]
        if not ops:
            continue
        earlier = [e for e in events if e.record_date < event.record_date]
        before = calculate_position(ops, earlier)
        if before.quantity == 0:
            continue
        after, _ = apply_stock_event(before.quantity, before.avg_price, event)
        applied.append(AppliedStockEvent(event, before.quantity, after))
    return applied


def calculate_portfolio(
    operations: list[Operation], stock_events: Iterable[StockEvent] = ()
) -> dict[str, Position]:
    """Group operations by ticker and compute each position.

    Closed positions (quantity 0) are kept, because their realized profit
    still matters.
    """
    by_ticker: dict[str, list[Operation]] = defaultdict(list)
    for op in operations:
        by_ticker[op.ticker].append(op)
    events = list(stock_events)
    return {ticker: calculate_position(ops, events) for ticker, ops in by_ticker.items()}
