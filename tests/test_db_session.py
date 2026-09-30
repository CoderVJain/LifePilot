"""Engine construction. Guards a bug that only showed up once a server thread existed."""

import threading

import sqlalchemy as sa

from lifepilot.db.models import Family
from lifepilot.db.session import make_engine, make_session_factory


def test_in_memory_sqlite_is_shared_across_threads():
    """SQLAlchemy's default pool gives each thread its own connection, and for `:memory:` that means
    its own empty database. A server thread would see `no such table`. StaticPool prevents it, and it
    has to apply whether the URL is passed in or defaulted."""
    engine = make_engine("sqlite+pysqlite:///:memory:")
    factory = make_session_factory(engine, create=True)
    with factory() as session:
        session.add(Family(name="Sharma"))
        session.commit()

    seen = []

    def read_from_another_thread():
        with factory() as session:
            seen.extend(session.scalars(sa.select(Family.name)))

    thread = threading.Thread(target=read_from_another_thread)
    thread.start()
    thread.join()

    assert seen == ["Sharma"]


def test_default_engine_is_in_memory_sqlite(monkeypatch):
    """`str(url)` percent-encodes the colons, so compare the parsed database name."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert make_engine().url.database == ":memory:"


def test_database_url_is_used_when_set(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///lifepilot-test.db")
    assert make_engine().url.database == "lifepilot-test.db"
