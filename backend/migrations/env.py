"""Alembic environment. The app passes an open connection (holding the
migration advisory lock) through config.attributes; the CLI builds its own."""

from alembic import context

from seltzer.db.engine import make_sync_engine
from seltzer.db.models import Base

target_metadata = Base.metadata


def run_migrations_online() -> None:
    connection = context.config.attributes.get("connection")
    if connection is not None:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
        return

    engine = make_sync_engine()
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run_migrations_online()
