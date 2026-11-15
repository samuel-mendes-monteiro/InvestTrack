"""Where market prices come from.

The API depends on the PriceProvider interface, not on a concrete source:
- StaticPriceProvider: fixed prices (tests, offline demos)
- CachedPriceProvider: real quotes with a database cache and fallback
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Protocol

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from investtrack.sources.brapi import QuoteUnavailableError, SourceDownError
from investtrack.storage.models import PriceCache

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Quote:
    price: Decimal
    as_of: datetime | None  # when the price was fetched (None for fixed prices)
    stale: bool = False  # True when the source failed and an old price is used


class PriceProvider(Protocol):
    def get_quote(self, ticker: str) -> Quote | None:
        """Current quote, or None if no price is known at all."""
        ...


class StaticPriceProvider:
    """Returns prices from a fixed table."""

    def __init__(self, prices: dict[str, Decimal]):
        self._prices = {t.upper(): p for t, p in prices.items()}

    def get_quote(self, ticker: str) -> Quote | None:
        price = self._prices.get(ticker.upper())
        return None if price is None else Quote(price, as_of=None)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class CachedPriceProvider:
    """Real quotes with a cache in the price_cache table.

    - A cached price younger than `ttl` is used without calling the API.
    - Otherwise the price is fetched and the cache updated.
    - If fetching fails, the last known price is returned marked as stale.
    - If brapi itself is down (SourceDownError), it is not called again for
      `retry_after`, so a portfolio with many tickers does not wait for one
      timeout per ticker. A per-ticker error (e.g. 404) does not pause others.

    The cache lives in the database, so it survives server restarts.
    """

    def __init__(
        self,
        engine: Engine,
        fetch_price: Callable[[str], Decimal],
        ttl: timedelta = timedelta(minutes=15),
        retry_after: timedelta = timedelta(minutes=1),
        clock: Callable[[], datetime] = _utc_now,
    ):
        self._engine = engine
        self._fetch_price = fetch_price
        self._ttl = ttl
        self._retry_after = retry_after
        self._clock = clock  # injectable, so tests can control time
        self._source_down_until: datetime | None = None

    def get_quote(self, ticker: str) -> Quote | None:
        ticker = ticker.upper()
        now = self._clock()

        with Session(self._engine) as session:
            cached = session.get(PriceCache, ticker)
            cached_at = _as_utc(cached.fetched_at) if cached else None

            if cached and now - cached_at < self._ttl:
                return Quote(cached.price, cached_at)

            if not self._source_is_down(now):
                try:
                    price = self._fetch_price(ticker)
                except QuoteUnavailableError as e:
                    log.warning("Quote unavailable, using cache if any: %s", e)
                    if isinstance(e, SourceDownError):  # only outages pause all tickers
                        self._source_down_until = now + self._retry_after
                else:
                    if cached:
                        cached.price, cached.fetched_at = price, now
                    else:
                        session.add(PriceCache(ticker=ticker, price=price, fetched_at=now))
                    session.commit()
                    return Quote(price, now)

            if cached:
                return Quote(cached.price, cached_at, stale=True)
            return None

    def _source_is_down(self, now: datetime) -> bool:
        return self._source_down_until is not None and now < self._source_down_until


def _as_utc(value: datetime) -> datetime:
    """SQLite drops the timezone when storing datetimes; put UTC back."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)
