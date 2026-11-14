"""Migrations: old databases keep their data, new ones get the full schema."""

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from investtrack.db import MIGRATIONS, create_db_engine, init_db


def alembic(engine, action: str, revision: str) -> None:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        getattr(command, action)(config, revision)


@pytest.fixture
def engine():
    e = create_db_engine("sqlite://")
    yield e
    e.dispose()


@pytest.fixture
def v04(engine):
    """A database as v0.4 left it: tables made by create_all, no Alembic history."""
    alembic(engine, "upgrade", "0001")
    with engine.begin() as c:
        c.execute(text("DROP TABLE alembic_version"))
        c.execute(text("INSERT INTO assets (id, ticker, asset_type) VALUES (1, 'PETR4', 'STOCK')"))
        c.execute(
            text(
                "INSERT INTO operations (asset_id, op_type, date, quantity, price, fees) "
                "VALUES (1, 'BUY', '2026-01-05', '100', '30', '0')"
            )
        )
        c.execute(
            text(
                "INSERT INTO bonus_costs (ticker, record_date, unit_cost) "
                "VALUES ('PETR4', '2026-02-01', '4.5')"
            )
        )
    return engine


def columns(engine, table):
    return {c["name"] for c in inspect(engine).get_columns(table)}


def test_new_database_gets_every_table(engine):
    init_db(engine)
    assert {"users", "auth_sessions", "operations", "fixed_income"} <= set(
        inspect(engine).get_table_names()
    )
    assert "user_id" in columns(engine, "operations")


def test_v04_database_keeps_its_data_and_gets_owners(v04):
    engine = v04
    init_db(engine)
    with engine.connect() as c:
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0002"
        assert c.execute(text("SELECT quantity, user_id FROM operations")).one() == ("100", None)
        assert c.execute(text("SELECT ticker, unit_cost FROM bonus_costs")).one() == (
            "PETR4",
            "4.5",
        )
    assert {"id", "user_id"} <= columns(engine, "bonus_costs")


def test_running_twice_changes_nothing(v04):
    engine = v04
    init_db(engine)
    init_db(engine)
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM operations")).scalar() == 1


def test_downgrade_restores_v04_shape_and_data(v04):
    engine = v04
    init_db(engine)
    alembic(engine, "downgrade", "0001")
    assert "users" not in inspect(engine).get_table_names()
    assert "user_id" not in columns(engine, "operations")
    with engine.connect() as c:
        assert c.execute(text("SELECT unit_cost FROM bonus_costs")).scalar() == "4.5"
