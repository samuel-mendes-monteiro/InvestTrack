"""Deciding what a statement import adds. Pure: no database, HTTP or files.

Each row of the statement gets a status:
- NEW: will be added;
- DUPLICATE: an operation with the same date, type, ticker, quantity and
  price already exists (imported before, or typed by hand);
- REJECTED: the ticker's trades would sell more than owned.

Duplicates are found by comparing multisets, not sets: two identical buys
on the same day are two trades, so each existing operation matches at most
one row. That also makes overlapping statements safe to import: the
trades present in both are matched once.

Fees don't take part in the comparison: the statement doesn't have them,
and an operation typed by hand with its fees is still the same trade.
"""

from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from investtrack.core.portfolio import (
    InsufficientPositionError,
    Operation,
    OpType,
    StockEvent,
    calculate_position,
)


@dataclass(frozen=True)
class StatementRow:
    """One trade read from the statement (sources/b3_statement.py)."""

    line: int  # row number in the spreadsheet, for messages
    date: date
    op_type: OpType
    ticker: str
    quantity: Decimal
    price: Decimal


class Status(StrEnum):
    NEW = "NEW"
    DUPLICATE = "DUPLICATE"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class PlannedRow:
    row: StatementRow
    status: Status
    error: InsufficientPositionError | None = None


def _key(date, op_type, ticker, quantity, price):
    # normalize(): 12.66 and 12.660 are the same price
    return (date, op_type, ticker, quantity.normalize(), price.normalize())


def to_operation(row: StatementRow) -> Operation:
    return Operation(row.ticker, row.op_type, row.date, row.quantity, row.price)


def plan_import(
    existing: list[Operation],
    rows: list[StatementRow],
    stock_events: Iterable[StockEvent] = (),
) -> list[PlannedRow]:
    """The status of each row, in file order."""
    available = Counter(
        _key(op.date, op.op_type, op.ticker, op.quantity, op.price) for op in existing
    )
    statuses: list[Status] = []
    for row in rows:
        key = _key(row.date, row.op_type, row.ticker, row.quantity, row.price)
        if available[key] > 0:
            available[key] -= 1
            statuses.append(Status.DUPLICATE)
        else:
            statuses.append(Status.NEW)

    # Validate each ticker with everything it would have after the import.
    # One bad sale rejects the ticker's new rows: importing only part of a
    # ticker's history would leave an average price that matches nothing.
    stock_events = list(stock_events)
    existing_by_ticker: dict[str, list[Operation]] = defaultdict(list)
    for op in existing:
        existing_by_ticker[op.ticker].append(op)
    new_by_ticker: dict[str, list[Operation]] = defaultdict(list)
    for row, status in zip(rows, statuses, strict=True):
        if status is Status.NEW:
            new_by_ticker[row.ticker].append(to_operation(row))

    errors: dict[str, InsufficientPositionError] = {}
    for ticker, new in new_by_ticker.items():
        try:
            calculate_position(existing_by_ticker[ticker] + new, stock_events)
        except InsufficientPositionError as e:
            errors[ticker] = e

    return [
        PlannedRow(row, Status.REJECTED, errors[row.ticker])
        if status is Status.NEW and row.ticker in errors
        else PlannedRow(row, status)
        for row, status in zip(rows, statuses, strict=True)
    ]
