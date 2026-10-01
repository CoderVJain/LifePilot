"""what_if against the seeded family. Offline and free.

The first test is the one that counts: a what-if that leaves a mark is not a what-if.
"""

import hashlib
from datetime import date

import pytest
import sqlalchemy as sa

from eval.generate import MONDAY, build_demo_family
from lifepilot.db.models import Base
from lifepilot.db.session import make_engine, make_session_factory
from lifepilot.tools.what_if import what_if

FRIDAY = date(2026, 10, 9)


@pytest.fixture
def session():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    factory = make_session_factory(engine, create=True)
    with factory() as s:
        build_demo_family(s)
        yield s


def fingerprint(session) -> str:
    """Every row of every table, hashed. Any write at all changes this."""
    digest = hashlib.sha256()
    for name in sorted(Base.metadata.tables):
        table = Base.metadata.tables[name]
        digest.update(name.encode())
        for row in session.execute(sa.select(table).order_by(*table.c)):
            digest.update(repr(tuple(row)).encode())
    return digest.hexdigest()


ASKS = [
    {"kind": "runs_late", "title": "performance review", "until": "17:30"},
    {"kind": "new_event", "title": "coffee", "start": "2026-10-06T11:00", "end": "2026-10-06T11:30"},
    {"kind": "new_event", "title": "6pm meeting", "start": "2026-10-09T18:00", "end": "2026-10-09T19:00"},
    {"kind": "cancelled", "title": "football practice"},
    {"kind": "teleport", "title": "piano class"},
]


def test_the_database_is_byte_identical_afterwards(session):
    before = fingerprint(session)
    for ask in ASKS:
        what_if(session, "Dad", MONDAY, FRIDAY, ask)
    assert fingerprint(session) == before


def test_no_proposal_row_is_created(session):
    """fix_week writes a proposal. what_if must not, even though it runs the same solver."""
    from lifepilot.db.models import Proposal

    what_if(session, "Dad", MONDAY, FRIDAY, ASKS[0])
    assert session.scalar(sa.select(sa.func.count()).select_from(Proposal)) == 0


def test_a_late_meeting_that_breaks_something_says_what_and_offers_a_fix(session):
    result = what_if(
        session,
        "Mom",
        MONDAY,
        FRIDAY,
        {"kind": "new_event", "title": "late client call", "start": "2026-10-08T16:30",
         "end": "2026-10-08T17:30", "member_ids": [2], "location_id": 3},
    )
    assert result["understood"] is True
    assert result["ripple"]["safe"] is False
    assert "That breaks" in result["say"]
    assert "fix" in result


def test_a_harmless_question_gets_a_short_yes(session):
    """Tuesday evening, after work is over and with no lift to reach. Genuinely free."""
    result = what_if(
        session,
        "Dad",
        MONDAY,
        FRIDAY,
        {"kind": "new_event", "title": "coffee", "start": "2026-10-06T17:00", "end": "2026-10-06T17:30"},
    )
    assert result["ripple"]["safe"] is True
    assert result["say"] == "That works. Nothing new breaks."


def test_something_booked_over_work_is_correctly_called_a_clash(session):
    """An 11am coffee on a Tuesday is not harmless: Dad is at the office until half four."""
    result = what_if(
        session,
        "Dad",
        MONDAY,
        FRIDAY,
        {"kind": "new_event", "title": "coffee", "start": "2026-10-06T11:00", "end": "2026-10-06T11:30"},
    )
    assert result["ripple"]["safe"] is False
    assert any(c["kind"] == "overlap" for c in result["ripple"]["breaks"])


def test_a_cancellation_that_helps_is_reported_as_helping(session):
    result = what_if(session, "Dad", MONDAY, FRIDAY, {"kind": "cancelled", "title": "football practice"})
    assert result["ripple"]["safe"] is True
    assert "actually helps" in result["say"]
    assert result["ripple"]["resolves"]


def test_problems_that_were_already_there_are_not_blamed_on_the_change(session):
    """The project block already breaks the homework rule. A new meeting did not cause that."""
    result = what_if(
        session,
        "Mom",
        MONDAY,
        FRIDAY,
        {"kind": "new_event", "title": "late client call", "start": "2026-10-08T16:30",
         "end": "2026-10-08T17:30", "member_ids": [2], "location_id": 3},
    )
    unchanged = {c["kind"] for c in result["ripple"]["unchanged"]}
    broke = {c["kind"] for c in result["ripple"]["breaks"]}
    assert "rule_clash" in unchanged
    assert "rule_clash" not in broke


def test_a_question_it_cannot_parse_is_refused_in_plain_words(session):
    result = what_if(session, "Dad", MONDAY, FRIDAY, {"kind": "teleport", "title": "piano class"})
    assert result["understood"] is False
    assert "I cannot work out" in result["say"]


def test_a_new_event_belongs_to_whoever_asked_unless_told_otherwise(session):
    """"Can I say yes to a six o'clock" is about the person speaking."""
    mine = what_if(
        session, "Dad", MONDAY, FRIDAY,
        {"kind": "new_event", "title": "6pm", "start": "2026-10-08T16:30", "end": "2026-10-08T17:30"},
    )
    theirs = what_if(
        session, "Grandpa", MONDAY, FRIDAY,
        {"kind": "new_event", "title": "6pm", "start": "2026-10-08T16:30", "end": "2026-10-08T17:30"},
    )
    assert mine["ripple"] != theirs["ripple"], "it must matter whose diary the thing lands in"


def test_a_child_may_ask_what_if_too(session):
    """Asking is not changing, so the role check is on writes, not on questions."""
    result = what_if(session, "Aarav", MONDAY, FRIDAY, {"kind": "cancelled", "title": "football practice"})
    assert result["understood"] is True
