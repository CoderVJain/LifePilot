"""Alembic environment. The URL comes from DATABASE_URL via lifepilot.db.session, not alembic.ini,
so there is one place that decides which database we are talking to."""

from alembic import context
from lifepilot.db.models import Base
from lifepilot.db.session import make_engine

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=str(make_engine().url),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = make_engine()
    with engine.connect() as connection:
        # render_as_batch: SQLite cannot ALTER columns in place.
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
