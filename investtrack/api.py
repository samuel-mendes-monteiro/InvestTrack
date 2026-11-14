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

from argon2 import PasswordHasher
from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request, status
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from investtrack import repository
from investtrack.auth import (
    Auth,
    EmailTakenError,
    InvalidCredentialsError,
    InvalidEmailError,
    WeakPasswordError,
)
from investtrack.b3 import B3Client
from investtrack.b3_statement import MAX_FILE_SIZE, StatementError, read_statement
from investtrack.brapi import BrapiClient
from investtrack.db import create_db_engine, init_db
from investtrack.events import EventSource, StoredEvents
from investtrack.fixed_income import FixedIncome, daily_series, value_on
from investtrack.income import (
    Income,
    IncomeWithoutPositionError,
    monthly_income,
    net_income_by_ticker,
)
from investtrack.market_data import CDI, IBOV, MarketData, MarketDataSource
from investtrack.models import OperationRecord, User
from investtrack.performance import cdi_accumulated, index_return, portfolio_history
from investtrack.portfolio import InsufficientPositionError, Operation, value_position
from investtrack.prices import CachedPriceProvider, PriceProvider
from investtrack.schemas import (
    BonusCostIn,
    Credentials,
    ErrorOut,
    FixedIncomeCreate,
    FixedIncomeOut,
    ImportOut,
    ImportRowOut,
    IncomeCreate,
    IncomeOut,
    MonthlyIncomeOut,
    OperationCreate,
    OperationOut,
    PerformanceOut,
    PerformancePoint,
    PortfolioOut,
    PortfolioTotals,
    PositionOut,
    RedeemIn,
    SessionOut,
    SkippedRowOut,
    StockEventOut,
    UserOut,
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


def get_market_data(request: Request) -> MarketDataSource:
    return request.app.state.market_data


def bearer_token(request: Request) -> str | None:
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer":
        return None
    return token.strip() or None


def get_current_user(request: Request, session: Annotated[Session, Depends(get_session)]) -> User:
    """The logged-in user, from the "Authorization: Bearer <token>" header.

    Every endpoint with user data depends on this, so a request without a
    valid session never reaches it.
    """
    token = bearer_token(request)
    user = request.app.state.auth.user_for_token(session, token) if token else None
    if user is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            {"code": "NOT_AUTHENTICATED", "message": "missing, invalid or expired session"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


async def statement_file(request: Request) -> bytes:
    """The uploaded file, sent as the raw request body.

    Too large a file is refused from the Content-Length header, before
    reading it: a huge upload costs nothing to refuse.
    """
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_FILE_SIZE:
        raise HTTPException(413, {"code": "FILE_TOO_LARGE", "message": "file too large"})
    data = await request.body()
    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(413, {"code": "FILE_TOO_LARGE", "message": "file too large"})
    return data


SessionDep = Annotated[Session, Depends(get_session)]
StatementDep = Annotated[bytes, Depends(statement_file)]
UserDep = Annotated[User, Depends(get_current_user)]
MarketDep = Annotated[MarketDataSource, Depends(get_market_data)]
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


def all_incomes(
    session: Session, user_id: int, events: EventSource
) -> list[tuple[int | None, Income]]:
    """Manual entries (with their id) and computed income, by payment date."""
    manual = [
        (r.id, repository.income_to_domain(r)) for r in repository.list_incomes(session, user_id)
    ]
    computed = [(None, i) for i in repository.computed_incomes(session, user_id, events)]
    return sorted(manual + computed, key=lambda pair: (pair[1].date, pair[1].ticker))


def business_days(market: MarketDataSource, start: date) -> tuple[list[date], dict]:
    """Business days until the last close, and the CDI rates since `start`.

    The CDI has a rate only on business days, but is published a day late;
    the Ibovespa adds the last trading day, whose value needs only the rates
    of the days before it.
    """
    cdi = market.series(CDI, start)
    ibov = market.series(IBOV, start)
    days = sorted(d for d in set(cdi) | set(ibov) if d <= market.last_day())
    return days, cdi


def fixed_income_to_out(
    record, investment: FixedIncome, days: list[date], cdi: dict
) -> FixedIncomeOut:
    last_day = days[-1] if days else None
    if investment.redeemed_on:
        status = "REDEEMED"
    elif last_day is not None and investment.maturity <= last_day:
        status = "MATURED"
    else:
        status = "ACTIVE"
    valuation = value_on(investment, investment.end, days, cdi) if days else None
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
        status=status,
        as_of=valuation.day if valuation else None,
        gross=valuation.gross if valuation else None,
        iof=valuation.iof if valuation else None,
        ir=valuation.ir if valuation else None,
        net=valuation.net if valuation else None,
        gross_return=(valuation.gross / investment.amount - 1) * 100 if valuation else None,
    )


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
    market_data: MarketDataSource | None = None,
    password_hasher: PasswordHasher | None = None,
) -> FastAPI:
    """Build the app. Tests pass their own engine, prices, events, history
    and a cheap password hasher."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        load_dotenv()  # reads .env into environment variables (never committed)
        logging.basicConfig(level=logging.INFO)
        app.state.engine = engine or create_db_engine()
        app.state.price_provider = price_provider or default_price_provider(app.state.engine)
        app.state.events = events or StoredEvents(app.state.engine, B3Client().fetch_events)
        app.state.market_data = market_data or MarketData(app.state.engine)
        app.state.auth = Auth(hasher=password_hasher)
        init_db(app.state.engine)
        yield
        if engine is None:  # only close what this app created: a given engine may be shared
            app.state.engine.dispose()

    app = FastAPI(
        title="InvestTrack API",
        description="Portfolio tracker for the Brazilian stock market (B3).",
        version="0.6.0",
        lifespan=lifespan,
    )

    @app.get("/health", tags=["meta"])
    def health(session: SessionDep) -> dict[str, str]:
        session.execute(text("SELECT 1"))  # fails if the database is unreachable
        return {"status": "ok"}

    @app.post(
        "/auth/register",
        status_code=status.HTTP_201_CREATED,
        tags=["auth"],
        responses={
            409: {"model": ErrorOut, "description": "Email already registered"},
            422: {"model": ErrorOut, "description": "Invalid email or weak password"},
        },
    )
    def register(payload: Credentials, session: SessionDep, request: Request) -> UserOut:
        """Create an account. The first account adopts data from before v0.5."""
        try:
            user = request.app.state.auth.register(session, payload.email, payload.password)
        except EmailTakenError as e:
            raise api_error(409, "EMAIL_TAKEN", e) from e
        except InvalidEmailError as e:
            raise api_error(422, "INVALID_EMAIL", e) from e
        except WeakPasswordError as e:
            raise api_error(422, "WEAK_PASSWORD", e) from e
        return UserOut(id=user.id, email=user.email)

    @app.post(
        "/auth/login",
        tags=["auth"],
        responses={401: {"model": ErrorOut, "description": "Wrong email or password"}},
    )
    def login(payload: Credentials, session: SessionDep, request: Request) -> SessionOut:
        try:
            token, expires = request.app.state.auth.login(session, payload.email, payload.password)
        except InvalidCredentialsError as e:
            raise api_error(401, "INVALID_CREDENTIALS", e) from e
        return SessionOut(token=token, expires_at=expires)

    @app.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT, tags=["auth"])
    def logout(session: SessionDep, user: UserDep, request: Request) -> None:
        request.app.state.auth.logout(session, bearer_token(request))

    @app.get("/auth/me", tags=["auth"])
    def me(user: UserDep) -> UserOut:
        return UserOut(id=user.id, email=user.email)

    @app.post(
        "/operations",
        status_code=status.HTTP_201_CREATED,
        tags=["operations"],
        responses={
            422: {"model": ErrorOut, "description": "Invalid data, or selling more than owned"}
        },
    )
    def create_operation(
        payload: OperationCreate, session: SessionDep, user: UserDep, events: EventsDep
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
            record = repository.add_operation(session, user.id, op, payload.asset_type, events)
        except InsufficientPositionError as e:
            raise api_error(422, "INSUFFICIENT_POSITION", e) from e
        except ValueError as e:  # domain validation, e.g. a blank ticker
            raise api_error(422, "INVALID_OPERATION", e) from e
        return to_out(record)

    @app.get("/operations", tags=["operations"])
    def list_operations(
        session: SessionDep,
        user: UserDep,
        ticker: Annotated[str | None, Query(description="Filter by ticker")] = None,
    ) -> list[OperationOut]:
        return [to_out(r) for r in repository.list_operations(session, user.id, ticker)]

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

    @app.put(
        "/operations/{operation_id}",
        tags=["operations"],
        responses={
            404: {"model": ErrorOut, "description": "Operation not found"},
            409: {
                "model": ErrorOut,
                "description": "Would leave a sale, or income, without shares",
            },
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
            op = Operation(
                ticker=payload.ticker,
                op_type=payload.op_type,
                date=payload.date,
                quantity=payload.quantity,
                price=payload.price,
                fees=payload.fees,
            )
            record = repository.update_operation(
                session, user.id, operation_id, op, payload.asset_type, events
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
        return to_out(record)

    @app.get("/stock-events", tags=["operations"])
    def list_stock_events(
        session: SessionDep, user: UserDep, events: EventsDep
    ) -> list[StockEventOut]:
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

    @app.put(
        "/stock-events/{ticker}/{record_date}/unit-cost",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["operations"],
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
            repository.set_bonus_cost(
                session, user.id, ticker, record_date, payload.unit_cost, events
            )
        except repository.StockEventNotFoundError as e:
            raise api_error(404, "STOCK_EVENT_NOT_FOUND", e) from e

    @app.delete(
        "/stock-events/{ticker}/{record_date}/unit-cost",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["operations"],
    )
    def delete_bonus_cost(
        ticker: str, record_date: date, session: SessionDep, user: UserDep
    ) -> None:
        """Back to zero cost."""
        repository.delete_bonus_cost(session, user.id, ticker, record_date)

    @app.post(
        "/income",
        status_code=status.HTTP_201_CREATED,
        tags=["income"],
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
        return income_to_out(record.id, repository.income_to_domain(record))

    @app.get("/income", tags=["income"])
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
            income_to_out(income_id, income)
            for income_id, income in all_incomes(session, user.id, events)
            if (ticker is None or income.ticker == ticker)
            and (year is None or income.date.year == year)
        ]

    @app.get("/income/monthly", tags=["income"])
    def income_per_month(
        session: SessionDep,
        user: UserDep,
        events: EventsDep,
        year: Annotated[int | None, Query(description="Only this year")] = None,
    ) -> list[MonthlyIncomeOut]:
        """Income already received, per month. Pending income is not included."""
        incomes = [
            i
            for i in received(all_incomes(session, user.id, events))
            if year in (None, i.date.year)
        ]
        return [MonthlyIncomeOut(**vars(m)) for m in monthly_income(incomes)]

    @app.delete(
        "/income/{income_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["income"],
        responses={404: {"model": ErrorOut, "description": "Income not found"}},
    )
    def delete_income(income_id: int, session: SessionDep, user: UserDep) -> None:
        try:
            repository.delete_income(session, user.id, income_id)
        except repository.IncomeNotFoundError as e:
            raise api_error(404, "INCOME_NOT_FOUND", e) from e

    @app.get("/portfolio", tags=["portfolio"])
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
                fixed_income=sum(
                    (
                        f.net
                        for f in list_fixed_income(session, user.id, market, background)
                        if f.status == "ACTIVE" and f.net is not None
                    ),
                    Decimal("0"),
                ),
            ),
        )

    def list_fixed_income(
        session: Session, user_id: int, market: MarketDataSource, background: BackgroundTasks
    ) -> list[FixedIncomeOut]:
        records = repository.list_fixed_income(session, user_id)
        if not records:
            return []
        start = min(r.start for r in records)
        if not market.syncing and not market.is_synced(start):
            background.add_task(market.sync, start)
        days, cdi = business_days(market, start)
        return [
            fixed_income_to_out(r, repository.fixed_income_to_domain(r), days, cdi) for r in records
        ]

    @app.post(
        "/fixed-income",
        status_code=status.HTTP_201_CREATED,
        tags=["fixed income"],
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
        if not market.syncing and not market.is_synced(investment.start):
            background.add_task(market.sync, investment.start)
        days, cdi = business_days(market, investment.start)
        return fixed_income_to_out(record, investment, days, cdi)

    @app.get("/fixed-income", tags=["fixed income"])
    def get_fixed_income(
        session: SessionDep, user: UserDep, market: MarketDep, background: BackgroundTasks
    ) -> list[FixedIncomeOut]:
        """Each investment valued at its last day (today, redemption or maturity)."""
        return list_fixed_income(session, user.id, market, background)

    @app.put(
        "/fixed-income/{investment_id}/redemption",
        tags=["fixed income"],
        responses={
            404: {"model": ErrorOut, "description": "Not found"},
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
        days, cdi = business_days(market, record.start)
        return fixed_income_to_out(record, repository.fixed_income_to_domain(record), days, cdi)

    @app.delete(
        "/fixed-income/{investment_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["fixed income"],
        responses={404: {"model": ErrorOut, "description": "Not found"}},
    )
    def delete_fixed_income(investment_id: int, session: SessionDep, user: UserDep) -> None:
        try:
            repository.delete_fixed_income(session, user.id, investment_id)
        except repository.FixedIncomeNotFoundError as e:
            raise api_error(404, "FIXED_INCOME_NOT_FOUND", e) from e

    def statement_result(session, user, events, data: bytes, save: bool) -> ImportOut:
        # (user comes first in the endpoints: FastAPI resolves dependencies in
        # parameter order, so an anonymous upload is refused before being read)
        try:
            rows, skipped = read_statement(data)
        except StatementError as e:
            raise api_error(422, "INVALID_STATEMENT", e) from e
        action = repository.import_statement if save else repository.plan_statement_import
        plan = action(session, user.id, rows, events)

        def out(p) -> ImportRowOut:
            status = "IMPORTED" if save and p.status == "NEW" else str(p.status)
            error = api_error(422, "INSUFFICIENT_POSITION", p.error).detail if p.error else None
            return ImportRowOut(
                line=p.row.line,
                status=status,
                date=p.row.date,
                op_type=p.row.op_type,
                ticker=p.row.ticker,
                quantity=p.row.quantity,
                price=p.row.price,
                error=error,
            )

        def count(status: str) -> int:
            return sum(1 for p in plan if p.status == status)

        return ImportOut(
            imported=save,
            new=count("NEW"),
            duplicates=count("DUPLICATE"),
            rejected=count("REJECTED"),
            skipped=len(skipped),
            rows=[out(p) for p in plan],
            skipped_rows=[
                SkippedRowOut(line=s.line, reason=s.reason, detail=s.detail) for s in skipped
            ],
        )

    statement_body = {
        "requestBody": {
            "content": {XLSX: {"schema": {"type": "string", "format": "binary"}}},
            "description": "The trade statement (Negociação) from B3's Área do Investidor",
        }
    }
    import_errors = {
        413: {"model": ErrorOut, "description": "File larger than 5 MB"},
        422: {"model": ErrorOut, "description": "Not a B3 trade statement"},
    }

    @app.post(
        "/imports/b3/preview",
        tags=["import"],
        openapi_extra=statement_body,
        responses=import_errors,
    )
    def preview_b3_import(
        user: UserDep, data: StatementDep, session: SessionDep, events: EventsDep
    ) -> ImportOut:
        """What importing the statement would add. Nothing is saved."""
        return statement_result(session, user, events, data, save=False)

    @app.post("/imports/b3", tags=["import"], openapi_extra=statement_body, responses=import_errors)
    def import_b3(
        user: UserDep, data: StatementDep, session: SessionDep, events: EventsDep
    ) -> ImportOut:
        """Add the statement's new trades, all in one transaction.

        Duplicates are left out and rejected tickers are not imported. The
        file is sent again instead of reusing the preview: the server keeps
        no state between the two calls.
        """
        return statement_result(session, user, events, data, save=True)

    @app.get("/performance", tags=["portfolio"])
    def performance(
        session: SessionDep,
        user: UserDep,
        events: EventsDep,
        market: MarketDep,
        background: BackgroundTasks,
    ) -> PerformanceOut:
        """Time-weighted return since the first trade, against CDI and Ibovespa.

        Answers right away with the history already stored. If something is
        missing, it is downloaded in the background and `syncing` is true.
        """
        operations, stock = repository.operations_and_stock_events(session, user.id, events)
        investments = [
            repository.fixed_income_to_domain(r)
            for r in repository.list_fixed_income(session, user.id)
        ]
        if not operations and not investments:
            return PerformanceOut(
                syncing=False,
                start=None,
                as_of=None,
                twr=None,
                cdi=None,
                ibovespa=None,
                pct_of_cdi=None,
                points=[],
            )
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
        fi_values, fi_flows = daily_series(investments, *business_days(market, start))
        history = portfolio_history(
            operations, days, closes, stock, incomes, other_values=fi_values, other_flows=fi_flows
        )
        if not history:
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

        first = history[0].date
        cdi_acc = cdi_accumulated(cdi, days, first) if cdi else {}
        ibov_ret = index_return(ibov, days, first)

        def pct(value: Decimal | None) -> Decimal | None:
            return None if value is None else value * 100

        points = [
            PerformancePoint(
                date=h.date,
                value=h.value,
                twr=h.twr * 100,
                cdi=pct(cdi_acc.get(h.date)),
                ibovespa=pct(ibov_ret.get(h.date)),
            )
            for h in history
        ]
        last = points[-1]
        return PerformanceOut(
            syncing=syncing,
            start=first,
            as_of=last.date,
            twr=last.twr,
            cdi=last.cdi,
            ibovespa=last.ibovespa,
            pct_of_cdi=last.twr / last.cdi * 100 if last.cdi else None,
            points=points,
        )

    return app


app = create_app()
