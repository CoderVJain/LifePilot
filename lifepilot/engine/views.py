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
    driven_event_ids: set[int],
    location_names: dict[int, str],
    member_names: dict[int, str] | None = None,
) -> dict | None:
    """One event as this viewer may see it, or None when they may not see it at all."""
    attending = viewer.member_id in event.member_ids
    driving = event.id in driven_event_ids

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
        "member_ids": list(event.member_ids),
        # Whose event this is. Without it a caller cannot tell Mom's work from Dad's, and anything
        # summarising the week will attach every event to whoever asked.
        "members": [names[mid] for mid in event.member_ids if mid in names],
        "redacted": False,
    }


def task_view(task, viewer: Viewer) -> dict | None:
    """Tasks are private to their owner and to parents. Caregivers see none."""
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
