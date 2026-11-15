import re
from contextlib import ExitStack, contextmanager
from datetime import date, timedelta
from decimal import Decimal

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from investtrack.api import SESSION_COOKIE, create_app
from investtrack.db import create_db_engine
from investtrack.events import StaticEvents
from investtrack.income import IncomeEvent, IncomeType
from investtrack.market_data import StaticMarketData
from investtrack.portfolio import StockEvent, StockEventType
from investtrack.prices import StaticPriceProvider
from tests.test_b3_statement import statement, trade

PRICES = StaticPriceProvider({"PETR4": Decimal("38"), "HGLG11": Decimal("160")})


# Real Argon2id with the cheapest parameters: logging in stays fast.
FAST_HASHER = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)


def log_in(c: TestClient, email: str = "ana@example.com", password: str = "long enough"):
    c.post("/auth/register", json={"email": email, "password": password})
    c.post("/auth/login", json={"email": email, "password": password})  # sets the cookie
    return c


@contextmanager
def api_client(**overrides):
    """An API with test doubles everywhere (no network), already logged in.

    In-memory database, fixed prices, no corporate events, fixed history.
    Each test overrides only what it is about.
    """
    own_engine = "engine" not in overrides
    settings = {
        "engine": create_db_engine("sqlite://") if own_engine else None,
        "price_provider": PRICES,
        "events": StaticEvents(),
        "market_data": StaticMarketData(),
        "password_hasher": FAST_HASHER,
    }
    settings.update(overrides)
    try:
        # "with" runs the lifespan; the base URL lets tests write "/health" for "/api/health".
        with TestClient(create_app(**settings), base_url="http://testserver/api") as c:
            yield log_in(c)
    finally:
        if own_engine:  # whoever creates an engine closes it
            settings["engine"].dispose()


@pytest.fixture
def shared_engine():
    """One database for two apps: two accounts using the same server."""
    engine = create_db_engine("sqlite://")
    yield engine
    engine.dispose()


@pytest.fixture
def client():
    with api_client() as c:
        yield c


def op(op_type="BUY", qty="100", price="30", fees="0", ticker="PETR4", day="2026-01-01", **extra):
    return {
        "ticker": ticker,
        "op_type": op_type,
        "date": day,
        "quantity": qty,
        "price": price,
        "fees": fees,
        **extra,
    }


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


@pytest.mark.parametrize(
    "field, value",
    [
        ("quantity", "0"),
        ("quantity", "-5"),
        ("price", "-1"),
        ("fees", "-1"),
        ("op_type", "HOLD"),
        ("ticker", ""),
        ("ticker", "   "),
        ("date", "not-a-date"),
    ],
)
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
    assert r.json()["detail"] == {
        "code": "INSUFFICIENT_POSITION",
        "message": "Cannot sell 101 PETR4: only 100 available",
        "ticker": "PETR4",
        "available": "100",
        "requested": "101",
    }
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
    r = client.delete("/operations/999")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "OPERATION_NOT_FOUND"


def test_delete_that_breaks_a_later_sale_is_refused(client):
    first_buy = client.post("/operations", json=op(qty="100")).json()
    client.post("/operations", json=op("SELL", qty="80", day="2026-01-02"))
    r = client.delete(f"/operations/{first_buy['id']}")
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "DELETE_BREAKS_LATER_SALE"
    assert len(client.get("/operations").json()) == 2


# --- PUT /operations/{id} ----------------------------------------------------


def test_update_operation(client):
    created = client.post("/operations", json=op()).json()
    r = client.put(f"/operations/{created['id']}", json=op(fees="4.90"))
    assert r.status_code == 200
    assert r.json() == created | {"fees": "4.90"}
    assert client.get("/portfolio").json()["positions"][0]["avg_price"] == "30.05"


def test_update_unknown_operation(client):
    r = client.put("/operations/999", json=op())
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "OPERATION_NOT_FOUND"


def test_update_that_breaks_a_later_sale_is_refused(client):
    first_buy = client.post("/operations", json=op(qty="100")).json()
    client.post("/operations", json=op("SELL", qty="80", day="2026-01-02"))
    r = client.put(f"/operations/{first_buy['id']}", json=op(qty="50"))
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert (detail["code"], detail["available"], detail["requested"]) == (
        "EDIT_BREAKS_HISTORY",
        "50",
        "80",
    )


def test_update_with_invalid_data(client):
    created = client.post("/operations", json=op()).json()
    assert client.put(f"/operations/{created['id']}", json=op(qty="0")).status_code == 422


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
        "price_as_of": None,
        "price_stale": False,
        "invested": "5250.00",
        "current_value": "5700.00",
        "result": "450.00",
        "result_pct": "8.57",
        "income": "0.00",
    }
    assert body["totals"]["result"] == "450.00"
    assert body["totals"]["realized_profit"] == "750.00"


def test_portfolio_totals_across_assets(client):
    client.post("/operations", json=op(qty="100", price="30"))  # 3000 -> 3800
    client.post("/operations", json=op(ticker="HGLG11", qty="10", price="150"))  # 1500 -> 1600
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


# --- income ------------------------------------------------------------------


def inc(kind="DIVIDEND", amount="10", tax="0", ticker="PETR4", day="2026-01-05"):
    return {"ticker": ticker, "income_type": kind, "date": day, "amount": amount, "tax": tax}


def test_create_income(client):
    client.post("/operations", json=op())
    r = client.post("/income", json=inc("JCP", amount="100", tax="15", ticker="petr4"))
    assert r.status_code == 201
    body = r.json()
    assert body["ticker"] == "PETR4"
    assert body["net"] == "85"


