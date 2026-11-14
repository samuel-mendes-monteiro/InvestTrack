"""B3Client tests. No real HTTP: the requests session is a Mock.

The JSON below is trimmed from real B3 responses (November 2026).
"""

import base64
import json
from datetime import date
from decimal import Decimal
from unittest.mock import Mock

import pytest
import requests

from investtrack.b3 import (
    B3Client,
    EventsUnavailableError,
    SourceDownError,
    isin_matches,
    parse_events,
    parse_stock_events,
)
from investtrack.income import IncomeType, TickerEvents
from investtrack.portfolio import StockEventType


def item(isin, label, rate, record="01/09/2026", payment="11/09/2026"):
    return {
        "isinCode": isin,
        "label": label,
        "rate": rate,
        "lastDatePrior": record,
        "paymentDate": payment,
        "relatedTo": "2º Trimestre/2026",
    }


BBAS = {
    "code": "BBAS",
    "cashDividends": [
        item("BRBBASACNOR3", "JRS CAP PROPRIO", "0,10245643978"),
        item("BRBBASACNOR3", "RENDIMENTO", "0,00281361809"),
        item("BRBBASA04OR8", "JRS CAP PROPRIO", "0,10245643978"),  # a receipt, not BBAS3
    ],
}
HGLG = {
    "code": "HGLG",
    "cashDividends": [
        item("BRHGLGCTF004", "RENDIMENTO", "1,17000000000", "30/10/2026", "16/11/2026"),
        item("BRHGLGCTF004", "AMORTIZACAO", "2,00000000000"),  # capital back, not income
        item("BRHGLGR26M17", "RENDIMENTO", "0,50000000000"),  # subscription receipt
    ],
}


@pytest.mark.parametrize(
    "isin, ticker, expected",
    [
        ("BRBBASACNOR3", "BBAS3", True),
        ("BRPETRACNPR6", "PETR4", True),
        ("BRPETRACNOR9", "PETR4", False),  # ON is PETR3
        ("BRHGLGCTF004", "HGLG11", True),
        ("BRTAEECDAM10", "TAEE11", True),  # unit
        ("BRHGLGR26M17", "HGLG11", False),
        ("BRVALEACNOR0", "BBAS3", False),
        ("", "BBAS3", False),
    ],
)
def test_isin_matches(isin, ticker, expected):
    assert isin_matches(isin, ticker) is expected


def test_parse_company_events():
    events = parse_events("BBAS3", BBAS)
    assert [(e.income_type, e.rate) for e in events] == [
        (IncomeType.JCP, Decimal("0.10245643978")),
        (IncomeType.DIVIDEND, Decimal("0.00281361809")),
    ]
    assert events[0].record_date == date(2026, 9, 1)
    assert events[0].payment_date == date(2026, 9, 11)


def test_parse_fund_events_skips_amortization_and_receipts():
    [e] = parse_events("HGLG11", HGLG)
    assert e.income_type is IncomeType.DISTRIBUTION
    assert e.rate == Decimal("1.17")


def test_fund_is_detected_from_isin_not_endpoint():
    payload = {"cashDividends": [item("BRNDIVCTF004", "RENDIMENTO", "0,19")]}
    [e] = parse_events("NDIV11", payload)
    assert e.income_type is IncomeType.DISTRIBUTION


def test_missing_payment_date_is_none():
    payload = {"cashDividends": [item("BRBBASACNOR3", "DIVIDENDO", "1,0", payment="")]}
    assert parse_events("BBAS3", payload)[0].payment_date is None


def test_unexpected_format_is_an_error():
    payload = {"cashDividends": [item("BRBBASACNOR3", "DIVIDENDO", "abc")]}
    with pytest.raises(EventsUnavailableError):
        parse_events("BBAS3", payload)


# --- HTTP --------------------------------------------------------------------


def fake_response(status: int, body: str) -> requests.Response:
    r = requests.Response()
    r.status_code = status
    r._content = body.encode()
    r.encoding = "utf-8"
    r.url = "https://b3.test/"
    return r


def client_returning(*responses, error=None):
    session = Mock(spec=requests.Session)
    if error:
        session.get.side_effect = error
    else:
        session.get.side_effect = list(responses)
    return B3Client(base_url="https://b3.test", session=session), session


def decoded_params(session, call=0) -> dict:
    url = session.get.call_args_list[call].args[0]
    return json.loads(base64.b64decode(url.rsplit("/", 1)[1]))


