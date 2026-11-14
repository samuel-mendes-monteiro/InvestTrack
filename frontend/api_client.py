"""Talks to the InvestTrack API over HTTP.

The frontend never imports the backend package: everything goes through
the API, exactly like the future React frontend will.
"""

from decimal import Decimal

import requests


class ApiError(Exception):
    """A user-facing error message from the API (or from not reaching it)."""


class ApiClient:
    def __init__(self, base_url: str, timeout: float = 15.0, session: requests.Session | None = None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()

    def is_up(self) -> bool:
        try:
            return self.session.get(f"{self.base_url}/health", timeout=3).ok
        except requests.RequestException:
            return False

    def portfolio(self) -> dict:
        return self._request("GET", "/portfolio")

    def operations(self, ticker: str | None = None) -> list[dict]:
        params = {"ticker": ticker} if ticker else None
        return self._request("GET", "/operations", params=params)

    def create_operation(self, payload: dict) -> dict:
        return self._request("POST", "/operations", json=payload)

    def delete_operation(self, operation_id: int) -> None:
        self._request("DELETE", f"/operations/{operation_id}")

    def _request(self, method: str, path: str, **kwargs):
        try:
            r = self.session.request(method, self.base_url + path, timeout=self.timeout, **kwargs)
        except requests.RequestException as e:
            raise ApiError(f"Não foi possível falar com a API em {self.base_url}.") from e

        if r.status_code >= 400:
            raise ApiError(error_message(r))
        if r.status_code == 204:
            return None
        return r.json(parse_float=Decimal)


def error_message(response: requests.Response) -> str:
    """Turn FastAPI error bodies into one readable sentence.

    Our own errors have {"detail": "text"}; Pydantic validation errors have
    {"detail": [{"loc": [...], "msg": "..."}, ...]}.
    """
    try:
        detail = response.json().get("detail")
    except ValueError:
        return f"Erro {response.status_code} da API."
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):
        parts = []
        for err in detail:
            field = err.get("loc", [])[-1] if err.get("loc") else ""
            parts.append(f"{field}: {err.get('msg', '')}".strip(": "))
        return "; ".join(parts)
    return f"Erro {response.status_code} da API."
