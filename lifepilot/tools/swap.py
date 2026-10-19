"""request_swap (#6): two parents trade two lifts, in one proposal, decided by the other one.

A swap is two reassignments that stand or fall together. "You take Thursday, I'll take Monday" is not
two favours; agreeing to half of it leaves a week nobody chose. So it is one proposal carrying two
`assign` changes, which `approve_proposal` already applies all-or-nothing.

The cross-session part needs no new machinery: `needs_approval_from` is set to the other parent, and
the approval rules already refuse everyone else. She says yes in her own session and the plan moves.

Feasibility is checked under the **swapped** arrangement, not the current one, so a swap can never be
offered that breaks either parent's day. The reasons come from reachability, so a refusal names a
specific commitment or travel time rather than saying no.
"""

from datetime import date, datetime, time

import sqlalchemy as sa
from sqlalchemy.orm import Session

from lifepilot.db.models import Member, Proposal
from lifepilot.engine.reachability import assess
from lifepilot.tools.context import resolve_viewer
from lifepilot.tools.detect_conflicts import load_week
from lifepilot_shared.speech import say_when
from lifepilot_shared.week import demo_week


class Ambiguous(Exception):
    """That day holds more than one lift, so which one was meant is a real question."""

    def __init__(self, whose: str, day: date, lifts: list[dict]):
        self.whose, self.day, self.lifts = whose, day, lifts
        super().__init__(f"{whose} has {len(lifts)} lifts on {day}")


def request_swap(
    session: Session,
    speaker: str,
    partner: str,
    give_day: date | None = None,
    take_day: date | None = None,
    give_event_id: int | None = None,
    take_event_id: int | None = None,
) -> dict:
    """Propose trading a lift of mine for one of theirs. Creates nothing unless both legs work."""
    viewer = resolve_viewer(session, speaker)
    if viewer.role != "parent":
        return {"proposed": False, "say": "Only a parent can arrange a swap."}

    family_id = session.get(Member, viewer.member_id).family_id
    other = _partner(session, family_id, partner)
    if other is None:
        return {"proposed": False, "say": _no_such_partner(session, family_id, partner)}
    if other.id == viewer.member_id:
        return {"proposed": False, "say": "A swap needs two people."}

    week = load_week(session, family_id, *_window(give_day, take_day))

    try:
        giving = _lift_of(week, viewer.member_id, viewer.name, give_day, give_event_id)
        taking = _lift_of(week, other.id, other.name, take_day, take_event_id)
    except Ambiguous as question:
        return {
            "proposed": False,
            "whose": question.whose,
            "options": question.lifts,
            "say": _which_one(question),
        }

    if giving is None or taking is None:
        return {"proposed": False, "say": _nothing_to_swap(viewer, other, giving, taking,
                                                           give_day, take_day)}

    swapped = _with_swap(week, giving, taking, viewer.member_id, other.id)
    blocked = _first_problem(week, swapped, [(giving, other), (taking, viewer)])
    if blocked is not None:
        return {"proposed": False, "feasible": False, **blocked}

    proposal = Proposal(
        family_id=family_id,
        kind="swap",
        created_by=viewer.member_id,
        changes=[
            _change(giving, other, viewer, swapped.whys[giving.event_id]),
            _change(taking, viewer, other, swapped.whys[taking.event_id]),
        ],
        violations=[],
        status="pending",
        needs_approval_from=other.id,
    )
    session.add(proposal)
    session.commit()

    return {
        "proposed": True,
        "feasible": True,
        "proposal_id": proposal.id,
        "awaiting": other.name,
        "change_count": len(proposal.changes),
        "changes": proposal.changes,
        "say": (
            f"I have asked {other.name} to take {giving.title} {say_when(giving.moment)}, "
            f"with you taking {taking.title} {say_when(taking.moment)}. "
            f"It works for both of you. {other.name} has to agree before anything changes."
        ),
    }


def _window(*days: date | None) -> tuple[date, date]:
    """The week to search. Naming a lift outright is enough, so days are optional: without one the
    loaded week is the same demo week every other tool answers about."""
    named = [d for d in days if d is not None]
    if not named:
        return demo_week()
    start, end = min(named), max(named)
    return min(start, demo_week()[0]), max(end, demo_week()[1])


# --------------------------------------------------------------------------- finding the two lifts


def _parents(session: Session, family_id: int) -> list[Member]:
    return list(
        session.scalars(
            sa.select(Member).where(Member.family_id == family_id, Member.role == "parent")
        )
    )


def _partner(session: Session, family_id: int, name: str) -> Member | None:
    """The other parent, by name. A swap trades duties, so it is parents only."""
    wanted = (name or "").strip().lower()
    return next((m for m in _parents(session, family_id) if m.name.lower() == wanted), None)


