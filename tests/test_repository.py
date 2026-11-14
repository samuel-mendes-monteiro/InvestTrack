from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from investtrack.db import create_db_engine, init_db
from investtrack.models import Asset, AssetType, OperationRecord
from investtrack.portfolio import InsufficientPositionError, Operation, OpType
from investtrack.repository import (
    OperationNotFoundError,
    add_operation,
    delete_operation,
    get_portfolio,
    list_operations,
)


@pytest.fixture
def session():
    """A fresh in-memory SQLite database for each test."""
    engine = create_db_engine("sqlite://")
    init_db(engine)
    with Session(engine) as s:
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
    add_operation(session, buy(1, "0.1", "35.123456789", fees="0.2"))
    session.expire_all()  # force a real read from the database

    record = list_operations(session)[0]
    assert isinstance(record.price, Decimal)
    assert record.price == Decimal("35.123456789")
    assert record.quantity + record.fees == Decimal("0.3")  # would fail with float


def test_asset_is_created_once_per_ticker(session):
    add_operation(session, buy(1, "100", "30"))
    add_operation(session, buy(2, "100", "40"))
    assert len(session.scalars(select(Asset)).all()) == 1


def test_asset_type_is_saved(session):
    add_operation(session, buy(1, "10", "158", ticker="HGLG11"), AssetType.FII)
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
    add_operation(session, buy(5, "1", "10", ticker="VALE3"))
    add_operation(session, buy(1, "1", "10"))
    add_operation(session, buy(3, "1", "10"))

    assert [r.date.day for r in list_operations(session)] == [1, 3, 5]
    assert [r.asset.ticker for r in list_operations(session, "vale3")] == ["VALE3"]


def test_selling_more_than_owned_is_refused_and_not_saved(session):
    add_operation(session, buy(1, "100", "30"))
    with pytest.raises(InsufficientPositionError):
        add_operation(session, sell(2, "101", "35"))
    assert len(list_operations(session)) == 1


def test_backdated_sale_is_checked_against_history(session):
    add_operation(session, buy(10, "100", "30"))
    with pytest.raises(InsufficientPositionError):
        add_operation(session, sell(5, "10", "35"))  # before the buy existed


def test_delete_operation(session):
    record = add_operation(session, buy(1, "100", "30"))
    delete_operation(session, record.id)
    assert list_operations(session) == []


def test_delete_that_breaks_a_later_sale_is_refused(session):
    first_buy = add_operation(session, buy(1, "100", "30"))
    add_operation(session, sell(2, "80", "35"))

    with pytest.raises(InsufficientPositionError):
        delete_operation(session, first_buy.id)
    assert len(list_operations(session)) == 2


def test_delete_unknown_operation(session):
    with pytest.raises(OperationNotFoundError):
        delete_operation(session, 42)


def test_portfolio_from_database(session):
    add_operation(session, buy(1, "100", "30", fees="10"))
    add_operation(session, buy(2, "100", "40", fees="10"))
    add_operation(session, sell(3, "50", "50", fees="10"))
    add_operation(session, buy(1, "10", "158.40", ticker="HGLG11"), AssetType.FII)

    portfolio = get_portfolio(session)
    assert portfolio["PETR4"].quantity == Decimal("150")
    assert portfolio["PETR4"].avg_price == Decimal("35.10")
    assert portfolio["PETR4"].realized_profit == Decimal("735")
    assert portfolio["HGLG11"].avg_price == Decimal("158.40")


def test_values_are_stored_as_text_on_sqlite(session):
    add_operation(session, buy(1, "100", "30.10"))
    stored_type = session.execute(text("SELECT typeof(price) FROM operations")).scalar()
    assert stored_type == "text"  # not "real", i.e. never a float
