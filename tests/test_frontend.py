"""Frontend helpers: Brazilian formatting/parsing and the API client."""

from decimal import Decimal
from unittest.mock import Mock

import pytest
import requests
from api_client import ApiClient, ApiError
from formatting import brl, parse_decimal, pct, quantity


# --- formatting --------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    ("1234.5", "R$ 1.234,50"),
    ("0", "R$ 0,00"),
    ("-123.8", "R$ -123,80"),
    ("1234567.891", "R$ 1.234.567,89"),
    (None, "—"),
])
def test_brl(value, expected):
    assert brl(value) == expected


def test_pct():
    assert pct("8.57") == "+8,57%"
    assert pct("-7.82") == "-7,82%"
    assert pct(None) == "—"


def test_quantity_drops_trailing_zeros():
    assert quantity("150") == "150"
    assert quantity("0.50000000") == "0,5"
    assert quantity("100.00") == "100"


@pytest.mark.parametrize("text, expected", [
    ("30", "30"),
    ("30,50", "30.50"),
    ("30.50", "30.50"),
    ("1.234,56", "1234.56"),
    ("R$ 1.234,56", "1234.56"),
    (" 0,1 ", "0.1"),
])
def test_parse_decimal(text, expected):
    assert parse_decimal(text) == Decimal(expected)


@pytest.mark.parametrize("text", ["", "abc", "1,2,3", "NaN", "Infinity"])
def test_parse_decimal_rejects_garbage(text):
    with pytest.raises(ValueError):
        parse_decimal(text)


# --- API client --------------------------------------------------------------

def fake_response(status: int, body: str = "") -> requests.Response:
    r = requests.Response()
    r.status_code = status
    r._content = body.encode()
    r.encoding = "utf-8"
    return r


def client_with(response=None, error=None):
    session = Mock(spec=requests.Session)
    if error:
        session.request.side_effect = error
    else:
        session.request.return_value = response
    return ApiClient("http://api.test", session=session), session


def test_create_operation_posts_json():
    client, session = client_with(fake_response(201, '{"id": 1}'))
    assert client.create_operation({"ticker": "PETR4"}) == {"id": 1}
    session.request.assert_called_once_with(
        "POST", "http://api.test/operations", timeout=15.0, json={"ticker": "PETR4"})


def test_delete_returns_none_on_204():
    client, _ = client_with(fake_response(204))
    assert client.delete_operation(3) is None


def test_our_error_message_is_passed_through():
    body = '{"detail": "Cannot sell 101 PETR4: only 100 available"}'
    client, _ = client_with(fake_response(422, body))
    with pytest.raises(ApiError, match="only 100 available"):
        client.create_operation({})


def test_validation_errors_become_one_sentence():
    body = ('{"detail": [{"loc": ["body", "price"], "msg": "must be >= 0"},'
            ' {"loc": ["body", "quantity"], "msg": "must be > 0"}]}')
    client, _ = client_with(fake_response(422, body))
    with pytest.raises(ApiError, match="price: must be >= 0; quantity: must be > 0"):
        client.create_operation({})


def test_api_offline():
    client, _ = client_with(error=requests.ConnectionError("refused"))
    with pytest.raises(ApiError, match="Não foi possível falar com a API"):
        client.portfolio()


def test_numbers_are_not_parsed_as_float():
    client, _ = client_with(fake_response(200, '[{"price": 0.1}]'))
    assert client.operations()[0]["price"] == Decimal("0.1")
