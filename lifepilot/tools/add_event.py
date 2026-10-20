"""add_event: put something new in the week, once a parent has said yes.

Nothing is written here. The event becomes a pending proposal, exactly as a repair does, and
`approve_proposal` is still the only thing that writes. A tester asked how data would ever get in;
this is the answer, and it goes through the same gate as every other change.

The new event is checked before it is proposed, by applying it to an in-memory copy of the week and
looking at what breaks. That reuses the what-if engine rather than repeating its reasoning, and it
means the proposal already carries the conflict and the fix, so the turn costs no extra model call.
"""

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session

from lifepilot.db.models import Event, Location, Member, Proposal
from lifepilot.engine.conflicts import detect
from lifepilot.engine.whatif import (
    CANCELLED,
    DEFAULT_LENGTH,
    apply_hypothetical,
    ripple,
)
from lifepilot.solver.repair import repair
from lifepilot.tools.cancel_event import who_else_loses_it
from lifepilot.tools.context import resolve_viewer
from lifepilot.tools.detect_conflicts import load_week
from lifepilot.tools.fix_week import NotAllowed
from lifepilot_shared.speech import say_list, say_span


class CannotAdd(ValueError):
    """The event could not be understood well enough to propose it."""


def add_event(
    session: Session,
    speaker: str,
    title: str,
    start: str,
    end: str | None = None,
    location: str | None = None,
    members: list[str] | None = None,
    needs_transport: bool = False,
    category: str = "other",
) -> dict:
    """Propose a new event. Returns the proposal, what it breaks, and how it could be fixed."""
    viewer = resolve_viewer(session, speaker)
    if viewer.role != "parent":
        raise NotAllowed(f"{viewer.name} is a {viewer.role}; only a parent can change the plan.")

    family_id = session.get(Member, viewer.member_id).family_id
    begins = _moment(start)
    finishes = _moment(end) if end else begins + DEFAULT_LENGTH
    if finishes <= begins:
        finishes = begins + DEFAULT_LENGTH

    whose = _members(session, family_id, members, viewer)
    place = _location(session, family_id, location)

    change = {
        "kind": "add",
        "title": title.strip(),
        "category": category,
        "start_iso": begins.isoformat(),
        "end_iso": finishes.isoformat(),
        "location_id": place.id if place else None,
        "location": place.name if place else None,
        "member_ids": [m.id for m in whose],
        "members": [m.name for m in whose],
        "needs_transport": bool(needs_transport),
        "reason": f"{speaker} asked for it",
    }

    week = load_week(session, family_id, begins.date(), finishes.date())
    taken = _already_there(session, family_id, change, begins, finishes)

    # Something comparable in the slot is offered as a swap: a parent booking four o'clock when four
    # o'clock is taken means one of them, not both. Stacking two events and warning about it left the
    # diary in a state nobody asked for.
    changes = [_removal(taken), change] if taken is not None else [change]

    # Both legs are judged together, because both are approved together. Judging the new event
    # against a week that still holds what it replaces reported "Dad is in two places at once:
    # performance review and coffee with Mom" -- a clash with the very event being removed. Same
    # lesson `request_swap` learned: judging a parent while they still hold what they are handing
    # over is judging the wrong week.
    planned = _week_after(week, change, taken)
    effect = ripple(detect(week), detect(planned))

    # Lunch at Grandpa's is one row with five people on it. Replacing it clears the afternoon of
    # everyone else on it too, and they are named before the yes rather than after it.
    losing = (
        who_else_loses_it(session, family_id, taken, viewer.member_id) if taken is not None else []
    )

    proposal = Proposal(
        family_id=family_id,
        kind="event",
        created_by=viewer.member_id,
        changes=changes,
        violations=[c.as_dict() for c in effect.breaks],
        status="pending",
    )
    session.add(proposal)
    session.commit()

    result = {
        "proposal_id": proposal.id,
        "status": "pending",
        "title": change["title"],
        "when": say_span(begins, finishes),
        "breaks": [c.as_dict() for c in effect.breaks],
        "replaces": _removal(taken) if taken is not None else None,
        "also_loses_it": losing,
        "say": _describe(change, effect, begins, finishes, taken, losing),
    }
    if effect.breaks:
        fix = repair(planned)
        result["fix"] = {
            "change_count": fix.change_count,
            "changes": [c.as_dict() for c in fix.changes],
            "unfixable": fix.unfixable,
        }
    return result


#: How much longer than the new event an existing one may be and still count as "the same slot".
#: A 4 o'clock meeting over an existing 4 o'clock appointment is a swap. The same meeting over a
#: nine-to-half-four working day is not: offering to delete somebody's whole day because they asked
#: for an hour in the middle of it would be the most destructive reading of a reasonable request.
SWAPPABLE = 2


