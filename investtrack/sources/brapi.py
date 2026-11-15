"""HTTP client for brapi.dev (B3 quotes).

Only this module knows brapi's URL and JSON format. Every failure
(network, timeout, HTTP error, unexpected payload) becomes a single
QuoteUnavailableError, so callers handle one exception type.
"""

from decimal import Decimal

import requests

DEFAULT_BASE_URL = "https://brapi.dev/api"


class QuoteUnavailableError(Exception):
    """The quote for this ticker could not be fetched (e.g. unknown ticker,
    ticker not allowed without a token, unexpected response)."""


class SourceDownError(QuoteUnavailableError):
    """brapi itself is unreachable or failing (network, timeout, 5xx).
    Unlike a per-ticker problem, this affects every ticker."""


class BrapiClient:
    def __init__(
        self,
        token: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 5.0,
        session: requests.Session | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()
        if token:
            # Sent in a header, not in the URL: URLs end up in logs.
            self.session.headers["Authorization"] = f"Bearer {token}"

    def fetch_price(self, ticker: str) -> Decimal:
        """Current market price of one ticker.

        One ticker per request keeps us within the free plan's limits.
        """
        url = f"{self.base_url}/quote/{ticker}"
        try:
            # Without a timeout, a hanging server would freeze our API forever.
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            # parse_float=Decimal: JSON numbers go straight to Decimal, never float.
            data = response.json(parse_float=Decimal)
        except (requests.ConnectionError, requests.Timeout) as e:
            raise SourceDownError(f"{ticker}: {e}") from e
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code >= 500:
                raise SourceDownError(f"{ticker}: {e}") from e
            raise QuoteUnavailableError(f"{ticker}: {e}") from e  # 4xx: this ticker only
        except requests.RequestException as e:  # e.g. invalid JSON
            raise QuoteUnavailableError(f"{ticker}: {e}") from e

        try:
            price = data["results"][0]["regularMarketPrice"]
        except (KeyError, IndexError, TypeError) as e:
            raise QuoteUnavailableError(f"{ticker}: unexpected response format") from e
        if isinstance(price, int):  # e.g. a price of exactly 38 comes as an int
            price = Decimal(price)
        if not isinstance(price, Decimal) or price <= 0:
            raise QuoteUnavailableError(f"{ticker}: invalid price {price!r}")
        return price