def test_income_before_first_buy_is_rejected(client):
    client.post("/operations", json=op(day="2026-01-10"))
    r = client.post("/income", json=inc(day="2026-01-05"))
    assert r.status_code == 422
    assert r.json()["detail"] == {
        "code": "INCOME_WITHOUT_POSITION",
        "message": "Income from PETR4 on 2026-01-05, but PETR4 was first bought on 2026-01-10",
        "ticker": "PETR4",
        "income_date": "2026-01-05",
        "first_buy": "2026-01-10",
    }


def test_income_for_unknown_ticker_is_rejected(client):
    r = client.post("/income", json=inc(ticker="PETR3"))
    assert r.status_code == 422
    assert r.json()["detail"]["first_buy"] is None


@pytest.mark.parametrize(
    "field, value",
    [("amount", "0"), ("tax", "-1"), ("tax", "10.01"), ("kind", "BONUS"), ("ticker", "")],
)
def test_invalid_income_is_rejected(client, field, value):
    client.post("/operations", json=op())
    assert client.post("/income", json=inc(**{field: value})).status_code == 422


def test_future_income_is_rejected(client):
    client.post("/operations", json=op())
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    assert client.post("/income", json=inc(day=tomorrow)).status_code == 422


def test_list_income_filtered(client):
    client.post("/operations", json=op())
    client.post("/operations", json=op(ticker="HGLG11"))
    client.post("/income", json=inc(day="2026-02-01"))
    client.post("/income", json=inc("DISTRIBUTION", ticker="HGLG11", day="2026-01-15"))

    assert [i["date"] for i in client.get("/income").json()] == ["2026-01-15", "2026-02-01"]
    assert len(client.get("/income", params={"ticker": "PETR4"}).json()) == 1
    assert client.get("/income", params={"year": 2025}).json() == []


def test_delete_income(client):
    client.post("/operations", json=op())
    created = client.post("/income", json=inc()).json()
    assert client.delete(f"/income/{created['id']}").status_code == 204
    assert client.get("/income").json() == []
    r = client.delete(f"/income/{created['id']}")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "INCOME_NOT_FOUND"


def test_deleting_buy_behind_income_is_refused(client):
    buy_op = client.post("/operations", json=op()).json()
    client.post("/income", json=inc())
    r = client.delete(f"/operations/{buy_op['id']}")
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "DELETE_ORPHANS_INCOME"


def test_income_per_month(client):
    client.post("/operations", json=op())
    client.post("/income", json=inc(amount="10", day="2026-01-05"))
    client.post("/income", json=inc("JCP", amount="100", tax="15", day="2026-01-20"))
    client.post("/income", json=inc(amount="5", day="2026-03-05"))

    months = client.get("/income/monthly").json()
    assert months[0] == {
        "year": 2026,
        "month": 1,
        "dividend": "10.00",
        "jcp": "85.00",
        "distribution": "0.00",
        "tax": "15.00",
        "net": "95.00",
    }
    assert [m["month"] for m in months] == [1, 3]
    assert client.get("/income/monthly", params={"year": 2025}).json() == []


def test_portfolio_includes_net_income_without_changing_avg_price(client):
    client.post("/operations", json=op(qty="100", price="30"))
    client.post("/income", json=inc("JCP", amount="100", tax="15"))
    client.post("/income", json=inc(amount="20"))

    body = client.get("/portfolio").json()
    assert body["positions"][0]["income"] == "105.00"
    assert body["positions"][0]["avg_price"] == "30.00"  # income is not a discount on cost
    assert body["totals"]["income"] == "105.00"


# --- income computed from B3 events -----------------------------------------


def event(kind, record_day, payment_day, rate, ticker="PETR4"):
    return IncomeEvent(
        ticker,
        IncomeType(kind),
        date.fromisoformat(record_day),
        date.fromisoformat(payment_day) if payment_day else None,
        Decimal(rate),
    )


@pytest.fixture
def events_client():
    """Factory: an API whose income events are the given list."""
    with ExitStack() as stack:
        yield lambda *events: stack.enter_context(api_client(events=StaticEvents(income=events)))


def test_income_is_computed_from_shares_held_on_record_date(events_client):
    client = events_client(event("JCP", "2026-03-10", "2026-03-31", "0.50"))
    client.post("/operations", json=op(qty="100", day="2026-01-05"))
    client.post("/operations", json=op(qty="50", day="2026-03-10"))  # on the record date: counts
    client.post("/operations", json=op("SELL", qty="30", day="2026-03-11"))  # after: doesn't

    [income] = client.get("/income").json()
    assert income["source"] == "B3"
    assert income["id"] is None  # computed, so it can't be deleted
    assert income["quantity"] == "150"
    assert income["record_date"] == "2026-03-10"
    assert Decimal(income["amount"]) == Decimal("75")
    assert Decimal(income["tax"]) == Decimal("11.25")  # 15% withheld on JCP
    assert Decimal(income["net"]) == Decimal("63.75")


def test_no_income_without_shares_on_record_date(events_client):
    client = events_client(event("DIVIDEND", "2026-01-02", "2026-01-20", "1"))
    client.post("/operations", json=op(day="2026-01-03"))  # bought one day late
    assert client.get("/income").json() == []


def test_fixing_a_trade_fixes_the_income(events_client):
    client = events_client(event("DIVIDEND", "2026-02-01", "2026-02-15", "1"))
    client.post("/operations", json=op(qty="100", day="2026-01-05"))
    extra = client.post("/operations", json=op(qty="100", day="2026-01-06")).json()
    assert client.get("/income").json()[0]["quantity"] == "200"

    client.delete(f"/operations/{extra['id']}")
    assert client.get("/income").json()[0]["quantity"] == "100"


