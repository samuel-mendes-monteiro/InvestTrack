"""Historical market data kept in the database: prices, Ibovespa and CDI.

The first download for a year of trades is about 100 MB (one COTAHIST file
per month), so it must not run inside an HTTP request: the API starts it
in the background and answers with whatever is already stored. After that,
each day adds one small file.

What to download is decided by comparing the periods needed (from the
first trade until yesterday) with the periods recorded in history_loads:
- months already over: one monthly file;
- the current month: one daily file per weekday (today's is only published
  in the evening, so the history goes until yesterday);
- a weekday without a file is a holiday, recorded so it isn't asked again;
- Ibovespa and CDI of the current year are refreshed once a day.
"""

import logging
import threading
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Protocol

from sqlalchemy import Engine, delete, func, insert, select
from sqlalchemy.orm import Session

from investtrack.history import (
    CotahistClient,
    HistoryUnavailableError,
    NotPublishedError,
    fetch_cdi,
    fetch_ibovespa_year,
)
from investtrack.models import BenchmarkValue, DailyPrice, HistoryLoad

log = logging.getLogger(__name__)

IBOV, CDI = "IBOV", "CDI"


class MarketDataSource(Protocol):
    syncing: bool

    def is_synced(self, start: date) -> bool: ...
    def sync(self, start: date) -> None: ...
    def last_day(self) -> date: ...
    def closes(self, tickers: set[str], start: date) -> dict[str, dict[date, Decimal]]: ...
    def series(self, name: str, start: date) -> dict[date, Decimal]: ...


def _months(start: date, end: date):
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        yield year, month
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def _weekdays(start: date, end: date):
    day = start
    while day <= end:
        if day.weekday() < 5:
            yield day
        day += timedelta(days=1)


def _month_end(year: int, month: int) -> date:
    next_month = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return next_month - timedelta(days=1)


def _day_period(day: date) -> str:
    return f"COTAHIST:D{day:%d%m%Y}"


