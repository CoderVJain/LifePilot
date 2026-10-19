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


def _tasks_shown(tasks, viewer: Viewer, names: dict[int, str], wanted: str) -> list[dict]:
    """The tasks this viewer may see, narrowed by name if one was asked for.

    Narrowing by title used to apply to events alone, so "when is the fancy dress competition" could
    not find a task however plainly it was named. As with events, it happens after the visibility
    rules, never instead of them.
    """
    shown = [view for view in (task_view(t, viewer, names) for t in tasks) if view is not None]
    if wanted:
        shown = [view for view in shown if wanted in view["title"].lower()]
    return shown


def _resolve_subject(session: Session, family_id: int, about: str) -> Member | None:
    """Whose day is being asked about. "me" and "my" mean whoever is speaking."""
    wanted = about.strip().lower()
    for member in session.scalars(sa.select(Member).where(Member.family_id == family_id)):
        if member.name.lower() == wanted:
            return member
    return None


def _resolve_moment(at: str | None, day: date) -> datetime | None:
    """A full timestamp, or a bare time of day taken to mean the day being asked about."""
    text = (at or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass
    try:
        hour, _, minute = text.partition(":")
        return datetime.combine(day, time(int(hour), int(minute or 0)))
    except ValueError:
        return None


def _at_that_time(views: list[dict], moment: datetime) -> dict:
    """What is running at that moment, and what starts or finishes on it.

    An event that ends exactly then does not make the time busy, but saying so matters: "football
    finishes at five" is why somebody is not free at five even though nothing overlaps it.
    """
    running, starting, finishing = [], [], []
    for view in views:
        begins = datetime.fromisoformat(view["start"])
        ends = datetime.fromisoformat(view["end"]) if view.get("end") else begins
        if begins < moment < ends:
            running.append(view)
        elif begins == moment:
            starting.append(view)
        elif ends == moment:
            finishing.append(view)

    return {
        "free": not running and not starting,
        "running": running,
        "starting": starting,
        "finishing": finishing,
    }


def get_schedule(
    session: Session,
    speaker: str,
    start: date,
    end: date,
    about: str | None = None,
    at: str | None = None,
    title: str | None = None,
) -> dict:
    """Events and tasks between two dates, inclusive, as this speaker may see them.

    `about` narrows the answer to one person's day. "What is my schedule" and "what is Aarav's
    school timing" are both questions about somebody in particular, and answering either with the
    whole household buries what was asked. Driving someone counts as that driver's day: it is their
    afternoon.

    `at` narrows it to one moment. "Do I have anything at five" is a question about five o'clock,
    and answering it with the whole day leaves the asker to do the work themselves. What is running
    then is reported separately from what merely starts or finishes then, because "football finishes
    at five" is the difference between free and not.

    `title` narrows it to one named thing. "What is the piano class timing and day" is a question
    about the piano class; without this it fell through to reciting the whole week, and the answer a
    tester wanted was in there somewhere behind nineteen other events.

    Narrowing happens after the visibility rules, never instead of them: a child asking about a
    parent still sees "Busy", not the meeting.
    """
    viewer = resolve_viewer(session, speaker)
    family_id = _family_id(session, viewer)
    window_start = datetime.combine(start, time.min)
    window_end = datetime.combine(end, time.max)

    location_names = {
        loc.id: loc.name
        for loc in session.scalars(sa.select(Location).where(Location.family_id == family_id))
    }
    member_names = {
        m.id: m.name
        for m in session.scalars(sa.select(Member).where(Member.family_id == family_id))
    }
    # Event id to "pickup" or "drop", not just the ids: which one it is decides the sentence. A
    # parent down for the football pickup is at the gate at five, not at football for an hour.
    driven = {
        event_id: kind
        for event_id, kind in session.execute(
            sa.select(Assignment.event_id, Assignment.kind).where(
                Assignment.member_id == viewer.member_id
            )
        )
    }

    # Who is down to drive each event, whoever is asking. Coordination information: a parent asking
    # when they collect Aarav needs the name as much as the hour.
    assigned_to = {
        event_id: member_names[member_id]
        for event_id, member_id in session.execute(
            sa.select(Assignment.event_id, Assignment.member_id)
        )
        if member_id in member_names
    }

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

    subject = _resolve_subject(session, family_id, about) if about else None
    if subject is not None:
        theirs = set(
            session.scalars(sa.select(Assignment.event_id).where(Assignment.member_id == subject.id))
        )
        events = [e for e in events if subject.id in (e.member_ids or []) or e.id in theirs]
        # An unowned task is the household's, so it survives narrowing to a parent. Dropping it
        # meant a task extracted from a school email -- which often names no child we recognise --
        # existed in the database and appeared in nobody's answer.
        tasks = [
            t
            for t in tasks
            if t.owner_id == subject.id or (t.owner_id is None and subject.role == "parent")
        ]

    moment = _resolve_moment(at, start)
    shown = [
        view
        for view in (
            event_view(e, viewer, driven, location_names, member_names, assigned_to) for e in events
        )
        if view is not None
    ]

    # After the visibility rules, so narrowing can never widen what somebody may see. A redacted
    # event reads as "Busy", and matching on that would leak which meeting it was.
    wanted = (title or "").strip().lower()
    if wanted:
        shown = [v for v in shown if not v.get("redacted") and wanted in v["title"].lower()]

    return {
        "speaker": {"name": viewer.name, "role": viewer.role},
        "from": start.isoformat(),
        "to": end.isoformat(),
        "about": subject.name if subject is not None else None,
        "title": title if wanted else None,
        "at": moment.isoformat(timespec="minutes") if moment else None,
        "at_that_time": _at_that_time(shown, moment) if moment else None,
        "events": shown,
        "tasks": _tasks_shown(tasks, viewer, member_names, wanted),
    }
