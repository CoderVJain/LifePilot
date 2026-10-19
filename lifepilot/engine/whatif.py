"""Try a change without making it.

"What if my four o'clock runs until half five?" and "can I say yes to a six o'clock on Friday?" are
the same question underneath: apply the change to a copy of the week, see what breaks, and put the
copy in the bin. Nothing here touches the database, which is what makes that guarantee cheap to keep
rather than something to remember.

Pure: a week and a hypothetical in, a different week out. The caller compares the two.
"""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from lifepilot.engine.conflicts import Conflict, Week
from lifepilot.engine.reachability import Commitment
from lifepilot_shared.speech import say_time

RUNS_LATE = "runs_late"
NEW_EVENT = "new_event"
CANCELLED = "cancelled"
KINDS = (RUNS_LATE, NEW_EVENT, CANCELLED)


class UnknownHypothetical(ValueError):
    """Not a question this can answer, and not one to guess at."""


@dataclass(frozen=True)
class Ripple:
    """What the change would do. `breaks` is the answer; the rest is the working."""

    breaks: tuple[Conflict, ...] = ()
    resolves: tuple[Conflict, ...] = ()
    unchanged: tuple[Conflict, ...] = ()
    worsens: tuple[Conflict, ...] = ()

    @property
    def is_safe(self) -> bool:
        """Nothing broke and nothing got worse.

        `worsens` belongs here because a standing problem the change deepens is not safety. Dad's
        football pickup was already unreachable at 17:25; letting his review run to 17:30 means he
        cannot go at all, and calling that "nothing new breaks" was the answer the browser run
        caught.
        """
        return not self.breaks and not self.worsens

    def as_dict(self) -> dict:
        return {
            "safe": self.is_safe,
            "breaks": [c.as_dict() for c in self.breaks],
            "resolves": [c.as_dict() for c in self.resolves],
            "unchanged": [c.as_dict() for c in self.unchanged],
            "worsens": [c.as_dict() for c in self.worsens],
        }


def apply_hypothetical(week: Week, change: dict) -> Week:
    """A copy of the week with the change made. The original is never touched."""
    kind = change.get("kind")
    if kind == RUNS_LATE:
        return _runs_late(week, change)
    if kind == NEW_EVENT:
        return _new_event(week, change)
    if kind == CANCELLED:
        return _cancelled(week, change)
    raise UnknownHypothetical(
        f"I cannot work out {kind!r}. I can try: something running late, something new being added, "
        "or something being cancelled."
    )


def ripple(before: list[Conflict], after: list[Conflict]) -> Ripple:
    """What changed between the two weeks, keyed on the problem rather than its wording.

    A problem present both times is split on its `detail`: that sentence is generated from the same
    data every time, so if it reads differently the change reached this problem even though its key
    did not move.
    """
    was = {_key(c): c for c in before}
    now = {_key(c): c for c in after}
    both = [(c, was[k]) for k, c in now.items() if k in was]
    return Ripple(
        breaks=tuple(c for k, c in now.items() if k not in was),
        resolves=tuple(c for k, c in was.items() if k not in now),
        unchanged=tuple(c for c, earlier in both if c.detail == earlier.detail),
        worsens=tuple(c for c, earlier in both if c.detail != earlier.detail),
    )


def _key(conflict: Conflict) -> tuple:
    return (conflict.kind, conflict.event_id, conflict.title)


# --------------------------------------------------------------------------- the changes


#: People round a time when they speak: a 15:45 review is "my four o'clock". Half an hour each way
#: covers that without reaching the next thing in an ordinary diary.
ROUNDING = timedelta(minutes=30)


def _starting_around(week: Week, moment: datetime, mine: set[int]) -> Commitment | None:
    """The asker's own commitment starting at or near `moment`, exact first, else the closest.

    Restricted to the asker on purpose. A bare time used to fall back to whoever else had something
    then, so "what if my four o'clock runs late" answered about a child's 16:00 project -- and
    reported that nothing broke, having quietly shortened it. A time with no title is a claim about
    one's own diary; naming an event is how you ask about somebody else's.

    An empty `mine` means the caller never said who is asking, so it cannot be claiming ownership.
    """
    ours = [c for c in week.commitments if mine & set(c.member_ids)] if mine else week.commitments
    exact = [c for c in ours if c.start == moment]
    if exact:
        return min(exact, key=lambda c: c.id)
    near = [c for c in ours if abs(c.start - moment) <= ROUNDING]
    if near:
        return min(near, key=lambda c: (abs(c.start - moment), c.id))
    return None


