"""scan_risks: the warning, the slot, and the approval that books it.

The loop everything rests on, applied to tasks: observe -> detect -> propose -> approve -> execute.
Nothing reaches the diary without a parent's yes.
"""

from datetime import datetime, timedelta

import pytest
import sqlalchemy as sa

from eval.generate import MONDAY, build_demo_family
from lifepilot.db.models import Event, Member, Proposal, Task
from lifepilot.db.session import make_engine, make_session_factory
from lifepilot.tools.approve import approve_proposal
from lifepilot.tools.scan_risks import scan_risks

FRIDAY = MONDAY + timedelta(days=4)


@pytest.fixture
def session():
    factory = make_session_factory(make_engine("sqlite+pysqlite:///:memory:"), create=True)
    with factory() as made:
        build_demo_family(made)
        yield made


def _member(session, name: str) -> Member:
    return session.scalars(sa.select(Member).where(Member.name == name)).one()


def _add_task(session, title: str, due: datetime, est: int = 90, prep: int = 2, owner="Aarav"):
    task = Task(
        family_id=1, owner_id=_member(session, owner).id, title=title, category="study",
        due=due, est_minutes=est, prep_days=prep, source="email",
    )
    session.add(task)
    session.commit()
    return task


def test_the_seeded_week_has_time_set_aside_already(session):
    """The demo family's project has a block booked for it, so warning about it would be noise."""
    found = scan_risks(session, "Dad", on=MONDAY)
    assert found["at_risk"] == []
    assert "Nothing is at risk" in found["say"]


def test_a_task_from_an_email_is_flagged_with_a_slot(session):
    """The case that matters: a task nobody put in the calendar, so nothing is set aside."""
    _add_task(session, "costume making", datetime.combine(FRIDAY, datetime.min.time()))
    found = scan_risks(session, "Dad", on=MONDAY + timedelta(days=3))

    assert len(found["at_risk"]) == 1
    risk = found["at_risk"][0]
    assert risk["title"] == "costume making"
    assert risk["kinds"] == ["unbooked"]
    assert risk["slot"] is not None
    assert "Shall I put it in?" in found["say"]


def test_the_offer_books_only_what_the_task_needs(session):
    """A ninety-minute job does not take the whole evening; claiming the lot would make the next
    thing look impossible."""
    _add_task(session, "costume making", datetime.combine(FRIDAY, datetime.min.time()), est=90)
    found = scan_risks(session, "Dad", on=MONDAY + timedelta(days=3))

    change = found["changes"][0]
    start = datetime.fromisoformat(change["start_iso"])
    end = datetime.fromisoformat(change["end_iso"])
    assert (end - start) == timedelta(minutes=90)


def test_nothing_is_in_the_diary_until_a_parent_says_yes(session):
    _add_task(session, "costume making", datetime.combine(FRIDAY, datetime.min.time()))
    before = session.scalar(sa.select(sa.func.count()).select_from(Event))
    found = scan_risks(session, "Dad", on=MONDAY + timedelta(days=3))

    assert session.get(Proposal, found["proposal_id"]).status == "pending"
    assert session.scalar(sa.select(sa.func.count()).select_from(Event)) == before

    approve_proposal(session, "Dad", found["proposal_id"])
    assert session.get(Proposal, found["proposal_id"]).status == "approved"
    assert session.scalar(sa.select(sa.func.count()).select_from(Event)) == before + 1


def test_the_booked_block_belongs_to_the_child_who_owns_the_task(session):
    _add_task(session, "costume making", datetime.combine(FRIDAY, datetime.min.time()))
    found = scan_risks(session, "Dad", on=MONDAY + timedelta(days=3))
    approve_proposal(session, "Dad", found["proposal_id"])

    aarav = _member(session, "Aarav").id
    booked = session.scalars(sa.select(Event).where(Event.title.like("%costume%"))).one()
    assert booked.member_ids == [aarav]


def test_once_booked_the_task_stops_being_at_risk(session):
    """The scan has to notice its own repair, or it warns about the same thing forever."""
    _add_task(session, "costume making", datetime.combine(FRIDAY, datetime.min.time()))
    on = MONDAY + timedelta(days=3)
    found = scan_risks(session, "Dad", on=on)
    approve_proposal(session, "Dad", found["proposal_id"])

    again = scan_risks(session, "Dad", on=on)
    assert again["at_risk"] == []


def test_a_child_sees_only_their_own_tasks(session):
    _add_task(session, "costume making", datetime.combine(FRIDAY, datetime.min.time()),
              owner="Aarav")
    on = MONDAY + timedelta(days=3)
    assert scan_risks(session, "Aarav", on=on)["at_risk"]
    assert scan_risks(session, "Anaya", on=on)["at_risk"] == []


def test_a_caregiver_has_no_tasks_to_forget(session):
    _add_task(session, "costume making", datetime.combine(FRIDAY, datetime.min.time()))
    on = MONDAY + timedelta(days=3)
    assert scan_risks(session, "Grandpa", on=on)["at_risk"] == []


def test_a_task_with_no_room_left_says_something_has_to_move(session):
    """No slot means no offer. Inventing one would be the thing the project refuses to do."""
    due = datetime.combine(MONDAY + timedelta(days=1), datetime.min.time())
    _add_task(session, "impossible model", due, est=600, prep=1)
    found = scan_risks(session, "Dad", on=MONDAY)

    assert found["at_risk"][0]["kinds"] == ["not_enough_time"]
    assert found["at_risk"][0]["slot"] is None
    assert "has to move" in found["say"]
    assert "proposal_id" not in found
