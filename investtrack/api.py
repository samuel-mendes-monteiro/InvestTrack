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
from pathlib import Path
from typing import Annotated

from argon2 import PasswordHasher
from dotenv import load_dotenv
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi import Path as PathParam
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from investtrack import repository
from investtrack.auth import (
    Auth,
    EmailTakenError,
    InvalidCredentialsError,
    InvalidEmailError,
    TooManyAttemptsError,
    WeakPasswordError,
    as_utc,
)
from investtrack.b3 import B3Client
from investtrack.b3_statement import MAX_FILE_SIZE, StatementError, read_statement
from investtrack.brapi import BrapiClient
from investtrack.db import create_db_engine, init_db
from investtrack.events import EventSource, StoredEvents
from investtrack.fixed_income import (
    FixedIncome,
    PartialRedemption,
    RedemptionTooLargeError,
    daily_net_values,
    daily_series,
    is_estimated,
    money_in,
    partial_valuations,
    value_on,
)
from investtrack.income import (
    Income,
    IncomeWithoutPositionError,
    monthly_income,
    net_income_by_ticker,
)
from investtrack.market_data import CDI, IBOV, IPCA, IPCA_SINCE, MarketData, MarketDataSource
from investtrack.models import OperationRecord, User
from investtrack.performance import (
    Period,
    cdi_accumulated,
    index_return,
    operation_flow,
    portfolio_history,
    rebase,
    window_base,
)
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
    PartialRedemptionIn,
    PartialRedemptionOut,
    PasswordChange,
    PerformanceOut,
    PerformancePoint,
    PortfolioOut,
    PortfolioTotals,
    PositionOut,
    PriceOut,
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


# The session travels in a cookie the page's JavaScript can't read
# (HttpOnly), so an injected script can't steal it. SameSite=Strict keeps the
# browser from sending it on requests started by another site, which is
# what a CSRF attack needs; the app and the API share an origin, so it never
# needs to cross sites.
SESSION_COOKIE = "investtrack_session"


def user_out(user: User) -> UserOut:
    # SQLite drops the timezone; the API always answers in UTC.
    return UserOut(id=user.id, email=user.email, created_at=as_utc(user.created_at))


def session_token(request: Request) -> str | None:
    return request.cookies.get(SESSION_COOKIE) or None


def get_current_user(request: Request, session: Annotated[Session, Depends(get_session)]) -> User:
    """The logged-in user, from the session cookie.

    Every endpoint with user data depends on this, so a request without a
    valid session never reaches it.
    """
    token = session_token(request)
    user = request.app.state.auth.user_for_token(session, token) if token else None
    if user is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            {"code": "NOT_AUTHENTICATED", "message": "missing, invalid or expired session"},
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


