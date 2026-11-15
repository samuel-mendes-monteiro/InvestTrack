"""Fixed income (CDB, LCI, LCA): investments, redemptions and withdrawals."""

from fastapi import APIRouter, BackgroundTasks, status

from investtrack.api.deps import MarketDep, SessionDep, UserDep
from investtrack.api.errors import api_error
from investtrack.api.schemas import (
    ErrorOut,
    FixedIncomeCreate,
    FixedIncomeOut,
    PartialRedemptionIn,
    RedeemIn,
)
from investtrack.api.views import (
    business_days,
    fixed_income_out,
    list_fixed_income,
    sync_market_data,
)
from investtrack.core.fixed_income import FixedIncome, PartialRedemption, RedemptionTooLargeError
from investtrack.storage import repository
from investtrack.storage.market_data import MarketDataSource
from investtrack.storage.models import FixedIncomeRecord

router = APIRouter(prefix="/fixed-income", tags=["fixed income"])

NOT_FOUND = {404: {"model": ErrorOut, "description": "Not found"}}


def valued(record: FixedIncomeRecord, market: MarketDataSource) -> FixedIncomeOut:
    """A stored investment, valued with the market data from its start."""
    days, cdi, ipca = business_days(market, record.start)
    return fixed_income_out(record, repository.fixed_income_to_domain(record), days, cdi, ipca)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses={422: {"model": ErrorOut, "description": "Invalid data"}},
)
def create_fixed_income(
    payload: FixedIncomeCreate,
    session: SessionDep,
    user: UserDep,
    market: MarketDep,
    background: BackgroundTasks,
) -> FixedIncomeOut:
    try:
        investment = FixedIncome(**payload.model_dump())
    except ValueError as e:
        raise api_error(422, "INVALID_FIXED_INCOME", e) from e
    record = repository.add_fixed_income(session, user.id, investment)
    sync_market_data(market, investment.start, background)
    days, cdi, ipca = business_days(market, investment.start)
    return fixed_income_out(record, investment, days, cdi, ipca)


@router.put(
    "/{investment_id}",
    responses={
        **NOT_FOUND,
        422: {
            "model": ErrorOut,
            "description": "Invalid data, or a withdrawal no longer fits the investment",
        },
    },
)
def update_fixed_income(
    investment_id: int,
    payload: FixedIncomeCreate,
    session: SessionDep,
    user: UserDep,
    market: MarketDep,
    background: BackgroundTasks,
) -> FixedIncomeOut:
    """Edit an investment. Its redemption and withdrawals stay, and must still fit."""
    try:
        edited = FixedIncome(**payload.model_dump())
        days, cdi, ipca = business_days(market, edited.start)
        record = repository.update_fixed_income(
            session, user.id, investment_id, edited, days, cdi, ipca
        )
    except repository.FixedIncomeNotFoundError as e:
        raise api_error(404, "FIXED_INCOME_NOT_FOUND", e) from e
    except RedemptionTooLargeError as e:
        raise api_error(422, "REDEMPTION_TOO_LARGE", e) from e
    except ValueError as e:
        raise api_error(422, "INVALID_FIXED_INCOME", e) from e
    sync_market_data(market, record.start, background)
    return fixed_income_out(record, repository.fixed_income_to_domain(record), days, cdi, ipca)


@router.get("")
def get_fixed_income(
    session: SessionDep, user: UserDep, market: MarketDep, background: BackgroundTasks
) -> list[FixedIncomeOut]:
    """Each investment valued at its last day (today, redemption or maturity)."""
    return list_fixed_income(session, user.id, market, background)


@router.put(
    "/{investment_id}/redemption",
    responses={
        **NOT_FOUND,
        422: {"model": ErrorOut, "description": "Date outside the investment period"},
    },
)
def redeem_fixed_income(
    investment_id: int, payload: RedeemIn, session: SessionDep, user: UserDep, market: MarketDep
) -> FixedIncomeOut:
    """Early redemption (the whole investment), or null to undo it."""
    try:
        record = repository.redeem_fixed_income(
            session, user.id, investment_id, payload.redeemed_on
        )
    except repository.FixedIncomeNotFoundError as e:
        raise api_error(404, "FIXED_INCOME_NOT_FOUND", e) from e
    except ValueError as e:
        raise api_error(422, "INVALID_FIXED_INCOME", e) from e
    return valued(record, market)


@router.post(
    "/{investment_id}/partial-redemptions",
    status_code=status.HTTP_201_CREATED,
    responses={
        **NOT_FOUND,
        422: {
            "model": ErrorOut,
            "description": "Outside the period, value not known, or more than there is",
        },
    },
)
def add_partial_redemption(
    investment_id: int,
    payload: PartialRedemptionIn,
    session: SessionDep,
    user: UserDep,
    market: MarketDep,
) -> FixedIncomeOut:
    """Withdraw part of the money; the rest keeps running."""
    try:
        redemption = PartialRedemption(payload.date, payload.gross)
        record = repository.get_fixed_income(session, user.id, investment_id)
        days, cdi, ipca = business_days(market, record.start)
        record = repository.add_partial_redemption(
            session, user.id, investment_id, redemption, days, cdi, ipca
        )
    except repository.FixedIncomeNotFoundError as e:
        raise api_error(404, "FIXED_INCOME_NOT_FOUND", e) from e
    except RedemptionTooLargeError as e:
        raise api_error(422, "REDEMPTION_TOO_LARGE", e) from e
    except repository.ValueNotKnownError as e:
        raise api_error(422, "VALUE_NOT_KNOWN", e) from e
    except ValueError as e:
        raise api_error(422, "INVALID_PARTIAL_REDEMPTION", e) from e
    return fixed_income_out(record, repository.fixed_income_to_domain(record), days, cdi, ipca)


@router.delete("/{investment_id}/partial-redemptions/{redemption_id}", responses=NOT_FOUND)
def delete_partial_redemption(
    investment_id: int,
    redemption_id: int,
    session: SessionDep,
    user: UserDep,
    market: MarketDep,
) -> FixedIncomeOut:
    try:
        record = repository.delete_partial_redemption(
            session, user.id, investment_id, redemption_id
        )
    except repository.FixedIncomeNotFoundError as e:
        raise api_error(404, "FIXED_INCOME_NOT_FOUND", e) from e
    except repository.PartialRedemptionNotFoundError as e:
        raise api_error(404, "PARTIAL_REDEMPTION_NOT_FOUND", e) from e
    return valued(record, market)


@router.delete("/{investment_id}", status_code=status.HTTP_204_NO_CONTENT, responses=NOT_FOUND)
def delete_fixed_income(investment_id: int, session: SessionDep, user: UserDep) -> None:
    try:
        repository.delete_fixed_income(session, user.id, investment_id)
    except repository.FixedIncomeNotFoundError as e:
        raise api_error(404, "FIXED_INCOME_NOT_FOUND", e) from e
