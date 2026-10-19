"""request_swap (#6): two parents trade two lifts, and only the other one can say yes.

The seeded week carries exactly one lift a swap can be built on: Mom's Tuesday 6 PM cricket
collection, the only one of hers Dad can reach from the office. Everything else of Mom's is the
3 o'clock school run or 4:45 piano, which Dad can never make, so those pairings are correctly refused
and are tested as refusals.
"""

from datetime import date

import pytest
import sqlalchemy as sa

from eval.generate import build_demo_family
from lifepilot.db.models import Assignment, Event, Member, Proposal
from lifepilot.db.session import make_engine, make_session_factory
from lifepilot.tools.approve import approve_proposal, reject_proposal
from lifepilot.tools.swap import request_swap

MON, TUE, WED, THU = (date(2026, 10, d) for d in (5, 6, 7, 8))
FOOTBALL, MOM_SCHOOL_THU, MOM_PIANO = 18, 12, 17


@pytest.fixture
def session():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    factory = make_session_factory(engine, create=True)
    with factory() as s:
        build_demo_family(s)
        yield s


def _member(session, name: str) -> Member:
    return session.scalars(sa.select(Member).where(Member.name == name)).one()


def _late_lift_for_mom(session) -> int:
    """Mom's seeded Tuesday 6 PM cricket collection: the one lift Dad can genuinely take off her."""
    event = session.scalars(sa.select(Event).where(Event.title == "cricket practice")).one()
    return event.id


# --------------------------------------------------------------------------- the happy path


def test_a_workable_swap_becomes_one_proposal_awaiting_the_other_parent(session):
    cricket = _late_lift_for_mom(session)
    result = request_swap(
        session, "Dad", "Mom", give_event_id=FOOTBALL, take_event_id=cricket
    )

    assert result["proposed"] is True
    assert result["feasible"] is True
    assert result["awaiting"] == "Mom"

    proposal = session.get(Proposal, result["proposal_id"])
    assert proposal.kind == "swap"
    assert proposal.status == "pending"
    assert proposal.needs_approval_from == _member(session, "Mom").id
    assert proposal.created_by == _member(session, "Dad").id


def test_the_swap_carries_exactly_two_reassignments_each_with_a_reason(session):
    cricket = _late_lift_for_mom(session)
    result = request_swap(session, "Dad", "Mom", give_event_id=FOOTBALL, take_event_id=cricket)

    changes = result["changes"]
    assert len(changes) == 2
    assert {c["kind"] for c in changes} == {"assign"}
    assert {c["event_id"] for c in changes} == {FOOTBALL, cricket}
    for change in changes:
        assert change["reason"].strip()


# --------------------------------------------------------------------------- who may decide it


def test_the_asking_parent_cannot_approve_their_own_swap(session):
    cricket = _late_lift_for_mom(session)
    result = request_swap(session, "Dad", "Mom", give_event_id=FOOTBALL, take_event_id=cricket)

    with pytest.raises(PermissionError, match="only Mom"):
        approve_proposal(session, "Dad", result["proposal_id"])


def test_the_other_parent_accepting_moves_both_lifts(session):
    cricket = _late_lift_for_mom(session)
    result = request_swap(session, "Dad", "Mom", give_event_id=FOOTBALL, take_event_id=cricket)

    approve_proposal(session, "Mom", result["proposal_id"])

    dad, mom = _member(session, "Dad").id, _member(session, "Mom").id
    holder = {
        a.event_id: a.member_id
        for a in session.scalars(sa.select(Assignment).where(
            Assignment.event_id.in_([FOOTBALL, cricket])
        ))
    }
    assert holder[FOOTBALL] == mom
    assert holder[cricket] == dad


def test_declining_a_swap_leaves_both_lifts_where_they_were(session):
    cricket = _late_lift_for_mom(session)
    result = request_swap(session, "Dad", "Mom", give_event_id=FOOTBALL, take_event_id=cricket)

    reject_proposal(session, "Mom", result["proposal_id"])

    dad, mom = _member(session, "Dad").id, _member(session, "Mom").id
    holder = {
        a.event_id: a.member_id
        for a in session.scalars(sa.select(Assignment).where(
            Assignment.event_id.in_([FOOTBALL, cricket])
        ))
    }
    assert holder[FOOTBALL] == dad
    assert holder[cricket] == mom