class MarketData:
    def __init__(
        self,
        engine: Engine,
        cotahist: CotahistClient | None = None,
        fetch_ibovespa: Callable[[int], list[tuple[date, Decimal]]] = fetch_ibovespa_year,
        fetch_cdi_rates: Callable[[date, date], list[tuple[date, Decimal]]] = fetch_cdi,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self._engine = engine
        self._cotahist = cotahist or CotahistClient()
        self._fetch_ibovespa = fetch_ibovespa
        self._fetch_cdi = fetch_cdi_rates
        # One clock for "today" and for load timestamps, so tests control both.
        self._clock = clock
        self._lock = threading.Lock()

    def _today(self) -> date:
        return _day(self._clock())

    @property
    def syncing(self) -> bool:
        return self._lock.locked()

    def last_day(self) -> date:
        return self._today() - timedelta(days=1)

    # --- what is missing -----------------------------------------------------

    def _loaded(self, session: Session) -> dict[str, datetime]:
        return {r.period: r.loaded_at for r in session.scalars(select(HistoryLoad))}

    def _missing_price_periods(self, loaded: dict[str, datetime], start: date) -> list[str]:
        last, today = self.last_day(), self._today()
        missing = []
        for year, month in _months(start, last):
            first = max(start, date(year, month, 1))
            days = [_day_period(d) for d in _weekdays(first, min(_month_end(year, month), last))]
            month_over = (year, month) < (today.year, today.month)
            if month_over and f"COTAHIST:M{month:02d}{year}" in loaded:
                continue
            if all(d in loaded for d in days):
                continue
            # A closed month is one big file; the current month goes day by day.
            missing += [f"COTAHIST:M{month:02d}{year}"] if month_over else days
        return [p for p in missing if p not in loaded]

    def _missing_benchmarks(
        self, loaded: dict[str, datetime], start: date, cdi_from: date | None
    ) -> list[str]:
        today = self._today()
        missing = []
        for year in range(start.year, today.year + 1):
            period = f"{IBOV}:{year}"
            fresh = period in loaded and (year < today.year or _day(loaded[period]) == today)
            if not fresh:
                missing.append(period)
        # Loaded today is not enough: it must also go back far enough. A week of
        # slack covers a start on a weekend or holiday, which has no rate.
        covers_start = cdi_from is not None and cdi_from <= start + timedelta(days=7)
        if CDI not in loaded or _day(loaded[CDI]) != today or not covers_start:
            missing.append(CDI)
        return missing

    def missing(self, start: date) -> list[str]:
        with Session(self._engine) as session:
            loaded = self._loaded(session)
            cdi_from = session.scalar(
                select(func.min(BenchmarkValue.date)).where(BenchmarkValue.series == CDI)
            )
        return self._missing_price_periods(loaded, start) + self._missing_benchmarks(
            loaded, start, cdi_from
        )

    def is_synced(self, start: date) -> bool:
        return not self.missing(start)

    # --- downloading ---------------------------------------------------------

    def sync(self, start: date) -> None:
        """Download what is missing. Does nothing if a sync is already running."""
        if not self._lock.acquire(blocking=False):
            return
        try:
            for period in self.missing(start):
                try:
                    self._load(period, start)
                except HistoryUnavailableError as e:
                    log.warning("Could not load %s: %s", period, e)
        finally:
            self._lock.release()

    def _load(self, period: str, start: date) -> None:
        kind, _, key = period.partition(":")
        if kind == "COTAHIST" and key.startswith("M"):
            month, year = int(key[1:3]), int(key[3:])
            try:
                rows = self._cotahist.fetch_month(year, month)
            except NotPublishedError:
                # Monthly files appear a few days after the month ends: use daily ones.
                first = max(start, date(year, month, 1))
                for day in _weekdays(first, _month_end(year, month)):
                    self._load(_day_period(day), start)
                return
            self._save_prices(rows, date(year, month, 1), _month_end(year, month), period)
        elif kind == "COTAHIST":
            day = datetime.strptime(key[1:], "%d%m%Y").date()
            try:
                rows = self._cotahist.fetch_day(day)
            except NotPublishedError:
                if day >= self._today():
                    return  # not published yet: try again later
                rows = []  # a holiday
            self._save_prices(rows, day, day, period)
        elif kind == IBOV:
            year = int(key)
            self._save_series(IBOV, self._fetch_ibovespa(year), period)
        elif kind == CDI:
            self._save_series(CDI, self._fetch_cdi(start, self._today()), period)

    def _save_prices(self, rows, first: date, last: date, period: str) -> None:
        with Session(self._engine) as session:
            session.execute(delete(DailyPrice).where(DailyPrice.date.between(first, last)))
            if rows:
                session.execute(
                    insert(DailyPrice),
                    [{"ticker": t, "date": d, "close": c} for t, d, c in rows],
                )
            session.merge(HistoryLoad(period=period, loaded_at=self._clock()))
            session.commit()
        log.info("Loaded %s (%d prices)", period, len(rows))

    def _save_series(self, name: str, values: list[tuple[date, Decimal]], period: str) -> None:
        with Session(self._engine) as session:
            if values:
                first, last = values[0][0], values[-1][0]
                session.execute(
                    delete(BenchmarkValue).where(
                        BenchmarkValue.series == name, BenchmarkValue.date.between(first, last)
                    )
                )
                session.execute(
                    insert(BenchmarkValue),
                    [{"series": name, "date": d, "value": v} for d, v in values],
                )
            session.merge(HistoryLoad(period=period, loaded_at=self._clock()))
            session.commit()

    # --- reading -------------------------------------------------------------

    def closes(self, tickers: set[str], start: date) -> dict[str, dict[date, Decimal]]:
        result: dict[str, dict[date, Decimal]] = defaultdict(dict)
        with Session(self._engine) as session:
            rows = session.execute(
                select(DailyPrice.ticker, DailyPrice.date, DailyPrice.close).where(
                    DailyPrice.ticker.in_(tickers), DailyPrice.date >= start
                )
            )
            for ticker, day, close in rows:
                result[ticker][day] = close
        return dict(result)

    def series(self, name: str, start: date) -> dict[date, Decimal]:
        with Session(self._engine) as session:
            rows = session.execute(
                select(BenchmarkValue.date, BenchmarkValue.value).where(
                    BenchmarkValue.series == name, BenchmarkValue.date >= start
                )
            )
            return dict(rows.all())


def _day(value: datetime) -> date:
    """Day of a timestamp in local time (SQLite drops the timezone: it is UTC)."""
    aware = value if value.tzinfo else value.replace(tzinfo=UTC)
    return aware.astimezone().date()


class StaticMarketData:
    """Fixed history (tests, offline demos): always synced, never downloads."""

    syncing = False

    def __init__(
        self,
        closes: dict[str, dict[date, Decimal]] | None = None,
        series: dict[str, dict[date, Decimal]] | None = None,
        last_day: date | None = None,
    ):
        self._closes = closes or {}
        self._series = series or {}
        self._last_day = last_day or date.today() - timedelta(days=1)

    def is_synced(self, start: date) -> bool:
        return True

    def sync(self, start: date) -> None:
        pass

    def last_day(self) -> date:
        return self._last_day

    def closes(self, tickers: set[str], start: date) -> dict[str, dict[date, Decimal]]:
        return {
            t: {d: v for d, v in by_day.items() if d >= start}
            for t, by_day in self._closes.items()
            if t in tickers
        }

    def series(self, name: str, start: date) -> dict[date, Decimal]:
        return {d: v for d, v in self._series.get(name, {}).items() if d >= start}
