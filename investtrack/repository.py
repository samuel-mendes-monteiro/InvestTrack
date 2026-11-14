"""Reading and writing operations and income.

This is the only module that talks to both the database and the
calculation core. Business rules (no selling more than you own, no income
before the first buy) are not duplicated here: every change is validated
by the calculation core before it is saved.
"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session, contains_eager

from investtrack.income import Income, check_incomes, incomes_from_events
from investtrack.income_events import IncomeEventSource
from investtrack.models import Asset, AssetType, IncomeRecord, OperationRecord
from investtrack.portfolio import (
    Operation,
    Position,
    calculate_portfolio,
    calculate_position,
)


class OperationNotFoundError(LookupError):
    def __init__(self, operation_id: int):
        self.operation_id = operation_id
        super().__init__(f"operation {operation_id} not found")


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


def add_operation(
    session: Session, op: Operation, asset_type: AssetType = AssetType.STOCK
) -> OperationRecord:
    """Save an operation, refusing it if it would sell more than the position.

    asset_type is only used when the ticker is new.
    Raises InsufficientPositionError (nothing is saved in that case).
    """
    existing = [to_domain(r) for r in list_operations(session, op.ticker)]
    calculate_position(existing + [op])  # raises if the new list is invalid

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


def delete_operation(session: Session, operation_id: int) -> None:
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
        calculate_position(remaining)  # raises if the remaining list is invalid
    # Deleting the first buy may leave income paid before any remaining buy.
    incomes = [income_to_domain(r) for r in list_incomes(session, record.asset.ticker)]
    check_incomes(remaining, incomes)

    session.delete(record)
    session.commit()


def get_portfolio(session: Session) -> dict[str, Position]:
    return calculate_portfolio([to_domain(r) for r in list_operations(session)])


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


def computed_incomes(session: Session, events: IncomeEventSource) -> list[Income]:
    """Income from published events, given the operations. Never stored."""
    by_ticker: dict[str, tuple[AssetType, list[Operation]]] = {}
    for record in list_operations(session):
        asset_type, ops = by_ticker.setdefault(record.asset.ticker, (record.asset.asset_type, []))
        ops.append(to_domain(record))

    incomes = []
    for ticker, (asset_type, ops) in by_ticker.items():
        incomes += incomes_from_events(ops, events.events_for(ticker, asset_type))
    return incomes
