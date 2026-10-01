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
