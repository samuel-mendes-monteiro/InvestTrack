"""Talks to the InvestTrack API over HTTP.

The frontend never imports the backend package: everything goes through
the API, exactly like the future React frontend will.
"""

from decimal import Decimal

import requests

XLSX_HEADER = {"Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}


class ApiError(Exception):
    """A user-facing error message from the API (or from not reaching it)."""


class NotLoggedInError(ApiError):
    """The session is missing or expired: the user must log in again."""


class ApiClient:
    def __init__(
        self,
        base_url: str,
        timeout: float = 15.0,
        session: requests.Session | None = None,
        token: str | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"

    def register(self, email: str, password: str) -> dict:
        return self._request("POST", "/auth/register", json={"email": email, "password": password})

    def login(self, email: str, password: str) -> str:
        """The session token."""
        body = self._request("POST", "/auth/login", json={"email": email, "password": password})
        return body["token"]

    def logout(self) -> None:
        self._request("POST", "/auth/logout")

    def me(self) -> dict:
        return self._request("GET", "/auth/me")

    def is_up(self) -> bool:
        try:
            return self.session.get(f"{self.base_url}/health", timeout=3).ok
        except requests.RequestException:
            return False

    def portfolio(self) -> dict:
        return self._request("GET", "/portfolio")

    def fixed_income(self) -> list[dict]:
        return self._request("GET", "/fixed-income")

    def create_fixed_income(self, payload: dict) -> dict:
        return self._request("POST", "/fixed-income", json=payload)

    def redeem_fixed_income(self, investment_id: int, day: str | None) -> dict:
        url = f"/fixed-income/{investment_id}/redemption"
        return self._request("PUT", url, json={"redeemed_on": day})

    def delete_fixed_income(self, investment_id: int) -> None:
        self._request("DELETE", f"/fixed-income/{investment_id}")

    def preview_b3_import(self, data: bytes) -> dict:
        return self._request("POST", "/imports/b3/preview", data=data, headers=XLSX_HEADER)

    def import_b3(self, data: bytes) -> dict:
        return self._request("POST", "/imports/b3", data=data, headers=XLSX_HEADER)

    def performance(self) -> dict:
        return self._request("GET", "/performance")

    def operations(self, ticker: str | None = None) -> list[dict]:
        params = {"ticker": ticker} if ticker else None
        return self._request("GET", "/operations", params=params)

    def create_operation(self, payload: dict) -> dict:
        return self._request("POST", "/operations", json=payload)

    def update_operation(self, operation_id: int, payload: dict) -> dict:
        return self._request("PUT", f"/operations/{operation_id}", json=payload)

    def delete_operation(self, operation_id: int) -> None:
        self._request("DELETE", f"/operations/{operation_id}")

    def stock_events(self) -> list[dict]:
        return self._request("GET", "/stock-events")

    def set_bonus_cost(self, ticker: str, record_date: str, unit_cost: str) -> None:
        url = f"/stock-events/{ticker}/{record_date}/unit-cost"
        self._request("PUT", url, json={"unit_cost": unit_cost})

    def delete_bonus_cost(self, ticker: str, record_date: str) -> None:
        self._request("DELETE", f"/stock-events/{ticker}/{record_date}/unit-cost")

    def incomes(self) -> list[dict]:
        return self._request("GET", "/income")

    def monthly_income(self, year: int | None = None) -> list[dict]:
        params = {"year": year} if year else None
        return self._request("GET", "/income/monthly", params=params)

    def create_income(self, payload: dict) -> dict:
        return self._request("POST", "/income", json=payload)

    def delete_income(self, income_id: int) -> None:
        self._request("DELETE", f"/income/{income_id}")

    def _request(self, method: str, path: str, **kwargs):
        try:
            r = self.session.request(method, self.base_url + path, timeout=self.timeout, **kwargs)
        except requests.RequestException as e:
            raise ApiError(f"Não foi possível falar com a API em {self.base_url}.") from e

        if r.status_code == 401 and path not in ("/auth/login", "/auth/register"):
            raise NotLoggedInError(error_message(r))
        if r.status_code >= 400:
            raise ApiError(error_message(r))
        if r.status_code == 204:
            return None
        return r.json(parse_float=Decimal)


FIELD_NAMES = {
    "ticker": "Ticker",
    "op_type": "Tipo",
    "date": "Data",
    "quantity": "Quantidade",
    "price": "Preço",
    "fees": "Taxas",
    "asset_type": "Classe do ativo",
    "income_type": "Tipo de provento",
    "amount": "Valor bruto",
    "tax": "IR retido",
    "unit_cost": "Custo atribuído",
    "name": "Nome",
    "product": "Produto",
    "indexer": "Indexador",
    "rate": "Taxa",
    "start": "Data da aplicação",
    "maturity": "Vencimento",
    "redeemed_on": "Data do resgate",
}

# The domain's validation messages for fixed income, in Portuguese.
FIXED_INCOME_MESSAGES = {
    "maturity must be after the start date": "O vencimento deve ser depois da aplicação.",
    "redemption must be between the start and the maturity": (
        "A data do resgate deve estar entre a aplicação e o vencimento."
    ),
}


def _br_date(iso: str) -> str:
    """'2026-01-05' -> '05/01/2026'"""
    year, month, day = iso.split("-")
    return f"{day}/{month}/{year}"


def _qty(value: str) -> str:
    return str(value).rstrip("0").rstrip(".") if "." in str(value) else str(value)


def domain_error(d: dict) -> str:
    """Our API's errors, translated from their stable code."""
    match d.get("code"):
        case "INSUFFICIENT_POSITION":
            return (
                f"Você tem {_qty(d['available'])} {d['ticker']} nessa data e "
                f"tentou vender {_qty(d['requested'])}."
            )
        case "DELETE_BREAKS_LATER_SALE":
            return (
                f"Apagar essa operação deixaria uma venda posterior de {d['ticker']} "
                "sem ações suficientes. Apague a venda primeiro."
            )
        case "EDIT_BREAKS_HISTORY":
            return (
                f"Com essa alteração, uma venda de {d['ticker']} ficaria sem ações: "
                f"haveria {_qty(d['available'])} e a venda é de {_qty(d['requested'])}."
            )
        case "EDIT_ORPHANS_INCOME":
            return (
                f"Com essa alteração, proventos de {d['ticker']} ficariam antes "
                "da primeira compra. Confira a data."
            )
        case "OPERATION_NOT_FOUND":
            return "Operação não encontrada. Talvez ela já tenha sido apagada."
        case "INCOME_WITHOUT_POSITION" if d.get("first_buy"):
            return (
                f"A primeira compra de {d['ticker']} foi em {_br_date(d['first_buy'])}, "
                f"então não pode haver provento em {_br_date(d['income_date'])}."
            )
        case "INCOME_WITHOUT_POSITION":
            return f"Não há compra de {d['ticker']} registrada. Confira o ticker."
        case "DELETE_ORPHANS_INCOME":
            return (
                f"Apagar essa compra deixaria proventos de {d['ticker']} recebidos "
                "antes de qualquer compra. Apague os proventos primeiro."
            )
        case "INVALID_CREDENTIALS":
            return "E-mail ou senha incorretos."
        case "EMAIL_TAKEN":
            return "Já existe uma conta com esse e-mail."
        case "WEAK_PASSWORD":
            return "A senha precisa ter pelo menos 8 caracteres."
        case "INVALID_EMAIL":
            return "E-mail inválido."
        case "NOT_AUTHENTICATED":
            return "Sua sessão expirou. Entre de novo."
        case "INVALID_STATEMENT" if "columns" in d.get("message", ""):
            return (
                "Esse arquivo não parece ser o extrato de Negociação da B3. Na Área do "
                "Investidor, use Extratos → Negociação e exporte em Excel."
            )
        case "INVALID_STATEMENT":
            return "O arquivo não é uma planilha Excel (.xlsx)."
        case "FILE_TOO_LARGE":
            return "Arquivo grande demais (máximo de 5 MB)."
        case "INVALID_FIXED_INCOME":
            return FIXED_INCOME_MESSAGES.get(d.get("message"), d.get("message", ""))
        case "FIXED_INCOME_NOT_FOUND":
            return "Aplicação não encontrada. Talvez ela já tenha sido apagada."
        case "STOCK_EVENT_NOT_FOUND":
            return "Não há bonificação desse ativo nessa data."
        case "INCOME_NOT_FOUND":
            return "Provento não encontrado. Talvez ele já tenha sido apagado."
        case _:
            return d.get("message", "Erro desconhecido da API.")


def _validation_error(err: dict) -> str:
    """One Pydantic validation error, e.g. price < 0, in Portuguese."""
    field = FIELD_NAMES.get(err["loc"][-1], err["loc"][-1]) if err.get("loc") else "Campo"
    ctx = err.get("ctx", {})
    messages = {
        "greater_than": f"deve ser maior que {ctx.get('gt')}",
        "greater_than_equal": "não pode ser negativo",
        "string_too_short": "não pode ficar vazio",
        "string_too_long": f"pode ter no máximo {ctx.get('max_length')} caracteres",
        "decimal_parsing": "não é um número válido",
        "enum": "valor inválido",
        "missing": "é obrigatório",
    }
    if err.get("type") in messages:
        return f"{field} {messages[err['type']]}"
    if "future" in err.get("msg", ""):
        return "A data não pode estar no futuro"
    if "larger than the amount" in err.get("msg", ""):
        return "O IR retido não pode ser maior que o valor bruto"
    return f"{field}: {err.get('msg', 'inválido')}"


def error_message(response: requests.Response) -> str:
    """Turn API error bodies into one readable sentence in Portuguese.

    Our own errors have {"detail": {"code": ..., ...}}; Pydantic validation
    errors have {"detail": [{"loc": [...], "type": ..., "msg": ...}, ...]}.
    """
    try:
        detail = response.json().get("detail")
    except ValueError:
        return f"Erro {response.status_code} da API."
    if isinstance(detail, dict):
        return domain_error(detail)
    if isinstance(detail, list):
        return "; ".join(_validation_error(err) for err in detail) + "."
    if isinstance(detail, str):
        return detail
    return f"Erro {response.status_code} da API."