def _lift_of(week, member_id: int, name: str, day: date | None, event_id: int | None):
    """A lift this person currently holds: named outright, or the one on that day.

    More than one on the day is not resolved by picking the earliest. Swapping the school run when
    the parent meant football is a silent wrong answer, so it raises and the caller asks.
    """
    held = [n for n in week.needs if week.assigned.get(n.event_id) == member_id]

    if event_id is not None:
        return next((n for n in held if n.event_id == event_id), None)
    if day is None:
        return None

    on_day = [n for n in held if n.moment.date() == day]
    if len(on_day) > 1:
        raise Ambiguous(
            name,
            day,
            [{"event_id": n.event_id, "title": n.title,
              "when": n.moment.isoformat(timespec="minutes")} for n in on_day],
        )
    return on_day[0] if on_day else None


# --------------------------------------------------------------------------- feasibility


class _Swapped:
    """The week as it would be, plus the reason each new driver can do their leg."""

    def __init__(self, driven, assigned):
        self.driven, self.assigned = driven, assigned
        self.whys: dict[int, str] = {}


def _with_swap(week, giving, taking, mine: int, theirs: int) -> _Swapped:
    """The driving arrangement after the trade. Checking against the old one would be checking the
    wrong week: each parent is judged while still holding the lift they are handing over."""
    assigned = dict(week.assigned)
    assigned[giving.event_id] = theirs
    assigned[taking.event_id] = mine

    driven: dict[int, set[int]] = {}
    for event_id, member_id in assigned.items():
        driven.setdefault(member_id, set()).add(event_id)
    return _Swapped({k: frozenset(v) for k, v in driven.items()}, assigned)


def _first_problem(week, swapped: _Swapped, legs) -> dict | None:
    """Check each leg against the swapped week; the first that fails stops the swap.

    Recording the reason for the legs that pass is what lets the proposal explain itself later
    without asking anything again.
    """
    eligibility = [rule["params"] for rule in week.rules if rule["type"] == "eligibility"]
    for need, driver in legs:
        candidates = assess(
            need, week.people, week.commitments, week.travel, swapped.driven, eligibility
        )
        theirs = next((c for c in candidates if c.person_id == _id_of(driver)), None)
        if theirs is None or not theirs.reachable:
            reason = theirs.reason if theirs else "is not in the family"
            return {
                "blocked_leg": need.title,
                "blocked_person": _name_of(driver),
                "reason": reason,
                "say": (
                    f"That swap will not work: {_name_of(driver)} cannot take {need.title} "
                    f"{say_when(need.moment)}: {_name_of(driver)} {reason}."
                ),
            }
        swapped.whys[need.event_id] = theirs.reason
    return None


def _id_of(person) -> int:
    return getattr(person, "member_id", None) or person.id


def _name_of(person) -> str:
    return person.name


def _change(need, driver, holder, why: str) -> dict:
    """One leg of the trade, in the shape the proposal card reads.

    `was` and `now` are the card's contract, shared with `fix_week`: without them it rendered
    "undefined -> Mom" in the browser while the fix card beside it was correct.
    """
    return {
        "kind": "assign",
        "event_id": need.event_id,
        "person_id": _id_of(driver),
        "title": need.title,
        "when": need.moment.isoformat(timespec="minutes"),
        "was": _name_of(holder),
        "now": _name_of(driver),
        "reason": f"{_name_of(driver)} {why}",
    }


# --------------------------------------------------------------------------- wording


def _no_such_partner(session: Session, family_id: int, name: str) -> str:
    parents = ", ".join(m.name for m in _parents(session, family_id))
    return f"I do not know a parent called {name}. The parents here are {parents}."


def _which_one(question: Ambiguous) -> str:
    listed = ", ".join(
        f"{lift['title']} {say_when(datetime.fromisoformat(lift['when']))}"
        for lift in question.lifts
    )
    return f"{question.whose} has more than one lift that day: {listed}. Which one?"


def _nothing_to_swap(viewer, other, giving, taking, give_day, take_day) -> str:
    """Whose side was empty, and whether a day or a named lift came up short.

    A lift named outright that the person does not hold is a different mistake from a free day, and
    saying "no lift then" when a lift was named by name reads as if the name was not understood.
    """
    if giving is None and give_day is None:
        return "That is not one of your lifts."
    if giving is None:
        return f"You do not have a lift {_day_words(give_day)} to swap."
    if take_day is None:
        return f"That is not one of {other.name}'s lifts."
    return f"{other.name} does not have a lift {_day_words(take_day)}."


def _day_words(day: date | None) -> str:
    if day is None:
        return "then"
    return say_when(datetime.combine(day, time.min), with_day=True).replace(" at 12 AM", "")
