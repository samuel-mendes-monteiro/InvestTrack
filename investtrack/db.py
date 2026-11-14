"""Database setup: engine, base class and a Decimal-safe column type."""

import os
from decimal import Decimal

from sqlalchemy import Engine, Numeric, String, create_engine, event
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator

DEFAULT_DATABASE_URL = "sqlite:///investtrack.db"


class Base(DeclarativeBase):
    pass


class SafeDecimal(TypeDecorator):
    """Stores Decimal values without ever passing through float.

    PostgreSQL has a real NUMERIC type, so it is used directly. SQLite does
    not: SQLAlchemy would store NUMERIC as a floating point REAL and lose
    precision. On SQLite the value is stored as text instead and turned back
    into a Decimal when read.

    Trade-off: on SQLite, SQL cannot compare or sum these columns numerically.
    That is fine here, because every calculation happens in Python.
    """

    impl = Numeric
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "sqlite":
            return dialect.type_descriptor(String(40))
        return dialect.type_descriptor(Numeric(20, 8))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, Decimal):
            raise TypeError(f"expected Decimal, got {type(value).__name__}")
        return str(value) if dialect.name == "sqlite" else value

    def process_result_value(self, value, dialect):
        return None if value is None else Decimal(value)


def create_db_engine(url: str | None = None) -> Engine:
    """Create the engine from the given URL or the DATABASE_URL env variable."""
    url = url or os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
    engine = create_engine(url)

    if engine.dialect.name == "sqlite":
        # SQLite ignores foreign keys unless this is turned on per connection.
        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _record):
            dbapi_connection.execute("PRAGMA foreign_keys = ON")

    return engine


def init_db(engine: Engine) -> None:
    """Create all tables that do not exist yet."""
    from investtrack import models  # noqa: F401  (registers the tables)

    Base.metadata.create_all(engine)
