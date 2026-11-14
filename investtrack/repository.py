"""Reading and writing each user's operations, income and fixed income.

This is the only module that talks to both the database and the
calculation core. Business rules (no selling more than you own, no income
before the first buy) are not duplicated here: every change is validated
by the calculation core before it is saved.

Every function that touches a user's data takes `user_id` right after the
session, and every query filters by it. Reading another user's row by id
behaves exactly like a missing row (NotFound), so ids reveal nothing.
Market data (assets, quotes, B3 events) is shared by everyone.
"""

from dataclasses import replace
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, contains_eager

from investtrack.events import NO_EVENTS, EventSource
from investtrack.fixed_income import FixedIncome
from investtrack.income import Income, check_incomes, incomes_from_events
from investtrack.models import (
    Asset,
    AssetType,
    BonusCost,
    FixedIncomeRecord,
    IncomeRecord,
    OperationRecord,
)
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


def _owned(session: Session, model, row_id: int, user_id: int):
    """The row if it exists and belongs to this user, else None."""
    record = session.get(model, row_id)
    return record if record is not None and record.user_id == user_id else None


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


def list_operations(
    session: Session, user_id: int, ticker: str | None = None
) -> list[OperationRecord]:
    """Operations ordered by (date, id): same-day operations keep entry order."""
    stmt = (
        select(OperationRecord)
        .join(OperationRecord.asset)
        .options(contains_eager(OperationRecord.asset))  # avoids one query per row
        .where(OperationRecord.user_id == user_id)
        .order_by(OperationRecord.date, OperationRecord.id)
    )
    if ticker is not None:
        stmt = stmt.where(Asset.ticker == ticker.strip().upper())
    return list(session.scalars(stmt))


def get_or_create_asset(
    session: Session, ticker: str, asset_type: AssetType = AssetType.STOCK
) -> Asset:
    """Assets are shared: the first person to trade a ticker sets its type."""
    asset = session.scalar(select(Asset).where(Asset.ticker == ticker))
    if asset is None:
        asset = Asset(ticker=ticker, asset_type=asset_type)
        session.add(asset)
    return asset


def bonus_costs(session: Session, user_id: int) -> dict[tuple[str, date], Decimal]:
    costs = session.scalars(select(BonusCost).where(BonusCost.user_id == user_id))
    return {(c.ticker, c.record_date): c.unit_cost for c in costs}


def _with_bonus_costs(session: Session, user_id: int, stock: list[StockEvent]) -> list[StockEvent]:
    """Stock events with the attributed costs typed by this user filled in."""
    costs = bonus_costs(session, user_id)
    return [
        replace(e, unit_cost=costs[(e.ticker, e.record_date)])
        if e.event_type is StockEventType.BONUS and (e.ticker, e.record_date) in costs
        else e
        for e in stock
    ]


def _stock_events(
    session: Session, user_id: int, events: EventSource, ticker: str, new_asset_type: AssetType
) -> list[StockEvent]:
    asset = session.scalar(select(Asset).where(Asset.ticker == ticker))
    stock = events.events_for(ticker, asset.asset_type if asset else new_asset_type).stock
    return _with_bonus_costs(session, user_id, stock)


def _operations_by_ticker(
    session: Session, user_id: int
) -> dict[str, tuple[AssetType, list[Operation]]]:
    by_ticker: dict[str, tuple[AssetType, list[Operation]]] = {}
    for record in list_operations(session, user_id):
        _, ops = by_ticker.setdefault(record.asset.ticker, (record.asset.asset_type, []))
        ops.append(to_domain(record))
    return by_ticker


