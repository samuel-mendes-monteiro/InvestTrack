"""Reading and writing operations.

This is the only module that talks to both the database and the
calculation core. Business rules (no selling more than you own) are not
duplicated here: every change is validated by recalculating the position
with portfolio.calculate_position before it is saved.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session, contains_eager

from investtrack.models import Asset, AssetType, OperationRecord
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

    session.delete(record)
    session.commit()


def get_portfolio(session: Session) -> dict[str, Position]:
    return calculate_portfolio([to_domain(r) for r in list_operations(session)])
