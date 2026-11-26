"""The Carteira: positions valued at the current quote, and a ticker's price
on a day (to fill in a new operation)."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Query
from fastapi import Path as PathParam

from investtrack.api.deps import EventsDep, MarketDep, PricesDep, SessionDep, UserDep
from investtrack.api.errors import api_error
from investtrack.api.schemas import ErrorOut, PortfolioOut, PortfolioTotals, PositionOut, PriceOut
from investtrack.api.views import all_incomes, list_fixed_income, received
from investtrack.core.income import net_income_by_ticker
from investtrack.core.portfolio import value_position
from investtrack.storage import repository

router = APIRouter(tags=["portfolio"])


@router.get(
    "/prices/{ticker}",
    responses={404: {"model": ErrorOut, "description": "No price known for that day"}},
)
def price_on(
    ticker: Annotated[str, PathParam(pattern=r"^[A-Za-z0-9]{4,12}$")],
    user: UserDep,
    prices: PricesDep,
    market: MarketDep,
    # B3's history starts in 1986; an earlier day (0001-01-03, say) is a typo,
    # and a week back from it would not even be a date.
    day: Annotated[date | None, Query(alias="date", ge=date(1986, 1, 1))] = None,
) -> PriceOut:
    """Price of a ticker on a day, to fill in a new operation.

    Today (or no date): the current quote. An earlier day: B3's official
    close, or the last one before it on a weekend or holiday. Closes come
    from the history the performance page downloads, which starts at the
    first operation, so an older day may have none (404).
    """
    ticker = ticker.upper()
    today = date.today()
    day = min(day or today, today)
    if day == today:
        quote = prices.get_quote(ticker)
        if quote is not None:
            return PriceOut(ticker=ticker, date=today, price=quote.price, source="QUOTE")
    # A week back covers any weekend plus a holiday.
    closes = market.closes({ticker}, day - timedelta(days=7)).get(ticker, {})
    known = [d for d in closes if d <= day]
    if not known:
        raise api_error(404, "PRICE_NOT_FOUND", LookupError(f"no price for {ticker} on {day}"))
    last = max(known)
    return PriceOut(ticker=ticker, date=last, price=closes[last], source="CLOSE")


@router.get("/portfolio")
def get_portfolio(
    session: SessionDep,
    user: UserDep,
    prices: PricesDep,
    events: EventsDep,
    market: MarketDep,
    background: BackgroundTasks,
) -> PortfolioOut:
    positions: list[PositionOut] = []
    total_invested = Decimal("0")
    total_value: Decimal | None = Decimal("0")
    total_realized = Decimal("0")
    incomes = all_incomes(session, user.id, events)
    income = net_income_by_ticker(received(incomes))
    pending = sum((i.net for _, i in incomes if i.date > date.today()), Decimal("0"))

    for pos in repository.get_portfolio(session, user.id, events).values():
        total_realized += pos.realized_profit
        invested = pos.quantity * pos.avg_price
        total_invested += invested

        # Closed positions need no quote: saves an API call per sold-out ticker.
        quote = prices.get_quote(pos.ticker) if pos.quantity > 0 else None

        if quote is None:
            valuation = None
            if pos.quantity > 0:
                total_value = None  # totals would be misleading
        else:
            valuation = value_position(pos, quote.price)
            if total_value is not None:
                total_value += valuation.current_value

        positions.append(
            PositionOut(
                ticker=pos.ticker,
                quantity=pos.quantity,
                avg_price=pos.avg_price,
                realized_profit=pos.realized_profit,
                current_price=quote.price if quote else None,
                price_as_of=quote.as_of if quote else None,
                price_stale=quote.stale if quote else False,
                invested=invested,
                current_value=valuation.current_value if valuation else None,
                result=valuation.result if valuation else None,
                result_pct=valuation.result_pct if valuation else None,
                income=income.get(pos.ticker, Decimal("0")),
            )
        )

    # Fixed income from the CDI history. While a value is unknown (the history
    # is still downloading), the total is unknown too: leaving that investment
    # out would show a smaller net worth as if it were right.
    investments = list_fixed_income(session, user.id, market, background)
    active = [f for f in investments if f.status == "ACTIVE"]
    unknown = any(f.net is None for f in active)
    fixed_income = None if unknown else sum((f.net for f in active), Decimal("0"))
    # The screen asks again while this is true, instead of keeping old numbers until a reload.
    start = min((f.start for f in investments), default=None)
    syncing = unknown or (
        start is not None and (market.syncing or not market.is_synced(start, prices=False))
    )

    total_result = None if total_value is None else total_value - total_invested
    total_pct = (
        total_result / total_invested * 100 if total_result is not None and total_invested else None
    )
    return PortfolioOut(
        positions=positions,
        totals=PortfolioTotals(
            invested=total_invested,
            current_value=total_value,
            result=total_result,
            result_pct=total_pct,
            realized_profit=total_realized,
            income=sum(income.values(), Decimal("0")),
            income_pending=pending,
            fixed_income=fixed_income,
        ),
        syncing=syncing,
    )
