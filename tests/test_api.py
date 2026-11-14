from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from investtrack.api import create_app
from investtrack.db import create_db_engine
from investtrack.prices import StaticPriceProvider


@pytest.fixture
def client():
    """API backed by an in-memory database and fixed test prices."""
    app = create_app(
        engine=create_db_engine("sqlite://"),
        price_provider=StaticPriceProvider({"PETR4": Decimal("38"), "HGLG11": Decimal("160")}),
    )
    with TestClient(app) as c:  # "with" runs the startup/shutdown (lifespan)
        yield c


def op(op_type="BUY", qty="100", price="30", fees="0", ticker="PETR4", day="2026-01-01", **extra):
    return {"ticker": ticker, "op_type": op_type, "date": day,
            "quantity": qty, "price": price, "fees": fees, **extra}


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


# --- POST /operations --------------------------------------------------------

def test_create_operation(client):
    r = client.post("/operations", json=op(ticker="petr4", price="30.10"))
    assert r.status_code == 201
    body = r.json()
    assert body["id"] > 0
    assert body["ticker"] == "PETR4"
    assert body["price"] == "30.10"  # Decimal comes back as a string


def test_json_numbers_are_parsed_without_float_errors(client):
    r = client.post("/operations", json=op(qty=1, price=0.1, fees=0.2))
    assert r.status_code == 201
    assert Decimal(r.json()["price"]) + Decimal(r.json()["fees"]) == Decimal("0.3")


@pytest.mark.parametrize("field, value", [
    ("quantity", "0"),
    ("quantity", "-5"),
    ("price", "-1"),
    ("fees", "-1"),
    ("op_type", "HOLD"),
    ("ticker", ""),
    ("ticker", "   "),
    ("date", "not-a-date"),
])
def test_invalid_operation_is_rejected(client, field, value):
    r = client.post("/operations", json=op(**{field: value}))
    assert r.status_code == 422


def test_future_date_is_rejected(client):
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    assert client.post("/operations", json=op(day=tomorrow)).status_code == 422


def test_selling_more_than_owned_is_rejected(client):
    client.post("/operations", json=op(qty="100"))
    r = client.post("/operations", json=op("SELL", qty="101", day="2026-01-02"))
    assert r.status_code == 422
    assert "only 100 available" in r.json()["detail"]
    assert len(client.get("/operations").json()) == 1


# --- GET /operations ---------------------------------------------------------

def test_list_operations_ordered_and_filtered(client):
    client.post("/operations", json=op(ticker="HGLG11", day="2026-01-05"))
    client.post("/operations", json=op(day="2026-01-03"))

    all_ops = client.get("/operations").json()
    assert [o["date"] for o in all_ops] == ["2026-01-03", "2026-01-05"]

    only_fii = client.get("/operations", params={"ticker": "hglg11"}).json()
    assert [o["ticker"] for o in only_fii] == ["HGLG11"]


# --- DELETE /operations/{id} -------------------------------------------------

def test_delete_operation(client):
    created = client.post("/operations", json=op()).json()
    assert client.delete(f"/operations/{created['id']}").status_code == 204
    assert client.get("/operations").json() == []


def test_delete_unknown_operation(client):
    assert client.delete("/operations/999").status_code == 404


def test_delete_that_breaks_a_later_sale_is_refused(client):
    first_buy = client.post("/operations", json=op(qty="100")).json()
    client.post("/operations", json=op("SELL", qty="80", day="2026-01-02"))
    r = client.delete(f"/operations/{first_buy['id']}")
    assert r.status_code == 409
    assert len(client.get("/operations").json()) == 2


# --- GET /portfolio ----------------------------------------------------------

def test_portfolio_example_from_project_doc(client):
    client.post("/operations", json=op(qty="100", price="30", day="2026-01-01"))
    client.post("/operations", json=op(qty="100", price="40", day="2026-01-02"))
    client.post("/operations", json=op("SELL", qty="50", price="50", day="2026-01-03"))

    body = client.get("/portfolio").json()
    petr = body["positions"][0]
    assert petr == {
        "ticker": "PETR4",
        "quantity": "150",
        "avg_price": "35.00",
        "realized_profit": "750.00",
        "current_price": "38.00",
        "invested": "5250.00",
        "current_value": "5700.00",
        "result": "450.00",
        "result_pct": "8.57",
    }
    assert body["totals"]["result"] == "450.00"
    assert body["totals"]["realized_profit"] == "750.00"


def test_portfolio_totals_across_assets(client):
    client.post("/operations", json=op(qty="100", price="30"))                       # 3000 -> 3800
    client.post("/operations", json=op(ticker="HGLG11", qty="10", price="150"))      # 1500 -> 1600
    totals = client.get("/portfolio").json()["totals"]
    assert totals["invested"] == "4500.00"
    assert totals["current_value"] == "5400.00"
    assert totals["result"] == "900.00"
    assert totals["result_pct"] == "20.00"


def test_portfolio_with_unknown_price(client):
    client.post("/operations", json=op(ticker="XPTO3"))
    body = client.get("/portfolio").json()
    assert body["positions"][0]["current_price"] is None
    assert body["positions"][0]["result"] is None
    assert body["totals"]["current_value"] is None  # incomplete, so not shown


def test_empty_portfolio(client):
    body = client.get("/portfolio").json()
    assert body["positions"] == []
    assert body["totals"]["invested"] == "0.00"
    assert body["totals"]["result_pct"] is None
