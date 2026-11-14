"""HTTP layer (FastAPI).

Endpoints are thin: they convert JSON to domain objects, call the
repository, and translate domain errors into HTTP status codes.

Run with:  uvicorn investtrack.api:app --reload
"""

import logging
import os
from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import timedelta
from decimal import Decimal
from typing import Annotated

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from investtrack import repository
from investtrack.brapi import BrapiClient
from investtrack.db import create_db_engine, init_db
from investtrack.models import OperationRecord
from investtrack.portfolio import InsufficientPositionError, Operation, value_position
from investtrack.prices import CachedPriceProvider, PriceProvider
from investtrack.schemas import (
    ErrorOut,
    OperationCreate,
    OperationOut,
    PortfolioOut,
    PortfolioTotals,
    PositionOut,
)

# --- dependencies ------------------------------------------------------------


def get_session(request: Request) -> Iterator[Session]:
    """One database session per request, always closed at the end."""
    with Session(request.app.state.engine) as session:
        yield session


def get_price_provider(request: Request) -> PriceProvider:
    return request.app.state.price_provider


SessionDep = Annotated[Session, Depends(get_session)]
PricesDep = Annotated[PriceProvider, Depends(get_price_provider)]


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
) -> FastAPI:
    """Build the app. Tests pass their own engine and price provider."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        load_dotenv()  # reads .env into environment variables (never committed)
        logging.basicConfig(level=logging.INFO)
        app.state.engine = engine or create_db_engine()
        app.state.price_provider = price_provider or default_price_provider(app.state.engine)
        init_db(app.state.engine)
        yield
        app.state.engine.dispose()

    app = FastAPI(
        title="InvestTrack API",
        description="Portfolio tracker for the Brazilian stock market (B3).",
        version="0.1.0",
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
        responses={422: {"description": "Invalid data, or selling more than owned"}},
    )
    def create_operation(payload: OperationCreate, session: SessionDep) -> OperationOut:
        try:
            op = Operation(
                ticker=payload.ticker,
                op_type=payload.op_type,
                date=payload.date,
                quantity=payload.quantity,
                price=payload.price,
                fees=payload.fees,
            )
            record = repository.add_operation(session, op, payload.asset_type)
        except InsufficientPositionError as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e))
        except ValueError as e:  # domain validation, e.g. a blank ticker
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e))
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
            409: {"model": ErrorOut, "description": "Would leave a later sale invalid"},
        },
    )
    def delete_operation(operation_id: int, session: SessionDep) -> None:
        try:
            repository.delete_operation(session, operation_id)
        except repository.OperationNotFoundError as e:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
        except InsufficientPositionError as e:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Deleting this operation would break a later sale: {e}",
            )

    @app.get("/portfolio", tags=["portfolio"])
    def get_portfolio(session: SessionDep, prices: PricesDep) -> PortfolioOut:
        positions: list[PositionOut] = []
        total_invested = Decimal("0")
        total_value: Decimal | None = Decimal("0")
        total_realized = Decimal("0")

        for pos in repository.get_portfolio(session).values():
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

            positions.append(PositionOut(
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
            ))

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
            ),
        )

    return app


app = create_app()
