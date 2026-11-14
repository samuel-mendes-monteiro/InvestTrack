"""HTTP layer (FastAPI).

Endpoints are thin: they convert JSON to domain objects, call the
repository, and translate domain errors into HTTP status codes.

Run with:  uvicorn investtrack.api:app --reload
"""

import logging
import os
from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from investtrack import repository
from investtrack.b3 import B3Client
from investtrack.brapi import BrapiClient
from investtrack.db import create_db_engine, init_db
from investtrack.events import EventSource, StoredEvents
from investtrack.income import (
    Income,
    IncomeWithoutPositionError,
    monthly_income,
    net_income_by_ticker,
)
from investtrack.models import OperationRecord
from investtrack.portfolio import InsufficientPositionError, Operation, value_position
from investtrack.prices import CachedPriceProvider, PriceProvider
from investtrack.schemas import (
    BonusCostIn,
    ErrorOut,
    IncomeCreate,
    IncomeOut,
    MonthlyIncomeOut,
    OperationCreate,
    OperationOut,
    PortfolioOut,
    PortfolioTotals,
    PositionOut,
    StockEventOut,
)

# --- dependencies ------------------------------------------------------------


def get_session(request: Request) -> Iterator[Session]:
    """One database session per request, always closed at the end."""
    with Session(request.app.state.engine) as session:
        yield session


def get_price_provider(request: Request) -> PriceProvider:
    return request.app.state.price_provider


def get_events(request: Request) -> EventSource:
    return request.app.state.events


SessionDep = Annotated[Session, Depends(get_session)]
PricesDep = Annotated[PriceProvider, Depends(get_price_provider)]
EventsDep = Annotated[EventSource, Depends(get_events)]


def api_error(status_code: int, code: str, error: Exception) -> HTTPException:
    """An HTTP error with a stable machine-readable code.

    Clients translate the code into their own language and can use the
    extra fields (ticker, available, requested) to build the message.
    The English `message` is a fallback for codes a client doesn't know.
    """
    detail = {"code": code, "message": str(error)}
    if isinstance(error, InsufficientPositionError):
        detail |= {
            "ticker": error.ticker,
            "available": str(error.available),
            "requested": str(error.requested),
        }
    elif isinstance(error, IncomeWithoutPositionError):
        detail |= {
            "ticker": error.ticker,
            "income_date": error.date.isoformat(),
            "first_buy": error.first_buy.isoformat() if error.first_buy else None,
        }
    return HTTPException(status_code, detail)


def to_out(record: OperationRecord) -> OperationOut:
    return OperationOut(
        id=record.id,
        ticker=record.asset.ticker,
        op_type=record.op_type,
        date=record.date,
        quantity=record.quantity,
        price=record.price,
        fees=record.fees,
    )


def income_to_out(income_id: int | None, income: Income) -> IncomeOut:
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


def all_incomes(session: Session, events: EventSource) -> list[tuple[int | None, Income]]:
    """Manual entries (with their id) and computed income, by payment date."""
    manual = [(r.id, repository.income_to_domain(r)) for r in repository.list_incomes(session)]
    computed = [(None, i) for i in repository.computed_incomes(session, events)]
    return sorted(manual + computed, key=lambda pair: (pair[1].date, pair[1].ticker))


def received(incomes: list[tuple[int | None, Income]]) -> list[Income]:
    today = date.today()
    return [i for _, i in incomes if i.date <= today]


# --- app factory -------------------------------------------------------------


def default_price_provider(engine: Engine) -> PriceProvider:
    """Real quotes from brapi.dev, cached in the database.

    Settings come from environment variables (or the .env file):
    BRAPI_TOKEN (optional: without it only a few tickers work) and
    PRICE_CACHE_MINUTES (default 15).
    """
    client = BrapiClient(token=os.getenv("BRAPI_TOKEN") or None)
    ttl = timedelta(minutes=int(os.getenv("PRICE_CACHE_MINUTES", "15")))
    return CachedPriceProvider(engine, client.fetch_price, ttl=ttl)