def add_operation(
    session: Session,
    user_id: int,
    op: Operation,
    asset_type: AssetType = AssetType.STOCK,
    events: EventSource = NO_EVENTS,
) -> OperationRecord:
    """Save an operation, refusing it if it would sell more than the position.

    asset_type is only used when the ticker is new. Splits and bonus shares
    from `events` count: after a 1:2 split, selling the doubled amount is fine.
    Raises InsufficientPositionError (nothing is saved in that case).
    """
    existing = [to_domain(r) for r in list_operations(session, user_id, op.ticker)]
    stock = _stock_events(session, user_id, events, op.ticker, asset_type)
    calculate_position(existing + [op], stock)  # raises if the new list is invalid

    record = OperationRecord(
        user_id=user_id,
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


def delete_operation(
    session: Session, user_id: int, operation_id: int, events: EventSource = NO_EVENTS
) -> None:
    """Delete an operation, refusing it if a later sale would become invalid.

    Example: buy 100, sell 80. Deleting the buy would leave a sale of 80
    shares that were never bought, so it raises InsufficientPositionError.
    """
    record = _owned(session, OperationRecord, operation_id, user_id)
    if record is None:
        raise OperationNotFoundError(operation_id)

    ticker = record.asset.ticker
    remaining = [
        to_domain(r) for r in list_operations(session, user_id, ticker) if r.id != operation_id
    ]
    if remaining:
        stock = _stock_events(session, user_id, events, ticker, record.asset.asset_type)
        calculate_position(remaining, stock)  # raises if the remaining list is invalid
    # Deleting the first buy may leave income paid before any remaining buy.
    incomes = [income_to_domain(r) for r in list_incomes(session, user_id, ticker)]
    check_incomes(remaining, incomes)

    session.delete(record)
    session.commit()


def operations_and_stock_events(
    session: Session, user_id: int, events: EventSource
) -> tuple[list[Operation], list[StockEvent]]:
    operations: list[Operation] = []
    stock: list[StockEvent] = []
    for ticker, (asset_type, ops) in _operations_by_ticker(session, user_id).items():
        operations += ops
        stock += events.events_for(ticker, asset_type).stock
    return operations, _with_bonus_costs(session, user_id, stock)


def get_portfolio(
    session: Session, user_id: int, events: EventSource = NO_EVENTS
) -> dict[str, Position]:
    return calculate_portfolio(*operations_and_stock_events(session, user_id, events))


def get_applied_stock_events(
    session: Session, user_id: int, events: EventSource
) -> list[AppliedStockEvent]:
    return applied_stock_events(*operations_and_stock_events(session, user_id, events))


def set_bonus_cost(
    session: Session,
    user_id: int,
    ticker: str,
    record_date: date,
    unit_cost: Decimal,
    events: EventSource,
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

    cost = _bonus_cost(session, user_id, ticker, record_date)
    if cost is None:
        session.add(
            BonusCost(user_id=user_id, ticker=ticker, record_date=record_date, unit_cost=unit_cost)
        )
    else:
        cost.unit_cost = unit_cost
    session.commit()


def _bonus_cost(session: Session, user_id: int, ticker: str, record_date: date) -> BonusCost | None:
    return session.scalar(
        select(BonusCost).where(
            BonusCost.user_id == user_id,
            BonusCost.ticker == ticker,
            BonusCost.record_date == record_date,
        )
    )


def delete_bonus_cost(session: Session, user_id: int, ticker: str, record_date: date) -> None:
    """Back to zero cost. Deleting a cost that isn't there is not an error."""
    cost = _bonus_cost(session, user_id, ticker.strip().upper(), record_date)
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
    session: Session, user_id: int, ticker: str | None = None, year: int | None = None
) -> list[IncomeRecord]:
    """Income ordered by (date, id), optionally filtered by ticker and year."""
    stmt = (
        select(IncomeRecord)
        .join(IncomeRecord.asset)
        .options(contains_eager(IncomeRecord.asset))
        .where(IncomeRecord.user_id == user_id)
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


def add_income(session: Session, user_id: int, income: Income) -> IncomeRecord:
    """Save income, refusing it if this user hadn't bought the ticker by then.

    Raises IncomeWithoutPositionError (nothing is saved in that case). The
    asset is never created here: an unknown ticker is almost always a typo.
    """
    operations = [to_domain(r) for r in list_operations(session, user_id, income.ticker)]
    check_incomes(operations, [income])

    asset = session.scalar(select(Asset).where(Asset.ticker == income.ticker))
    record = IncomeRecord(
        user_id=user_id,
        asset=asset,
        income_type=income.income_type,
        date=income.date,
        amount=income.amount,
        tax=income.tax,
    )
    session.add(record)
    session.commit()
    return record


def delete_income(session: Session, user_id: int, income_id: int) -> None:
    """Income depends on nothing, so deleting it is always allowed."""
    record = _owned(session, IncomeRecord, income_id, user_id)
    if record is None:
        raise IncomeNotFoundError(income_id)
    session.delete(record)
    session.commit()


def computed_incomes(session: Session, user_id: int, events: EventSource) -> list[Income]:
    """Income from published events, given the operations. Never stored."""
    incomes = []
    for ticker, (asset_type, ops) in _operations_by_ticker(session, user_id).items():
        ticker_events = events.events_for(ticker, asset_type)
        incomes += incomes_from_events(ops, ticker_events.income, stock_events=ticker_events.stock)
    return incomes


# --- fixed income ------------------------------------------------------------


class FixedIncomeNotFoundError(LookupError):
    def __init__(self, investment_id: int):
        self.investment_id = investment_id
        super().__init__(f"fixed income {investment_id} not found")


def fixed_income_to_domain(record: FixedIncomeRecord) -> FixedIncome:
    return FixedIncome(
        name=record.name,
        product=record.product,
        indexer=record.indexer,
        rate=record.rate,
        start=record.start,
        maturity=record.maturity,
        amount=record.amount,
        redeemed_on=record.redeemed_on,
    )


def list_fixed_income(session: Session, user_id: int) -> list[FixedIncomeRecord]:
    stmt = (
        select(FixedIncomeRecord)
        .where(FixedIncomeRecord.user_id == user_id)
        .order_by(FixedIncomeRecord.start, FixedIncomeRecord.id)
    )
    return list(session.scalars(stmt))


def add_fixed_income(session: Session, user_id: int, investment: FixedIncome) -> FixedIncomeRecord:
    record = FixedIncomeRecord(
        user_id=user_id,
        name=investment.name,
        product=investment.product,
        indexer=investment.indexer,
        rate=investment.rate,
        start=investment.start,
        maturity=investment.maturity,
        amount=investment.amount,
        redeemed_on=investment.redeemed_on,
    )
    session.add(record)
    session.commit()
    return record


def _get_fixed_income(session: Session, user_id: int, investment_id: int) -> FixedIncomeRecord:
    record = _owned(session, FixedIncomeRecord, investment_id, user_id)
    if record is None:
        raise FixedIncomeNotFoundError(investment_id)
    return record


def redeem_fixed_income(
    session: Session, user_id: int, investment_id: int, day: date | None
) -> FixedIncomeRecord:
    """Early redemption on `day` (None undoes it). Validated by the domain class."""
    record = _get_fixed_income(session, user_id, investment_id)
    replace(fixed_income_to_domain(record), redeemed_on=day)  # raises if out of range
    record.redeemed_on = day
    session.commit()
    return record


def delete_fixed_income(session: Session, user_id: int, investment_id: int) -> None:
    session.delete(_get_fixed_income(session, user_id, investment_id))
    session.commit()
