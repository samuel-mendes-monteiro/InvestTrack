from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from investtrack.db import create_db_engine, init_db
from investtrack.events import StaticEvents
from investtrack.income import (
    Income,
    IncomeEvent,
    IncomeType,
    IncomeWithoutPositionError,
    TickerEvents,
)
from investtrack.models import Asset, AssetType, OperationRecord, User
from investtrack.portfolio import (
    InsufficientPositionError,
    Operation,
    OpType,
    StockEvent,
    StockEventType,
)
from investtrack.repository import (
    IncomeNotFoundError,
    OperationNotFoundError,
    add_income,
    add_operation,
    bonus_costs,
    computed_incomes,
    delete_bonus_cost,
    delete_income,
    delete_operation,
    get_portfolio,
    list_incomes,
    list_operations,
    set_bonus_cost,
)

USER = 1  # the first account of a fresh database


@pytest.fixture
def session():
    """A fresh in-memory SQLite database for each test, with one account."""
    engine = create_db_engine("sqlite://")
    init_db(engine)
    with Session(engine) as s:
        s.add(User(email="ana@example.com", password_hash="-", created_at=datetime.now(UTC)))
        s.commit()
        yield s
    engine.dispose()


def buy(day: int, qty: str, price: str, fees: str = "0", ticker: str = "PETR4"):
    return Operation(
        ticker, OpType.BUY, date(2026, 1, day), Decimal(qty), Decimal(price), Decimal(fees)
    )


def sell(day: int, qty: str, price: str, fees: str = "0", ticker: str = "PETR4"):
    return Operation(
        ticker, OpType.SELL, date(2026, 1, day), Decimal(qty), Decimal(price), Decimal(fees)
    )


def test_decimal_round_trip_is_exact(session):
    add_operation(session, USER, buy(1, "0.1", "35.123456789", fees="0.2"))
    session.expire_all()  # force a real read from the database

    record = list_operations(session, USER)[0]
    assert isinstance(record.price, Decimal)
    assert record.price == Decimal("35.123456789")
    assert record.quantity + record.fees == Decimal("0.3")  # would fail with float


def test_asset_is_created_once_per_ticker(session):
    add_operation(session, USER, buy(1, "100", "30"))
    add_operation(session, USER, buy(2, "100", "40"))
    assert len(session.scalars(select(Asset)).all()) == 1


def test_asset_type_is_saved(session):
    add_operation(session, USER, buy(1, "10", "158", ticker="HGLG11"), AssetType.FII)
    asset = session.scalar(select(Asset))
    assert asset.asset_type is AssetType.FII