def test_pending_income_is_separate_from_received(events_client):
    future = (date.today() + timedelta(days=30)).isoformat()
    client = events_client(
        event("DIVIDEND", "2026-02-01", "2026-02-15", "1"),
        event("DIVIDEND", "2026-03-01", future, "2"),
    )
    client.post("/operations", json=op(qty="10", day="2026-01-05"))

    incomes = client.get("/income").json()
    assert [i["pending"] for i in incomes] == [False, True]

    totals = client.get("/portfolio").json()["totals"]
    assert totals["income"] == "10.00"
    assert totals["income_pending"] == "20.00"
    assert [m["net"] for m in client.get("/income/monthly").json()] == ["10.00"]


def test_portfolio_adds_manual_and_computed_income(events_client):
    client = events_client(event("DIVIDEND", "2026-02-01", "2026-02-15", "1"))
    client.post("/operations", json=op(qty="10", day="2026-01-05"))
    client.post("/income", json=inc(amount="5", day="2026-01-10"))

    sources = [i["source"] for i in client.get("/income").json()]
    assert sources == ["MANUAL", "B3"]
    assert client.get("/portfolio").json()["positions"][0]["income"] == "15.00"


def test_income_filters_apply_to_computed_income(events_client):
    client = events_client(
        event("DIVIDEND", "2025-12-01", "2025-12-15", "1"),
        event("DIVIDEND", "2026-02-01", "2026-02-15", "1"),
    )
    client.post("/operations", json=op(qty="10", day="2025-11-05"))
    assert [i["date"] for i in client.get("/income", params={"year": 2026}).json()] == [
        "2026-02-15"
    ]
    assert client.get("/income", params={"ticker": "vale3"}).json() == []


# --- stock events ------------------------------------------------------------


def split_event(day, multiplier="2", ticker="PETR4"):
    return StockEvent(ticker, StockEventType.SPLIT, date.fromisoformat(day), Decimal(multiplier))


@pytest.fixture
def split_client():
    with api_client(events=StaticEvents(stock=[split_event("2026-02-01")])) as c:
        yield c


def test_portfolio_applies_splits(split_client):
    split_client.post("/operations", json=op(qty="100", price="30", day="2026-01-05"))
    petr = split_client.get("/portfolio").json()["positions"][0]
    assert petr["quantity"] == "200"
    assert petr["avg_price"] == "15.00"
    assert petr["invested"] == "3000.00"


def test_selling_split_shares_is_accepted(split_client):
    split_client.post("/operations", json=op(qty="100", day="2026-01-05"))
    r = split_client.post("/operations", json=op("SELL", qty="200", day="2026-02-02"))
    assert r.status_code == 201


def test_deleting_is_checked_with_splits(split_client):
    first = split_client.post("/operations", json=op(qty="100", day="2026-01-05")).json()
    split_client.post("/operations", json=op(qty="100", day="2026-01-06"))
    split_client.post("/operations", json=op("SELL", qty="300", day="2026-02-02"))
    r = split_client.delete(f"/operations/{first['id']}")
    assert r.status_code == 409  # 100 x 2 = 200 left, but 300 were sold


def test_list_applied_stock_events(split_client):
    split_client.post("/operations", json=op(qty="100", day="2026-01-05"))
    assert split_client.get("/stock-events").json() == [
        {
            "ticker": "PETR4",
            "event_type": "SPLIT",
            "record_date": "2026-02-01",
            "multiplier": "2",
            "quantity_before": "100",
            "quantity_after": "200",
            "unit_cost": None,
        }
    ]


# --- attributed cost of bonus shares -----------------------------------------


@pytest.fixture
def bonus_client():
    """A 10% bonus on 2026-02-01 and a split on 2026-03-01."""
    bonus = StockEvent("PETR4", StockEventType.BONUS, date(2026, 2, 1), Decimal("1.1"))
    with api_client(events=StaticEvents(stock=[bonus, split_event("2026-03-01")])) as c:
        c.post("/operations", json=op(qty="100", price="30", day="2026-01-05"))
        yield c


COST_URL = "/stock-events/PETR4/2026-02-01/unit-cost"


def test_bonus_without_cost_counts_as_zero(bonus_client):
    petr = bonus_client.get("/portfolio").json()["positions"][0]
    assert petr["quantity"] == "220"  # 100 -> 110 -> 220
    assert petr["invested"] == "3000.00"
    assert bonus_client.get("/stock-events").json()[0]["unit_cost"] is None


def test_attributed_cost_raises_the_average_price(bonus_client):
    assert bonus_client.put(COST_URL, json={"unit_cost": "4"}).status_code == 204
    petr = bonus_client.get("/portfolio").json()["positions"][0]
    assert petr["invested"] == "3040.00"  # + 10 bonus shares x R$ 4, then split
    assert bonus_client.get("/stock-events").json()[0]["unit_cost"] == "4"


def test_attributed_cost_can_be_changed_and_removed(bonus_client):
    bonus_client.put(COST_URL, json={"unit_cost": "4"})
    bonus_client.put(COST_URL, json={"unit_cost": "5"})
    assert bonus_client.get("/portfolio").json()["positions"][0]["invested"] == "3050.00"

    assert bonus_client.delete(COST_URL).status_code == 204
    assert bonus_client.get("/portfolio").json()["positions"][0]["invested"] == "3000.00"


@pytest.mark.parametrize(
    "url",
    [
        "/stock-events/PETR4/2026-02-02/unit-cost",  # wrong date
        "/stock-events/PETR4/2026-03-01/unit-cost",  # a split, not a bonus
        "/stock-events/VALE3/2026-02-01/unit-cost",  # not in the portfolio
    ],
)
def test_cost_for_missing_bonus_is_rejected(bonus_client, url):
    r = bonus_client.put(url, json={"unit_cost": "4"})
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "STOCK_EVENT_NOT_FOUND"


