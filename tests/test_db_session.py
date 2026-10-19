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


def test_an_in_memory_database_warns_that_nothing_will_survive(caplog):
    """Being asked to link Gmail again after every restart reads as the product forgetting. The
    cause is a database that was never on disk, and only the server can say so."""
    import logging

    import lifepilot.server as server
    from lifepilot.db.session import IN_MEMORY_SQLITE, make_engine

    with caplog.at_level(logging.WARNING, logger="lifepilot"):
        server._warn_if_ephemeral(make_engine(IN_MEMORY_SQLITE))

    assert "DATABASE_URL is not set" in caplog.text
    assert "Gmail" in caplog.text


def test_a_real_database_is_named_with_its_password_masked(caplog):
    import logging

    import lifepilot.server as server
    from lifepilot.db.session import make_engine

    with caplog.at_level(logging.INFO, logger="lifepilot"):
        server._warn_if_ephemeral(make_engine("postgresql+psycopg://user:secret@host/db"))

    assert "secret" not in caplog.text
    assert "***" in caplog.text


def test_a_file_backed_sqlite_database_is_not_called_ephemeral():
    """The check reads `url.database`, because SQLAlchemy renders `:memory:` as `%3Amemory%3A` and
    a substring check on the rendered URL silently never matches."""
    from lifepilot.db.session import IN_MEMORY_SQLITE, make_engine

    assert ":memory:" not in str(make_engine(IN_MEMORY_SQLITE).url)
    assert make_engine(IN_MEMORY_SQLITE).url.database == ":memory:"
    assert make_engine("sqlite+pysqlite:///demo.db").url.database == "demo.db"
