"""Engine and session factory. DATABASE_URL unset means in-memory SQLite: free, offline, fast."""

import os

import sqlalchemy as sa
from dotenv import load_dotenv
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from lifepilot.db.models import Base

load_dotenv()


IN_MEMORY_SQLITE = "sqlite+pysqlite:///:memory:"


def make_engine(url: str | None = None) -> sa.Engine:
    """An engine for `url`, DATABASE_URL, or in-memory SQLite in that order.

    In-memory SQLite needs StaticPool and check_same_thread=False whichever way its URL arrives:
    SQLAlchemy's default pool hands each thread its own connection, and for `:memory:` that means its
    own empty database. Without this, a server thread sees no tables at all.
    """
    url = url or os.environ.get("DATABASE_URL") or IN_MEMORY_SQLITE
    if ":memory:" in url:
        return sa.create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    return sa.create_engine(url)


def make_session_factory(engine: sa.Engine, create: bool = False) -> sessionmaker[Session]:
    if create:
        Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)
