"""cancel_event: take something out of the week, once a parent has said yes.

The mirror of `add_event`, and the half the write path was missing. Nothing is written here: the
cancellation becomes a pending proposal carrying `remove` changes, and `approve_proposal` is still
the only thing that writes. `_apply_remove` already takes the lift assignments with it.

A cancellation cannot create a clash -- it frees time -- so the check is not `add_event`'s run
backwards. It is the opposite question: what did this event unblock, and who still needs covering.
That is `what_if(kind="cancelled")`, which already computes exactly this ripple and changes nothing.
"""

from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session

from lifepilot.db.models import Event, Member, Proposal
from lifepilot.engine.conflicts import detect
from lifepilot.engine.whatif import CANCELLED, apply_hypothetical, ripple
from lifepilot.tools.context import resolve_viewer
from lifepilot.tools.detect_conflicts import load_week
from lifepilot.tools.fix_week import NotAllowed
from lifepilot_shared.clock import today
from lifepilot_shared.speech import plural, say_list, say_span
from lifepilot_shared.week import demo_week


class Ambiguous(Exception):
    """More than one event answers to that, so which one was meant is a real question.

    The same rule `request_swap` follows for a day holding two lifts: a day holding two of Mom's
    meetings is a question, not a guess. Guessing here deletes the wrong thing.
    """

    def __init__(self, said: str, events: list[Event]):
        self.said, self.events = said, events
        super().__init__(f"{len(events)} events answer to {said!r}")


def cancel_event(
    session: Session,
    speaker: str,
    title: str | None = None,
    at: str | None = None,
    event_id: int | None = None,
    day: date | None = None,
    override: bool = False,
    replace_with: str | None = None,
    replace_members: list[str] | None = None,
) -> dict:
    """Propose taking an event out. Returns what it frees, what it strands, and who loses it.

    `replace_with` puts something in its place: one proposal carrying the removal and the addition,
    applied together or not at all. The replacement takes the cancelled event's slot, because
    "instead" means the same slot -- a different time is a separate booking.
    """
    viewer = resolve_viewer(session, speaker)
    if viewer.role != "parent":
        raise NotAllowed(f"{viewer.name} is a {viewer.role}; only a parent can change the plan.")

    family_id = session.get(Member, viewer.member_id).family_id

    # The event is found first, then the week is loaded around it. Searching inside a fixed window
    # would refuse to cancel Sunday's lunch at Grandpa's, which is in the diary and not in the week.
    try:
        event = _which_event(session, family_id, viewer.member_id, title, at, event_id, day)
    except Ambiguous as question:
        return {
            "cancelled": False,
            "options": [_option(e) for e in question.events],
            "say": _which_one(question),
        }
    if event is None:
        return {"cancelled": False, "say": _nothing_like_that(session, family_id, title, at)}

    week = load_week(session, family_id, *_window_for(event))

    pinned = _pinned_by_a_rule(week, event)
    if pinned and not override:
        return {
            "cancelled": False,
            "blocked_by_rule": pinned,
            "say": (
                f"Your rule says {pinned} cannot move, and cancelling it outright is a bigger step "
                f"than moving it. Say cancel it anyway if you mean it."
            ),
        }

    instead = _replacement(session, family_id, viewer, event, replace_with, replace_members)
    effect = _effect_of(week, event, instead)
    losing = who_else_loses_it(session, family_id, event, viewer.member_id)
    freed_lifts = [need.title for need in week.needs if need.event_id == event.id]
    frees = _really_freed(effect, event, freed_lifts)

    changes = [_removal(event, speaker)]
    if instead is not None:
        changes.append(instead)

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

    return {
        "proposal_id": proposal.id,
        "cancelled": False,
        "status": "pending",
        "title": event.title,
        "when": say_span(event.start, event.end),
        "also_loses_it": losing,
        "frees": frees,
        "strands": [c.as_dict() for c in effect.breaks],
        "lifts_no_longer_needed": freed_lifts,
        "replaced_by": instead["title"] if instead else None,
        "say": _describe(event, effect, frees, losing, freed_lifts, pinned, instead),
    }