def create_app(
    engine: Engine | None = None,
    price_provider: PriceProvider | None = None,
    events: EventSource | None = None,
) -> FastAPI:
    """Build the app. Tests pass their own engine, prices and corporate events."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        load_dotenv()  # reads .env into environment variables (never committed)
        logging.basicConfig(level=logging.INFO)
        app.state.engine = engine or create_db_engine()
        app.state.price_provider = price_provider or default_price_provider(app.state.engine)
        app.state.events = events or StoredEvents(app.state.engine, B3Client().fetch_events)
        init_db(app.state.engine)
        yield
        app.state.engine.dispose()

    app = FastAPI(
        title="InvestTrack API",
        description="Portfolio tracker for the Brazilian stock market (B3).",
        version="0.2.2",
        lifespan=lifespan,
    )

    @app.get("/health", tags=["meta"])
    def health(session: SessionDep) -> dict[str, str]:
        session.execute(text("SELECT 1"))  # fails if the database is unreachable
        return {"status": "ok"}

    @app.post(
        "/operations",
        status_code=status.HTTP_201_CREATED,
        tags=["operations"],
        responses={
            422: {"model": ErrorOut, "description": "Invalid data, or selling more than owned"}
        },
    )
    def create_operation(
        payload: OperationCreate, session: SessionDep, events: EventsDep
    ) -> OperationOut:
        try:
            op = Operation(
                ticker=payload.ticker,
                op_type=payload.op_type,
                date=payload.date,
                quantity=payload.quantity,
                price=payload.price,
                fees=payload.fees,
            )
            record = repository.add_operation(session, op, payload.asset_type, events)
        except InsufficientPositionError as e:
            raise api_error(422, "INSUFFICIENT_POSITION", e) from e
        except ValueError as e:  # domain validation, e.g. a blank ticker
            raise api_error(422, "INVALID_OPERATION", e) from e
        return to_out(record)

    @app.get("/operations", tags=["operations"])
    def list_operations(
        session: SessionDep,
        ticker: Annotated[str | None, Query(description="Filter by ticker")] = None,
    ) -> list[OperationOut]:
        return [to_out(r) for r in repository.list_operations(session, ticker)]

    @app.delete(
        "/operations/{operation_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["operations"],
        responses={
            404: {"model": ErrorOut, "description": "Operation not found"},
            409: {
                "model": ErrorOut,
                "description": "Would leave a later sale, or income, without shares",
            },
        },
    )
    def delete_operation(operation_id: int, session: SessionDep, events: EventsDep) -> None:
        try:
            repository.delete_operation(session, operation_id, events)
        except repository.OperationNotFoundError as e:
            raise api_error(404, "OPERATION_NOT_FOUND", e) from e
        except InsufficientPositionError as e:
            raise api_error(409, "DELETE_BREAKS_LATER_SALE", e) from e
        except IncomeWithoutPositionError as e:
            raise api_error(409, "DELETE_ORPHANS_INCOME", e) from e

    @app.get("/stock-events", tags=["operations"])
    def list_stock_events(session: SessionDep, events: EventsDep) -> list[StockEventOut]:
        """Splits, reverse splits and bonus shares that changed one of your positions."""
        costs = repository.bonus_costs(session)
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
            for a in repository.get_applied_stock_events(session, events)
        ]

    @app.put(
        "/stock-events/{ticker}/{record_date}/unit-cost",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["operations"],
        responses={404: {"model": ErrorOut, "description": "No bonus event on that date"}},
    )
    def set_bonus_cost(
        ticker: str, record_date: date, payload: BonusCostIn, session: SessionDep, events: EventsDep
    ) -> None:
        """Attributed cost (custo atribuído) of bonus shares, from the company's notice."""
        try:
            repository.set_bonus_cost(session, ticker, record_date, payload.unit_cost, events)
        except repository.StockEventNotFoundError as e:
            raise api_error(404, "STOCK_EVENT_NOT_FOUND", e) from e

    @app.delete(
        "/stock-events/{ticker}/{record_date}/unit-cost",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["operations"],
    )
    def delete_bonus_cost(ticker: str, record_date: date, session: SessionDep) -> None:
        """Back to zero cost."""
        repository.delete_bonus_cost(session, ticker, record_date)

    @app.post(
        "/income",
        status_code=status.HTTP_201_CREATED,
        tags=["income"],
        responses={
            422: {"model": ErrorOut, "description": "Invalid data, or ticker not bought by then"}
        },
    )
    def create_income(payload: IncomeCreate, session: SessionDep) -> IncomeOut:
        try:
            income = Income(
                ticker=payload.ticker,
                income_type=payload.income_type,
                date=payload.date,
                amount=payload.amount,
                tax=payload.tax,
            )
            record = repository.add_income(session, income)
        except IncomeWithoutPositionError as e:  # before ValueError: it is a subclass
            raise api_error(422, "INCOME_WITHOUT_POSITION", e) from e
        except ValueError as e:
            raise api_error(422, "INVALID_INCOME", e) from e
        return income_to_out(record.id, repository.income_to_domain(record))

    @app.get("/income", tags=["income"])
    def list_income(
        session: SessionDep,
        events: EventsDep,
        ticker: Annotated[str | None, Query(description="Filter by ticker")] = None,
        year: Annotated[int | None, Query(description="Filter by payment year")] = None,
    ) -> list[IncomeOut]:
        """Computed income from B3 events plus manual entries, including pending ones."""
        ticker = ticker.strip().upper() if ticker else None
        return [
            income_to_out(income_id, income)
            for income_id, income in all_incomes(session, events)
            if (ticker is None or income.ticker == ticker)
            and (year is None or income.date.year == year)
        ]

    @app.get("/income/monthly", tags=["income"])
    def income_per_month(
        session: SessionDep,
        events: EventsDep,
        year: Annotated[int | None, Query(description="Only this year")] = None,
    ) -> list[MonthlyIncomeOut]:
        """Income already received, per month. Pending income is not included."""
        incomes = [i for i in received(all_incomes(session, events)) if year in (None, i.date.year)]
        return [MonthlyIncomeOut(**vars(m)) for m in monthly_income(incomes)]

    @app.delete(
        "/income/{income_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["income"],
        responses={404: {"model": ErrorOut, "description": "Income not found"}},
    )
    def delete_income(income_id: int, session: SessionDep) -> None:
        try:
            repository.delete_income(session, income_id)
        except repository.IncomeNotFoundError as e:
            raise api_error(404, "INCOME_NOT_FOUND", e) from e

    @app.get("/portfolio", tags=["portfolio"])
    def get_portfolio(session: SessionDep, prices: PricesDep, events: EventsDep) -> PortfolioOut:
        positions: list[PositionOut] = []
        total_invested = Decimal("0")
        total_value: Decimal | None = Decimal("0")
        total_realized = Decimal("0")
        incomes = all_incomes(session, events)
        income = net_income_by_ticker(received(incomes))
        pending = sum((i.net for _, i in incomes if i.date > date.today()), Decimal("0"))

        for pos in repository.get_portfolio(session, events).values():
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

        total_result = None if total_value is None else total_value - total_invested
        total_pct = (
            total_result / total_invested * 100
            if total_result is not None and total_invested
            else None
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
            ),
        )

    return app


app = create_app()
