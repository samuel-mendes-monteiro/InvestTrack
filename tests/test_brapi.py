"""BrapiClient tests. No real HTTP: the requests session is a Mock.

Tests must never depend on the internet: they would be slow, flaky,
and would spend the API quota.
"""

from decimal import Decimal
from unittest.mock import Mock

import pytest
import requests

from investtrack.sources.brapi import BrapiClient, QuoteUnavailableError, SourceDownError


def fake_response(status: int, body: str) -> requests.Response:
    """A real Response object with fake content."""
    r = requests.Response()
    r.status_code = status
    r._content = body.encode()
    r.encoding = "utf-8"
    r.url = "https://brapi.dev/api/quote/TEST"
    return r


def client_returning(response=None, error=None, token=None):
    session = Mock(spec=requests.Session)
    session.headers = {}
    if error:
        session.get.side_effect = error
    else:
        session.get.return_value = response
    return BrapiClient(token=token, session=session), session


PETR4_JSON = '{"results":[{"symbol":"PETR4","regularMarketPrice":45.37}],"took":0}'


def test_price_is_parsed_as_exact_decimal():
    client, _ = client_returning(fake_response(200, PETR4_JSON))
    price = client.fetch_price("PETR4")
    assert price == Decimal("45.37")
    assert isinstance(price, Decimal)


def test_integer_price_becomes_decimal():
    body = '{"results":[{"regularMarketPrice":38}]}'
    client, _ = client_returning(fake_response(200, body))
    assert client.fetch_price("PETR4") == Decimal("38")


def test_calls_quote_url_with_timeout():
    client, session = client_returning(fake_response(200, PETR4_JSON))
    client.fetch_price("PETR4")
    session.get.assert_called_once_with("https://brapi.dev/api/quote/PETR4", timeout=5.0)


def test_token_goes_in_authorization_header():
    _, session = client_returning(fake_response(200, PETR4_JSON), token="secret")
    assert session.headers["Authorization"] == "Bearer secret"


def test_no_token_no_header():
    _, session = client_returning(fake_response(200, PETR4_JSON))
    assert "Authorization" not in session.headers


@pytest.mark.parametrize(
    "error",
    [
        requests.Timeout("timed out"),
        requests.ConnectionError("no internet"),
    ],
)
def test_network_errors_mean_source_down(error):
    client, _ = client_returning(error=error)
    with pytest.raises(SourceDownError):
        client.fetch_price("PETR4")


@pytest.mark.parametrize(
    "status, body",
    [
        (401, '{"error":true,"code":"MISSING_TOKEN"}'),
        (404, '{"error":true,"message":"not found"}'),
        (200, "<html>not json</html>"),
        (200, '{"results":[]}'),
        (200, '{"results":[{"symbol":"PETR4"}]}'),
        (200, '{"results":[{"regularMarketPrice":null}]}'),
        (200, '{"results":[{"regularMarketPrice":0}]}'),
    ],
)
def test_bad_responses(status, body):
    client, _ = client_returning(fake_response(status, body))
    with pytest.raises(QuoteUnavailableError):
        client.fetch_price("PETR4")


def test_server_error_means_source_down():
    client, _ = client_returning(fake_response(503, "Service Unavailable"))
    with pytest.raises(SourceDownError):
        client.fetch_price("PETR4")


def test_client_error_is_only_about_this_ticker():
    client, _ = client_returning(fake_response(404, '{"error":true}'))
    with pytest.raises(QuoteUnavailableError) as exc:
        client.fetch_price("XPTO3")
    assert not isinstance(exc.value, SourceDownError)
