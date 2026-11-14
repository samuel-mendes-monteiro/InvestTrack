"""Parsers and clients of historical data. No real HTTP."""

import base64
import io
import json
import zipfile
from datetime import date
from decimal import Decimal
from unittest.mock import Mock

import pytest
import requests

from investtrack.history import (
    CotahistClient,
    HistoryUnavailableError,
    NotPublishedError,
    fetch_cdi,
    fetch_ibovespa_year,
    fetch_ipca,
    parse_cdi,
    parse_cotahist,
    parse_ibovespa_year,
)


def cotahist_line(ticker="PETR4", day="20261113", market="010", close=4530, factor=1):
    """A record in B3's fixed-width layout (245 characters)."""
    line = [" "] * 245

    def put(start, text):  # 1-based start, like B3's documentation
        line[start - 1 : start - 1 + len(text)] = text

    put(1, "01")
    put(3, day)
    put(11, "02")
    put(13, ticker.ljust(12))
    put(25, market)
    put(109, f"{close:013d}")
    put(211, f"{factor:07d}")
    return "".join(line)


def test_parse_cotahist():
    lines = [
        "00COTAHIST.2026BOVESPA 20261113",
        cotahist_line(),
        cotahist_line("PETR4", market="020", close=4531),  # odd lot: ignored
        cotahist_line("XPTO3", close=150000, factor=1000),  # quoted per 1000 shares
        "99COTAHIST.2026BOVESPA 20261113000000003",
    ]
    assert list(parse_cotahist(iter(lines))) == [
        ("PETR4", date(2026, 11, 13), Decimal("45.30")),
        ("XPTO3", date(2026, 11, 13), Decimal("1.5")),
    ]


def test_parse_cotahist_rejects_garbage():
    with pytest.raises(HistoryUnavailableError):
        list(parse_cotahist(iter([cotahist_line(day="2026XX13")])))


def zipped(text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("COTAHIST_D13112026.TXT", text.encode("latin-1"))
    return buffer.getvalue()


def response(status, content=b""):
    r = requests.Response()
    r.status_code = status
    r._content = content
    return r


def test_cotahist_client_reads_the_zip():
    session = Mock(spec=requests.Session)
    session.get.return_value = response(200, zipped(cotahist_line()))
    rows = CotahistClient(session=session).fetch_day(date(2026, 11, 13))
    assert rows == [("PETR4", date(2026, 11, 13), Decimal("45.30"))]
    assert session.get.call_args.args[0].endswith("/COTAHIST_D13112026.ZIP")


@pytest.mark.parametrize(
    "result, error",
    [
        (response(404), NotPublishedError),
        (response(500), HistoryUnavailableError),
        (response(200, b"not a zip"), HistoryUnavailableError),
        (requests.ConnectionError("down"), HistoryUnavailableError),
    ],
)
def test_cotahist_client_errors(result, error):
    session = Mock(spec=requests.Session)
    if isinstance(result, Exception):
        session.get.side_effect = result
    else:
        session.get.return_value = result
    with pytest.raises(error):
        CotahistClient(session=session).fetch_month(2026, 10)


def test_parse_ibovespa_year():
    payload = {
        "results": [
            {"day": 1, "rateValue1": None, "rateValue4": "187.952,91"},
            {"day": 2, "rateValue1": "160.538,69", "rateValue4": "188.052,02"},
        ]
    }
    assert parse_ibovespa_year(2026, payload) == [
        (date(2026, 1, 2), Decimal("160538.69")),
        (date(2026, 4, 1), Decimal("187952.91")),
        (date(2026, 4, 2), Decimal("188052.02")),
    ]


def test_parse_ibovespa_rejects_garbage():
    with pytest.raises(HistoryUnavailableError):
        parse_ibovespa_year(2026, {"results": [{"day": 31, "rateValue2": "1,0"}]})  # Feb 31


def test_parse_cdi():
    assert parse_cdi([{"data": "02/01/2026", "valor": "0.055131"}]) == [
        (date(2026, 1, 2), Decimal("0.055131"))
    ]
    with pytest.raises(HistoryUnavailableError):
        parse_cdi([{"data": "2026-01-02", "valor": "x"}])


def test_cdi_without_data_is_empty():
    session = Mock(spec=requests.Session)
    session.get.return_value = response(404)
    assert fetch_cdi(date(2026, 11, 14), date(2026, 11, 14), session=session) == []


def test_fetch_ibovespa_year_sends_base64_params():
    session = Mock(spec=requests.Session)
    session.get.return_value = response(200, b'{"results": [{"day": 2, "rateValue1": "1,5"}]}')
    assert fetch_ibovespa_year(2026, session=session) == [(date(2026, 1, 2), Decimal("1.5"))]
    encoded = session.get.call_args.args[0].rsplit("/", 1)[1]
    assert json.loads(base64.b64decode(encoded))["year"] == "2026"

    session.get.return_value = response(503)
    with pytest.raises(HistoryUnavailableError):
        fetch_ibovespa_year(2026, session=session)


def test_fetch_cdi_sends_brazilian_dates():
    session = Mock(spec=requests.Session)
    session.get.return_value = response(200, b'[{"data": "02/01/2026", "valor": "0.05"}]')
    assert fetch_cdi(date(2026, 1, 1), date(2026, 1, 31), session=session) == [
        (date(2026, 1, 2), Decimal("0.05"))
    ]
    params = session.get.call_args.kwargs["params"]
    assert (params["dataInicial"], params["dataFinal"]) == ("01/01/2026", "31/01/2026")


def test_fetch_ipca_reads_the_monthly_series():
    session = Mock()
    session.get.return_value = Mock(
        status_code=200, json=lambda: [{"data": "01/10/2026", "valor": "0.14"}]
    )
    assert fetch_ipca(date(2026, 1, 1), date(2026, 11, 14), session=session) == [
        (date(2026, 10, 1), Decimal("0.14"))
    ]
    assert "sgs.433" in session.get.call_args.args[0]
