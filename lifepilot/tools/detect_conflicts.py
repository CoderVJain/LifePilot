"""Load a week out of the database and say what is broken about it.

This module is the only place the pure engine meets SQLAlchemy. Everything it hands to
`lifepilot.engine.conflicts` is plain values, which is what keeps the engine testable without a
database and the answers reproducible.
"""

from datetime import date, datetime, time

import sqlalchemy as sa
from sqlalchemy.orm import Session

from lifepilot.db.models import Assignment, Event, Location, Member, Rule, TravelTime
from lifepilot.engine.conflicts import Week, detect
from lifepilot.engine.reachability import Commitment, Person, TransportNeed
from lifepilot.tools.context import resolve_viewer


def load_week(session: Session, family_id: int, start: date, end: date) -> Week:
    """Everything the checks need, as plain values."""
    window_start = datetime.combine(start, time.min)
    window_end = datetime.combine(end, time.max)

    members = session.scalars(sa.select(Member).where(Member.family_id == family_id)).all()
    people = [
        Person(m.id, m.name, m.role, bool(m.can_drive), m.home_location_id) for m in members
    ]

    events = session.scalars(
        sa.select(Event)
        .where(Event.family_id == family_id, Event.start >= window_start, Event.start <= window_end)
        .order_by(Event.start, Event.id)
    ).all()
    commitments = [
        Commitment(
            e.id,
            e.title,
            e.start,
            e.end,
            e.location_id,
            tuple(e.member_ids or ()),
            e.category,
            bool(e.movable),
        )
        for e in events
    ]

    locations = {
        loc.id for loc in session.scalars(sa.select(Location).where(Location.family_id == family_id))
    }
    travel = {
        (row.from_location_id, row.to_location_id): row.minutes
        for row in session.scalars(sa.select(TravelTime))
        if row.from_location_id in locations
    }

    event_ids = {e.id for e in events}
    assignments = [
        a for a in session.scalars(sa.select(Assignment)) if a.event_id in event_ids
    ]
    assigned = {a.event_id: a.member_id for a in assignments}
    driven: dict[int, set[int]] = {}
    for a in assignments:
        driven.setdefault(a.member_id, set()).add(a.event_id)

    rules = [
        {"type": r.type, "params": r.params, "spoken_text": r.spoken_text}
        for r in session.scalars(
            sa.select(Rule).where(Rule.family_id == family_id, Rule.active.is_(True))
        )
    ]

    # An event needing transport creates one need: somebody must collect the child when it ends.
    needs = [
        TransportNeed(e.id, f"{e.title} pickup", (e.member_ids or [None])[0], e.end, e.location_id)
        for e in events
        if e.needs_transport and e.location_id is not None
    ]

    return Week(
        people=people,
        commitments=commitments,
        needs=needs,
        travel=travel,
        driven={k: frozenset(v) for k, v in driven.items()},
        assigned=assigned,
        rules=rules,
    )


def detect_conflicts(session: Session, speaker: str, start: date, end: date) -> dict:
    """Problems in the week, as this speaker is allowed to see them."""
    viewer = resolve_viewer(session, speaker)
    family_id = session.get(Member, viewer.member_id).family_id
    week = load_week(session, family_id, start, end)
    conflicts = detect(week)

    if viewer.role != "parent":
        conflicts = [c for c in conflicts if _concerns(c, viewer.member_id, week)]

    return {
        "speaker": {"name": viewer.name, "role": viewer.role},
        "from": start.isoformat(),
        "to": end.isoformat(),
        "conflicts": [c.as_dict() for c in conflicts],
        "checked": {
            "events": len(week.commitments),
            "lifts_needed": len(week.needs),
            "rules": len(week.rules),
        },
    }


def _concerns(conflict, member_id: int, week: Week) -> bool:
    """A child or caregiver only sees problems that involve them."""
    if conflict.event_id is None:
        return False
    event = next((c for c in week.commitments if c.id == conflict.event_id), None)
    if event is None:
        return False
    if member_id in event.member_ids:
        return True
    return conflict.event_id in week.driven.get(member_id, frozenset())
