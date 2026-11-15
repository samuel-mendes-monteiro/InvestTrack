"""Buy and sell trades, and the stock events (splits, bonus shares) that
changed a position."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, status

from investtrack.api.deps import EventsDep, SessionDep, UserDep
from investtrack.api.errors import api_error
from investtrack.api.schemas import (
    BonusCostIn,
    ErrorOut,
    OperationCreate,
    OperationOut,
    StockEventOut,
)
from investtrack.api.views import operation_out
from investtrack.core.income import IncomeWithoutPositionError
from investtrack.core.portfolio import InsufficientPositionError, Operation
from investtrack.storage import repository

router = APIRouter(tags=["operations"])


def to_domain(payload: OperationCreate) -> Operation:
    return Operation(
        ticker=payload.ticker,
        op_type=payload.op_type,
        date=payload.date,
        quantity=payload.quantity,
        price=payload.price,
        fees=payload.fees,
    )


@router.post(
    "/operations",
    status_code=status.HTTP_201_CREATED,
    responses={422: {"model": ErrorOut, "description": "Invalid data, or selling more than owned"}},
)
def create_operation(
    payload: OperationCreate, session: SessionDep, user: UserDep, events: EventsDep
) -> OperationOut:
    try:
        record = repository.add_operation(
            session, user.id, to_domain(payload), payload.asset_type, events
        )
    except InsufficientPositionError as e:
        raise api_error(422, "INSUFFICIENT_POSITION", e) from e
    except ValueError as e:  # domain validation, e.g. a blank ticker
        raise api_error(422, "INVALID_OPERATION", e) from e
    return operation_out(record)


@router.get("/operations")
def list_operations(
    session: SessionDep,
    user: UserDep,
    ticker: Annotated[str | None, Query(description="Filter by ticker")] = None,
) -> list[OperationOut]:
    return [operation_out(r) for r in repository.list_operations(session, user.id, ticker)]


@router.delete(
    "/operations/{operation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        404: {"model": ErrorOut, "description": "Operation not found"},
        409: {
            "model": ErrorOut,
            "description": "Would leave a later sale, or income, without shares",
        },
    },
)
def delete_operation(
    operation_id: int, session: SessionDep, user: UserDep, events: EventsDep
) -> None:
    try:
        repository.delete_operation(session, user.id, operation_id, events)
    except repository.OperationNotFoundError as e:
        raise api_error(404, "OPERATION_NOT_FOUND", e) from e
    except InsufficientPositionError as e:
        raise api_error(409, "DELETE_BREAKS_LATER_SALE", e) from e
    except IncomeWithoutPositionError as e:
        raise api_error(409, "DELETE_ORPHANS_INCOME", e) from e


@router.put(
    "/operations/{operation_id}",
    responses={
        404: {"model": ErrorOut, "description": "Operation not found"},
        409: {"model": ErrorOut, "description": "Would leave a sale, or income, without shares"},
        422: {"model": ErrorOut, "description": "Invalid data"},
    },
)
def update_operation(
    operation_id: int,
    payload: OperationCreate,
    session: SessionDep,
    user: UserDep,
    events: EventsDep,
) -> OperationOut:
    """Replace every field of an operation, e.g. to add the fees of an
    imported trade. Same body as creating one; the id stays the same."""
    try:
        record = repository.update_operation(
            session, user.id, operation_id, to_domain(payload), payload.asset_type, events
        )
    except repository.OperationNotFoundError as e:
        raise api_error(404, "OPERATION_NOT_FOUND", e) from e
    # 409, not 422: the data is valid, it conflicts with the other operations.
    except InsufficientPositionError as e:
        raise api_error(409, "EDIT_BREAKS_HISTORY", e) from e
    except IncomeWithoutPositionError as e:
        raise api_error(409, "EDIT_ORPHANS_INCOME", e) from e
    except ValueError as e:
        raise api_error(422, "INVALID_OPERATION", e) from e
    return operation_out(record)


@router.get("/stock-events")
def list_stock_events(session: SessionDep, user: UserDep, events: EventsDep) -> list[StockEventOut]:
    """Splits, reverse splits and bonus shares that changed one of your positions."""
    costs = repository.bonus_costs(session, user.id)
    return [
        StockEventOut(
            ticker=a.event.ticker,
            event_type=a.event.event_type,
            record_date=a.event.record_date,
            multiplier=a.event.multiplier,
            quantity_before=a.quantity_before,
            quantity_after=a.quantity_after,
            unit_cost=costs.get((a.event.ticker, a.event.record_date)),
        )
        for a in repository.get_applied_stock_events(session, user.id, events)
    ]


@router.put(
    "/stock-events/{ticker}/{record_date}/unit-cost",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"model": ErrorOut, "description": "No bonus event on that date"}},
)
def set_bonus_cost(
    ticker: str,
    record_date: date,
    payload: BonusCostIn,
    session: SessionDep,
    user: UserDep,
    events: EventsDep,
) -> None:
    """Attributed cost (custo atribuído) of bonus shares, from the company's notice."""
    try:
        repository.set_bonus_cost(session, user.id, ticker, record_date, payload.unit_cost, events)
    except repository.StockEventNotFoundError as e:
        raise api_error(404, "STOCK_EVENT_NOT_FOUND", e) from e


@router.delete(
    "/stock-events/{ticker}/{record_date}/unit-cost", status_code=status.HTTP_204_NO_CONTENT
)
def delete_bonus_cost(ticker: str, record_date: date, session: SessionDep, user: UserDep) -> None:
    """Back to zero cost."""
    repository.delete_bonus_cost(session, user.id, ticker, record_date)
