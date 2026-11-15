"""MarketData tests: what gets downloaded, and when. All sources are fakes."""

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import Mock

import pytest

from investtrack.sources.history import HistoryUnavailableError, NotPublishedError
from investtrack.storage.db import create_db_engine, init_db
from investtrack.storage.market_data import CDI, IBOV, MarketData

TODAY = date(2026, 11, 14)  # a Saturday


@pytest.fixture
def engine():
    e = create_db_engine("sqlite://")
    init_db(e)
    yield e
    e.dispose()


def fake_cotahist(missing_months=(), holidays=()):
    client = Mock()

    def month(year, m):
        if (year, m) in missing_months:
            raise NotPublishedError("not yet")
        return [("PETR4", date(year, m, 2), Decimal("30"))]

    def day(d):
        if d in holidays:
            raise NotPublishedError("holiday")
        return [("PETR4", d, Decimal("31")), ("VALE3", d, Decimal("60"))]

    client.fetch_month.side_effect = month
    client.fetch_day.side_effect = day
    return client


def market(engine, cotahist, today=TODAY):
    # Noon UTC: the same calendar day in Brazil and on a UTC machine (CI).
    noon = datetime(today.year, today.month, today.day, 15, tzinfo=UTC)
    return MarketData(
        engine,
        cotahist=cotahist,
        fetch_ibovespa=Mock(return_value=[(date(2026, 9, 30), Decimal("170000"))]),
        fetch_cdi_rates=Mock(return_value=[(date(2026, 10, 1), Decimal("0.05"))]),
        fetch_ipca_rates=Mock(return_value=[(date(2026, 10, 1), Decimal("0.14"))]),
        clock=lambda: noon,
    )


def test_closed_months_by_file_current_month_by_day(engine):
    november = [2, 3, 4, 5, 6, 9, 10, 11, 12, 13]  # weekdays until Friday 13
    assert market(engine, fake_cotahist()).missing(date(2026, 9, 15)) == [
        "COTAHIST:M092026",
        "COTAHIST:M102026",
        *[f"COTAHIST:D{d:02d}112026" for d in november],
        "IBOV:2026",
        "CDI",
        "IPCA",
    ]


def test_sync_downloads_everything_once(engine):
    cotahist = fake_cotahist()
    m = market(engine, cotahist)
    m.sync(date(2026, 10, 20))
    assert m.is_synced(date(2026, 10, 20))
    assert cotahist.fetch_month.call_count == 1  # October
    assert cotahist.fetch_day.call_count == 10  # weekdays of November until Friday 13

    m.sync(date(2026, 10, 20))
    assert cotahist.fetch_month.call_count == 1
    assert cotahist.fetch_day.call_count == 10


def test_stored_prices_and_series(engine):
    m = market(engine, fake_cotahist())
    m.sync(date(2026, 11, 12))
    assert m.closes({"PETR4"}, date(2026, 11, 1)) == {
        "PETR4": {date(2026, 11, 12): Decimal("31"), date(2026, 11, 13): Decimal("31")}
    }
    assert m.series(IBOV, date(2026, 1, 1)) == {date(2026, 9, 30): Decimal("170000")}
    assert m.series(CDI, date(2026, 1, 1)) == {date(2026, 10, 1): Decimal("0.05")}
    assert m.last_day() == date(2026, 11, 13)


def test_holiday_is_recorded_and_not_asked_again(engine):
    holiday = date(2026, 11, 2)
    cotahist = fake_cotahist(holidays={holiday})
    m = market(engine, cotahist)
    m.sync(date(2026, 11, 2))
    assert "COTAHIST:D02112026" not in m.missing(date(2026, 11, 2))
    assert date(2026, 11, 2) not in m.closes({"PETR4"}, date(2026, 11, 1))["PETR4"]


def test_month_not_published_yet_falls_back_to_daily_files(engine):
    cotahist = fake_cotahist(missing_months={(2026, 10)})
    m = market(engine, cotahist, today=date(2026, 11, 3))
    m.sync(date(2026, 10, 28))
    days = {c.args[0] for c in cotahist.fetch_day.call_args_list}
    assert {date(2026, 10, 28), date(2026, 10, 29), date(2026, 10, 30)} <= days
    assert m.is_synced(date(2026, 10, 28))


def test_today_is_never_requested(engine):
    cotahist = fake_cotahist()
    m = market(engine, cotahist, today=date(2026, 11, 13))
    m.sync(date(2026, 11, 12))
    assert [c.args[0] for c in cotahist.fetch_day.call_args_list] == [date(2026, 11, 12)]


def test_benchmarks_of_the_current_year_are_refreshed_daily(engine):
    m = market(engine, fake_cotahist())
    m.sync(date(2026, 11, 12))
    assert m.is_synced(date(2026, 11, 12))
    tomorrow = market(engine, fake_cotahist(), today=date(2026, 11, 15))
    assert tomorrow.missing(date(2026, 11, 12)) == ["IBOV:2026", "CDI", "IPCA"]


def test_failed_download_is_retried_later(engine):
    cotahist = fake_cotahist()
    cotahist.fetch_day.side_effect = HistoryUnavailableError("timeout")
    m = market(engine, cotahist)
    m.sync(date(2026, 11, 12))  # logs, doesn't raise
    assert "COTAHIST:D12112026" in m.missing(date(2026, 11, 12))


def test_sync_running_is_not_started_twice(engine):
    m = market(engine, fake_cotahist())
    m._lock.acquire()
    try:
        assert m.syncing
        m.sync(date(2026, 11, 12))  # returns at once
        assert not m.is_synced(date(2026, 11, 12))
    finally:
        m._lock.release()


def test_cdi_is_fetched_again_when_the_start_moves_back(engine):
    m = market(engine, fake_cotahist())
    m.sync(date(2026, 10, 1))  # the fake CDI starts on Oct 1
    assert "CDI" not in m.missing(date(2026, 10, 1))
    assert "CDI" in m.missing(date(2025, 6, 2))  # loaded today, but not that far back


def test_ipca_is_downloaded_whole_and_stored(engine):
    m = market(engine, fake_cotahist())
    m.sync(date(2026, 11, 12))
    m._fetch_ipca.assert_called_once_with(date(2000, 1, 1), TODAY)
    assert m.series("IPCA", date(2026, 1, 1)) == {date(2026, 10, 1): Decimal("0.14")}