def _find(week: Week, change: dict) -> Commitment:
    event_id = change.get("event_id")
    if event_id is not None:
        found = next((c for c in week.commitments if c.id == event_id), None)
        if found is None:
            raise UnknownHypothetical(f"There is no event {event_id} that week.")
        return found

    # "my four o'clock" names a time, not a title, so a start time identifies an event too.
    mine = set(change.get("for_member") or ())
    at = change.get("at") or change.get("start")
    title = (change.get("title") or "").strip().lower()
    if at:
        moment = _moment(at, like=None)
        found = _starting_around(week, moment, mine)
        if found is not None:
            return found
        if not title:
            raise UnknownHypothetical(
                f"You have nothing starting around {say_time(moment)} that day."
            )

    if not title:
        raise UnknownHypothetical("I need to know which event you mean.")
    matches = [c for c in week.commitments if title in c.title.lower()]
    preferred = [c for c in matches if mine & set(c.member_ids)] or matches
    if not preferred:
        known = ", ".join(sorted({c.title for c in week.commitments}))
        raise UnknownHypothetical(f"I cannot find {change.get('title')!r}. That week has: {known}.")
    return min(preferred, key=lambda c: c.start)


def _runs_late(week: Week, change: dict) -> Week:
    """Something overruns. Its end moves; everything else stays where it is."""
    event = _find(week, change)
    until = _moment(change.get("until"), like=event.end)
    if until <= event.start:
        raise UnknownHypothetical("That would end before it starts.")

    commitments = [replace(c, end=until) if c.id == event.id else c for c in week.commitments]
    # A lift from this event moves with it: if football overruns, the collection is later too.
    needs = [
        replace(n, moment=until) if n.event_id == event.id else n for n in week.needs
    ]
    return replace(week, commitments=commitments, needs=needs)


# Nobody says "a six o'clock meeting, finishing at seven". An hour is the ordinary assumption, and
# refusing the question over it would be pedantry.
DEFAULT_LENGTH = timedelta(hours=1)


def _new_event(week: Week, change: dict) -> Week:
    """Something new is offered. Can it be said yes to?"""
    start = _moment(change.get("start"), like=None)
    end = _moment(change.get("end"), like=start) if change.get("end") else start + DEFAULT_LENGTH
    if end == start:
        # "A meeting at five" arrives as the same moment twice. That is a one-hour meeting, not a
        # contradiction, and refusing it answered a reasonable question with a riddle.
        end = start + DEFAULT_LENGTH
    if end < start:
        raise UnknownHypothetical("That would end before it starts.")

    who = change.get("member_ids") or ()
    new_id = max((c.id for c in week.commitments), default=0) + 1000
    added = Commitment(
        id=new_id,
        title=change.get("title") or "new commitment",
        start=start,
        end=end,
        location_id=change.get("location_id"),
        member_ids=tuple(who),
        category=change.get("category", "other"),
        movable=False,
    )
    return replace(week, commitments=[*week.commitments, added])


def _cancelled(week: Week, change: dict) -> Week:
    """Something falls through. It and any lift for it disappear."""
    event = _find(week, change)
    return replace(
        week,
        commitments=[c for c in week.commitments if c.id != event.id],
        needs=[n for n in week.needs if n.event_id != event.id],
        assigned={k: v for k, v in week.assigned.items() if k != event.id},
        driven={
            person: frozenset(e for e in events if e != event.id)
            for person, events in week.driven.items()
        },
    )


def _moment(value, like: datetime | None) -> datetime:
    """A full timestamp, or a bare time of day taken to mean the same day as `like`."""
    if isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    if not text:
        raise UnknownHypothetical("I need to know what time.")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass
    if like is not None and ":" in text:
        try:
            hour, minute = (int(part) for part in text.split(":", 1))
            return like.replace(hour=hour, minute=minute)
        except ValueError:
            pass
    raise UnknownHypothetical(f"{value!r} is not a time I can read.")
