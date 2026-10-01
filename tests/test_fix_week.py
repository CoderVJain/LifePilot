"""fix_week against the seeded family. Offline and free."""

from datetime import date

import pytest
import sqlalchemy as sa

from eval.generate import MONDAY, build_demo_family
from lifepilot.db.models import Assignment, Event, Proposal
from lifepilot.db.session import make_engine, make_session_factory
from lifepilot.tools.fix_week import NotAllowed, fix_week

FRIDAY = date(2026, 10, 9)


@pytest.fixture
def session():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    factory = make_session_factory(engine, create=True)
    with factory() as s:
        build_demo_family(s)
        yield s


def test_the_week_is_fixed_in_two_changes(session):
    result = fix_week(session, "Dad", MONDAY, FRIDAY)
    assert result["solved"] is True
    assert result["change_count"] == 2


def test_the_spoken_answer_is_a_short_diff_ending_in_a_question(session):
    say = fix_week(session, "Dad", MONDAY, FRIDAY)["say"]
    assert say.startswith("2 changes:")
    assert "Mom takes football practice pickup" in say
    assert say.endswith("Shall I make them?")


def test_nothing_is_changed_until_a_parent_approves(session):
    """The whole loop rests on this: propose, then approve. Never act first."""
    before_assignee = session.scalars(
        sa.select(Assignment.member_id).where(Assignment.event_id == _football_id(session))
    ).one()
    before_start = session.scalars(
        sa.select(Event.start).where(Event.title == "science project block")
    ).one()

    fix_week(session, "Dad", MONDAY, FRIDAY)

    assert session.scalars(
        sa.select(Assignment.member_id).where(Assignment.event_id == _football_id(session))
    ).one() == before_assignee
    assert session.scalars(
        sa.select(Event.start).where(Event.title == "science project block")
    ).one() == before_start


def test_a_pending_proposal_is_recorded_for_approval(session):
    result = fix_week(session, "Dad", MONDAY, FRIDAY)
    proposal = session.get(Proposal, result["proposal_id"])

    assert proposal.kind == "fix"
    assert proposal.status == "pending"
    assert len(proposal.changes) == 2
    assert proposal.violations, "a proposal should record what it was fixing"
    assert proposal.solve_ms >= 0


def test_the_proposal_says_what_it_was_fixing(session):
    result = fix_week(session, "Dad", MONDAY, FRIDAY)
    kinds = {v["kind"] for v in result["fixes"]}
    assert "unreachable" in kinds
    assert "rule_clash" in kinds


def test_only_a_parent_may_propose_changes(session):
    with pytest.raises(NotAllowed):
        fix_week(session, "Aarav", MONDAY, FRIDAY)


def test_a_week_that_already_works_proposes_nothing(session):
    """No proposal row, no diff, and it says so plainly."""
    quiet = date(2026, 10, 12), date(2026, 10, 16)
    result = fix_week(session, "Dad", *quiet)
    assert result["needed"] is False
    assert result["change_count"] == 0
    assert "Nothing needs changing" in result["say"]
    assert session.scalar(sa.select(sa.func.count()).select_from(Proposal)) == 0


def _football_id(session) -> int:
    return session.scalars(sa.select(Event.id).where(Event.title == "football practice")).one()
