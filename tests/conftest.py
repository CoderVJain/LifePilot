"""Keep the suite hermetic.

CLAUDE.md requires tests to be free, offline and fast. `lifepilot.db.session` calls `load_dotenv()`,
so once a developer puts a real `DATABASE_URL` in `.env` any default `make_engine()` would quietly
reach for Neon. Clearing it for the whole session means the tests cannot touch a real database by
accident, whatever is in the environment.
"""

import os

import pytest

# Pin the day before anything imports it. The seeded family follows the real calendar so that
# "tomorrow" lands on a day with events in it, but a test that means Thursday the 8th has to keep
# meaning Thursday the 8th however long from now it runs. Pinning the day rather than the week keeps
# "today", "tomorrow" and "this week" talking about the same days; pinning only the week did not,
# and every relative-date expectation became a trick question.
os.environ["LIFEPILOT_TODAY"] = "2026-10-08"
os.environ.pop("LIFEPILOT_WEEK", None)


@pytest.fixture(autouse=True, scope="session")
def _offline_database(request):
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    request.addfinalizer(monkeypatch.undo)


@pytest.fixture(autouse=True)
def _empty_route_cache():
    """The routing cache is module-level, so one test's fake answer can serve another's question.

    A test that routes "what is my schedule" through a fake model left `get_family` cached under that
    exact phrase; the end-to-end transcripts then asked the same question and got the fake answer,
    and failed only when run in the same session. Order-dependent failures are expensive to read, so
    the cache starts and ends every test empty.
    """
    from simulator.agent import _route_cache

    _route_cache.clear()
    yield
    _route_cache.clear()
