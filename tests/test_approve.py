"""The approval loop. Offline and free.

This is the only code in LifePilot that changes a family's plan, so these tests are the safety model
written down: approve acts, reject does not, and not everyone may say yes.
"""

from datetime import date, datetime

import pytest
import sqlalchemy as sa

from eval.generate import MONDAY, build_demo_family
from lifepilot.db.models import Assignment, Event, Member, Proposal
from lifepilot.db.session import make_engine, make_session_factory
from lifepilot.tools.approve import (
    CannotApply,
    NotAllowed,
    approve_proposal,
    list_proposals,
    reject_proposal,
)
from lifepilot.tools.detect_conflicts import detect_conflicts
from lifepilot.tools.fix_week import fix_week

FRIDAY = date(2026, 10, 9)


@pytest.fixture
def session():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    factory = make_session_factory(engine, create=True)
    with factory() as s:
        build_demo_family(s)
        yield s


def a_proposal(session) -> int:
    return fix_week(session, "Dad", MONDAY, FRIDAY)["proposal_id"]


def football_driver(session) -> str:
    return session.scalars(
        sa.select(Member.name)
        .join(Assignment, Assignment.member_id == Member.id)
        .join(Event, Event.id == Assignment.event_id)
        .where(Event.title == "football practice")
    ).one()


def project_start(session) -> datetime:
    return session.scalars(
        sa.select(Event.start).where(Event.title == "science project block")
    ).one()


def test_approving_actually_changes_the_plan(session):
    proposal_id = a_proposal(session)
    assert football_driver(session) == "Dad"

    result = approve_proposal(session, "Mom", proposal_id)

    assert result["approved"] is True
    assert football_driver(session) == "Mom"
    assert project_start(session) == datetime(2026, 10, 8, 19, 30)


def test_approving_clears_the_conflicts_it_was_fixing(session):
    """The point of the whole loop: after yes, the week works."""
    assert detect_conflicts(session, "Dad", MONDAY, FRIDAY)["conflicts"]
    approve_proposal(session, "Dad", a_proposal(session))
    assert detect_conflicts(session, "Dad", MONDAY, FRIDAY)["conflicts"] == []


def test_rejecting_leaves_everything_exactly_as_it_was(session):
    proposal_id = a_proposal(session)
    before = (football_driver(session), project_start(session))

    result = reject_proposal(session, "Dad", proposal_id)

    assert result["rejected"] is True
    assert (football_driver(session), project_start(session)) == before
    assert session.get(Proposal, proposal_id).status == "rejected"


def test_a_child_cannot_approve_anything(session):
    proposal_id = a_proposal(session)
    with pytest.raises(NotAllowed) as raised:
        approve_proposal(session, "Aarav", proposal_id)
    assert "only a parent" in str(raised.value)
    assert football_driver(session) == "Dad"


def test_a_caregiver_cannot_approve_anything(session):
    with pytest.raises(NotAllowed):
        approve_proposal(session, "Grandpa", a_proposal(session))


def test_a_child_cannot_reject_either(session):
    """Rejecting is a decision too, and a decided proposal cannot be approved afterwards."""
    with pytest.raises(NotAllowed):
        reject_proposal(session, "Anaya", a_proposal(session))


def test_either_parent_may_decide_when_nobody_is_named(session):
    approve_proposal(session, "Mom", a_proposal(session))
    assert football_driver(session) == "Mom"


def test_only_the_named_person_may_decide_when_one_is_named(session):
    """The shape a swap request needs: Dad proposes, Mom answers."""
    proposal_id = a_proposal(session)
    mom = session.scalars(sa.select(Member).where(Member.name == "Mom")).one()
    session.get(Proposal, proposal_id).needs_approval_from = mom.id
    session.commit()

    with pytest.raises(NotAllowed) as raised:
        approve_proposal(session, "Dad", proposal_id)
    assert "only Mom can answer" in str(raised.value)

    assert approve_proposal(session, "Mom", proposal_id)["approved"] is True


def test_a_proposal_is_decided_only_once(session):
    proposal_id = a_proposal(session)
    approve_proposal(session, "Dad", proposal_id)

    with pytest.raises(CannotApply) as raised:
        approve_proposal(session, "Dad", proposal_id)
    assert "already approved" in str(raised.value)


def test_a_rejected_proposal_cannot_then_be_approved(session):
    proposal_id = a_proposal(session)
    reject_proposal(session, "Dad", proposal_id)
    with pytest.raises(CannotApply):
        approve_proposal(session, "Dad", proposal_id)


def test_who_decided_is_recorded(session):
    proposal_id = a_proposal(session)
    approve_proposal(session, "Mom", proposal_id)
    mom = session.scalars(sa.select(Member).where(Member.name == "Mom")).one()
    assert session.get(Proposal, proposal_id).decided_by == mom.id


def test_a_proposal_referring_to_a_deleted_event_changes_nothing(session):
    """All or nothing: a half-applied plan would be worse than a refused one."""
    proposal_id = a_proposal(session)
    before = football_driver(session)

    project = session.scalars(sa.select(Event).where(Event.title == "science project block")).one()
    session.delete(project)
    session.commit()

    result = approve_proposal(session, "Dad", proposal_id)

    assert result["approved"] is False
    assert "no longer in the calendar" in result["say"]
    assert football_driver(session) == before, "the assignment must not have been applied either"
    assert session.get(Proposal, proposal_id).status == "pending"


def test_the_confirmation_says_what_was_done(session):
    say = approve_proposal(session, "Dad", a_proposal(session))["say"]
    assert say.startswith("Done.")
    assert "Mom has football practice" in say


def test_pending_proposals_can_be_listed_and_say_whose_call_it_is(session):
    a_proposal(session)
    for_dad = list_proposals(session, "Dad")
    for_aarav = list_proposals(session, "Aarav")

    assert len(for_dad["proposals"]) == 1
    assert for_dad["proposals"][0]["yours_to_decide"] is True
    assert for_dad["proposals"][0]["created_by"] == "Dad"
    assert for_aarav["proposals"][0]["yours_to_decide"] is False


def test_a_decided_proposal_drops_off_the_waiting_list(session):
    proposal_id = a_proposal(session)
    approve_proposal(session, "Dad", proposal_id)
    assert list_proposals(session, "Dad")["proposals"] == []
