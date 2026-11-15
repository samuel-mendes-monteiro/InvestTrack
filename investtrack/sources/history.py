"""Clients for historical market data: daily prices, Ibovespa, CDI and IPCA.

All these sources are free and official, and none needs a token:
- Prices: B3's COTAHIST files, the official historical series. Unlike
  brapi's history (limited to 3 months on the free plan), they cover any
  period. They are also unadjusted: splits and dividends are applied by
  this project itself, so adjusted prices would count them twice.
- Ibovespa: the daily closes B3 shows on its index page.
- CDI: the Central Bank's SGS series 12 (daily rate, % per day).
- IPCA: SGS series 433 (monthly inflation, %), dated the 1st of each month.

Only this module knows these URLs and formats.
"""

import base64
import io
import json
import zipfile
from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import requests

COTAHIST_URL = "https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_{period}.ZIP"
IBOV_URL = (
    "https://sistemaswebb3-listados.b3.com.br/indexStatisticsProxy/IndexCall/GetPortfolioDay/"
)
CDI_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.12/dados"
IPCA_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.433/dados"

SPOT_MARKET = "010"  # mercado à vista, lote padrão


class HistoryUnavailableError(Exception):
    """A historical file or series could not be fetched or read."""


class NotPublishedError(HistoryUnavailableError):
    """The file doesn't exist (yet): a holiday, or a period not closed yet."""


# --- COTAHIST ----------------------------------------------------------------


def parse_cotahist(lines: Iterator[str]) -> Iterator[tuple[str, date, Decimal]]:
    """(ticker, date, close) for each spot-market quote in a COTAHIST file.

    Fixed-width layout (positions from B3's documentation, 1-based):
    record type 1-2 ("01" = quote), date 3-10 (YYYYMMDD), ticker 13-24,
    market 25-27, close 109-121 (2 implied decimals), quotation factor
    211-217 (prices are per that many shares, almost always 1).
    """
    for line in lines:
        if line[:2] != "01" or line[24:27] != SPOT_MARKET:
            continue
        try:
            day = datetime.strptime(line[2:10], "%Y%m%d").date()
            close = Decimal(int(line[108:121])) / 100
            factor = int(line[210:217]) or 1
        except ValueError as e:
            raise HistoryUnavailableError(f"unexpected COTAHIST line: {line[:40]!r}") from e
        yield line[12:24].strip(), day, close / factor


class CotahistClient:
    def __init__(self, timeout: float = 120.0, session: requests.Session | None = None):
        self.timeout = timeout
        self.session = session or requests.Session()

    def fetch_month(self, year: int, month: int) -> list[tuple[str, date, Decimal]]:
        """A whole month (about 10 MB zipped). Only exists once the month is over."""
        return self._fetch(f"M{month:02d}{year}")

    def fetch_day(self, day: date) -> list[tuple[str, date, Decimal]]:
        """One trading day (about 550 KB). Published in the evening of that day."""
        return self._fetch(f"D{day:%d%m%Y}")

    def _fetch(self, period: str) -> list[tuple[str, date, Decimal]]:
        url = COTAHIST_URL.format(period=period)
        try:
            response = self.session.get(url, timeout=self.timeout)
        except requests.RequestException as e:
            raise HistoryUnavailableError(f"COTAHIST {period}: {e}") from e
        if response.status_code == 404:
            raise NotPublishedError(f"COTAHIST {period} not published")
        if not response.ok:
            raise HistoryUnavailableError(f"COTAHIST {period}: HTTP {response.status_code}")
        try:
            with zipfile.ZipFile(io.BytesIO(response.content)) as z:
                text = z.read(z.namelist()[0]).decode("latin-1")
        except (zipfile.BadZipFile, IndexError) as e:
            raise HistoryUnavailableError(f"COTAHIST {period}: not a valid zip") from e
        return list(parse_cotahist(iter(text.splitlines())))


# --- Ibovespa ----------------------------------------------------------------


def _br_number(text: str) -> Decimal:
    return Decimal(text.replace(".", "").replace(",", "."))


def parse_ibovespa_year(year: int, payload: dict) -> list[tuple[date, Decimal]]:
    """B3's table has one row per day of the month (1-31) and one column per
    month (rateValue1..rateValue12); empty cells are days without trading."""
    values = []
    try:
        for row in payload["results"]:
            for month in range(1, 13):
                cell = row.get(f"rateValue{month}")
                if cell:
                    values.append((date(year, month, int(row["day"])), _br_number(cell)))
    except (KeyError, TypeError, ValueError, InvalidOperation) as e:
        raise HistoryUnavailableError(f"unexpected Ibovespa format: {e}") from e
    return sorted(values)


def fetch_ibovespa_year(
    year: int, session: requests.Session | None = None, timeout: float = 30.0
) -> list[tuple[date, Decimal]]:
    params = {"index": "IBOV", "language": "pt-br", "year": str(year)}
    encoded = base64.b64encode(json.dumps(params).encode()).decode()
    try:
        response = (session or requests).get(IBOV_URL + encoded, timeout=timeout)
        response.raise_for_status()
        return parse_ibovespa_year(year, response.json())
    except (requests.RequestException, ValueError) as e:
        raise HistoryUnavailableError(f"Ibovespa {year}: {e}") from e


# --- Central Bank series (CDI, IPCA) ------------------------------------------


def parse_cdi(payload: list) -> list[tuple[date, Decimal]]:
    """[{"data": "02/01/2026", "valor": "0.055131"}] -> (day, value) pairs.

    Every SGS series has this format: CDI in % per day, IPCA in % per month.
    """
    try:
        return [
            (datetime.strptime(item["data"], "%d/%m/%Y").date(), Decimal(item["valor"]))
            for item in payload
        ]
    except (KeyError, TypeError, ValueError, InvalidOperation) as e:
        raise HistoryUnavailableError(f"unexpected SGS format: {e}") from e


def _fetch_sgs(
    name: str, url: str, start: date, end: date, session: requests.Session | None, timeout: float
) -> list[tuple[date, Decimal]]:
    params = {"formato": "json", "dataInicial": f"{start:%d/%m/%Y}", "dataFinal": f"{end:%d/%m/%Y}"}
    try:
        response = (session or requests).get(url, params=params, timeout=timeout)
        if response.status_code == 404:  # the Central Bank answers 404 for "no data"
            return []
        response.raise_for_status()
        return parse_cdi(response.json())
    except (requests.RequestException, ValueError) as e:
        raise HistoryUnavailableError(f"{name}: {e}") from e


def fetch_cdi(
    start: date, end: date, session: requests.Session | None = None, timeout: float = 30.0
) -> list[tuple[date, Decimal]]:
    return _fetch_sgs("CDI", CDI_URL, start, end, session, timeout)


def fetch_ipca(
    start: date, end: date, session: requests.Session | None = None, timeout: float = 30.0
) -> list[tuple[date, Decimal]]:
    return _fetch_sgs("IPCA", IPCA_URL, start, end, session, timeout)
