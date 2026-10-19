"""cancel_event: the other half of the write path.

You could book an event and you could not cancel one, so a planner that only added things was the
whole of it. `_apply_remove` already existed and worked -- reachable only as the `remove` leg of a
booking over a taken slot -- which made this the fourth thing built, tested and unreachable.

A cancellation cannot create a clash; it frees time. So these tests are not `add_event`'s run
backwards: they pin what the cancellation *unblocks*, who else loses it, and the two cases where
LifePilot must ask instead of deleting.
"""

from datetime import date

import pytest
import sqlalchemy as sa

from eval.generate import build_demo_family
from lifepilot.db.models import Assignment, Event, Proposal
from lifepilot.db.session import make_engine, make_session_factory
from lifepilot.tools.approve import approve_proposal
from lifepilot.tools.cancel_event import cancel_event
from lifepilot.tools.fix_week import NotAllowed

THURSDAY = date(2026, 10, 8)


@pytest.fixture
def session():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    factory = make_session_factory(engine, create=True)
    with factory() as s:
        build_demo_family(s)
        yield s


def count_events(session) -> int:
    return session.scalar(sa.select(sa.func.count()).select_from(Event))


def test_proposing_a_cancellation_writes_nothing(session):
    """The same gate as every other change: nothing goes until a parent says yes."""
    before = count_events(session)
    result = cancel_event(session, "Dad", title="performance review")

    assert result["proposal_id"]
    assert result["status"] == "pending"
    assert count_events(session) == before, "the event is still there until it is approved"


def test_a_cancellation_can_repair_the_week(session):
    """The differentiator. Dad's review is what makes Thursday's football pickup unreachable, so
    cancelling it is not just a deletion -- it fixes the thing the week was broken by."""
    result = cancel_event(session, "Dad", title="performance review")

    assert "football practice pickup" in result["frees"]
    assert "It also fixes football practice pickup." in result["say"]
    assert result["strands"] == []


def test_everyone_who_loses_the_event_is_named(session):
    """Lunch at Grandpa's is one row with five people on it. A cancellation that silently empties
    three other people's afternoons is the failure mode here."""
    result = cancel_event(session, "Dad", title="lunch at grandpa's")

    assert result["also_loses_it"] == ["Mom", "Aarav", "Anaya", "Grandpa"]
    assert "clears the day for Mom, Aarav, Anaya and Grandpa" in result["say"]


def test_a_lift_nobody_needs_any_more_is_said_once(session):
    """Cancelling football practice makes its pickup go away, but it did not *fix* it: there is
    nothing left to drive to. Saying both read as two separate pieces of good news."""
    result = cancel_event(session, "Dad", title="football practice")

    assert result["lifts_no_longer_needed"] == ["football practice pickup"]
    assert result["frees"] == [], "deleting the reason for a lift is not fixing the lift"
    assert result["say"].count("football practice pickup") == 1


def test_two_of_the_askers_own_events_is_a_question_not_a_guess(session):
    """The rule `request_swap` already follows. Guessing here deletes the wrong thing."""
    result = cancel_event(session, "Dad", title="work")

    assert result["cancelled"] is False
    assert result.get("proposal_id") is None, "an ambiguous cancellation proposes nothing"
    assert len(result["options"]) == 5
    assert result["say"].startswith("Which one:")


def test_naming_the_day_settles_which_one(session):
    result = cancel_event(session, "Dad", title="work", day=THURSDAY)

    assert result["proposal_id"]
    assert result["title"] == "work"
    # Thursday is the pinned "today", so the spoken form says so. The day still did the narrowing.
    assert session.get(Event, _only_change(session, result)["event_id"]).start.date() == THURSDAY


def test_the_askers_own_event_wins_over_the_other_parents(session):
    """"My meeting" is a claim about the asker's own diary. Both parents work on Thursday."""
    result = cancel_event(session, "Mom", title="work", day=THURSDAY)

    event = session.get(Event, result["proposal_id"] and _only_change(session, result)["event_id"])
    names = {m for m in event.member_ids}
    assert names == {_member_id(session, "Mom")}