def test_negative_cost_is_rejected(bonus_client):
    assert bonus_client.put(COST_URL, json={"unit_cost": "-1"}).status_code == 422


def test_cost_is_used_when_validating_sales(bonus_client):
    bonus_client.put(COST_URL, json={"unit_cost": "4"})
    r = bonus_client.post("/operations", json=op("SELL", qty="220", price="20", day="2026-03-02"))
    assert r.status_code == 201
    realized = bonus_client.get("/portfolio").json()["totals"]["realized_profit"]
    assert realized == "1360.00"  # 220 x 20 - 3040


# --- performance -------------------------------------------------------------

MON, TUE = date(2026, 3, 2), date(2026, 3, 3)


def performance_client(market):
    return api_client(market_data=market)


HISTORY = StaticMarketData(
    closes={"PETR4": {MON: Decimal("10"), TUE: Decimal("11")}},
    series={
        "IBOV": {date(2026, 2, 27): Decimal("100"), MON: Decimal("110"), TUE: Decimal("121")},
        "CDI": {MON: Decimal("1")},
    },
    last_day=TUE,
)


def test_performance_against_benchmarks():
    with performance_client(HISTORY) as client:
        client.post("/operations", json=op(qty="100", price="10", day="2026-03-02"))
        body = client.get("/performance").json()

    assert body["syncing"] is False
    assert (body["start"], body["as_of"]) == ("2026-03-02", "2026-03-03")
    assert body["twr"] == "10.00"
    assert body["cdi"] == "1.00"
    assert body["ibovespa"] == "21.00"  # from the close before the first trade
    assert body["pct_of_cdi"] == "1000.00"
    assert body["points"][0] == {
        "date": "2026-03-02",
        "value": "1000.00",
        "net_worth": "1000.00",  # no fixed income: no tax to take out
        "invested": "1000.00",  # 100 x 10, the money put in
        "twr": "0.00",
        "cdi": "0.00",
        "ibovespa": "10.00",
    }


def test_price_today_is_the_current_quote():
    with performance_client(HISTORY) as client:
        body = client.get("/prices/petr4").json()
    assert body == {
        "ticker": "PETR4",
        "date": date.today().isoformat(),
        "price": "38.00",
        "source": "QUOTE",
    }


def test_price_on_an_earlier_day_is_that_close_or_the_one_before():
    with performance_client(HISTORY) as client:
        on_tuesday = client.get("/prices/PETR4", params={"date": TUE.isoformat()}).json()
        weekend = TUE + timedelta(days=4)  # Saturday: Tuesday's is the last close
        saturday = client.get("/prices/PETR4", params={"date": weekend.isoformat()}).json()
        unknown = client.get("/prices/VALE3", params={"date": TUE.isoformat()})
        bad = client.get("/prices/PETR-4")
    assert (on_tuesday["price"], on_tuesday["source"]) == ("11.00", "CLOSE")
    assert (saturday["date"], saturday["price"]) == (TUE.isoformat(), "11.00")
    assert (unknown.status_code, unknown.json()["detail"]["code"]) == (404, "PRICE_NOT_FOUND")
    assert bad.status_code == 422


LONG_HISTORY = StaticMarketData(
    closes={
        "PETR4": {
            date(2026, 1, 5): Decimal("10"),
            date(2026, 2, 2): Decimal("12"),
            date(2026, 3, 2): Decimal("15"),
            date(2026, 3, 3): Decimal("18"),
        }
    },
    series={
        "IBOV": {
            date(2026, 1, 2): Decimal("100"),
            date(2026, 1, 5): Decimal("100"),
            date(2026, 2, 2): Decimal("200"),
            date(2026, 3, 2): Decimal("250"),
            date(2026, 3, 3): Decimal("300"),
        },
        "CDI": {date(2026, 1, 5): Decimal("1"), date(2026, 2, 2): Decimal("1"), MON: Decimal("1")},
    },
    last_day=TUE,
)


def test_performance_of_a_period_starts_at_zero():
    with performance_client(LONG_HISTORY) as client:
        client.post("/operations", json=op(qty="100", price="10", day="2026-01-05"))
        whole = client.get("/performance").json()
        month = client.get("/performance", params={"period": "1M"}).json()

    assert whole["twr"] == "80.00"
    # 03/03 - 1 month = 03/02 (3 Feb), which has no close: the window starts at 02/02's.
    assert month["start"] == "2026-02-02"
    assert [p["date"] for p in month["points"]] == ["2026-02-02", "2026-03-02", "2026-03-03"]
    assert month["points"][0] == {
        "date": "2026-02-02",
        "value": "1200.00",
        "net_worth": "1200.00",
        "invested": "1000.00",  # since the first trade, not since the period's start
        "twr": "0.00",
        "cdi": "0.00",
        "ibovespa": "0.00",
    }
    assert month["twr"] == "50.00"  # 18 / 12 - 1
    assert month["ibovespa"] == "50.00"  # 300 / 200 - 1
    assert month["cdi"] == "2.01"  # the rates of 02/02 and 02/03, earned overnight
    assert month["pct_of_cdi"] == "2487.56"


def test_period_longer_than_the_history_shows_everything():
    with performance_client(LONG_HISTORY) as client:
        client.post("/operations", json=op(qty="100", price="10", day="2026-01-05"))
        year = client.get("/performance", params={"period": "1Y"}).json()
    assert year["start"] == "2026-01-05"
    assert year["twr"] == "80.00"


def test_unknown_period_is_refused():
    with performance_client(LONG_HISTORY) as client:
        assert client.get("/performance", params={"period": "2Y"}).status_code == 422


