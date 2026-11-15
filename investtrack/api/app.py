"""The app factory: data sources on `app.state`, the routers under /api,
and the built web app on every other path."""

import logging
import os
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

from argon2 import PasswordHasher
from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI
from sqlalchemy import Engine, text

from investtrack import __version__
from investtrack.api.deps import SessionDep
from investtrack.api.routes import (
    auth,
    fixed_income,
    imports,
    income,
    operations,
    performance,
    portfolio,
)
from investtrack.api.web import serve_web
from investtrack.auth import Auth
from investtrack.sources.b3 import B3Client
from investtrack.sources.brapi import BrapiClient
from investtrack.storage.db import create_db_engine, init_db
from investtrack.storage.events import EventSource, StoredEvents
from investtrack.storage.market_data import MarketData, MarketDataSource
from investtrack.storage.prices import CachedPriceProvider, PriceProvider

# In the order they appear in the OpenAPI schema (and the generated types).
ROUTERS = [
    auth.router,
    operations.router,
    income.router,
    portfolio.router,
    fixed_income.router,
    imports.router,
    performance.router,
]


def default_price_provider(engine: Engine) -> PriceProvider:
    """Real quotes from brapi.dev, cached in the database.

    Settings come from environment variables (or the .env file):
    BRAPI_TOKEN (optional: without it only a few tickers work) and
    PRICE_CACHE_MINUTES (default 15).
    """
    client = BrapiClient(token=os.getenv("BRAPI_TOKEN") or None)
    ttl = timedelta(minutes=int(os.getenv("PRICE_CACHE_MINUTES", "15")))
    return CachedPriceProvider(engine, client.fetch_price, ttl=ttl)


def health(session: SessionDep) -> dict[str, str]:
    session.execute(text("SELECT 1"))  # fails if the database is unreachable
    return {"status": "ok"}


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
        version=__version__,
        lifespan=lifespan,
        # Everything the API answers lives under /api; the rest of the URL
        # space belongs to the web app (see serve_web).
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    api = APIRouter(prefix="/api")
    api.add_api_route("/health", health, methods=["GET"], tags=["meta"])
    for router in ROUTERS:
        api.include_router(router)
    app.include_router(api)  # after the routes exist: including copies them

    web_dir = web_dir or (Path(os.environ["WEB_DIST"]) if os.getenv("WEB_DIST") else None)
    if web_dir is not None:
        serve_web(app, web_dir)
    return app


app = create_app()
