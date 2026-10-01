"""Apply a proposed plan to a week, so any repairer can be judged the same way.

Both the solver and the model hand back a list of changes in the same shape. This applies them and
hands the result to the ordinary conflict detector. Scoring a plan by the code that produced it would
prove nothing; scoring every plan with the same detector is the only comparison worth making.
"""

from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime

from lifepilot.engine.conflicts import Week, detect


class ImpossibleChange(ValueError):
    """The plan asks for something that cannot be carried out at all."""


def apply_changes(week: Week, changes: Sequence[dict]) -> Week:
    """The week as it would be if this plan were approved.

    Raises `ImpossibleChange` when a plan names an event or a person that does not exist. That is a
    real failure of the plan, not of the evaluation, and it is counted as one.
    """
    assigned = dict(week.assigned)
    commitments = list(week.commitments)
    people = {person.id for person in week.people}
    by_id = {c.id: i for i, c in enumerate(commitments)}

    for change in changes:
        event_id = change.get("event_id")
        kind = change.get("kind")

        if kind == "assign":
            person_id = change.get("person_id")
            if person_id not in people:
                raise ImpossibleChange(f"no such person: {person_id}")
            if not any(need.event_id == event_id for need in week.needs):
                raise ImpossibleChange(f"no lift for event {event_id}")
            assigned[event_id] = person_id

        elif kind == "move":
            if event_id not in by_id:
                raise ImpossibleChange(f"no such event: {event_id}")
            start_iso = change.get("start_iso")
            if not start_iso:
                raise ImpossibleChange(f"move with no new time for event {event_id}")
            try:
                start = datetime.fromisoformat(start_iso)
            except ValueError as bad:
                raise ImpossibleChange(f"{start_iso!r} is not a time") from bad

            index = by_id[event_id]
            old = commitments[index]
            if not old.movable:
                raise ImpossibleChange(f"{old.title} cannot be moved")
            commitments[index] = replace(old, start=start, end=start + (old.end - old.start))

        else:
            raise ImpossibleChange(f"unknown kind of change: {kind!r}")

    driven: dict[int, set[int]] = {}
    for event_id, member_id in assigned.items():
        driven.setdefault(member_id, set()).add(event_id)

    return Week(
        people=week.people,
        commitments=commitments,
        needs=week.needs,
        travel=week.travel,
        driven={k: frozenset(v) for k, v in driven.items()},
        assigned=assigned,
        rules=week.rules,
    )


def remaining_problems(week: Week, changes: Sequence[dict]) -> list:
    """What is still broken once this plan is applied. An impossible plan fixes nothing."""
    try:
        after = apply_changes(week, changes)
    except ImpossibleChange:
        return detect(week)
    return detect(after)


def breaks_a_rule(week: Week, changes: Sequence[dict]) -> bool:
    """Did the plan leave, or introduce, a breach of a rule the family actually stated?"""
    return any(problem.kind == "rule_clash" for problem in remaining_problems(week, changes))


def moved_something_immovable(week: Week, changes: Sequence[dict]) -> bool:
    """A plan that moves piano is not merely suboptimal; it broke a promise."""
    fixed = {c.id for c in week.commitments if not c.movable}
    return any(c.get("kind") == "move" and c.get("event_id") in fixed for c in changes)


def is_applicable(week: Week, changes: Sequence[dict]) -> bool:
    try:
        apply_changes(week, changes)
    except ImpossibleChange:
        return False
    return True
