"""Role-aware redaction. Pure: rows in, plain dicts out, no DB and no model calls.

Privacy is enforced here and called by the tool layer, never asked of a prompt. A model that is never
given a child's view of an adult's calendar cannot leak it.

    parent     everything
    child      own events in full; everyone else's as "Busy", times only; own tasks only
    caregiver  only events they are assigned to drive; no tasks
"""

from dataclasses import dataclass
from datetime import datetime

BUSY = "Busy"


@dataclass(frozen=True)
class Viewer:
    """Who is asking. The simulator's speaker switcher decides this; the server enforces it."""

    member_id: int
    name: str
    role: str


def event_view(
    event,
    viewer: Viewer,
    driven_event_ids: set[int] | dict[int, str],
    location_names: dict[int, str],
    member_names: dict[int, str] | None = None,
    assigned_to: dict[int, str] | None = None,
) -> dict | None:
    """One event as this viewer may see it, or None when they may not see it at all.

    `driven_event_ids` may be a mapping of event id to "pickup" or "drop", in which case the view says
    which. The difference is the whole content of the sentence: a parent who is down for the football
    pickup is not at football for an hour, they are at the gate at five.
    """
    attending = viewer.member_id in event.member_ids
    driving = event.id in driven_event_ids
    lift = driven_event_ids.get(event.id) if isinstance(driven_event_ids, dict) else None

    if viewer.role == "caregiver" and not driving:
        return None

    full = viewer.role == "parent" or attending or driving
    if not full:
        # A child sees that the time is taken, not what it is taken by.
        return {
            "id": event.id,
            "title": BUSY,
            "start": _iso(event.start),
            "end": _iso(event.end),
            "redacted": True,
        }

    names = member_names or {}
    return {
        "id": event.id,
        "title": event.title,
        "category": event.category,
        "start": _iso(event.start),
        "end": _iso(event.end),
        "location": location_names.get(event.location_id),
        "needs_transport": event.needs_transport,
        "movable": event.movable,
        # True when this is in the viewer's day because they are driving, not attending. Saying
        # "school 8 AM to 3 PM" to the parent doing the pickup implies they are there all day.
        "driving": driving and not attending,
        "lift": lift if driving and not attending else None,
        # Who is down to drive, whoever is asking. "At what time do I collect Aarav" is answered by
        # naming the person and the hour; "someone has to collect them" answers neither half.
        "lift_by": (assigned_to or {}).get(event.id),
        "member_ids": list(event.member_ids),
        # Whose event this is. Without it a caller cannot tell Mom's work from Dad's, and anything
        # summarising the week will attach every event to whoever asked.
        "members": [names[mid] for mid in event.member_ids if mid in names],
        "redacted": False,
    }


def task_view(task, viewer: Viewer, names: dict[int, str] | None = None) -> dict | None:
    """Tasks are private to their owner and to parents. Caregivers see none.

    `owner` is the name, not just the id: a task is read aloud, and "Aarav needs a costume" needs a
    person rather than a foreign key. A task with no owner is the household's.
    """
    if viewer.role == "caregiver":
        return None
    if viewer.role == "child" and task.owner_id != viewer.member_id:
        return None
    return {
        "id": task.id,
        "title": task.title,
        "category": task.category,
        "due": _iso(task.due),
        "owner_id": task.owner_id,
        "owner": (names or {}).get(task.owner_id),
        "status": task.status,
        "source": task.source,
    }


def member_view(member, viewer: Viewer) -> dict:
    """Names, roles and who can drive are visible to everyone: coordination needs them."""
    return {
        "id": member.id,
        "name": member.name,
        "role": member.role,
        "can_drive": member.can_drive,
        "is_you": member.id == viewer.member_id,
    }


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="minutes")
