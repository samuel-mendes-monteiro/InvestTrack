"""CachedPriceProvider tests. The quote source and the clock are fakes."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock

import pytest

from investtrack.brapi import QuoteUnavailableError, SourceDownError
from investtrack.db import create_db_engine, init_db
from investtrack.prices import CachedPriceProvider

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


def make_provider(engine, clock, fetch):
    return CachedPriceProvider(engine, fetch, ttl=timedelta(minutes=15),
                               retry_after=timedelta(minutes=1), clock=clock)


def test_first_call_fetches_and_caches(engine, clock):
    fetch = Mock(return_value=Decimal("45.37"))
    quote = make_provider(engine, clock, fetch).get_quote("petr4")

    fetch.assert_called_once_with("PETR4")
    assert quote.price == Decimal("45.37")
    assert quote.as_of == T0
    assert quote.stale is False


def test_fresh_cache_does_not_call_the_api(engine, clock):
    fetch = Mock(return_value=Decimal("45.37"))
    provider = make_provider(engine, clock, fetch)
    provider.get_quote("PETR4")
    clock.advance(minutes=14)
    provider.get_quote("PETR4")
    assert fetch.call_count == 1


def test_expired_cache_fetches_again(engine, clock):
    fetch = Mock(side_effect=[Decimal("45.37"), Decimal("46.00")])
    provider = make_provider(engine, clock, fetch)
    provider.get_quote("PETR4")
    clock.advance(minutes=15)
    quote = provider.get_quote("PETR4")

    assert fetch.call_count == 2
    assert quote.price == Decimal("46.00")
    assert quote.as_of == T0 + timedelta(minutes=15)


def test_api_down_uses_last_known_price(engine, clock):
    fetch = Mock(side_effect=[Decimal("45.37"), QuoteUnavailableError("down")])
    provider = make_provider(engine, clock, fetch)
    provider.get_quote("PETR4")
    clock.advance(hours=2)
    quote = provider.get_quote("PETR4")

    assert quote.price == Decimal("45.37")
    assert quote.as_of == T0  # the user can see how old it is
    assert quote.stale is True


def test_api_down_and_no_cache_returns_none(engine, clock):
    fetch = Mock(side_effect=QuoteUnavailableError("down"))
    assert make_provider(engine, clock, fetch).get_quote("PETR4") is None


def test_after_an_outage_the_api_is_not_retried_immediately(engine, clock):
    fetch = Mock(side_effect=SourceDownError("down"))
    provider = make_provider(engine, clock, fetch)

    provider.get_quote("PETR4")
    provider.get_quote("VALE3")   # within retry_after: no call, no timeout wait
    assert fetch.call_count == 1

    clock.advance(minutes=1)
    provider.get_quote("VALE3")   # retry window over: tries again
    assert fetch.call_count == 2


def test_cache_survives_a_restart(engine, clock):
    make_provider(engine, clock, Mock(return_value=Decimal("45.37"))).get_quote("PETR4")

    fetch_after_restart = Mock()
    quote = make_provider(engine, clock, fetch_after_restart).get_quote("PETR4")

    fetch_after_restart.assert_not_called()
    assert quote.price == Decimal("45.37")
    assert quote.as_of == T0  # timezone restored after the SQLite round trip


def test_a_ticker_error_does_not_pause_other_tickers(engine, clock):
    fetch = Mock(side_effect=[QuoteUnavailableError("401 for HGLG11"), Decimal("45.37")])
    provider = make_provider(engine, clock, fetch)

    assert provider.get_quote("HGLG11") is None
    assert provider.get_quote("PETR4").price == Decimal("45.37")  # still fetched
