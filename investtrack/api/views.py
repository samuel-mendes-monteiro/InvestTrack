"""What more than one route needs: domain objects turned into response
schemas, and the reads shared by several pages (income, fixed income).
"""

from datetime import date, timedelta

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from investtrack.api.schemas import (
    FixedIncomeOut,
    IncomeOut,
    OperationOut,
    PartialRedemptionOut,
    UserOut,
)
from investtrack.auth import as_utc
from investtrack.core.fixed_income import FixedIncome, is_estimated, partial_valuations, value_on
from investtrack.core.income import Income
from investtrack.storage import repository
from investtrack.storage.events import EventSource
from investtrack.storage.market_data import CDI, IBOV, IPCA, IPCA_SINCE, MarketDataSource
from investtrack.storage.models import OperationRecord, User

# --- conversions -------------------------------------------------------------


def user_out(user: User) -> UserOut:
    # SQLite drops the timezone; the API always answers in UTC.
    return UserOut(id=user.id, email=user.email, created_at=as_utc(user.created_at))


def operation_out(record: OperationRecord) -> OperationOut:
    return OperationOut(
        id=record.id,
        ticker=record.asset.ticker,
        op_type=record.op_type,
        date=record.date,
        quantity=record.quantity,
        price=record.price,
        fees=record.fees,
    )


def income_out(income_id: int | None, income: Income) -> IncomeOut:
    return IncomeOut(
        id=income_id,
        source=income.source,
        ticker=income.ticker,
        income_type=income.income_type,
        date=income.date,
        pending=income.date > date.today(),
        amount=income.amount,
        tax=income.tax,
        net=income.net,
        record_date=income.record_date,
        quantity=income.quantity,
        rate=income.rate,
    )


def fixed_income_out(
    record, investment: FixedIncome, days: list[date], cdi: dict, ipca: dict
) -> FixedIncomeOut:
    last_day = days[-1] if days else None
    if investment.redeemed_on:
        status = "REDEEMED"
    elif last_day is not None and investment.maturity <= last_day:
        status = "MATURED"
    else:
        status = "ACTIVE"
    valuation = value_on(investment, investment.end, days, cdi, ipca) if days else None
    withdrawals = [
        PartialRedemptionOut(
            id=r.id,
            date=r.date,
            gross=r.gross,
            iof=v.iof if v else None,
            ir=v.ir if v else None,
            net=v.net if v else None,
        )
        # Both lists are sorted by date: the record's by its order_by, the
        # domain's in FixedIncome itself (same-day ties keep the record order).
        for r, v in zip(
            record.partial_redemptions, partial_valuations(investment, days, cdi, ipca), strict=True
        )
    ]
    return FixedIncomeOut(
        id=record.id,
        name=investment.name,
        product=investment.product,
        indexer=investment.indexer,
        rate=investment.rate,
        start=investment.start,
        maturity=investment.maturity,
        amount=investment.amount,
        redeemed_on=investment.redeemed_on,
        partial_redemptions=withdrawals,
        principal=valuation.principal if valuation else investment.amount,
        status=status,
        as_of=valuation.day if valuation else None,
        estimated=is_estimated(investment, valuation.day, ipca) if valuation else False,
        gross=valuation.gross if valuation else None,
        iof=valuation.iof if valuation else None,
        ir=valuation.ir if valuation else None,
        net=valuation.net if valuation else None,
        gross_return=valuation.gross_return if valuation else None,
    )


# --- shared reads ------------------------------------------------------------


def all_incomes(
    session: Session, user_id: int, events: EventSource
) -> list[tuple[int | None, Income]]:
    """Manual entries (with their id) and computed income, by payment date."""
    manual = [
        (r.id, repository.income_to_domain(r)) for r in repository.list_incomes(session, user_id)
    ]
    computed = [(None, i) for i in repository.computed_incomes(session, user_id, events)]
    return sorted(manual + computed, key=lambda pair: (pair[1].date, pair[1].ticker))


def received(incomes: list[tuple[int | None, Income]]) -> list[Income]:
    today = date.today()
    return [i for _, i in incomes if i.date <= today]


def business_days(market: MarketDataSource, start: date) -> tuple[list[date], dict, dict]:
    """Business days until the last close, and the CDI and IPCA since `start`.

    The CDI has a rate only on business days, but is published a day late;
    the Ibovespa adds the last trading day, whose value needs only the rates
    of the days before it.
    """
    # From a little before `start`, so the list always holds the last business
    # day before it: an investment applied after that day (today, on a weekend)
    # is then known to be new, not missing its history.
    since = start - timedelta(days=15)
    cdi = market.series(CDI, since)
    ibov = market.series(IBOV, since)
    days = sorted(d for d in set(cdi) | set(ibov) if d <= market.last_day())
    # All of it (a few hundred numbers): when the start month isn't published
    # yet, its estimate comes from a month before the start.
    ipca = market.series(IPCA, IPCA_SINCE)
    return days, cdi, ipca


def sync_market_data(market: MarketDataSource, start: date, background: BackgroundTasks) -> None:
    """Download the missing history from `start` after the response is sent."""
    if not market.syncing and not market.is_synced(start):
        background.add_task(market.sync, start)


def list_fixed_income(
    session: Session, user_id: int, market: MarketDataSource, background: BackgroundTasks
) -> list[FixedIncomeOut]:
    records = repository.list_fixed_income(session, user_id)
    if not records:
        return []
    start = min(r.start for r in records)
    sync_market_data(market, start, background)
    days, cdi, ipca = business_days(market, start)
    return [
        fixed_income_out(r, repository.fixed_income_to_domain(r), days, cdi, ipca) for r in records
    ]
