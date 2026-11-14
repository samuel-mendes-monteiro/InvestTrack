"""Reading and writing operations and income.

This is the only module that talks to both the database and the
calculation core. Business rules (no selling more than you own, no income
before the first buy) are not duplicated here: every change is validated
by the calculation core before it is saved.
"""

from dataclasses import replace
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, contains_eager

from investtrack.events import NO_EVENTS, EventSource
from investtrack.income import Income, check_incomes, incomes_from_events
from investtrack.models import Asset, AssetType, BonusCost, IncomeRecord, OperationRecord
from investtrack.portfolio import (
    AppliedStockEvent,
    Operation,
    Position,
    StockEvent,
    StockEventType,
    applied_stock_events,
    calculate_portfolio,
    calculate_position,
)


class OperationNotFoundError(LookupError):
    def __init__(self, operation_id: int):
        self.operation_id = operation_id
        super().__init__(f"operation {operation_id} not found")


class StockEventNotFoundError(LookupError):
    def __init__(self, ticker: str, record_date: date):
        self.ticker = ticker
        self.record_date = record_date
        super().__init__(f"no bonus event for {ticker} on {record_date}")


class IncomeNotFoundError(LookupError):
    def __init__(self, income_id: int):
        self.income_id = income_id
        super().__init__(f"income {income_id} not found")


def to_domain(record: OperationRecord) -> Operation:
    """Convert a database row into the dataclass used by the calculations."""
    return Operation(
        ticker=record.asset.ticker,
        op_type=record.op_type,
        date=record.date,
        quantity=record.quantity,
        price=record.price,
        fees=record.fees,
    )


def list_operations(session: Session, ticker: str | None = None) -> list[OperationRecord]:
    """Operations ordered by (date, id): same-day operations keep entry order."""
    stmt = (
        select(OperationRecord)
        .join(OperationRecord.asset)
        .options(contains_eager(OperationRecord.asset))  # avoids one query per row
        .order_by(OperationRecord.date, OperationRecord.id)
    )
    if ticker is not None:
        stmt = stmt.where(Asset.ticker == ticker.strip().upper())
    return list(session.scalars(stmt))


def get_or_create_asset(
    session: Session, ticker: str, asset_type: AssetType = AssetType.STOCK
) -> Asset:
    asset = session.scalar(select(Asset).where(Asset.ticker == ticker))
    if asset is None:
        asset = Asset(ticker=ticker, asset_type=asset_type)
        session.add(asset)
    return asset


def bonus_costs(session: Session) -> dict[tuple[str, date], Decimal]:
    return {(c.ticker, c.record_date): c.unit_cost for c in session.scalars(select(BonusCost))}


def _with_bonus_costs(session: Session, stock: list[StockEvent]) -> list[StockEvent]:
    """Stock events with the attributed costs typed by the user filled in."""
    costs = bonus_costs(session)
    return [
        replace(e, unit_cost=costs[(e.ticker, e.record_date)])
        if e.event_type is StockEventType.BONUS and (e.ticker, e.record_date) in costs
        else e
        for e in stock
    ]


def _stock_events(
    session: Session, events: EventSource, ticker: str, new_asset_type: AssetType
) -> list[StockEvent]:
    asset = session.scalar(select(Asset).where(Asset.ticker == ticker))
    stock = events.events_for(ticker, asset.asset_type if asset else new_asset_type).stock
    return _with_bonus_costs(session, stock)


def _operations_by_ticker(session: Session) -> dict[str, tuple[AssetType, list[Operation]]]:
    by_ticker: dict[str, tuple[AssetType, list[Operation]]] = {}
    for record in list_operations(session):
        _, ops = by_ticker.setdefault(record.asset.ticker, (record.asset.asset_type, []))
        ops.append(to_domain(record))
    return by_ticker


def add_operation(
    session: Session,
    op: Operation,
    asset_type: AssetType = AssetType.STOCK,
    events: EventSource = NO_EVENTS,
) -> OperationRecord:
    """Save an operation, refusing it if it would sell more than the position.

    asset_type is only used when the ticker is new. Splits and bonus shares
    from `events` count: after a 1:2 split, selling the doubled amount is fine.
    Raises InsufficientPositionError (nothing is saved in that case).
    """
    existing = [to_domain(r) for r in list_operations(session, op.ticker)]
    stock = _stock_events(session, events, op.ticker, asset_type)
    calculate_position(existing + [op], stock)  # raises if the new list is invalid

    record = OperationRecord(
        asset=get_or_create_asset(session, op.ticker, asset_type),
        op_type=op.op_type,
        date=op.date,
        quantity=op.quantity,
        price=op.price,
        fees=op.fees,
    )
    session.add(record)
    session.commit()
    return record


