"""Where corporate events come from: income and stock events (splits, bonus).

The API depends on the EventSource interface, not on B3 directly:
- StaticEvents: fixed lists (tests, offline demos)
- StoredEvents: events from B3, kept in the database

Same idea as prices.py, with two differences:
- Events are refreshed once a day, not every 15 minutes: they are announced
  days or weeks ahead, so there is nothing to gain from fetching more often.
- Events are never thrown away. B3 shows only about 12 months of income
  history, so each sync replaces the window B3 returned and keeps
  everything older.
"""

import logging
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from investtrack.b3 import EventsUnavailableError, SourceDownError
from investtrack.income import IncomeEvent, TickerEvents
from investtrack.models import AssetType, EventSync, IncomeEventRecord, StockEventRecord
from investtrack.portfolio import StockEvent

log = logging.getLogger(__name__)

FUND_TYPES = {AssetType.FII, AssetType.ETF}


class EventSource(Protocol):
    def events_for(self, ticker: str, asset_type: AssetType) -> TickerEvents: ...


class StaticEvents:
    """Returns events from fixed lists."""

    def __init__(self, income: Iterable[IncomeEvent] = (), stock: Iterable[StockEvent] = ()):
        self._income = list(income)
        self._stock = list(stock)

    def events_for(self, ticker: str, asset_type: AssetType) -> TickerEvents:
        ticker = ticker.upper()
        return TickerEvents(
            [e for e in self._income if e.ticker == ticker],
            [e for e in self._stock if e.ticker == ticker],
        )


NO_EVENTS = StaticEvents()


def _utc_now() -> datetime:
    return datetime.now(UTC)


class StoredEvents:
    """B3 events stored in the database, refreshed at most once per `ttl`.

    If B3 fails, the stored events are used: an outage only delays new
    announcements, it never hides events already known.
    """

    def __init__(
        self,
        engine: Engine,
        fetch_events: Callable[[str, bool], TickerEvents],
        ttl: timedelta = timedelta(hours=24),
        retry_after: timedelta = timedelta(minutes=5),
        clock: Callable[[], datetime] = _utc_now,
    ):
        self._engine = engine
        self._fetch_events = fetch_events
        self._ttl = ttl
        self._retry_after = retry_after
        self._clock = clock
        self._source_down_until: datetime | None = None

    def events_for(self, ticker: str, asset_type: AssetType) -> TickerEvents:
        ticker = ticker.upper()
        if asset_type is AssetType.BDR:
            return TickerEvents([], [])  # not published by B3: use manual entries

        with Session(self._engine) as session:
            if self._needs_sync(session, ticker):
                self._sync(session, ticker, asset_type in FUND_TYPES)
            income = session.scalars(
                select(IncomeEventRecord)
                .where(IncomeEventRecord.ticker == ticker)
                .order_by(IncomeEventRecord.record_date, IncomeEventRecord.id)
            )
            stock = session.scalars(
                select(StockEventRecord)
                .where(StockEventRecord.ticker == ticker)
                .order_by(StockEventRecord.record_date, StockEventRecord.id)
            )
            return TickerEvents(
                [
                    IncomeEvent(r.ticker, r.income_type, r.record_date, r.payment_date, r.rate)
                    for r in income
                ],
                [
                    StockEvent(r.ticker, r.event_type, r.record_date, r.multiplier, r.unit_cost)
                    for r in stock
                ],
            )

    def _needs_sync(self, session: Session, ticker: str) -> bool:
        now = self._clock()
        if self._source_down_until is not None and now < self._source_down_until:
            return False
        sync = session.get(EventSync, ticker)
        return sync is None or now - _as_utc(sync.synced_at) >= self._ttl

    def _sync(self, session: Session, ticker: str, is_fund: bool) -> None:
        now = self._clock()
        try:
            fresh = self._fetch_events(ticker, is_fund)
        except SourceDownError as e:
            log.warning("B3 unavailable, using stored events: %s", e)
            self._source_down_until = now + self._retry_after
            return  # not marked as synced: it is retried after retry_after
        except EventsUnavailableError as e:
            # Probably a format change: retried tomorrow, not on every request.
            log.warning("Could not read B3 events, using stored events: %s", e)
            fresh = TickerEvents([], [])

        _replace_window(
            session,
            IncomeEventRecord,
            ticker,
            [
                IncomeEventRecord(
                    ticker=ticker,
                    income_type=e.income_type,
                    record_date=e.record_date,
                    payment_date=e.payment_date,
                    rate=e.rate,
                )
                for e in fresh.income
            ],
        )
        _replace_window(
            session,
            StockEventRecord,
            ticker,
            [
                StockEventRecord(
                    ticker=ticker,
                    event_type=e.event_type,
                    record_date=e.record_date,
                    multiplier=e.multiplier,
                    unit_cost=e.unit_cost,
                )
                for e in fresh.stock
            ],
        )
        session.merge(EventSync(ticker=ticker, synced_at=now))
        session.commit()


def _replace_window(session: Session, model, ticker: str, fresh: list) -> None:
    """Replace stored rows from the oldest fresh record date onward.

    Corrections and cancellations inside the window B3 returned are applied;
    older history is kept. An empty answer changes nothing.
    """
    if not fresh:
        return
    oldest = min(r.record_date for r in fresh)
    session.execute(delete(model).where(model.ticker == ticker, model.record_date >= oldest))
    session.add_all(fresh)


def _as_utc(value: datetime) -> datetime:
    """SQLite drops the timezone when storing datetimes; put UTC back."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)
