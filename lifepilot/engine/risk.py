"""Which tasks are going to be missed, and the slot that would save each one.

A reminder app warns you when a task is due. That is too late: on Thursday night "the project is due
tomorrow" is not help, it is an accusation. This asks the useful question instead -- **is there still
enough free time to get it done?** -- and warns the day the answer becomes no, while there is still
something a parent can do about it.

Pure, like reachability: values in, values out, no database and no model calls. The family's rules
narrow the usable hours, so a "no homework after 9 PM" rule shrinks every evening and brings the
warning forward. That is the point of storing rules at all.

Three warnings, in order of severity, and only ever one per task:

    not_enough_time   the free hours left before it is due are less than the task needs
    needs_splitting   enough free time in total, but no single stretch long enough
    unbooked          there is a slot, the prep window has opened, and nothing is set aside

`unbooked` is the common and most useful one, and it is why the slot matters. A first pass defined
risk as "cannot be done", which made the repair unreachable: any task with a big enough gap was by
definition not at risk, so a warning could never carry a slot. The real risk is that nothing is
booked and the window is closing -- so the scan reports the task, names the gap, and a parent says
yes. A task that already has time set aside is not at risk at all, whatever the calendar looks like.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from lifepilot.engine.reachability import Commitment

#: When a person is realistically available. Narrowed per task by any `latest_end` rule that
#: applies to its category, so the family's own rules decide how much of the evening counts.
DAY_OPENS = time(7, 0)
DAY_CLOSES = time(21, 30)

#: A gap shorter than this is not usable time, it is the walk between two things.
USABLE_GAP_MINUTES = 15



@dataclass(frozen=True)
class Task:
    """A task as the risk scan needs it. Plain values, so this module never touches the ORM."""

    id: int
    title: str
    due: datetime
    est_minutes: int
    owner_id: int | None = None
    prep_days: int = 0
    category: str = "other"
    status: str = "open"
    source: str = "voice"

    @property
    def start_by(self) -> date:
        """The day work has to have begun, which is what `prep_days` actually means."""
        return (self.due - timedelta(days=self.prep_days)).date()


@dataclass(frozen=True)
class Slot:
    start: datetime
    end: datetime

    @property
    def minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


@dataclass(frozen=True)
class Risk:
    """One task that is not going to happen by itself, and what to do about it."""

    task_id: int
    title: str
    due: datetime
    kinds: tuple[str, ...]
    minutes_needed: int
    minutes_free: int
    slot: Slot | None
    detail: str

    @property
    def at_risk(self) -> bool:
        return bool(self.kinds)

    @property
    def days_left(self) -> int:
        return 0


def scan(
    tasks: Sequence[Task],
    commitments: Sequence[Commitment],
    today: date,
    rules: Sequence[Mapping] = (),
    booked: Sequence[int] = (),
) -> list[Risk]:
    """Every open task that is at risk, soonest due first.

    `booked` is the ids of tasks that already have time set aside for them. Working that out needs
    the database, so the tool layer does it and this module stays pure.
    """
    already = set(booked)
    found = [
        risk
        for task in tasks
        if task.status == "open" and task.due.date() >= today and task.id not in already
        for risk in [_assess(task, commitments, today, rules)]
        if risk.at_risk
    ]
    return sorted(found, key=lambda risk: (risk.due, risk.title))


def _assess(
    task: Task, commitments: Sequence[Commitment], today: date, rules: Sequence[Mapping]
) -> Risk:
    """One task's verdict. At most one kind, most serious first: they are not cumulative."""
    closes = _day_closes(task, rules)
    gaps = free_gaps(task.owner_id, commitments, today, task.due.date(), closes)
    minutes_free = sum(gap.minutes for gap in gaps)
    slot = next((gap for gap in gaps if gap.minutes >= task.est_minutes), None)

    kinds = []
    if minutes_free < task.est_minutes:
        kinds.append("not_enough_time")
    elif slot is None:
        kinds.append("needs_splitting")
    elif today >= task.start_by:
        # There is room and nothing is in it. Before the prep window opens there is nothing to
        # warn about yet, which is what keeps this from nagging about every task every day.
        #
        # Tried and reverted: also requiring the free time to be scarce, so a task with ten times
        # the hours it needs stayed quiet. It silenced the case that matters most -- "the costume
        # is needed tomorrow and nothing is set aside" -- because a single free evening is plenty
        # of hours for ninety minutes of work. Proximity is already carried by `prep_days`, and an
        # unbooked task near its deadline is worth saying out loud whatever the calendar looks
        # like. The real fault was experiment 5's ground truth, which counted that as a false
        # alarm; a task nobody has set aside time for is not "fine".
        kinds.append("unbooked")

    return Risk(
        task_id=task.id,
        title=task.title,
        due=task.due,
        kinds=tuple(kinds),
        minutes_needed=task.est_minutes,
        minutes_free=minutes_free,
        slot=slot,
        detail=_detail(task, kinds, minutes_free, slot, today),
    )