def test_fees_count_as_money_put_in_not_as_net_worth():
    # The ITUB4 case: bought at the close, plus fees. Net worth is the market
    # value; the money put in has the fees, so gain = net worth - money in.
    with performance_client(HISTORY) as client:
        client.post("/operations", json=op(qty="100", price="10", fees="7.90", day="2026-03-02"))
        body = client.get("/performance").json()
    first = body["points"][0]
    assert (first["net_worth"], first["invested"]) == ("1000.00", "1007.90")
    assert body["invested_now"] == "1007.90"


def test_money_in_now_counts_a_sale_after_the_last_close():
    with performance_client(HISTORY) as client:  # history ends on TUE
        client.post("/operations", json=op(qty="100", price="10", day="2026-03-02"))
        sale = op("SELL", qty="40", price="12", fees="1", day="2026-03-05")
        client.post("/operations", json=sale)
        body = client.get("/performance").json()
    assert body["points"][-1]["invested"] == "1000.00"  # the sale isn't in the history yet
    assert body["invested_now"] == "521.00"  # 1000 - (40 x 12 - 1)


def test_performance_without_operations():
    with performance_client(HISTORY) as client:
        body = client.get("/performance").json()
    assert body["points"] == []
    assert body["twr"] is None


class UnsyncedMarket(StaticMarketData):
    def __init__(self):
        super().__init__(last_day=TUE)
        self.synced_from = []

    def is_synced(self, start):
        return False

    def sync(self, start):
        self.synced_from.append(start)


def test_missing_history_is_downloaded_in_the_background():
    market = UnsyncedMarket()
    with performance_client(market) as client:
        client.post("/operations", json=op(day="2026-03-02"))
        body = client.get("/performance").json()
    assert body["syncing"] is True
    assert market.synced_from == [MON]  # TestClient runs background tasks after the response


# --- fixed income ------------------------------------------------------------

WED = date(2026, 3, 4)
ONE_PERCENT_A_DAY = StaticMarketData(
    series={
        "CDI": {MON: Decimal("1"), TUE: Decimal("1")},  # Wednesday's rate not published yet
        "IBOV": {MON: Decimal("100"), TUE: Decimal("100"), WED: Decimal("100")},
    },
    last_day=WED,
)


def fixed(product="LCI", rate="100", start="2026-03-02", maturity="2027-03-02", **extra):
    return {
        "name": "LCI Banco X",
        "product": product,
        "indexer": "CDI",
        "rate": rate,
        "start": start,
        "maturity": maturity,
        "amount": "1000",
        **extra,
    }


@pytest.fixture
def fi_client():
    with performance_client(ONE_PERCENT_A_DAY) as c:
        yield c


def test_create_fixed_income_and_value_it(fi_client):
    r = fi_client.post("/fixed-income", json=fixed())
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "ACTIVE"
    assert body["as_of"] == "2026-03-04"
    assert body["gross"] == "1020.10"  # 1000 x 1.01 x 1.01
    assert body["net"] == "1020.10"  # LCI: no tax
    assert body["gross_return"] == "2.01"
    assert body["estimated"] is False


def test_cdb_shows_taxes(fi_client):
    body = fi_client.post("/fixed-income", json=fixed(product="CDB")).json()
    assert Decimal(body["iof"]) > 0  # redeemed within 30 days
    assert Decimal(body["ir"]) > 0
    assert Decimal(body["net"]) < Decimal(body["gross"])


@pytest.mark.parametrize(
    "changes",
    [
        {"maturity": "2026-03-01"},  # before the start
        {"rate": "0"},
        {"product": "TESOURO"},
        {"start": (date.today() + timedelta(days=1)).isoformat()},
    ],
)
def test_invalid_fixed_income_is_rejected(fi_client, changes):
    assert fi_client.post("/fixed-income", json=fixed(**changes)).status_code == 422


def test_domain_error_has_a_code(fi_client):
    r = fi_client.post("/fixed-income", json=fixed(maturity="2026-03-01"))
    assert r.json()["detail"]["code"] == "INVALID_FIXED_INCOME"


def test_early_redemption_and_undo(fi_client):
    created = fi_client.post("/fixed-income", json=fixed()).json()
    url = f"/fixed-income/{created['id']}/redemption"

    redeemed = fi_client.put(url, json={"redeemed_on": "2026-03-03"}).json()
    assert (redeemed["status"], redeemed["gross"]) == ("REDEEMED", "1010.00")

    undone = fi_client.put(url, json={"redeemed_on": None}).json()
    assert undone["status"] == "ACTIVE"

    r = fi_client.put(url, json={"redeemed_on": "2026-02-01"})
    assert r.status_code == 422
    assert (
        fi_client.put("/fixed-income/99/redemption", json={"redeemed_on": None}).status_code == 404
    )


def test_delete_fixed_income(fi_client):
    created = fi_client.post("/fixed-income", json=fixed()).json()
    assert fi_client.delete(f"/fixed-income/{created['id']}").status_code == 204
    assert fi_client.get("/fixed-income").json() == []
    assert fi_client.delete(f"/fixed-income/{created['id']}").status_code == 404


def test_ipca_plus_is_valued_and_flagged_as_estimate():
    market = StaticMarketData(
        series={
            "CDI": {MON: Decimal("1"), TUE: Decimal("1")},
            "IBOV": {MON: Decimal("100"), TUE: Decimal("100"), WED: Decimal("100")},
            "IPCA": {date(2026, 2, 1): Decimal("1")},  # March not published yet
        },
        last_day=WED,
    )
    with performance_client(market) as c:
        body = c.post("/fixed-income", json=fixed(indexer="IPCA", rate="6")).json()
        assert body["indexer"] == "IPCA"
        assert body["as_of"] == WED.isoformat()
        assert body["estimated"] is True
        assert Decimal(body["gross"]) > 1000


