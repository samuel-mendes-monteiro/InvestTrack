"""Alembic environment: how migrations connect to the database.

Two ways in:
- db.init_db passes an open connection in config.attributes, so the API
  and the tests migrate exactly the engine they use (even in-memory ones);
- the alembic command line uses DATABASE_URL, like the API.
"""

from alembic import context

from investtrack.storage import models  # noqa: F401  (registers the tables)
from investtrack.storage.db import Base, create_db_engine

target_metadata = Base.metadata


def run(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # SQLite can't alter columns or constraints in place: "batch" mode
        # rebuilds the table (create new, copy rows, swap) when needed.
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


connection = context.config.attributes.get("connection")
if connection is not None:
    run(connection)
else:
    engine = create_db_engine()
    with engine.connect() as conn:
        run(conn)
    engine.dispose()
