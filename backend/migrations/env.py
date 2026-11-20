"""Alembic environment: uses the application's engine and metadata (no URL duplicated here)."""
from alembic import context

from app import models  # noqa: F401  (registers every table on Base.metadata)
from app.db import Base, engine

config = context.config
target_metadata = Base.metadata


def _run(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        render_as_batch=connection.dialect.name == "sqlite",  # SQLite needs table rebuilds for ALTER
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    conn = config.attributes.get("connection")
    if conn is not None:
        _run(conn)
        return
    with engine.connect() as connection:
        _run(connection)


if context.is_offline_mode():
    raise SystemExit("Offline SQL generation is not supported; run against a database.")
run_migrations_online()