def test_a_child_cannot_arrange_a_swap(session):
    result = request_swap(session, "Aarav", "Mom", give_day=THU, take_day=MON)
    assert result["proposed"] is False
    assert "parent" in result["say"]


# --------------------------------------------------------------------------- refusing, with a reason


def test_an_unworkable_swap_is_refused_and_names_what_blocks_it(session):
    result = request_swap(
        session, "Dad", "Mom", give_event_id=FOOTBALL, take_event_id=MOM_PIANO
    )

    assert result["proposed"] is False
    assert result["feasible"] is False
    assert result["blocked_person"] == "Dad"
    assert "arrives" in result["reason"]


def test_a_refused_swap_writes_no_proposal(session):
    request_swap(session, "Dad", "Mom", give_event_id=FOOTBALL, take_event_id=MOM_PIANO)
    assert session.scalars(sa.select(Proposal)).all() == []


def test_feasibility_is_judged_after_the_swap_not_before(session):
    """Mom holds Thursday's 3 PM school run and is asked to take the 5 PM football too.

    Judged against the week as it stands she is the football pickup's best candidate; the question
    the swap has to answer is whether she can do it while giving up nothing of her own.
    """
    result = request_swap(
        session, "Dad", "Mom", give_event_id=FOOTBALL, take_event_id=MOM_SCHOOL_THU
    )
    assert result["proposed"] is False
    assert result["blocked_person"] == "Dad"


# --------------------------------------------------------------------------- asking rather than guessing


def test_a_day_holding_two_of_their_lifts_is_a_question_not_a_guess(session):
    result = request_swap(session, "Dad", "Mom", give_day=THU, take_day=THU)

    assert result["proposed"] is False
    assert result["whose"] == "Mom"
    assert {o["event_id"] for o in result["options"]} == {MOM_SCHOOL_THU, MOM_PIANO}
    assert "Which one?" in result["say"]


def test_a_day_with_one_lift_each_needs_no_question(session):
    result = request_swap(session, "Dad", "Mom", give_day=THU, take_day=MON)
    assert "Which one?" not in result["say"]


def test_a_partner_who_is_not_a_parent_here_is_named_as_unknown(session):
    result = request_swap(session, "Dad", "Priya", give_day=THU, take_day=MON)
    assert result["proposed"] is False
    assert "Priya" in result["say"]
    assert "Dad, Mom" in result["say"]


def test_a_day_where_the_speaker_holds_nothing_says_so(session):
    result = request_swap(session, "Dad", "Mom", give_day=WED, take_day=MON)
    assert result["proposed"] is False
    assert "do not have a lift" in result["say"]


def test_naming_a_lift_the_partner_does_not_hold_says_that(session):
    """Dad's own football lift, offered as the one Mom hands back. It is not hers to give."""
    result = request_swap(
        session, "Dad", "Mom", give_event_id=FOOTBALL, take_event_id=FOOTBALL
    )
    assert result["proposed"] is False
    assert result["say"] == "That is not one of Mom's lifts."


def test_a_swap_fills_the_card_the_same_way_a_fix_does(session):
    """The proposal card is one template reading `change_count` and each change's `was` and `now`.
    A swap supplied neither, so the card rendered "undefined changes" and "undefined -> Mom" in the
    browser while the fix card beside it was right. One card, one contract."""
    cricket = _late_lift_for_mom(session)
    result = request_swap(
        session, "Dad", "Mom", give_event_id=FOOTBALL, take_event_id=cricket
    )

    assert result["change_count"] == 2
    for change in result["changes"]:
        assert change["was"], "who holds it now"
        assert change["now"], "who would take it"
        assert change["reason"]

    handed_over = next(c for c in result["changes"] if c["event_id"] == FOOTBALL)
    assert handed_over["was"] == "Dad"
    assert handed_over["now"] == "Mom"
    taken_on = next(c for c in result["changes"] if c["event_id"] == cricket)
    assert taken_on["was"] == "Mom"
    assert taken_on["now"] == "Dad"
