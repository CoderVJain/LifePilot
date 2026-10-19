"""add_event: the only way data gets in, and it still goes through a parent.

A tester asked how anything would ever be added to the database. Nothing could: the approval executor
understood only "reassign" and "move". These tests pin the whole path -- propose, write nothing,
approve, one row -- and the refusals around it.
"""

from datetime import date

import pytest
import sqlalchemy as sa

from eval.generate import build_demo_family
from lifepilot.db.models import Event, Proposal
from lifepilot.db.session import make_engine, make_session_factory
from lifepilot.tools.add_event import CannotAdd, add_event
from lifepilot.tools.approve import CannotApply, approve_proposal, reject_proposal
from lifepilot.tools.approve import NotAllowed as CannotDecide
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


def test_proposing_writes_nothing(session):
    """The whole point of the loop: LifePilot never changes a family's plan on its own."""
    before = count_events(session)
    result = add_event(session, "Dad", title="team meeting", start="2026-10-09T17:00")

    assert result["status"] == "pending"
    assert count_events(session) == before
    assert session.get(Proposal, result["proposal_id"]).status == "pending"


def test_approving_adds_exactly_one_event(session):
    before = count_events(session)
    result = add_event(session, "Dad", title="team meeting", start="2026-10-09T17:00")
    approve_proposal(session, "Dad", result["proposal_id"])

    assert count_events(session) == before + 1
    added = session.scalars(sa.select(Event).where(Event.title == "team meeting")).one()
    assert added.start.isoformat() == "2026-10-09T17:00:00"
    assert added.end.isoformat() == "2026-10-09T18:00:00", "an hour by default"
    assert added.movable is True


def test_rejecting_leaves_the_calendar_alone(session):
    before = count_events(session)
    result = add_event(session, "Dad", title="team meeting", start="2026-10-09T17:00")
    reject_proposal(session, "Dad", result["proposal_id"])

    assert count_events(session) == before
    assert session.get(Proposal, result["proposal_id"]).status == "rejected"


def test_a_child_cannot_add_an_event(session):
    with pytest.raises(NotAllowed):
        add_event(session, "Aarav", title="party", start="2026-10-09T18:00")


def test_a_caregiver_cannot_add_an_event(session):
    with pytest.raises(NotAllowed):
        add_event(session, "Grandpa", title="bowls", start="2026-10-09T18:00")


def test_a_child_cannot_approve_a_parents_proposal(session):
    result = add_event(session, "Dad", title="team meeting", start="2026-10-09T17:00")
    before = count_events(session)

    with pytest.raises(CannotDecide):
        approve_proposal(session, "Aarav", result["proposal_id"])

    assert count_events(session) == before
    assert session.get(Proposal, result["proposal_id"]).status == "pending"


def test_a_replacement_is_judged_against_the_week_it_would_leave(session):
    """Both legs are approved together, so both are judged together.

    Judged against a week that still held what it replaces, this reported "Dad is in two places at
    once: performance review and client call" -- a clash with the very event being removed. Same
    lesson `request_swap` learned about judging a parent who still holds what they are handing over.
    """
    result = add_event(
        session, "Dad", title="client call", start="2026-10-08T16:30", end="2026-10-08T17:30"
    )

    # Comparable in length, so it is offered as a swap. The review is immovable, and saying so is the
    # point: nobody should drop a performance review thinking it was an ordinary hour.
    assert result["replaces"]["title"] == "performance review"
    assert result["breaks"] == [], "the only clash was with the event this takes out"
    assert "fixed commitment" in result["say"]
    assert result["say"].endswith("Shall I replace it with client call?")


def test_an_event_that_breaks_the_week_says_so_before_asking(session):
    """It is proposed either way -- the parent decides -- but they are told what it costs.

    This one replaces something *and* breaks a rule, which is what keeps the two independent: a
    replacement must not quietly swallow a real problem.
    """
    result = add_event(
        session,
        "Dad",
        title="revision",
        start="2026-10-08T20:30",
        end="2026-10-08T22:00",
        members=["Aarav"],
        category="study",
    )

    assert result["replaces"]["title"] == "science project block"
    assert [b["detail"] for b in result["breaks"]] == [
        "revision runs to 10 PM, past your rule of 9 PM"
    ]


def test_an_event_that_breaks_nothing_says_that_instead(session):
    result = add_event(session, "Dad", title="team meeting", start="2026-10-09T19:00")
    assert result["breaks"] == []
    assert "Nothing else breaks" in result["say"]


def test_the_event_belongs_to_whoever_asked_unless_told_otherwise(session):
    """"My five o'clock" is the asker's, so nothing has to be said about whose it is."""
    result = add_event(session, "Mom", title="dentist", start="2026-10-09T11:00")
    approve_proposal(session, "Mom", result["proposal_id"])

    added = session.scalars(sa.select(Event).where(Event.title == "dentist")).one()
    mom_owned = session.scalars(sa.select(Event).where(Event.title == "piano class")).one()
    assert added.member_ids != mom_owned.member_ids, "piano is Anaya's, dentist is Mom's"
    assert len(added.member_ids) == 1


def test_naming_a_member_puts_it_in_their_day(session):
    result = add_event(
        session, "Dad", title="swimming", start="2026-10-09T18:00", members=["Aarav"],
        needs_transport=True,
    )
    approve_proposal(session, "Dad", result["proposal_id"])

    added = session.scalars(sa.select(Event).where(Event.title == "swimming")).one()
    aarav = session.scalars(sa.select(Event).where(Event.title == "football practice")).one()
    assert added.member_ids == aarav.member_ids
    assert added.needs_transport is True


