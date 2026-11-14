"""Pure portfolio calculations.

This module has no database, HTTP or I/O. It receives a list of operations
and returns positions. Money and quantities are always Decimal, never float.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

ZERO = Decimal("0")


class OpType(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class InsufficientPositionError(ValueError):
    """Raised when a sale is larger than the current position."""

    def __init__(self, ticker: str, available: Decimal, requested: Decimal):
        self.ticker = ticker
        self.available = available
        self.requested = requested
        super().__init__(
            f"Cannot sell {requested} {ticker}: only {available} available"
        )


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


@dataclass(frozen=True)
class Position:
    ticker: str
    quantity: Decimal
    avg_price: Decimal
    realized_profit: Decimal


def calculate_position(operations: list[Operation]) -> Position:
    """Compute the position of a single ticker.

    Operations are processed in date order. The sort is stable, so operations
    on the same date keep the order in which they were given.

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

    for op in sorted(operations, key=lambda o: o.date):
        if op.op_type is OpType.BUY:
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


def calculate_portfolio(operations: list[Operation]) -> dict[str, Position]:
    """Group operations by ticker and compute each position.

    Closed positions (quantity 0) are kept, because their realized profit
    still matters.
    """
    by_ticker: dict[str, list[Operation]] = defaultdict(list)
    for op in operations:
        by_ticker[op.ticker].append(op)
    return {ticker: calculate_position(ops) for ticker, ops in by_ticker.items()}
