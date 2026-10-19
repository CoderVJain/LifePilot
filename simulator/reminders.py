"""What LifePilot should say when nobody has asked it anything.

Two kinds, and the difference matters. A **nudge** says something is about to start, which is what a
reminder app does. A **warning** says a lift is about to become impossible and names who could go
instead, which is what a planner does. CLAUDE.md says reminders are supporting cast and never the
headline, so the warning is the one worth showing.

Every sentence here is built from templates. Nothing in this module calls a model: the cost rules
forbid pointing a scheduled job at Bedrock, and a timer that phrased its output through Nova would
spend money on every tick for the rest of the demo.

Pure functions over plain data, so the whole thing is testable offline with no clock and no socket.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from lifepilot_shared.speech import say_lift, say_list, say_time

#: How long before something starts to mention it.
SOON = timedelta(minutes=15)

#: How long before an unmakeable lift to raise it. Longer, because the point is to leave time to fix
#: it: a warning that arrives as the pickup starts is just bad news.
IN_TIME = timedelta(minutes=45)


@dataclass(frozen=True)
class Spoken:
    """Something to say, and a key so it is only ever said once."""

    key: str
    kind: str
    speak: str


def due_now(schedule: dict, conflicts: dict, now: datetime, already_said: set[str]) -> list[Spoken]:
    """Everything worth saying at this moment, warnings first, nothing repeated."""
    found = [
        *_warnings(conflicts, now),
        *_nudges(schedule, now),
    ]
    return [item for item in found if item.key not in already_said]


def _warnings(conflicts: dict, now: datetime) -> list[Spoken]:
    """A lift nobody can make, raised while there is still time to do something about it."""
    said = []
    for conflict in (conflicts or {}).get("conflicts", []):
        if conflict.get("kind") != "unreachable":
            continue
        when = _moment(conflict.get("when"))
        if when is None or not (now <= when <= now + IN_TIME):
            continue

        detail = conflict.get("detail") or conflict.get("title") or "a pickup cannot be made"
        cover = conflict.get("could_cover") or []
        suggestion = f" {say_list(cover)} could go instead." if cover else ""
        said.append(
            Spoken(
                key=f"unreachable:{conflict.get('title')}:{conflict.get('when')}",
                kind="warning",
                speak=f"Before this gets away from us: {detail}.{suggestion}",
            )
        )
    return said


def _nudges(schedule: dict, now: datetime) -> list[Spoken]:
    """Something starting shortly. Deliberately plain: it is the least interesting thing here."""
    said = []
    for event in (schedule or {}).get("events", []):
        if event.get("redacted"):
            continue
        start = _moment(event.get("start"))
        if start is None or not (now < start <= now + SOON):
            continue

        minutes = max(1, round((start - now).total_seconds() / 60))
        whose = say_list(event.get("members") or [])
        owner = f"{whose}'s " if whose else ""
        lift = f" {say_lift(event.get('members') or [])}." if event.get("needs_transport") else ""
        said.append(
            Spoken(
                key=f"soon:{event.get('title')}:{event.get('start')}",
                kind="nudge",
                speak=(
                    f"{owner}{event.get('title')} starts in {minutes} "
                    f"{'minute' if minutes == 1 else 'minutes'}, at {say_time(start)}.{lift}"
                ),
            )
        )
    return said


def _moment(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None