def test_a_name_nobody_has_is_refused_rather_than_guessed(session):
    with pytest.raises(CannotAdd):
        add_event(session, "Dad", title="lunch", start="2026-10-09T12:00", members=["Priya"])


def test_a_time_that_is_not_a_time_is_refused(session):
    with pytest.raises(CannotAdd):
        add_event(session, "Dad", title="lunch", start="sometime tuesday")


def test_an_unknown_place_is_left_empty_rather_than_invented(session):
    """Inventing a location would put a place in the week with no journey known to or from it, and
    reachability would quietly treat it as next door."""
    result = add_event(
        session, "Dad", title="offsite", start="2026-10-09T10:00", location="Bangalore"
    )
    approve_proposal(session, "Dad", result["proposal_id"])

    added = session.scalars(sa.select(Event).where(Event.title == "offsite")).one()
    assert added.location_id is None


def test_an_end_before_its_start_becomes_an_hour(session):
    """"A meeting at five" arrives as the same moment twice; that is an hour, not a contradiction."""
    result = add_event(
        session, "Dad", title="standup", start="2026-10-09T09:00", end="2026-10-09T09:00"
    )
    approve_proposal(session, "Dad", result["proposal_id"])

    added = session.scalars(sa.select(Event).where(Event.title == "standup")).one()
    assert (added.end - added.start).total_seconds() == 3600


def test_an_approved_proposal_cannot_be_approved_twice(session):
    result = add_event(session, "Dad", title="team meeting", start="2026-10-09T17:00")
    approve_proposal(session, "Dad", result["proposal_id"])
    before = count_events(session)

    with pytest.raises(CannotApply):
        approve_proposal(session, "Dad", result["proposal_id"])

    assert count_events(session) == before, "no duplicate row"


# --------------------------------------------------------------------------- one of them, not both


def book(session, title, start="2026-10-09T16:00", end="2026-10-09T17:00", who="Dad"):
    return add_event(session, who, title=title, start=start, end=end)


def test_a_taken_slot_is_offered_as_a_swap(session):
    """Asked for: booking four o'clock when four o'clock is taken means one of them, not both.
    Stacking two events and warning about it left the diary in a state nobody asked for."""
    approve_proposal(session, "Dad", book(session, "client call")["proposal_id"])

    second = book(session, "team meeting")

    assert second["replaces"]["title"] == "client call"
    assert "You already have client call" in second["say"]
    assert "Shall I replace it with team meeting?" in second["say"]


def test_approving_a_swap_leaves_one_event_not_two(session):
    approve_proposal(session, "Dad", book(session, "client call")["proposal_id"])
    before = count_events(session)

    approve_proposal(session, "Dad", book(session, "team meeting")["proposal_id"])

    assert count_events(session) == before, "swapped, not stacked"
    titles = {e.title for e in session.scalars(sa.select(Event))}
    assert "team meeting" in titles
    assert "client call" not in titles


def test_refusing_a_swap_keeps_what_was_there(session):
    approve_proposal(session, "Dad", book(session, "client call")["proposal_id"])
    before = count_events(session)

    reject_proposal(session, "Dad", book(session, "team meeting")["proposal_id"])

    titles = {e.title for e in session.scalars(sa.select(Event))}
    assert count_events(session) == before
    assert "client call" in titles, "the old one survives a no"
    assert "team meeting" not in titles


def test_a_lift_assignment_goes_with_the_event_it_belonged_to(session):
    """Removing an event must not leave an assignment pointing at nothing."""
    from lifepilot.db.models import Assignment

    first = add_event(
        session, "Dad", title="swimming", start="2026-10-09T18:00", end="2026-10-09T19:00",
        members=["Aarav"], needs_transport=True,
    )
    approve_proposal(session, "Dad", first["proposal_id"])
    swimming = session.scalars(sa.select(Event).where(Event.title == "swimming")).one()
    session.add(Assignment(event_id=swimming.id, member_id=1, kind="pickup"))
    session.commit()
    before = session.scalar(sa.select(sa.func.count()).select_from(Assignment))

    # Aarav's slot, so Aarav's swimming is what stands in its way.
    replacement = add_event(
        session, "Dad", title="chess club", start="2026-10-09T18:00", end="2026-10-09T19:00",
        members=["Aarav"],
    )
    assert replacement["replaces"]["title"] == "swimming"
    approve_proposal(session, "Dad", replacement["proposal_id"])

    assert session.scalar(sa.select(sa.func.count()).select_from(Assignment)) == before - 1


def test_a_long_containing_block_is_not_offered_for_deletion(session):
    """The judgement call: an hour inside a nine-to-half-four working day is not a swap. Offering to
    delete somebody's whole day because they asked for an hour in the middle of it would be the most
    destructive reading of a reasonable request."""
    asked = book(session, "team meeting")

    assert asked["replaces"] is None
    assert "breaks one thing" in asked["say"]
    assert "Shall I still put it in?" in asked["say"]


def test_somebody_elses_commitment_does_not_block_you(session):
    """Mom's work is not in the way of Dad booking an hour."""
    asked = add_event(session, "Mom", title="yoga", start="2026-10-09T18:00",
                      end="2026-10-09T19:00")
    assert asked["replaces"] is None
    assert "Nothing else breaks" in asked["say"]


def test_an_event_that_vanished_before_approval_is_not_an_error(session):
    """The end state is the one that was asked for, whoever got there first."""
    approve_proposal(session, "Dad", book(session, "client call")["proposal_id"])
    swap = book(session, "team meeting")

    call = session.scalars(sa.select(Event).where(Event.title == "client call")).one()
    session.delete(call)
    session.commit()

    approve_proposal(session, "Dad", swap["proposal_id"])

    assert {e.title for e in session.scalars(sa.select(Event))} >= {"team meeting"}