# --------------------------------------------------------------------------- which event


def _which_event(session, family_id, member_id, title, at, event_id, day) -> Event | None:
    """The one event meant, or None, or a question.

    An id settles it. Otherwise the words narrow the week, and the speaker's own events win: "my
    meeting" is a claim about their own diary, which is the rule `what_if` already follows.
    """
    if event_id is not None:
        found = session.get(Event, event_id)
        return found if found is not None and found.family_id == family_id else None

    matches = _matching(session, family_id, title, at, day)
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]

    mine = [e for e in matches if member_id in (e.member_ids or ())]
    if len(mine) == 1:
        return mine[0]
    raise Ambiguous(title or str(at), mine or matches)


def _matching(session, family_id, title, at, day) -> list[Event]:
    """Every event in the window the words could mean."""
    query = sa.select(Event).where(Event.family_id == family_id).order_by(Event.start, Event.id)
    events = list(session.scalars(query))

    if at:
        moment = datetime.fromisoformat(at)
        events = [e for e in events if e.start == moment]
    elif day:
        events = [e for e in events if e.start.date() == day]

    wanted = (title or "").strip().lower()
    if wanted:
        events = [e for e in events if wanted in e.title.lower()]
    return events


def _window_for(event: Event) -> tuple[date, date]:
    """The span the ripple is measured over: the demo week when the event is in it, otherwise the
    event's own day. What a cancellation frees is only readable where the rest of the week is."""
    start, end = demo_week()
    day = event.start.date()
    return (start, end) if start <= day <= end else (day, day)


def _option(event: Event) -> dict:
    return {
        "event_id": event.id,
        "title": event.title,
        "when": say_span(event.start, event.end),
    }


# --------------------------------------------------------------------------- what it does


def _effect_of(week, event: Event, instead: dict | None = None):
    """What the whole proposal would do. The copy is examined and thrown away.

    Both legs are judged together because both are approved together, and the replacement is judged
    against the week with the old event already gone -- the principle `request_swap` learned, and
    the one `add_event` had to be corrected for.
    """
    planned = apply_hypothetical(week, {"kind": CANCELLED, "event_id": event.id})
    if instead is not None:
        planned = apply_hypothetical(planned, {**instead, "kind": "new_event",
                                               "start": instead["start_iso"],
                                               "end": instead["end_iso"]})
    return ripple(detect(week), detect(planned))


def _replacement(session, family_id, viewer, event: Event, title: str | None,
                 members: list[str] | None) -> dict | None:
    """What goes in the cancelled event's place, in the shape `_apply_add` reads.

    Whoever is named plus the parent asking: "book lunch with Mom instead" is the two of them, not
    the five people who were at Grandpa's. Taking the old event's people would quietly re-book the
    children and Grandpa into something nobody mentioned.
    """
    wanted = (title or "").strip()
    if not wanted:
        return None

    whose = {viewer.member_id}
    named = {n.strip().lower() for n in (members or []) if n and n.strip()}
    if named:
        whose |= {
            m.id
            for m in session.scalars(sa.select(Member).where(Member.family_id == family_id))
            if m.name.lower() in named
        }
    people = session.scalars(
        sa.select(Member).where(Member.family_id == family_id, Member.id.in_(whose))
    ).all()

    return {
        "kind": "add",
        "title": wanted,
        "category": event.category,
        "start_iso": event.start.isoformat(),
        "end_iso": event.end.isoformat(),
        "location_id": None,
        "member_ids": [m.id for m in people],
        "members": [m.name for m in people],
        "needs_transport": False,
        "when": say_span(event.start, event.end),
        "was": "nothing",
        "now": say_span(event.start, event.end),
        "reason": f"replaces {event.title}",
    }


def _pinned_by_a_rule(week, event: Event) -> str | None:
    """The title an `immovable_event` rule names, when it names this event.

    `movable = False` in the data is **not** this: that is a property of the event, and a parent is
    the authority on their own diary. A family rule is something the family said, so cancelling what
    it pins needs them to say it again.
    """
    for rule in week.rules:
        if rule["type"] != "immovable_event":
            continue
        named = rule["params"].get("title", "").lower()
        if named and named in event.title.lower():
            return rule["params"]["title"]
    return None


