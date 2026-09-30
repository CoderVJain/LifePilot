"""Keep the suite hermetic.

CLAUDE.md requires tests to be free, offline and fast. `lifepilot.db.session` calls `load_dotenv()`,
so once a developer puts a real `DATABASE_URL` in `.env` any default `make_engine()` would quietly
reach for Neon. Clearing it for the whole session means the tests cannot touch a real database by
accident, whatever is in the environment.
"""

import pytest


@pytest.fixture(autouse=True, scope="session")
def _offline_database(request):
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    request.addfinalizer(monkeypatch.undo)
