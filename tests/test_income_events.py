"""StoredIncomeEvents tests. The B3 fetcher and the clock are fakes."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock

import pytest

from investtrack.b3 import EventsUnavailableError, SourceDownError
from investtrack.db import create_db_engine, init_db
from investtrack.income import IncomeEvent, IncomeType
from investtrack.income_events import StaticIncomeEvents, StoredIncomeEvents
from investtrack.models import AssetType

T0 = datetime(2026, 11, 14, 13, 0, tzinfo=UTC)


class FakeClock:
    def __init__(self, now: datetime):
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs):
        self.now += timedelta(**kwargs)


@pytest.fixture
def engine():
    e = create_db_engine("sqlite://")
    init_db(e)
    yield e
    e.dispose()


@pytest.fixture
def clock():
    return FakeClock(T0)


def ev(month, rate="1", ticker="BBAS3"):
    return IncomeEvent(
        ticker, IncomeType.JCP, date(2026, month, 1), date(2026, month, 20), Decimal(rate)
    )


def store(engine, clock, fetch):
    return StoredIncomeEvents(
        engine, fetch, ttl=timedelta(hours=24), retry_after=timedelta(minutes=5), clock=clock
    )


def test_first_call_fetches_and_stores(engine, clock):
    fetch = Mock(return_value=[ev(1), ev(2)])
    events = store(engine, clock, fetch).events_for("bbas3", AssetType.STOCK)
    fetch.assert_called_once_with("BBAS3", False)
    assert events == [ev(1), ev(2)]


def test_funds_ask_the_fund_endpoint_first(engine, clock):
    fetch = Mock(return_value=[])
    store(engine, clock, fetch).events_for("HGLG11", AssetType.FII)
    fetch.assert_called_once_with("HGLG11", True)


def test_bdr_is_never_fetched(engine, clock):
    fetch = Mock()
    assert store(engine, clock, fetch).events_for("AAPL34", AssetType.BDR) == []
    fetch.assert_not_called()


def test_synced_once_per_day(engine, clock):
    fetch = Mock(return_value=[ev(1)])
    s = store(engine, clock, fetch)
    s.events_for("BBAS3", AssetType.STOCK)
    clock.advance(hours=23)
    s.events_for("BBAS3", AssetType.STOCK)
    assert fetch.call_count == 1
    clock.advance(hours=1)
    s.events_for("BBAS3", AssetType.STOCK)
    assert fetch.call_count == 2


def test_sync_survives_restart(engine, clock):
    store(engine, clock, Mock(return_value=[ev(1)])).events_for("BBAS3", AssetType.STOCK)
    fetch = Mock()
    assert store(engine, clock, fetch).events_for("BBAS3", AssetType.STOCK) == [ev(1)]
    fetch.assert_not_called()


def test_history_older_than_b3_window_is_kept(engine, clock):
    fetch = Mock(return_value=[ev(1), ev(2)])
    s = store(engine, clock, fetch)
    s.events_for("BBAS3", AssetType.STOCK)

    # A day later B3 no longer lists January, corrected February and added March.
    fetch.return_value = [ev(2, rate="1.5"), ev(3)]
    clock.advance(days=1)
    assert s.events_for("BBAS3", AssetType.STOCK) == [ev(1), ev(2, rate="1.5"), ev(3)]


def test_empty_answer_keeps_stored_events(engine, clock):
    fetch = Mock(return_value=[ev(1)])
    s = store(engine, clock, fetch)
    s.events_for("BBAS3", AssetType.STOCK)
    fetch.return_value = []
    clock.advance(days=1)
    assert s.events_for("BBAS3", AssetType.STOCK) == [ev(1)]


def test_outage_uses_stored_events_and_pauses_calls(engine, clock):
    fetch = Mock(return_value=[ev(1)])
    s = store(engine, clock, fetch)
    s.events_for("BBAS3", AssetType.STOCK)

    fetch.side_effect = SourceDownError("timeout")
    clock.advance(days=1)
    assert s.events_for("BBAS3", AssetType.STOCK) == [ev(1)]
    s.events_for("PETR4", AssetType.STOCK)  # other tickers don't wait for a timeout too
    assert fetch.call_count == 2

    clock.advance(minutes=5)
    fetch.side_effect, fetch.return_value = None, [ev(1), ev(2)]
    assert s.events_for("BBAS3", AssetType.STOCK) == [ev(1), ev(2)]  # retried: not marked synced


def test_format_error_is_retried_only_the_next_day(engine, clock):
    fetch = Mock(side_effect=EventsUnavailableError("format changed"))
    s = store(engine, clock, fetch)
    assert s.events_for("BBAS3", AssetType.STOCK) == []
    s.events_for("BBAS3", AssetType.STOCK)
    assert fetch.call_count == 1


def test_static_events_filter_by_ticker():
    source = StaticIncomeEvents([ev(1), ev(1, ticker="PETR4")])
    assert source.events_for("petr4", AssetType.STOCK) == [ev(1, ticker="PETR4")]
