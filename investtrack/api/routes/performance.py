"""Rentabilidade and Patrimônio: the time-weighted return against the CDI and
the Ibovespa, and the net worth and money put in at each close."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Query

from investtrack.api.deps import EventsDep, MarketDep, SessionDep, UserDep
from investtrack.api.schemas import PerformanceOut, PerformancePoint
from investtrack.api.views import all_incomes, business_days, received
from investtrack.core.fixed_income import daily_net_values, daily_series, money_in
from investtrack.core.performance import (
    Period,
    cdi_accumulated,
    index_return,
    operation_flow,
    portfolio_history,
    rebase,
    window_base,
)
from investtrack.storage import repository
from investtrack.storage.market_data import CDI, IBOV

router = APIRouter(tags=["portfolio"])


def empty(syncing: bool) -> PerformanceOut:
    return PerformanceOut(
        syncing=syncing,
        start=None,
        as_of=None,
        twr=None,
        cdi=None,
        ibovespa=None,
        pct_of_cdi=None,
        points=[],
    )


@router.get("/performance")
def performance(
    session: SessionDep,
    user: UserDep,
    events: EventsDep,
    market: MarketDep,
    background: BackgroundTasks,
    period: Annotated[
        Period, Query(description="Only the last month, 6 months, year, or everything")
    ] = Period.ALL,
) -> PerformanceOut:
    """Time-weighted return since the first trade, against CDI and Ibovespa.

    Answers right away with the history already stored. If something is
    missing, it is downloaded in the background and `syncing` is true.
    With a period, every series starts at 0% on the close before it.
    """
    operations, stock = repository.operations_and_stock_events(session, user.id, events)
    investments = [
        repository.fixed_income_to_domain(r) for r in repository.list_fixed_income(session, user.id)
    ]
    if not operations and not investments:
        return empty(syncing=False)
    start = min([op.date for op in operations] + [i.start for i in investments])
    syncing = market.syncing
    if not syncing and not market.is_synced(start):
        background.add_task(market.sync, start)
        syncing = True

    last_day = market.last_day()
    closes = market.closes({op.ticker for op in operations}, start)
    ibov = market.series(IBOV, start - timedelta(days=15))  # includes the close before
    cdi = market.series(CDI, start)
    days = sorted(
        d
        for d in set(ibov) | {d for by_day in closes.values() for d in by_day}
        if start <= d <= last_day
    )
    incomes = [i for i in received(all_incomes(session, user.id, events)) if i.date <= last_day]
    fi_days = business_days(market, start)
    fi_values, fi_flows = daily_series(investments, *fi_days)
    fi_net = daily_net_values(investments, *fi_days)
    history = portfolio_history(
        operations, days, closes, stock, incomes, other_values=fi_values, other_flows=fi_flows
    )
    # The same without income: the part of the return that came from prices
    # (and fees, and fixed income). The rest of the TWR is the income.
    price_only = {
        h.date: h.twr
        for h in portfolio_history(
            operations, days, closes, stock, (), other_values=fi_values, other_flows=fi_flows
        )
    }
    if not history:
        return empty(syncing)

    # Money put in until each close, over the whole history: a period's
    # gain is its change in net worth minus what went in during it.
    invested: dict[date, Decimal] = {}
    running = Decimal("0")
    for h in history:
        running += h.flow
        invested[h.date] = running
    fi_in = money_in(investments, *fi_days, date.today())
    invested_now = (
        None
        if fi_in is None
        else sum((operation_flow(op) for op in operations), Decimal("0")) + fi_in
    )

    first = history[0].date
    cdi_acc = cdi_accumulated(cdi, days, first) if cdi else {}
    ibov_ret = index_return(ibov, days, first)

    def pct(value: Decimal | None) -> Decimal | None:
        return None if value is None else value * 100

    base = window_base([h.date for h in history], period)
    if base is not None:
        twr_base = next(h.twr for h in history if h.date == base)
        history = [h for h in history if h.date >= base]

        def rebased(series: dict[date, Decimal]) -> dict[date, Decimal]:
            if base not in series:
                return {}
            return {d: rebase(v, series[base]) for d, v in series.items() if d >= base}

        cdi_acc, ibov_ret = rebased(cdi_acc), rebased(ibov_ret)
        twr = {h.date: rebase(h.twr, twr_base) for h in history}
    else:
        twr = {h.date: h.twr for h in history}
    # Price-only return at each close, measured from the same base as the TWR.
    price_twr = {
        h.date: price_only[h.date] if base is None else rebase(price_only[h.date], price_only[base])
        for h in history
    }

    points = [
        PerformancePoint(
            date=h.date,
            value=h.value,
            # The same day with fixed income net of taxes instead of gross.
            net_worth=h.value
            - fi_values.get(h.date, Decimal("0"))
            + fi_net.get(h.date, Decimal("0")),
            invested=invested[h.date],
            twr=twr[h.date] * 100,
            twr_price=price_twr[h.date] * 100,
            cdi=pct(cdi_acc.get(h.date)),
            ibovespa=pct(ibov_ret.get(h.date)),
        )
        for h in history
    ]
    last = points[-1]
    return PerformanceOut(
        syncing=syncing,
        start=points[0].date,
        as_of=last.date,
        twr=last.twr,
        twr_price=last.twr_price,
        cdi=last.cdi,
        ibovespa=last.ibovespa,
        pct_of_cdi=last.twr / last.cdi * 100 if last.cdi else None,
        pct_of_cdi_price=last.twr_price / last.cdi * 100 if last.cdi else None,
        points=points,
        invested_now=invested_now,
    )