def test_partial_redemption(fi_client):
    created = fi_client.post("/fixed-income", json=fixed(product="CDB")).json()
    url = f"/fixed-income/{created['id']}/partial-redemptions"
    r = fi_client.post(url, json={"date": "2026-03-03", "gross": "505"})  # half of 1010
    assert r.status_code == 201
    body = r.json()
    assert (body["gross"], body["principal"], body["gross_return"]) == ("510.05", "500.00", "2.01")
    [withdrawal] = body["partial_redemptions"]
    assert (withdrawal["gross"], withdrawal["iof"]) == ("505.00", "4.80")  # 96% of the 5 gain

    r = fi_client.delete(f"{url}/{withdrawal['id']}")
    assert (r.status_code, r.json()["gross"], r.json()["partial_redemptions"]) == (
        200,
        "1020.10",
        [],
    )
    assert fi_client.delete(f"{url}/{withdrawal['id']}").status_code == 404


@pytest.mark.parametrize(
    "payload, code",
    [
        ({"date": "2026-03-03", "gross": "1010"}, "REDEMPTION_TOO_LARGE"),
        ({"date": "2026-03-02", "gross": "10"}, "INVALID_PARTIAL_REDEMPTION"),  # the start
        ({"date": "2026-03-01", "gross": "10"}, "INVALID_PARTIAL_REDEMPTION"),
    ],
)
def test_partial_redemption_errors(fi_client, payload, code):
    created = fi_client.post("/fixed-income", json=fixed()).json()
    r = fi_client.post(f"/fixed-income/{created['id']}/partial-redemptions", json=payload)
    assert (r.status_code, r.json()["detail"]["code"]) == (422, code)
    assert fi_client.get("/fixed-income").json()[0]["partial_redemptions"] == []


def test_partial_redemption_on_a_day_without_value(fi_client):
    with performance_client(ONE_PERCENT_A_DAY) as c:
        created = c.post("/fixed-income", json=fixed(start="2026-02-27")).json()
        r = c.post(  # a Sunday, inside the period
            f"/fixed-income/{created['id']}/partial-redemptions",
            json={"date": "2026-03-01", "gross": "10"},
        )
        assert r.json()["detail"]["code"] == "VALUE_NOT_KNOWN"


def test_deleting_an_investment_deletes_its_withdrawals(fi_client):
    created = fi_client.post("/fixed-income", json=fixed()).json()
    url = f"/fixed-income/{created['id']}/partial-redemptions"
    fi_client.post(url, json={"date": "2026-03-03", "gross": "100"})
    fi_client.delete(f"/fixed-income/{created['id']}")
    assert fi_client.delete(f"{url}/1").status_code == 404


def test_portfolio_totals_include_fixed_income_still_invested(fi_client):
    fi_client.post("/fixed-income", json=fixed())
    redeemed = fi_client.post("/fixed-income", json=fixed()).json()
    fi_client.put(f"/fixed-income/{redeemed['id']}/redemption", json={"redeemed_on": "2026-03-03"})
    assert fi_client.get("/portfolio").json()["totals"]["fixed_income"] == "1020.10"


def test_portfolio_says_when_fixed_income_is_settled(fi_client):
    fi_client.post("/fixed-income", json=fixed())
    body = fi_client.get("/portfolio").json()
    assert (body["totals"]["fixed_income"], body["syncing"]) == ("1020.10", False)


def test_unknown_fixed_income_is_not_left_out_of_the_total():
    # No CDI yet (still downloading): the investment has no value. The total
    # is unknown rather than smaller, and the screen is told to ask again.
    with performance_client(StaticMarketData()) as client:
        client.post("/fixed-income", json=fixed())
        body = client.get("/portfolio").json()
    assert (body["totals"]["fixed_income"], body["syncing"]) == (None, True)


def test_lci_at_100_percent_of_cdi_earns_exactly_the_cdi(fi_client):
    fi_client.post("/fixed-income", json=fixed())
    body = fi_client.get("/performance").json()
    assert body["twr"] == body["cdi"] == "2.01"
    assert body["pct_of_cdi"] == "100.00"


def test_net_worth_over_time_ends_where_the_portfolio_is(fi_client):
    # A CDB two days old: IOF and income tax take most of the gain.
    fi_client.post("/fixed-income", json=fixed(product="CDB"))
    last = fi_client.get("/performance").json()["points"][-1]
    assert last["value"] == "1020.10"  # gross: what the return is measured on
    # Net: the same number the Carteira shows as fixed income, so the chart
    # ends exactly at the Patrimônio card.
    assert last["net_worth"] == fi_client.get("/portfolio").json()["totals"]["fixed_income"]
    assert last["net_worth"] < last["value"]


# --- accounts and isolation --------------------------------------------------

PUBLIC = {("GET", "/health"), ("POST", "/auth/register"), ("POST", "/auth/login")}


def all_routes():
    """Every route of the API, read from its OpenAPI schema: the public list
    of what it answers. (app.routes no longer lists the routes of an included
    router one by one, which once made this test check nothing at all.)"""
    schema = create_app(password_hasher=FAST_HASHER).openapi()  # the lifespan never runs
    routes = {
        (method.upper(), path.removeprefix("/api"))
        for path, operations in schema["paths"].items()
        for method in operations
    }
    assert len(routes) > 20, "found no routes: this test would pass without checking anything"
    return routes