def test_ticker_must_be_unique(session):
    session.add_all(
        [
            Asset(ticker="PETR4", asset_type=AssetType.STOCK),
            Asset(ticker="PETR4", asset_type=AssetType.STOCK),
        ]
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_foreign_keys_are_enforced(session):
    session.add(
        OperationRecord(
            asset_id=999,
            op_type=OpType.BUY,
            date=date(2026, 1, 1),
            quantity=Decimal("1"),
            price=Decimal("1"),
            fees=Decimal("0"),
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_list_is_ordered_by_date_and_filterable(session):
    add_operation(session, USER, buy(5, "1", "10", ticker="VALE3"))
    add_operation(session, USER, buy(1, "1", "10"))
    add_operation(session, USER, buy(3, "1", "10"))

    assert [r.date.day for r in list_operations(session, USER)] == [1, 3, 5]
    assert [r.asset.ticker for r in list_operations(session, USER, "vale3")] == ["VALE3"]


def test_selling_more_than_owned_is_refused_and_not_saved(session):
    add_operation(session, USER, buy(1, "100", "30"))
    with pytest.raises(InsufficientPositionError):
        add_operation(session, USER, sell(2, "101", "35"))
    assert len(list_operations(session, USER)) == 1


def test_backdated_sale_is_checked_against_history(session):
    add_operation(session, USER, buy(10, "100", "30"))
    with pytest.raises(InsufficientPositionError):
        add_operation(session, USER, sell(5, "10", "35"))  # before the buy existed


def test_delete_operation(session):
    record = add_operation(session, USER, buy(1, "100", "30"))
    delete_operation(session, USER, record.id)
    assert list_operations(session, USER) == []


def test_delete_that_breaks_a_later_sale_is_refused(session):
    first_buy = add_operation(session, USER, buy(1, "100", "30"))
    add_operation(session, USER, sell(2, "80", "35"))

    with pytest.raises(InsufficientPositionError):
        delete_operation(session, USER, first_buy.id)
    assert len(list_operations(session, USER)) == 2


def test_delete_unknown_operation(session):
    with pytest.raises(OperationNotFoundError):
        delete_operation(session, USER, 42)


def test_portfolio_from_database(session):
    add_operation(session, USER, buy(1, "100", "30", fees="10"))
    add_operation(session, USER, buy(2, "100", "40", fees="10"))
    add_operation(session, USER, sell(3, "50", "50", fees="10"))
    add_operation(session, USER, buy(1, "10", "158.40", ticker="HGLG11"), AssetType.FII)

    portfolio = get_portfolio(session, USER)
    assert portfolio["PETR4"].quantity == Decimal("150")
    assert portfolio["PETR4"].avg_price == Decimal("35.10")
    assert portfolio["PETR4"].realized_profit == Decimal("735")
    assert portfolio["HGLG11"].avg_price == Decimal("158.40")


def test_values_are_stored_as_text_on_sqlite(session):
    add_operation(session, USER, buy(1, "100", "30.10"))
    stored_type = session.execute(text("SELECT typeof(price) FROM operations")).scalar()
    assert stored_type == "text"  # not "real", i.e. never a float


# --- income ------------------------------------------------------------------


def dividend(day: int, amount: str, tax: str = "0", ticker: str = "PETR4"):
    return Income(ticker, IncomeType.DIVIDEND, date(2026, 1, day), Decimal(amount), Decimal(tax))


def test_add_and_list_income(session):
    add_operation(session, USER, buy(1, "100", "30"))
    add_income(session, USER, dividend(5, "45.10"))
    session.expire_all()

    record = list_incomes(session, USER)[0]
    assert record.asset.ticker == "PETR4"
    assert record.amount == Decimal("45.10")


def test_income_before_first_buy_is_refused_and_not_saved(session):
    add_operation(session, USER, buy(10, "100", "30"))
    with pytest.raises(IncomeWithoutPositionError):
        add_income(session, USER, dividend(5, "10"))
    assert list_incomes(session, USER) == []


def test_income_for_unknown_ticker_does_not_create_asset(session):
    with pytest.raises(IncomeWithoutPositionError):
        add_income(session, USER, dividend(5, "10", ticker="PETR3"))
    assert session.scalars(select(Asset)).all() == []


def test_list_income_filters_by_ticker_and_year(session):
    add_operation(session, USER, buy(1, "100", "30"))
    add_operation(session, USER, buy(1, "10", "158", ticker="HGLG11"), AssetType.FII)
    add_income(session, USER, dividend(5, "10"))
    add_income(session, USER, dividend(6, "1", ticker="HGLG11"))

    assert [r.asset.ticker for r in list_incomes(session, USER, "hglg11")] == ["HGLG11"]
    assert len(list_incomes(session, USER, year=2026)) == 2
    assert list_incomes(session, USER, year=2025) == []


def test_delete_income(session):
    add_operation(session, USER, buy(1, "100", "30"))
    record = add_income(session, USER, dividend(5, "10"))
    delete_income(session, USER, record.id)
    assert list_incomes(session, USER) == []


def test_delete_unknown_income(session):
    with pytest.raises(IncomeNotFoundError):
        delete_income(session, USER, 42)


def test_deleting_the_buy_behind_an_income_is_refused(session):
    first_buy = add_operation(session, USER, buy(1, "100", "30"))
    add_operation(session, USER, buy(10, "100", "30"))
    add_income(session, USER, dividend(5, "10"))

    with pytest.raises(IncomeWithoutPositionError):
        delete_operation(session, USER, first_buy.id)
    assert len(list_operations(session, USER)) == 2


def test_deleting_a_later_buy_keeps_income_valid(session):
    add_operation(session, USER, buy(1, "100", "30"))
    later = add_operation(session, USER, buy(10, "100", "30"))
    add_income(session, USER, dividend(5, "10"))
    delete_operation(session, USER, later.id)  # first buy still covers the income


def test_computed_incomes_use_each_asset_type(session):
    add_operation(session, USER, buy(1, "100", "30"))
    add_operation(session, USER, buy(1, "10", "158", ticker="HGLG11"), AssetType.FII)
    asked = []

    class Events:
        def events_for(self, ticker, asset_type):
            asked.append((ticker, asset_type))
            rate = Decimal("1.10") if ticker == "HGLG11" else Decimal("0.50")
            income = IncomeEvent(
                ticker, IncomeType.DIVIDEND, date(2026, 1, 2), date(2026, 1, 9), rate
            )
            return TickerEvents([income], [])

    incomes = computed_incomes(session, USER, Events())
    assert sorted(asked) == [("HGLG11", AssetType.FII), ("PETR4", AssetType.STOCK)]
    assert {i.ticker: i.amount for i in incomes} == {
        "PETR4": Decimal("50"),
        "HGLG11": Decimal("11"),
    }


def test_bonus_cost_lowercase_ticker_and_delete_missing(session):
    bonus = StockEvent("PETR4", StockEventType.BONUS, date(2026, 1, 5), Decimal("1.1"))
    events = StaticEvents(stock=[bonus])
    add_operation(session, USER, buy(1, "100", "30"), events=events)

    set_bonus_cost(session, USER, "petr4", date(2026, 1, 5), Decimal("7.82"), events)
    assert bonus_costs(session, USER) == {("PETR4", date(2026, 1, 5)): Decimal("7.82")}
    assert get_portfolio(session, USER, events)["PETR4"].avg_price == Decimal("3078.2") / 110

    delete_bonus_cost(session, USER, "PETR4", date(2026, 1, 6))  # nothing there: no error
    delete_bonus_cost(session, USER, "PETR4", date(2026, 1, 5))
    assert bonus_costs(session, USER) == {}
