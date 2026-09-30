"""The two context tools: get_family and get_schedule. Both role-aware from the first line."""

from datetime import date, datetime, time

import sqlalchemy as sa
from sqlalchemy.orm import Session

from lifepilot.db.models import Assignment, Event, Location, Member, Task
from lifepilot.engine.views import Viewer, event_view, member_view, task_view


class UnknownSpeaker(ValueError):
    """The speaker is not a member of any family."""


def resolve_viewer(session: Session, speaker: str) -> Viewer:
    """Turn a spoken name into a Viewer. The role comes from the database, never from the caller."""
    member = session.scalars(sa.select(Member).where(Member.name == speaker)).first()
    if member is None:
        raise UnknownSpeaker(f"no family member named {speaker!r}")
    return Viewer(member_id=member.id, name=member.name, role=member.role)


def _family_id(session: Session, viewer: Viewer) -> int:
    return session.get(Member, viewer.member_id).family_id


def get_family(session: Session, speaker: str) -> dict:
    """Who is in the family, what roles they hold, who can drive, and the places they go."""
    viewer = resolve_viewer(session, speaker)
    family_id = _family_id(session, viewer)
    members = session.scalars(
        sa.select(Member).where(Member.family_id == family_id).order_by(Member.id)
    ).all()
    locations = session.scalars(
        sa.select(Location).where(Location.family_id == family_id).order_by(Location.id)
    ).all()
    return {
        "speaker": {"name": viewer.name, "role": viewer.role},
        "members": [member_view(m, viewer) for m in members],
        "locations": [loc.name for loc in locations],
    }


def get_schedule(session: Session, speaker: str, start: date, end: date) -> dict:
    """Events and tasks between two dates, inclusive, as this speaker may see them."""
    viewer = resolve_viewer(session, speaker)
    family_id = _family_id(session, viewer)
    window_start = datetime.combine(start, time.min)
    window_end = datetime.combine(end, time.max)

    location_names = {
        loc.id: loc.name
        for loc in session.scalars(sa.select(Location).where(Location.family_id == family_id))
    }
    driven = set(
        session.scalars(sa.select(Assignment.event_id).where(Assignment.member_id == viewer.member_id))
    )

    events = session.scalars(
        sa.select(Event)
        .where(Event.family_id == family_id, Event.start >= window_start, Event.start <= window_end)
        .order_by(Event.start, Event.id)
    ).all()
    tasks = session.scalars(
        sa.select(Task)
        .where(Task.family_id == family_id, Task.due >= window_start, Task.due <= window_end)
        .order_by(Task.due, Task.id)
    ).all()

    return {
        "speaker": {"name": viewer.name, "role": viewer.role},
        "from": start.isoformat(),
        "to": end.isoformat(),
        "events": [
            view
            for view in (event_view(e, viewer, driven, location_names) for e in events)
            if view is not None
        ],
        "tasks": [view for view in (task_view(t, viewer) for t in tasks) if view is not None],
    }