def fixed_income_to_out(
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


def received(incomes: list[tuple[int | None, Income]]) -> list[Income]:
    today = date.today()
    return [i for _, i in incomes if i.date <= today]


# --- app factory -------------------------------------------------------------


def serve_web(app: FastAPI, web_dir: Path) -> None:
    """Serve the built web app, with index.html for every other path.

    The app routes in the browser (/proventos, /renda-fixa...), so reloading
    one of those pages asks the server for a path that is not a file: it
    must get index.html, and the React router takes it from there.
    """
    root = web_dir.resolve()
    index = root / "index.html"
    forever = {"Cache-Control": "public, max-age=31536000, immutable"}

    @app.get("/{path:path}", include_in_schema=False)
    def web(path: str):
        if path == "api" or path.startswith("api/"):  # an API typo is a 404, not the app
            return JSONResponse({"detail": "Not Found"}, status.HTTP_404_NOT_FOUND)
        file = (root / path).resolve()
        if path and file.is_file() and file.is_relative_to(root):  # no ../ escapes
            # Vite puts a hash of the content in every name under assets/, so
            # they can be cached forever: a new build has new names.
            if path.startswith("assets/"):
                return FileResponse(file, headers=forever)
            return FileResponse(file)
        # index.html names the current assets, so it must always be fresh.
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


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
    web_dir: Path | None = None,
) -> FastAPI:
    """Build the app. Tests pass their own engine, prices, events, history
    and a cheap password hasher.

    `web_dir` (or the WEB_DIST environment variable) is the built React app
    (web/dist): served from the same origin as the API, so the browser needs
    no CORS and the session cookie can be SameSite=Strict. In development it
    is left out and Vite serves the app instead.
    """

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
        version="1.0.0",
        lifespan=lifespan,
        # Everything the API answers lives under /api; the rest of the URL
        # space belongs to the web app (see serve_web below).
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    api = APIRouter(prefix="/api")

    @api.get("/health", tags=["meta"])
    def health(session: SessionDep) -> dict[str, str]:
        session.execute(text("SELECT 1"))  # fails if the database is unreachable
        return {"status": "ok"}

    @api.post(
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
        return user_out(user)

    @api.post(
        "/auth/login",
        tags=["auth"],
        responses={
            401: {"model": ErrorOut, "description": "Wrong email or password"},
            429: {"model": ErrorOut, "description": "Too many failed attempts"},
        },
    )
    def login(
        payload: Credentials, session: SessionDep, request: Request, response: Response
    ) -> SessionOut:
        # Behind a reverse proxy this is the proxy's address, unless uvicorn
        # runs with --proxy-headers (it then trusts X-Forwarded-For).
        ip = request.client.host if request.client else ""
        try:
            token, expires = request.app.state.auth.login(
                session, payload.email, payload.password, ip
            )
        except InvalidCredentialsError as e:
            raise api_error(401, "INVALID_CREDENTIALS", e) from e
        except TooManyAttemptsError as e:
            error = api_error(429, "TOO_MANY_ATTEMPTS", e)
            error.detail["retry_after"] = e.retry_after
            error.headers = {"Retry-After": str(e.retry_after)}  # the standard header
            raise error from e
        response.set_cookie(
            SESSION_COOKIE,
            token,
            expires=expires,
            httponly=True,
            samesite="strict",
            # Only over HTTPS when the site is on HTTPS (always, deployed);
            # plain http://localhost in development would otherwise drop it.
            secure=request.url.scheme == "https",
            path="/api",  # only the API needs it, not every asset request
        )
        return SessionOut(expires_at=expires)

    @api.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT, tags=["auth"])
    def logout(session: SessionDep, user: UserDep, request: Request, response: Response) -> None:
        request.app.state.auth.logout(session, session_token(request))
        response.delete_cookie(SESSION_COOKIE, path="/api", httponly=True, samesite="strict")

    @api.get("/auth/me", tags=["auth"])
    def me(user: UserDep) -> UserOut:
        return user_out(user)

    @api.post(
        "/auth/password",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["auth"],
        responses={
            # 403, not 401: a 401 means "no session", and the app would log out.
            403: {"model": ErrorOut, "description": "Wrong current password"},
            422: {"model": ErrorOut, "description": "Weak new password"},
            429: {"model": ErrorOut, "description": "Too many failed attempts"},
        },
    )
    def change_password(
        payload: PasswordChange, session: SessionDep, user: UserDep, request: Request
    ) -> None:
        """Change the password. Every other session of this account is ended."""
        ip = request.client.host if request.client else ""
        try:
            request.app.state.auth.change_password(
                session,
                user,
                session_token(request),
                payload.current_password,
                payload.new_password,
                ip,
            )
        except InvalidCredentialsError as e:
            raise api_error(403, "WRONG_PASSWORD", e) from e
        except WeakPasswordError as e:
            raise api_error(422, "WEAK_PASSWORD", e) from e
        except TooManyAttemptsError as e:
            error = api_error(429, "TOO_MANY_ATTEMPTS", e)
            error.detail["retry_after"] = e.retry_after
            error.headers = {"Retry-After": str(e.retry_after)}
            raise error from e

    @api.post(
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

    @api.get("/operations", tags=["operations"])
    def list_operations(
        session: SessionDep,
        user: UserDep,
        ticker: Annotated[str | None, Query(description="Filter by ticker")] = None,
    ) -> list[OperationOut]:
        return [to_out(r) for r in repository.list_operations(session, user.id, ticker)]

    @api.delete(
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

    @api.put(
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

    @api.get("/stock-events", tags=["operations"])
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

    @api.put(
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

    @api.delete(
        "/stock-events/{ticker}/{record_date}/unit-cost",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["operations"],
    )
    def delete_bonus_cost(
        ticker: str, record_date: date, session: SessionDep, user: UserDep
    ) -> None:
        """Back to zero cost."""
        repository.delete_bonus_cost(session, user.id, ticker, record_date)

    @api.post(
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

    @api.get("/income", tags=["income"])
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

    @api.get("/income/monthly", tags=["income"])
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

    @api.delete(
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

    @api.get(
        "/prices/{ticker}",
        tags=["portfolio"],
        responses={404: {"model": ErrorOut, "description": "No price known for that day"}},
    )
    def price_on(
        ticker: Annotated[str, PathParam(pattern=r"^[A-Za-z0-9]{4,12}$")],
        user: UserDep,
        prices: PricesDep,
        market: MarketDep,
        day: Annotated[date | None, Query(alias="date")] = None,
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

    @api.get("/portfolio", tags=["portfolio"])
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
        syncing = unknown or (start is not None and (market.syncing or not market.is_synced(start)))

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
                fixed_income=fixed_income,
            ),
            syncing=syncing,
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
        days, cdi, ipca = business_days(market, start)
        return [
            fixed_income_to_out(r, repository.fixed_income_to_domain(r), days, cdi, ipca)
            for r in records
        ]

    @api.post(
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
        days, cdi, ipca = business_days(market, investment.start)
        return fixed_income_to_out(record, investment, days, cdi, ipca)

    @api.get("/fixed-income", tags=["fixed income"])
    def get_fixed_income(
        session: SessionDep, user: UserDep, market: MarketDep, background: BackgroundTasks
    ) -> list[FixedIncomeOut]:
        """Each investment valued at its last day (today, redemption or maturity)."""
        return list_fixed_income(session, user.id, market, background)

    @api.put(
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
        days, cdi, ipca = business_days(market, record.start)
        return fixed_income_to_out(
            record, repository.fixed_income_to_domain(record), days, cdi, ipca
        )

    @api.post(
        "/fixed-income/{investment_id}/partial-redemptions",
        status_code=status.HTTP_201_CREATED,
        tags=["fixed income"],
        responses={
            404: {"model": ErrorOut, "description": "Not found"},
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
            error = api_error(422, "REDEMPTION_TOO_LARGE", e)
            error.detail |= {"date": e.day.isoformat(), "available": str(e.available)}
            raise error from e
        except repository.ValueNotKnownError as e:
            raise api_error(422, "VALUE_NOT_KNOWN", e) from e
        except ValueError as e:
            raise api_error(422, "INVALID_PARTIAL_REDEMPTION", e) from e
        return fixed_income_to_out(
            record, repository.fixed_income_to_domain(record), days, cdi, ipca
        )

    @api.delete(
        "/fixed-income/{investment_id}/partial-redemptions/{redemption_id}",
        tags=["fixed income"],
        responses={404: {"model": ErrorOut, "description": "Not found"}},
    )
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
        days, cdi, ipca = business_days(market, record.start)
        return fixed_income_to_out(
            record, repository.fixed_income_to_domain(record), days, cdi, ipca
        )

    @api.delete(
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

    @api.post(
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

    @api.post("/imports/b3", tags=["import"], openapi_extra=statement_body, responses=import_errors)
    def import_b3(
        user: UserDep, data: StatementDep, session: SessionDep, events: EventsDep
    ) -> ImportOut:
        """Add the statement's new trades, all in one transaction.

        Duplicates are left out and rejected tickers are not imported. The
        file is sent again instead of reusing the preview: the server keeps
        no state between the two calls.
        """
        return statement_result(session, user, events, data, save=True)

    @api.get("/performance", tags=["portfolio"])
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
            h.date: price_only[h.date]
            if base is None
            else rebase(price_only[h.date], price_only[base])
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

    app.include_router(api)  # after the routes exist: including copies them
    web_dir = web_dir or (Path(os.environ["WEB_DIST"]) if os.getenv("WEB_DIST") else None)
    if web_dir is not None:
        serve_web(app, web_dir)
    return app


app = create_app()
