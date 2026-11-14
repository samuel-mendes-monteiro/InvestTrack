from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from investtrack.api import create_app
from investtrack.db import create_db_engine
from investtrack.events import StaticEvents
from investtrack.income import IncomeEvent, IncomeType
from investtrack.market_data import StaticMarketData
from investtrack.portfolio import StockEvent, StockEventType
from investtrack.prices import StaticPriceProvider

PRICES = StaticPriceProvider({"PETR4": Decimal("38"), "HGLG11": Decimal("160")})


@pytest.fixture
def client():
    """API backed by an in-memory database, fixed prices and no income events."""
    app = create_app(
        engine=create_db_engine("sqlite://"),
        price_provider=PRICES,
        events=StaticEvents(),
        market_data=StaticMarketData(),
    )
    with TestClient(app) as c:  # "with" runs the startup/shutdown (lifespan)
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
    clients = []

    def make(*events):
        app = create_app(
            engine=create_db_engine("sqlite://"),
            price_provider=PRICES,
            events=StaticEvents(income=events),
        )
        c = TestClient(app)
        c.__enter__()
        clients.append(c)
        return c

    yield make
    for c in clients:
        c.__exit__(None, None, None)


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
    app = create_app(
        engine=create_db_engine("sqlite://"),
        price_provider=PRICES,
        events=StaticEvents(stock=[split_event("2026-02-01")]),
    )
    with TestClient(app) as c:
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
    app = create_app(
        engine=create_db_engine("sqlite://"),
        price_provider=PRICES,
        events=StaticEvents(stock=[bonus, split_event("2026-03-01")]),
    )
    with TestClient(app) as c:
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
    app = create_app(
        engine=create_db_engine("sqlite://"),
        price_provider=PRICES,
        events=StaticEvents(),
        market_data=market,
    )
    return TestClient(app)


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
        "twr": "0.00",
        "cdi": "0.00",
        "ibovespa": "10.00",
    }


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


def test_portfolio_totals_include_fixed_income_still_invested(fi_client):
    fi_client.post("/fixed-income", json=fixed())
    redeemed = fi_client.post("/fixed-income", json=fixed()).json()
    fi_client.put(f"/fixed-income/{redeemed['id']}/redemption", json={"redeemed_on": "2026-03-03"})
    assert fi_client.get("/portfolio").json()["totals"]["fixed_income"] == "1020.10"


def test_lci_at_100_percent_of_cdi_earns_exactly_the_cdi(fi_client):
    fi_client.post("/fixed-income", json=fixed())
    body = fi_client.get("/performance").json()
    assert body["twr"] == body["cdi"] == "2.01"
    assert body["pct_of_cdi"] == "100.00"
