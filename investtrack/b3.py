"""HTTP client for B3's public listing pages (income events).

B3 publishes every dividend, JCP and FII distribution on its website. There
is no official API: these are the JSON endpoints the website itself calls,
undocumented and without guarantees. That is why only this module knows
their URLs and format. If B3 changes them, this is the one file to fix, and
events already stored in the database keep working meanwhile.

Quirks handled here:
- The request parameters go base64-encoded JSON inside the URL path.
- Companies and funds (FIIs, ETFs) use different endpoints.
- An unknown issuer returns 200 with an empty body, not 404.
- One issuer lists events for all its securities (ON and PN shares,
  subscription receipts...), identified by ISIN, not by ticker.
- Numbers and dates are Brazilian text: "0,1024", "11/09/2026".
"""

import base64
import json
import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import requests

from investtrack.income import IncomeEvent, IncomeType

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://sistemaswebb3-listados.b3.com.br"
COMPANY_PATH = "/listedCompaniesProxy/CompanyCall/GetListedSupplementCompany/"
FUND_PATH = "/fundsProxy/fundsCall/GetListedSupplementFunds/"

# Only labels that are income. Anything else (e.g. an FII "AMORTIZACAO",
# which returns invested capital) is ignored on purpose.
COMPANY_LABELS = {
    "DIVIDENDO": IncomeType.DIVIDEND,
    "JRS CAP PROPRIO": IncomeType.JCP,
    # A company "rendimento" is usually the monetary correction of a late
    # payment. Treated as a dividend: no withholding tax is computed.
    "RENDIMENTO": IncomeType.DIVIDEND,
}
FUND_LABELS = {"RENDIMENTO": IncomeType.DISTRIBUTION}

# The ISIN of a B3 security encodes its kind right after the issuer code:
# BRBBASACNOR3 = BBAS + ACNOR (common share), BRPETRACNPR6 = PETR + ACNPR (preferred).
SHARE_KINDS = {"3": "ACNOR", "4": "ACNPR", "5": "ACNPA", "6": "ACNPB", "7": "ACNPC", "8": "ACNPD"}


class EventsUnavailableError(Exception):
    """Events for this ticker could not be fetched (e.g. unexpected format)."""


class SourceDownError(EventsUnavailableError):
    """B3's website is unreachable or failing (network, timeout, 5xx)."""


def isin_matches(isin: str, ticker: str) -> bool:
    """Does this ISIN belong to this ticker? 'BRBBASACNOR3' -> BBAS3."""
    issuer, suffix = ticker[:4], ticker[4:]
    if len(isin) != 12 or isin[2:6] != issuer:
        return False
    kind = isin[6:11]
    if suffix in SHARE_KINDS:
        return kind == SHARE_KINDS[suffix]
    if suffix == "11":  # fund quota (CTF) or unit (certificate of deposit, CDA)
        return kind.startswith(("CTF", "CDA"))
    return False


def _br_decimal(text: str) -> Decimal:
    try:
        return Decimal(text.strip().replace(".", "").replace(",", "."))
    except InvalidOperation:
        raise ValueError(f"not a number: {text!r}") from None


def _br_date(text: str) -> date | None:
    text = (text or "").strip()
    return datetime.strptime(text, "%d/%m/%Y").date() if text else None


def is_fund_isin(isin: str) -> bool:
    """FII and ETF quotas: 'BRHGLGCTF004'."""
    return isin[6:9] == "CTF"


def parse_events(ticker: str, payload: dict) -> list[IncomeEvent]:
    """Turn one issuer's JSON into the events of a single ticker.

    Whether it's a fund comes from the ISIN, not from the endpoint that
    answered: the company endpoint also answers for some funds.
    """
    events = []
    for item in payload.get("cashDividends") or []:
        isin = item.get("isinCode", "")
        if not isin_matches(isin, ticker):
            continue
        labels = FUND_LABELS if is_fund_isin(isin) else COMPANY_LABELS
        income_type = labels.get(item.get("label", "").strip())
        if income_type is None:
            log.info("Ignoring %s event of %s", item.get("label"), ticker)
            continue
        try:
            record_date = _br_date(item["lastDatePrior"])
            payment_date = _br_date(item.get("paymentDate", ""))
            rate = _br_decimal(item["rate"])
        except (KeyError, ValueError, TypeError) as e:
            raise EventsUnavailableError(f"{ticker}: unexpected event format: {e}") from e
        if record_date is None:  # without a record date, entitlement can't be computed
            continue
        events.append(IncomeEvent(ticker, income_type, record_date, payment_date, rate))
    return events


class B3Client:
    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 10.0,
        session: requests.Session | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()

    def fetch_events(self, ticker: str, is_fund: bool) -> list[IncomeEvent]:
        """All income events B3 lists for this ticker (about the last 12 months).

        is_fund says which endpoint to try first. If the issuer isn't found
        there, the other one is tried: an FII registered as a stock by
        mistake still gets its income.
        """
        ticker = ticker.strip().upper()
        for fund in (is_fund, not is_fund):
            payload = self._get_issuer(ticker, fund)
            if payload is not None:
                return parse_events(ticker, payload)
        log.info("%s not found at B3", ticker)
        return []

    def _get_issuer(self, ticker: str, fund: bool) -> dict | None:
        """The issuer's JSON, or None if B3 doesn't know it."""
        issuer = ticker[:4]
        if fund:
            path, params = FUND_PATH, {"cnpj": "0", "identifierFund": issuer, "typeFund": 7}
        else:
            path, params = COMPANY_PATH, {"issuingCompany": issuer, "language": "pt-br"}
        encoded = base64.b64encode(json.dumps(params).encode()).decode()

        try:
            response = self.session.get(self.base_url + path + encoded, timeout=self.timeout)
            response.raise_for_status()
        except (requests.ConnectionError, requests.Timeout) as e:
            raise SourceDownError(f"{ticker}: {e}") from e
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code >= 500:
                raise SourceDownError(f"{ticker}: {e}") from e
            raise EventsUnavailableError(f"{ticker}: {e}") from e

        if not response.text.strip():
            return None  # B3's way of saying "unknown issuer"
        try:
            data = response.json()
        except ValueError as e:
            raise EventsUnavailableError(f"{ticker}: response is not JSON") from e
        if isinstance(data, list):  # companies come wrapped in a list
            data = data[0] if data else None
        if data is not None and not isinstance(data, dict):
            raise EventsUnavailableError(f"{ticker}: unexpected response format")
        return data