def test_a_rule_pinned_event_is_refused_until_the_parent_says_it_again(session):
    """Cancelling what a family rule pins is a stronger act than moving it, so it is never a
    silent yes. `movable = False` in the data is a different thing: that is a property of the
    event, and a parent is the authority on their own diary."""
    refused = cancel_event(session, "Dad", title="piano class")

    assert refused.get("proposal_id") is None
    assert refused["blocked_by_rule"] == "piano class"
    assert "cannot move" in refused["say"]

    anyway = cancel_event(session, "Dad", title="piano class", override=True)
    assert anyway["proposal_id"], "a parent who means it is still the authority"


def test_a_fixed_commitment_that_no_rule_names_is_simply_offered(session):
    """Lunch at Grandpa's is `movable = False` seed data, not an `immovable_event` rule."""
    result = cancel_event(session, "Dad", title="lunch at grandpa's")

    assert result["proposal_id"]
    assert "blocked_by_rule" not in result


def test_only_a_parent_can_cancel(session):
    with pytest.raises(NotAllowed):
        cancel_event(session, "Aarav", title="football practice")


def test_nothing_of_that_name_lists_what_there_is(session):
    result = cancel_event(session, "Dad", title="yoga")

    assert result.get("proposal_id") is None
    assert "I cannot find yoga" in result["say"]
    assert "football practice" in result["say"]


def test_approving_removes_the_event_and_its_lift(session):
    """The end of the path. `_apply_remove` takes the assignments with it, which is why no new
    approval machinery was needed."""
    proposed = cancel_event(session, "Dad", title="football practice")
    event_id = _only_change(session, proposed)["event_id"]
    before = count_events(session)

    done = approve_proposal(session, "Dad", proposed["proposal_id"])

    assert done["approved"] is True
    assert count_events(session) == before - 1
    assert session.get(Event, event_id) is None
    assert session.scalars(
        sa.select(Assignment).where(Assignment.event_id == event_id)
    ).first() is None, "the lift goes with the event"


def _only_change(session, result: dict) -> dict:
    proposal = session.get(Proposal, result["proposal_id"])
    assert len(proposal.changes) == 1
    return proposal.changes[0]


def _member_id(session, name: str) -> int:
    from lifepilot.db.models import Member

    return session.scalars(sa.select(Member).where(Member.name == name)).one().id


def test_an_event_that_is_already_over_says_so(session, monkeypatch):
    """Offering to cancel something that has happened reads as not knowing what day it is. It is
    still offered -- a parent may be tidying up -- but it is named for what it is."""
    monkeypatch.setenv("LIFEPILOT_TODAY", "2026-10-09")
    result = cancel_event(session, "Dad", title="performance review")

    assert result["proposal_id"], "still offered"
    assert "already happened" in result["say"]


def test_a_replacement_rides_in_the_same_proposal(session):
    """Flow A: "cancel our lunch at Grandpa's and book lunch with Mom instead" is one decision, so
    it is one proposal -- both legs or neither."""
    result = cancel_event(
        session, "Dad", title="lunch at grandpa's",
        replace_with="lunch with Mom", replace_members=["Mom"],
    )
    proposal = session.get(Proposal, result["proposal_id"])

    assert [c["kind"] for c in proposal.changes] == ["remove", "add"]
    assert result["replaced_by"] == "lunch with Mom"
    assert "putting lunch with Mom in its place for Dad and Mom" in result["say"]


def test_the_replacement_is_for_whoever_was_named_not_whoever_was_there(session):
    """Lunch at Grandpa's has five people on it. Carrying them over would quietly re-book the
    children and Grandpa into something nobody mentioned."""
    result = cancel_event(
        session, "Dad", title="lunch at grandpa's",
        replace_with="lunch with Mom", replace_members=["Mom"],
    )
    added = session.get(Proposal, result["proposal_id"]).changes[1]

    assert sorted(added["members"]) == ["Dad", "Mom"]


def test_approving_a_replacement_does_both_legs(session):
    before = count_events(session)
    result = cancel_event(
        session, "Dad", title="lunch at grandpa's",
        replace_with="lunch with Mom", replace_members=["Mom"],
    )
    approve_proposal(session, "Dad", result["proposal_id"])

    titles = {e.title for e in session.scalars(sa.select(Event))}
    assert "lunch at grandpa's" not in titles
    assert "lunch with Mom" in titles
    assert count_events(session) == before, "one out, one in"


def test_a_cancellation_with_no_replacement_is_still_one_change(session):
    result = cancel_event(session, "Dad", title="football practice")
    assert result["replaced_by"] is None
    assert len(session.get(Proposal, result["proposal_id"]).changes) == 1
