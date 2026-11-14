"""Where income events come from.

The API depends on the IncomeEventSource interface, not on B3 directly:
- StaticIncomeEvents: a fixed list (tests, offline demos)
- StoredIncomeEvents: events from B3, kept in the database

Same idea as prices.py, with two differences:
- Events are refreshed once a day, not every 15 minutes: they are announced
  days or weeks ahead, so there is nothing to gain from fetching more often.
- Events are never thrown away. B3 shows only about 12 months of history,
  so each sync replaces the window B3 returned and keeps everything older.
"""

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from investtrack.b3 import EventsUnavailableError, SourceDownError
from investtrack.income import IncomeEvent
from investtrack.models import AssetType, IncomeEventRecord, IncomeEventSync

log = logging.getLogger(__name__)

FUND_TYPES = {AssetType.FII, AssetType.ETF}


class IncomeEventSource(Protocol):
    def events_for(self, ticker: str, asset_type: AssetType) -> list[IncomeEvent]: ...


class StaticIncomeEvents:
    """Returns events from a fixed list."""

    def __init__(self, events: list[IncomeEvent] = ()):
        self._events = list(events)

    def events_for(self, ticker: str, asset_type: AssetType) -> list[IncomeEvent]:
        return [e for e in self._events if e.ticker == ticker.upper()]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class StoredIncomeEvents:
    """B3 events stored in the database, refreshed at most once per `ttl`.

    If B3 fails, the stored events are used: an outage only delays new
    announcements, it never hides income already known.
    """

    def __init__(
        self,
        engine: Engine,
        fetch_events: Callable[[str, bool], list[IncomeEvent]],
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

    def events_for(self, ticker: str, asset_type: AssetType) -> list[IncomeEvent]:
        ticker = ticker.upper()
        if asset_type is AssetType.BDR:
            return []  # paid abroad in dollars: not published by B3, use manual entries

        with Session(self._engine) as session:
            if self._needs_sync(session, ticker):
                self._sync(session, ticker, asset_type in FUND_TYPES)
            records = session.scalars(
                select(IncomeEventRecord)
                .where(IncomeEventRecord.ticker == ticker)
                .order_by(IncomeEventRecord.record_date, IncomeEventRecord.id)
            )
            return [
                IncomeEvent(r.ticker, r.income_type, r.record_date, r.payment_date, r.rate)
                for r in records
            ]

    def _needs_sync(self, session: Session, ticker: str) -> bool:
        now = self._clock()
        if self._source_down_until is not None and now < self._source_down_until:
            return False
        sync = session.get(IncomeEventSync, ticker)
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
            fresh = None

        if fresh:
            # Replace only the window B3 returned: corrections and
            # cancellations inside it are applied, older history is kept.
            oldest = min(e.record_date for e in fresh)
            session.execute(
                delete(IncomeEventRecord).where(
                    IncomeEventRecord.ticker == ticker, IncomeEventRecord.record_date >= oldest
                )
            )
            session.add_all(
                IncomeEventRecord(
                    ticker=ticker,
                    income_type=e.income_type,
                    record_date=e.record_date,
                    payment_date=e.payment_date,
                    rate=e.rate,
                )
                for e in fresh
            )
        session.merge(IncomeEventSync(ticker=ticker, synced_at=now))
        session.commit()


def _as_utc(value: datetime) -> datetime:
    """SQLite drops the timezone when storing datetimes; put UTC back."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)