def who_else_loses_it(session, family_id, event: Event, asker_id: int) -> list[str]:
    """Everyone else the event comes out of the diary of.

    A cancellation that silently empties three other people's afternoons is the failure mode here,
    so they are named before the yes, not after it.
    """
    others = [m for m in (event.member_ids or ()) if m != asker_id]
    if not others:
        return []
    people = session.scalars(
        sa.select(Member).where(Member.family_id == family_id, Member.id.in_(others))
    ).all()
    return [m.name for m in people]


def _removal(event: Event, speaker: str) -> dict:
    """The change that takes the event out, in the shape `_apply_remove` and the card both read."""
    return {
        "kind": "remove",
        "event_id": event.id,
        "title": event.title,
        "when": say_span(event.start, event.end),
        "was": say_span(event.start, event.end),
        "now": "cancelled",
        "reason": f"{speaker} asked to cancel it",
    }


# --------------------------------------------------------------------------- wording


def _really_freed(effect, event: Event, freed_lifts: list[str]) -> list[str]:
    """Problems the cancellation solves, minus the ones it merely deletes.

    Cancelling football practice makes the football pickup go away, but it did not *fix* it -- there
    is nothing left to drive to. The same goes for the event itself: "cancelling the science project
    block also fixes the science project block" is not two pieces of good news, it is one deletion
    described twice. What is left is the real claim -- cancelling Dad's review makes Thursday's
    football pickup reachable.
    """
    gone = {title.lower() for title in [*freed_lifts, event.title]}
    return [c.title for c in effect.resolves if c.title.lower() not in gone]


def _already_happened(event: Event) -> bool:
    """Over and done with. Day granularity, because `clock.today()` is all there is to be sure of."""
    return event.end.date() < today()


def _describe(event, effect, frees: list[str], losing: list[str], freed_lifts: list[str],
              pinned: str | None, instead: dict | None = None) -> str:
    opening = f"Cancelling {event.title}, {say_span(event.start, event.end)}."
    if instead is not None:
        opening = (
            f"Cancelling {event.title}, {say_span(event.start, event.end)}, and putting "
            f"{instead['title']} in its place for {say_list(instead['members'])}."
        )
    if pinned:
        opening = f"{opening} Your rule pins it, and you said to anyway."

    # Offering to cancel something that is over reads as not knowing what day it is. It is still
    # offered -- a parent may be tidying up -- and it is said as one more clause rather than an
    # early exit, because who else loses it and what it strands are still the answer.
    past = _already_happened(event)
    if past:
        opening = f"{opening} That one has already happened."

    parts = [opening]
    if losing:
        parts.append(f"It also clears the day for {say_list(losing)}.")
    if freed_lifts:
        parts.append(f"Nobody needs to drive {say_list(freed_lifts)} any more.")

    # The differentiator: a cancellation can *repair* the week, and saying so is the whole point of
    # checking rather than just deleting.
    if frees:
        parts.append(f"It also fixes {say_list(frees)}.")

    if effect.breaks:
        first = effect.breaks[0]
        count = plural(len(effect.breaks), "one thing", f"{len(effect.breaks)} things")
        parts.append(f"But it strands {count}: {first.detail}.")

    asking = "Shall I still take it out?" if past or effect.breaks else "Shall I cancel it?"
    parts.append(asking)
    return " ".join(parts)


def _which_one(question: Ambiguous) -> str:
    options = say_list([f"{e.title} {say_span(e.start, e.end)}" for e in question.events], "or")
    return f"Which one: {options}?"


def _nothing_like_that(session, family_id: int, title: str | None, at: str | None) -> str:
    titles = sorted(
        {t for (t,) in session.execute(
            sa.select(Event.title).where(Event.family_id == family_id).distinct()
        )}
    )
    if not titles:
        return "There is nothing in the diary to cancel."
    known = say_list(titles)
    said = title or at or "that"
    return f"I cannot find {said} in the diary. There is: {known}."