@pytest.mark.parametrize("method, path", sorted(set(all_routes()) - PUBLIC))
def test_every_endpoint_requires_login(method, path):
    """Covers endpoints added later too: forgetting the login check fails here."""
    url = path.replace("{ticker}", "PETR4").replace("{record_date}", "2026-01-05")
    url = re.sub(r"\{\w+_id\}", "1", url)
    with api_client() as c:
        c.cookies.clear()
        r = c.request(method, url, json={})
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "NOT_AUTHENTICATED"


@pytest.mark.parametrize("value", ["made-up", ""])
def test_bad_session_cookies(client, value):
    client.cookies.set(SESSION_COOKIE, value, path="/api")
    assert client.get("/portfolio").status_code == 401


def test_session_cookie_is_out_of_reach_of_scripts():
    with api_client() as c:
        r = c.post("/auth/login", json={"email": "ana@example.com", "password": "long enough"})
    cookie = r.headers["set-cookie"]
    assert cookie.startswith(f"{SESSION_COOKIE}=")
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie
    assert "Path=/api" in cookie
    assert "Secure" not in cookie  # plain http, as in development
    assert set(r.json()) == {"expires_at"}  # the token is never in the body


def test_session_cookie_is_secure_over_https():
    with api_client() as c:
        r = c.post(
            "https://testserver/api/auth/login",
            json={"email": "ana@example.com", "password": "long enough"},
        )
    assert "Secure" in r.headers["set-cookie"]


def test_users_only_see_their_own_data(shared_engine):
    engine = shared_engine
    with api_client(engine=engine) as ana:
        ana.post("/operations", json=op(qty="100"))
        ana.post("/fixed-income", json=fixed())
        with api_client(engine=engine) as bia:  # same database, another account
            log_in(bia, "bia@example.com")
            assert bia.get("/operations").json() == []
            assert bia.get("/portfolio").json()["positions"] == []
            assert bia.get("/fixed-income").json() == []
            assert bia.get("/income").json() == []

            bia.post("/operations", json=op(qty="5"))
            assert [o["quantity"] for o in ana.get("/operations").json()] == ["100"]


def test_other_users_rows_look_missing(shared_engine):
    engine = shared_engine
    with api_client(engine=engine) as ana:
        operation = ana.post("/operations", json=op()).json()
        investment = ana.post("/fixed-income", json=fixed()).json()
        with api_client(engine=engine) as bia:
            log_in(bia, "bia@example.com")
            r = bia.delete(f"/operations/{operation['id']}")
            assert r.status_code == 404  # not 403: ids reveal nothing
            assert bia.put(f"/operations/{operation['id']}", json=op()).status_code == 404
            assert bia.delete(f"/fixed-income/{investment['id']}").status_code == 404
            url = f"/fixed-income/{investment['id']}/redemption"
            assert bia.put(url, json={"redeemed_on": None}).status_code == 404
            partial = f"/fixed-income/{investment['id']}/partial-redemptions"
            assert bia.post(partial, json={"date": "2026-03-03", "gross": "1"}).status_code == 404
        assert len(ana.get("/operations").json()) == 1


def test_selling_is_checked_against_your_own_position(shared_engine):
    engine = shared_engine
    with api_client(engine=engine) as ana:
        ana.post("/operations", json=op(qty="100"))
        with api_client(engine=engine) as bia:
            log_in(bia, "bia@example.com")
            r = bia.post("/operations", json=op("SELL", qty="10", day="2026-01-02"))
            assert r.status_code == 422  # Ana's shares are not Bia's


def test_register_and_login_errors():
    with api_client() as c:  # already registered as ana@example.com
        taken = c.post(
            "/auth/register", json={"email": "ANA@example.com", "password": "long enough"}
        )
        assert (taken.status_code, taken.json()["detail"]["code"]) == (409, "EMAIL_TAKEN")
        weak = c.post("/auth/register", json={"email": "bia@example.com", "password": "short"})
        assert weak.json()["detail"]["code"] == "WEAK_PASSWORD"
        bad = c.post("/auth/register", json={"email": "bia", "password": "long enough"})
        assert bad.json()["detail"]["code"] == "INVALID_EMAIL"
        wrong = c.post("/auth/login", json={"email": "ana@example.com", "password": "wrong one"})
        assert (wrong.status_code, wrong.json()["detail"]["code"]) == (401, "INVALID_CREDENTIALS")


def test_too_many_failed_logins():
    with api_client() as c:
        wrong = {"email": "ana@example.com", "password": "wrong one"}
        for _ in range(5):
            c.post("/auth/login", json=wrong)
        r = c.post("/auth/login", json=wrong | {"password": "long enough"})
        assert r.status_code == 429
        assert r.json()["detail"]["code"] == "TOO_MANY_ATTEMPTS"
        assert r.headers["Retry-After"] == str(r.json()["detail"]["retry_after"]) == "900"


def test_me_and_logout(client):
    assert client.get("/auth/me").json()["email"] == "ana@example.com"
    token = client.cookies[SESSION_COOKIE]
    r = client.post("/auth/logout")
    assert r.status_code == 204
    assert f'{SESSION_COOKIE}=""' in r.headers["set-cookie"]  # the browser forgets it
    client.cookies.set(SESSION_COOKIE, token, path="/api")
    assert client.get("/auth/me").status_code == 401  # and the server too: a copy is useless


def test_me_says_when_the_account_was_created(client):
    created = client.get("/auth/me").json()["created_at"]
    assert created.endswith(("Z", "+00:00"))  # UTC, even from SQLite


