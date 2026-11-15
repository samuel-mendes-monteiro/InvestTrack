"""Shared test setup.

Tests run on an in-memory SQLite database by default. With
TEST_DATABASE_URL set to a PostgreSQL database, the same tests run there
instead (CI does both); each test then starts from an empty schema.
"""

import os

from sqlalchemy import Engine, text

from investtrack.storage.db import create_db_engine

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


def fresh_engine() -> Engine:
    """An empty database for one test."""
    if not TEST_DATABASE_URL:
        return create_db_engine("sqlite://")
    engine = create_db_engine(TEST_DATABASE_URL)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    return engine
