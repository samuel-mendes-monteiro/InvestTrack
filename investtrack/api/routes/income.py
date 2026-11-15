"""Income (proventos): computed from B3 events, plus manual entries."""

from typing import Annotated

from fastapi import APIRouter, Query, status

from investtrack.api.deps import EventsDep, SessionDep, UserDep
from investtrack.api.errors import api_error
from investtrack.api.schemas import ErrorOut, IncomeCreate, IncomeOut, MonthlyIncomeOut
from investtrack.api.views import all_incomes, income_out, received
from investtrack.core.income import Income, IncomeWithoutPositionError, monthly_income
from investtrack.storage import repository

router = APIRouter(prefix="/income", tags=["income"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses={
        422: {"model": ErrorOut, "description": "Invalid data, or ticker not bought by then"}
    },
)
def create_income(payload: IncomeCreate, session: SessionDep, user: UserDep) -> IncomeOut:
    try:
        income = Income(
            ticker=payload.ticker,
            income_type=payload.income_type,
            date=payload.date,
            amount=payload.amount,
            tax=payload.tax,
        )
        record = repository.add_income(session, user.id, income)
    except IncomeWithoutPositionError as e:  # before ValueError: it is a subclass
        raise api_error(422, "INCOME_WITHOUT_POSITION", e) from e
    except ValueError as e:
        raise api_error(422, "INVALID_INCOME", e) from e
    return income_out(record.id, repository.income_to_domain(record))


@router.get("")
def list_income(
    session: SessionDep,
    user: UserDep,
    events: EventsDep,
    ticker: Annotated[str | None, Query(description="Filter by ticker")] = None,
    year: Annotated[int | None, Query(description="Filter by payment year")] = None,
) -> list[IncomeOut]:
    """Computed income from B3 events plus manual entries, including pending ones."""
    ticker = ticker.strip().upper() if ticker else None
    return [
        income_out(income_id, income)
        for income_id, income in all_incomes(session, user.id, events)
        if (ticker is None or income.ticker == ticker)
        and (year is None or income.date.year == year)
    ]


@router.get("/monthly")
def income_per_month(
    session: SessionDep,
    user: UserDep,
    events: EventsDep,
    year: Annotated[int | None, Query(description="Only this year")] = None,
) -> list[MonthlyIncomeOut]:
    """Income already received, per month. Pending income is not included."""
    incomes = [
        i for i in received(all_incomes(session, user.id, events)) if year in (None, i.date.year)
    ]
    return [MonthlyIncomeOut(**vars(m)) for m in monthly_income(incomes)]


@router.delete(
    "/{income_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"model": ErrorOut, "description": "Income not found"}},
)
def delete_income(income_id: int, session: SessionDep, user: UserDep) -> None:
    try:
        repository.delete_income(session, user.id, income_id)
    except repository.IncomeNotFoundError as e:
        raise api_error(404, "INCOME_NOT_FOUND", e) from e