def test_change_password(client):
    wrong = client.post(
        "/auth/password", json={"current_password": "wrong one", "new_password": "a new one!"}
    )
    # 403, not 401: the session is fine, and the app must not log out.
    assert (wrong.status_code, wrong.json()["detail"]["code"]) == (403, "WRONG_PASSWORD")
    weak = client.post(
        "/auth/password", json={"current_password": "long enough", "new_password": "short"}
    )
    assert (weak.status_code, weak.json()["detail"]["code"]) == (422, "WEAK_PASSWORD")

    ok = client.post(
        "/auth/password", json={"current_password": "long enough", "new_password": "a new one!"}
    )
    assert ok.status_code == 204
    assert client.get("/auth/me").status_code == 200  # this session goes on
    login = {"email": "ana@example.com", "password": "a new one!"}
    assert client.post("/auth/login", json=login).status_code == 200


# --- B3 statement import -----------------------------------------------------

XLSX = {"Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
FILE = statement(
    trade(day="05/01/2026", qty=100, price=30),
    trade(day="05/01/2026", market="Mercado Fracionário", ticker="PETR4F", qty=5, price=30),
    trade(day="10/03/2026", kind="Venda", qty=50, price=50),
    trade(day="10/03/2026", market="Opção de Compra", ticker="PETRK300"),
)


def test_preview_saves_nothing(client):
    body = client.post("/imports/b3/preview", content=FILE, headers=XLSX).json()
    assert (body["imported"], body["new"], body["skipped"]) == (False, 3, 1)
    assert [r["ticker"] for r in body["rows"]] == ["PETR4"] * 3
    assert body["skipped_rows"][0]["reason"] == "UNSUPPORTED_MARKET"
    assert client.get("/operations").json() == []


def test_import_and_import_again(client):
    first = client.post("/imports/b3", content=FILE, headers=XLSX).json()
    assert first["imported"] is True
    assert [r["status"] for r in first["rows"]] == ["IMPORTED"] * 3
    petr = client.get("/portfolio").json()["positions"][0]
    assert (petr["quantity"], petr["avg_price"]) == ("55", "30.00")
    assert client.get("/operations").json()[0]["fees"] == "0"  # the statement has no fees

    again = client.post("/imports/b3", content=FILE, headers=XLSX).json()
    assert (again["new"], again["duplicates"]) == (0, 3)
    assert len(client.get("/operations").json()) == 3


def test_typed_operation_is_recognized(client):
    client.post("/operations", json=op(qty="100", price="30", fees="4.90", day="2026-01-05"))
    body = client.post("/imports/b3/preview", content=FILE, headers=XLSX).json()
    assert [r["status"] for r in body["rows"]] == ["DUPLICATE", "NEW", "NEW"]


def test_sale_without_shares_is_rejected_with_the_reason(client):
    sale = statement(trade(day="20/10/2026", kind="Venda", ticker="RECV3F", qty=9, price=12.66))
    body = client.post("/imports/b3", content=sale, headers=XLSX).json()
    assert body["rejected"] == 1
    assert body["rows"][0]["error"]["code"] == "INSUFFICIENT_POSITION"
    assert body["rows"][0]["error"]["available"] == "0"
    assert client.get("/operations").json() == []


def test_new_ticker_gets_a_guessed_type(client):
    fii = statement(trade(ticker="HGLG11", qty=10, price=158.4))
    client.post("/imports/b3", content=fii, headers=XLSX)
    assert client.get("/operations").json()[0]["ticker"] == "HGLG11"


def test_invalid_statement(client):
    r = client.post("/imports/b3/preview", content=b"not a spreadsheet", headers=XLSX)
    assert (r.status_code, r.json()["detail"]["code"]) == (422, "INVALID_STATEMENT")


def test_too_large_is_refused_before_reading(client):
    big = b"x" * (5 * 1024 * 1024 + 1)
    r = client.post("/imports/b3/preview", content=big, headers=XLSX)
    assert (r.status_code, r.json()["detail"]["code"]) == (413, "FILE_TOO_LARGE")


# --- serving the web app -----------------------------------------------------


@pytest.fixture
def web_client(tmp_path):
    """The API plus a fake build of the web app, as deployed."""
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>InvestTrack</title>")
    (tmp_path / "assets" / "index-abc123.js").write_text("console.log(1)")
    (tmp_path / "favicon.svg").write_text("<svg/>")
    (tmp_path.parent / "secret.txt").write_text("outside the build")
    engine = create_db_engine("sqlite://")
    app = create_app(
        engine=engine,
        price_provider=PRICES,
        events=StaticEvents(),
        market_data=StaticMarketData(),
        password_hasher=FAST_HASHER,
        web_dir=tmp_path,
    )
    with TestClient(app) as c:
        yield c
    engine.dispose()


@pytest.mark.parametrize("path", ["/", "/proventos", "/renda-fixa", "/rentabilidade?periodo=6M"])
def test_every_page_of_the_app_gets_index_html(web_client, path):
    r = web_client.get(path)
    assert r.status_code == 200
    assert "<title>InvestTrack</title>" in r.text
    assert r.headers["cache-control"] == "no-cache"  # always the newest build


def test_built_assets_are_cached_forever(web_client):
    r = web_client.get("/assets/index-abc123.js")
    assert r.text == "console.log(1)"
    assert "immutable" in r.headers["cache-control"]
    assert web_client.get("/favicon.svg").text == "<svg/>"


def test_api_is_not_hidden_by_the_app(web_client):
    assert web_client.get("/api/health").json() == {"status": "ok"}
    r = web_client.get("/api/no-such-route")
    assert r.status_code == 404  # a typo in the API is an error, not the app's HTML
    assert r.headers["content-type"] == "application/json"


@pytest.mark.parametrize(
    "path", ["/../secret.txt", "/%2e%2e/secret.txt", "/assets/../../secret.txt"]
)
def test_no_file_outside_the_build_is_served(web_client, path):
    assert "outside the build" not in web_client.get(path).text


def test_without_a_build_only_the_api_answers(client):
    assert client.get("http://testserver/").status_code == 404