def delete_operation(session: Session, operation_id: int, events: EventSource = NO_EVENTS) -> None:
    """Delete an operation, refusing it if a later sale would become invalid.

    Example: buy 100, sell 80. Deleting the buy would leave a sale of 80
    shares that were never bought, so it raises InsufficientPositionError.
    """
    record = session.get(OperationRecord, operation_id)
    if record is None:
        raise OperationNotFoundError(operation_id)

    remaining = [
        to_domain(r) for r in list_operations(session, record.asset.ticker) if r.id != operation_id
    ]
    if remaining:
        stock = _stock_events(session, events, record.asset.ticker, record.asset.asset_type)
        calculate_position(remaining, stock)  # raises if the remaining list is invalid
    # Deleting the first buy may leave income paid before any remaining buy.
    incomes = [income_to_domain(r) for r in list_incomes(session, record.asset.ticker)]
    check_incomes(remaining, incomes)

    session.delete(record)
    session.commit()


def _all_operations_and_stock_events(
    session: Session, events: EventSource
) -> tuple[list[Operation], list[StockEvent]]:
    operations: list[Operation] = []
    stock: list[StockEvent] = []
    for ticker, (asset_type, ops) in _operations_by_ticker(session).items():
        operations += ops
        stock += events.events_for(ticker, asset_type).stock
    return operations, _with_bonus_costs(session, stock)


def get_portfolio(session: Session, events: EventSource = NO_EVENTS) -> dict[str, Position]:
    return calculate_portfolio(*_all_operations_and_stock_events(session, events))


def get_applied_stock_events(session: Session, events: EventSource) -> list[AppliedStockEvent]:
    return applied_stock_events(*_all_operations_and_stock_events(session, events))


def set_bonus_cost(
    session: Session, ticker: str, record_date: date, unit_cost: Decimal, events: EventSource
) -> None:
    """Record the attributed cost of a bonus event that exists for this ticker.

    Raises StockEventNotFoundError otherwise: a cost for a date without a
    bonus would silently do nothing, so a typo in the date is refused.
    """
    ticker = ticker.strip().upper()
    asset = session.scalar(select(Asset).where(Asset.ticker == ticker))
    stock = events.events_for(ticker, asset.asset_type).stock if asset else []
    if not any(
        e.event_type is StockEventType.BONUS and e.record_date == record_date for e in stock
    ):
        raise StockEventNotFoundError(ticker, record_date)
    session.merge(BonusCost(ticker=ticker, record_date=record_date, unit_cost=unit_cost))
    session.commit()


def delete_bonus_cost(session: Session, ticker: str, record_date: date) -> None:
    """Back to zero cost. Deleting a cost that isn't there is not an error."""
    cost = session.get(BonusCost, (ticker.strip().upper(), record_date))
    if cost is not None:
        session.delete(cost)
        session.commit()


# --- income ------------------------------------------------------------------


def income_to_domain(record: IncomeRecord) -> Income:
    return Income(
        ticker=record.asset.ticker,
        income_type=record.income_type,
        date=record.date,
        amount=record.amount,
        tax=record.tax,
    )


def list_incomes(
    session: Session, ticker: str | None = None, year: int | None = None
) -> list[IncomeRecord]:
    """Income ordered by (date, id), optionally filtered by ticker and year."""
    stmt = (
        select(IncomeRecord)
        .join(IncomeRecord.asset)
        .options(contains_eager(IncomeRecord.asset))
        .order_by(IncomeRecord.date, IncomeRecord.id)
    )
    if ticker is not None:
        stmt = stmt.where(Asset.ticker == ticker.strip().upper())
    if year is not None:
        # A date range, not extract(year): an index can serve a range, not a function.
        stmt = stmt.where(
            IncomeRecord.date >= date(year, 1, 1), IncomeRecord.date < date(year + 1, 1, 1)
        )
    return list(session.scalars(stmt))


def add_income(session: Session, income: Income) -> IncomeRecord:
    """Save income, refusing it if the ticker wasn't bought by the payment date.

    Raises IncomeWithoutPositionError (nothing is saved in that case). The
    asset is never created here: an unknown ticker is almost always a typo.
    """
    operations = [to_domain(r) for r in list_operations(session, income.ticker)]
    check_incomes(operations, [income])

    asset = session.scalar(select(Asset).where(Asset.ticker == income.ticker))
    record = IncomeRecord(
        asset=asset,
        income_type=income.income_type,
        date=income.date,
        amount=income.amount,
        tax=income.tax,
    )
    session.add(record)
    session.commit()
    return record


def delete_income(session: Session, income_id: int) -> None:
    """Income depends on nothing, so deleting it is always allowed."""
    record = session.get(IncomeRecord, income_id)
    if record is None:
        raise IncomeNotFoundError(income_id)
    session.delete(record)
    session.commit()


def computed_incomes(session: Session, events: EventSource) -> list[Income]:
    """Income from published events, given the operations. Never stored."""
    incomes = []
    for ticker, (asset_type, ops) in _operations_by_ticker(session).items():
        ticker_events = events.events_for(ticker, asset_type)
        incomes += incomes_from_events(ops, ticker_events.income, stock_events=ticker_events.stock)
    return incomes