def _day_closes(task: Task, rules: Sequence[Mapping]) -> time:
    """When the day stops counting for this task, per any rule about its category.

    "No homework after 9 PM" is a rule about study, so it shortens the evenings available to a study
    task and leaves everything else alone. The rule is why the warning comes earlier.
    """
    closes = DAY_CLOSES
    for rule in rules:
        if rule.get("type") != "latest_end":
            continue
        params = rule.get("params") or {}
        category = params.get("category")
        if category and category != task.category:
            continue
        limit = _clock(str(params.get("latest_end", "")))
        if limit is not None and limit < closes:
            closes = limit
    return closes


def free_gaps(
    owner_id: int | None,
    commitments: Sequence[Commitment],
    first_day: date,
    due_day: date,
    closes: time = DAY_CLOSES,
) -> list[Slot]:
    """Usable gaps in this person's days, from `first_day` up to the day before `due_day`.

    The due day itself is excluded on purpose: something due at 8 AM on Friday cannot be done on
    Friday evening, and counting that day was the difference between a warning and a false comfort.
    """
    gaps = []
    day = first_day
    while day < due_day:
        gaps.extend(_gaps_in_day(owner_id, commitments, day, closes))
        day += timedelta(days=1)
    return gaps


def _gaps_in_day(
    owner_id: int | None, commitments: Sequence[Commitment], day: date, closes: time
) -> list[Slot]:
    opens_at = datetime.combine(day, DAY_OPENS)
    closes_at = datetime.combine(day, closes)
    if closes_at <= opens_at:
        return []

    busy = sorted(
        (c for c in _theirs(owner_id, commitments) if c.start.date() == day or c.end.date() == day),
        key=lambda c: c.start,
    )

    gaps = []
    cursor = opens_at
    for commitment in busy:
        start = max(commitment.start, opens_at)
        end = min(commitment.end, closes_at)
        if end <= cursor:
            continue
        if start > cursor:
            gaps.append(Slot(cursor, min(start, closes_at)))
        cursor = max(cursor, end)
        if cursor >= closes_at:
            break
    if cursor < closes_at:
        gaps.append(Slot(cursor, closes_at))

    return [gap for gap in gaps if gap.minutes >= USABLE_GAP_MINUTES]


def _theirs(owner_id: int | None, commitments: Sequence[Commitment]) -> list[Commitment]:
    """A task with no owner is the household's, so everything in the calendar blocks it."""
    if owner_id is None:
        return list(commitments)
    return [c for c in commitments if owner_id in c.member_ids]


def _detail(task: Task, kinds: Sequence[str], minutes_free: int, slot: Slot | None, today: date):
    """One sentence a parent can act on, naming the numbers rather than the verdict."""
    needed = _hours(task.est_minutes)
    if "not_enough_time" in kinds:
        return (
            f"{task.title} needs {needed} and there is only {_hours(minutes_free)} free "
            f"before it is due"
        )
    if "needs_splitting" in kinds:
        return (
            f"{task.title} needs {needed} in one go and the longest free stretch left is shorter, "
            f"so it has to be split"
        )
    if "unbooked" in kinds and slot is not None:
        late = (today - task.start_by).days
        due_in = (task.due.date() - today).days
        when = f"{slot.start:%A}" if slot.start.date() != today else "today"
        overdue = " and should have started already" if late > 0 else ""
        return (
            f"{task.title} needs {needed} before it is due in {due_in} "
            f"day{'s' if due_in != 1 else ''}, nothing is set aside for it{overdue}. "
            f"{when.capitalize()} is the first free stretch long enough"
        )
    return f"{task.title} is on track"


def _hours(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} minutes"
    hours, rest = divmod(minutes, 60)
    if not rest:
        return f"{hours} hour{'s' if hours > 1 else ''}"
    return f"{hours}h{rest:02d}"


def _clock(value: str) -> time | None:
    hour, _, minute = value.partition(":")
    try:
        return time(int(hour), int(minute or 0))
    except ValueError:
        return None


def first_warning_day(
    task: Task,
    commitments: Sequence[Commitment],
    rules: Sequence[Mapping] = (),
    horizon_days: int = 21,
    booked: Sequence[int] = (),
) -> date | None:
    """The earliest day this task would have been flagged, counting forward from the horizon.

    This is how experiment 5 measures days of warning. It replays the scan as of each day rather
    than reasoning about when the warning "should" appear, so the number is the product's own
    behaviour and not a second opinion about it.
    """
    due_day = task.due.date()
    day = due_day - timedelta(days=horizon_days)
    while day <= due_day:
        if scan([task], commitments, day, rules, booked):
            return day
        day += timedelta(days=1)
    return None
