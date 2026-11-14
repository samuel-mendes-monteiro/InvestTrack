"""Database setup: engine, base class and a Decimal-safe column type."""

import os
from decimal import Decimal
from pathlib import Path

from sqlalchemy import Engine, Numeric, String, create_engine, event
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import StaticPool
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
    kwargs = {}
    if url.startswith("sqlite"):
        # FastAPI runs sync endpoints in a thread pool, so a connection may be
        # used by a different thread than the one that opened it. That is safe
        # here because each request uses its own session.
        kwargs["connect_args"] = {"check_same_thread": False}
        if url in ("sqlite://", "sqlite:///:memory:"):
            # An in-memory database lives inside one connection. StaticPool
            # shares that single connection, so every thread sees the same data.
            kwargs["poolclass"] = StaticPool
    engine = create_engine(url, **kwargs)

    if engine.dialect.name == "sqlite":
        # SQLite ignores foreign keys unless this is turned on per connection.
        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _record):
            dbapi_connection.execute("PRAGMA foreign_keys = ON")

    return engine


MIGRATIONS = Path(__file__).parent / "migrations"


def init_db(engine: Engine) -> None:
    """Bring the database to the latest schema by applying pending migrations.

    Until v0.4 this was create_all, which only creates missing tables. v0.5
    adds columns to tables that already have data, which needs migrations.
    The baseline migration skips tables that exist, so databases from before
    and brand new ones take the same path.
    """
    from alembic import command
    from alembic.config import Config

    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    with engine.begin() as connection:
        config.attributes["connection"] = connection  # migrate this very engine
        command.upgrade(config, "head")