def test_company_request():
    client, session = client_returning(fake_response(200, json.dumps([BBAS])))
    assert len(client.fetch_events("bbas3", is_fund=False).income) == 2
    assert decoded_params(session) == {"issuingCompany": "BBAS", "language": "pt-br"}
    assert session.get.call_args.kwargs["timeout"] == 10.0


def test_fund_request():
    client, session = client_returning(fake_response(200, json.dumps(HGLG)))
    assert len(client.fetch_events("HGLG11", is_fund=True).income) == 1
    assert decoded_params(session)["identifierFund"] == "HGLG"


def test_falls_back_to_the_other_endpoint_when_issuer_is_unknown():
    client, session = client_returning(fake_response(200, ""), fake_response(200, json.dumps(HGLG)))
    assert len(client.fetch_events("HGLG11", is_fund=False).income) == 1  # registered as a stock
    assert "identifierFund" in decoded_params(session, call=1)


def test_unknown_everywhere_returns_no_events():
    client, _ = client_returning(fake_response(200, ""), fake_response(200, ""))
    assert client.fetch_events("XPTO3", is_fund=False) == TickerEvents([], [])


@pytest.mark.parametrize("error", [requests.ConnectionError("refused"), requests.Timeout("slow")])
def test_network_errors_mean_source_down(error):
    client, _ = client_returning(error=error)
    with pytest.raises(SourceDownError):
        client.fetch_events("BBAS3", is_fund=False)


def test_5xx_means_source_down():
    client, _ = client_returning(fake_response(503, "unavailable"))
    with pytest.raises(SourceDownError):
        client.fetch_events("BBAS3", is_fund=False)


def test_4xx_is_not_an_outage():
    client, _ = client_returning(fake_response(403, "forbidden"))
    with pytest.raises(EventsUnavailableError) as exc:
        client.fetch_events("BBAS3", is_fund=False)
    assert not isinstance(exc.value, SourceDownError)


@pytest.mark.parametrize("body", ["<html>maintenance</html>", "42"])
def test_unexpected_body_is_an_error(body):
    client, _ = client_returning(fake_response(200, body))
    with pytest.raises(EventsUnavailableError):
        client.fetch_events("BBAS3", is_fund=False)


# --- stock events ------------------------------------------------------------


def stock_item(isin, label, factor, record="15/04/2024"):
    return {"isinCode": isin, "label": label, "factor": factor, "lastDatePrior": record}


def test_parse_stock_events():
    payload = {
        "stockDividends": [
            stock_item("BRBBASACNOR3", "DESDOBRAMENTO", "100,00000000000"),
            stock_item("BRBBASACNOR3", "GRUPAMENTO", "0,00100000000", "23/01/2004"),
            stock_item("BRBBASACNOR3", "BONIFICACAO", "10,00000000000", "18/04/2022"),
            stock_item("BRBBASACNOR3", "DESDOBRAMENTO", "4.900,00000000000", "08/06/2009"),
            stock_item("BRBBASACNOR3", "CIS RED CAP", "100,00000000000"),  # not handled
            stock_item("BRBBASA04OR8", "DESDOBRAMENTO", "100,00000000000"),  # other security
        ]
    }
    events = parse_stock_events("BBAS3", payload)
    assert [(e.event_type, e.multiplier) for e in events] == [
        (StockEventType.SPLIT, Decimal("2")),  # +100%: 1 becomes 2
        (StockEventType.REVERSE_SPLIT, Decimal("0.001")),  # 1000 become 1
        (StockEventType.BONUS, Decimal("1.1")),  # +10%
        (StockEventType.SPLIT, Decimal("50")),  # +4900%: 1 becomes 50
    ]
    assert events[0].record_date == date(2024, 4, 15)


def test_stock_events_come_in_the_same_request():
    payload = dict(BBAS, stockDividends=[stock_item("BRBBASACNOR3", "DESDOBRAMENTO", "100,0")])
    client, session = client_returning(fake_response(200, json.dumps([payload])))
    result = client.fetch_events("BBAS3", is_fund=False)
    assert len(result.income) == 2
    assert len(result.stock) == 1
    assert session.get.call_count == 1


def test_unexpected_stock_event_format_is_an_error():
    payload = {"stockDividends": [stock_item("BRBBASACNOR3", "DESDOBRAMENTO", "x")]}
    with pytest.raises(EventsUnavailableError):
        parse_stock_events("BBAS3", payload)