def _already_there(session: Session, family_id: int, change: dict, begins, finishes):
    """The one thing in this slot that a new event would sensibly replace, or None.

    Only the same people's events count: Mom's work does not stand in the way of Dad booking four
    o'clock. A longer containing block is left alone and reported as a clash instead, so the answer
    becomes "that overlaps your work, put it in anyway?" rather than an offer to delete the day.
    """
    wanted = set(change["member_ids"])
    length = finishes - begins

    overlapping = session.scalars(
        sa.select(Event)
        .where(Event.family_id == family_id, Event.start < finishes, Event.end > begins)
        .order_by(Event.start, Event.id)
    ).all()

    for event in overlapping:
        if not wanted & set(event.member_ids or []):
            continue
        if (event.end - event.start) <= length * SWAPPABLE:
            return event
    return None


def _removal(event) -> dict:
    """The change that takes an event out. Paired with an add, it is a swap."""
    return {
        "kind": "remove",
        "event_id": event.id,
        "title": event.title,
        "when": say_span(event.start, event.end),
        "reason": "replaced by the new event",
    }


def _as_hypothetical(change: dict) -> dict:
    """The same event in the shape the what-if engine reads.

    The stored change uses `start_iso`, because that is what the approving side writes; the engine
    speaks of `start`. Translating here keeps one spelling in the database and one in the engine.
    """
    return {
        **change,
        "kind": "new_event",
        "start": change["start_iso"],
        "end": change["end_iso"],
    }


def _week_after(week, change: dict, taken):
    """The week as the whole proposal would leave it: what it replaces gone, the new event in.

    An in-memory copy, examined and thrown away. Nothing here opens a write.
    """
    if taken is not None:
        week = apply_hypothetical(week, {"kind": CANCELLED, "event_id": taken.id})
    return apply_hypothetical(week, _as_hypothetical(change))


def _moment(value: str) -> datetime:
    try:
        return datetime.fromisoformat(str(value))
    except ValueError as bad:
        raise CannotAdd(f"I did not understand {value!r} as a date and time") from bad


def _members(session: Session, family_id: int, names: list[str] | None, viewer) -> list[Member]:
    """Who the event is for. Nobody named means the parent who asked: "my 5 o'clock" is theirs."""
    if not names:
        return [session.get(Member, viewer.member_id)]

    wanted = {n.strip().lower() for n in names if n and n.strip()}
    found = [
        m
        for m in session.scalars(sa.select(Member).where(Member.family_id == family_id))
        if m.name.lower() in wanted
    ]
    if not found:
        raise CannotAdd(f"nobody in the family is called {say_list(sorted(wanted))}")
    return found


def _location(session: Session, family_id: int, name: str | None) -> Location | None:
    """An existing place, or none. Inventing locations would put a place in the travel-time table
    that no journey is known to or from, and reachability would silently treat it as next door."""
    if not name or not name.strip():
        return None
    wanted = name.strip().lower()
    for place in session.scalars(sa.select(Location).where(Location.family_id == family_id)):
        if place.name.lower() == wanted:
            return place
    return None


def _describe(change: dict, effect, begins: datetime, finishes: datetime, taken=None,
              losing: list[str] | None = None) -> str:
    whose = say_list(change["members"])
    where = f" at {change['location']}" if change.get("location") else ""
    opening = f"{change['title']} for {whose}, {say_span(begins, finishes)}{where}."

    # The slot is taken by something comparable: one of them, not both. A fixed commitment is still
    # offered -- the parent is the authority on their own diary -- but it is named as one, so nobody
    # agrees to dropping a performance review thinking it was an ordinary hour.
    if taken is not None:
        fixed = "" if taken.movable else ", which is a fixed commitment"
        others = f" It comes off {say_list(losing)}'s day too." if losing else ""
        return (
            f"You already have {taken.title}, {say_span(taken.start, taken.end)}{fixed}.{others} "
            f"Shall I replace it with {change['title']}?"
        )

    if not effect.breaks:
        return f"{opening} Nothing else breaks. Shall I put it in?"
    # Every one of them, not just the first. Announcing "it breaks 2 things" and then naming one
    # asks a parent to approve a problem they were never told about -- and the card beside this
    # sentence lists both, so the two answers disagreed. Surfaced once booking with somebody else
    # put them in the clash too, which is the first case here with more than one break.
    count = "one thing" if len(effect.breaks) == 1 else f"{len(effect.breaks)} things"
    details = ". ".join(c.detail for c in effect.breaks)
    return f"{opening} It breaks {count}: {details}. Shall I still put it in?"
