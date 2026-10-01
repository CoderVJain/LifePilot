"""Minimal-change repair on the seeded week. Offline and free: CP-SAT, no model calls."""

from datetime import date, datetime, timedelta

import pytest

from eval.generate import MONDAY, build_demo_family
from lifepilot.db.session import make_engine, make_session_factory
from lifepilot.engine.conflicts import Week, detect
from lifepilot.engine.reachability import Commitment, Person, TransportNeed
from lifepilot.solver.repair import MAX_SOLVE_SECONDS, SEARCH_WORKERS, repair
from lifepilot.tools.detect_conflicts import load_week

FRIDAY = date(2026, 10, 9)


@pytest.fixture
def week():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    factory = make_session_factory(engine, create=True)
    with factory() as session:
        build_demo_family(session)
        return load_week(session, 1, MONDAY, FRIDAY)


def test_the_broken_week_repairs_in_two_changes(week):
    result = repair(week)
    assert result.status == "optimal"
    assert result.change_count == 2


def test_the_two_changes_are_the_ones_a_parent_would_expect(week):
    changes = {c.kind: c for c in repair(week).changes}

    assert changes["assign"].title == "football practice pickup"
    assert changes["assign"].was == "Dad"
    assert changes["assign"].now == "Mom"
    assert "cannot get there in time" in changes["assign"].reason

    assert changes["move"].title == "science project block"
    assert changes["move"].was.startswith("Thursday 20:00")


def test_the_repair_actually_fixes_what_was_broken(week):
    """A diff that does not clear the conflicts is not a repair."""
    before = detect(week)
    assert before

    result = repair(week)
    fixed = _apply(week, result)
    assert detect(fixed) == []


def test_the_immovable_piano_class_never_moves(week):
    moved = {c.title for c in repair(week).changes if c.kind == "move"}
    assert "piano class" not in moved


def test_nothing_that_was_already_fine_is_touched(week):
    """Minimal change is the objective, so work and school must be left alone."""
    touched = {c.title for c in repair(week).changes}
    assert not touched & {"work", "school", "performance review"}


def test_the_answer_is_stable_across_runs(week):
    first = [c.as_dict() for c in repair(week).changes]
    for _ in range(3):
        assert [c.as_dict() for c in repair(week).changes] == first


def test_it_answers_fast_enough_for_a_voice_turn(week):
    result = repair(week)
    assert result.solve_ms < MAX_SOLVE_SECONDS * 1000
    assert SEARCH_WORKERS == 8  # OR-Tools 9.15 segfaults above this on a hinted model


def test_a_week_with_nothing_wrong_needs_no_changes(week):
    fixed = _apply(week, repair(week))
    again = repair(fixed)
    assert again.change_count == 0
    assert again.status == "optimal"


def test_a_lift_nobody_can_cover_is_reported_rather_than_faked():
    """When there is no answer, say so. Silently dropping the lift would be worse."""
    home, ground = 1, 2
    dad = Person(1, "Dad", "parent", True, home)
    aarav = Person(3, "Aarav", "child", False, home)
    day = datetime(2026, 10, 8)

    busy = Commitment(1, "all day offsite", day.replace(hour=9), day.replace(hour=20), home, (1,))
    football = Commitment(2, "football", day.replace(hour=16), day.replace(hour=17), ground, (3,))
    need = TransportNeed(2, "football pickup", aarav.id, day.replace(hour=17), ground)

    week = Week(
        people=[dad, aarav],
        commitments=[busy, football],
        needs=[need],
        travel={(home, ground): 15, (ground, home): 15},
    )
    result = repair(week)
    assert result.unfixable == ["nobody can cover football pickup"]


def test_an_empty_week_is_not_an_error():
    assert repair(Week(people=[], commitments=[], needs=[], travel={})).change_count == 0


def _apply(week: Week, result) -> Week:
    """The week as it would be after the changes are approved."""
    assigned = dict(week.assigned)
    commitments = list(week.commitments)
    names = {p.name: p.id for p in week.people}

    for change in result.changes:
        if change.kind == "assign":
            assigned[change.event_id] = names[change.now]
        elif change.kind == "move":
            index = next(i for i, c in enumerate(commitments) if c.id == change.event_id)
            old = commitments[index]
            length = old.end - old.start
            new_start = _parse(change.now, old.start)
            commitments[index] = Commitment(
                old.id, old.title, new_start, new_start + length, old.location_id,
                old.member_ids, old.category,
            )

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


def _parse(label: str, near: datetime) -> datetime:
    """Turn "Thursday 19:30" back into a datetime in the same week."""
    day_name, clock = label.split(" ")
    hour, minute = (int(part) for part in clock.split(":"))
    days = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
    shift = days.index(day_name) - near.weekday()
    return (near + timedelta(days=shift)).replace(hour=hour, minute=minute)
