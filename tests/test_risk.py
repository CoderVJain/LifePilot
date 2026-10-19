"""The risk scan: pure, offline, free. Values in, values out.

The property that matters is *when* a warning appears, not merely that it does. A warning on the
due date is what a reminder app already does.
"""

from datetime import date, datetime, timedelta

from lifepilot.engine.reachability import Commitment
from lifepilot.engine.risk import (
    Task,
    first_warning_day,
    free_gaps,
    scan,
)

AARAV = 3
MONDAY = date(2026, 10, 19)
NO_LATE_STUDY = {"type": "latest_end", "params": {"category": "study", "latest_end": "21:00"}}


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute)


def school(day: date, event_id: int = 1) -> Commitment:
    return Commitment(event_id, "school", at(day, 8), at(day, 15), 4, (AARAV,), "school", False)


def project(due_day: date, est_minutes: int = 180, prep_days: int = 3) -> Task:
    return Task(
        id=10, title="science project model", due=at(due_day, 8), est_minutes=est_minutes,
        owner_id=AARAV, prep_days=prep_days, category="study",
    )


def test_an_empty_week_leaves_a_task_alone():
    friday = MONDAY + timedelta(days=4)
    assert scan([project(friday)], [], MONDAY) == []


def test_a_genuinely_full_week_puts_the_task_at_risk():
    """Booked from seven in the morning to half nine at night, so the three hours do not exist.

    An earlier version of this test only filled the evenings and the task was correctly judged
    fine: school starts at eight, so every morning left a usable hour.
    """
    busy = []
    for offset in range(5):
        day = MONDAY + timedelta(days=offset)
        busy.append(Commitment(200 + offset, "cricket", at(day, 7, 0), at(day, 21, 30), 5,
                               (AARAV,), "activity"))
    found = scan([project(MONDAY + timedelta(days=4))], busy, MONDAY)
    assert len(found) == 1
    assert "not_enough_time" in found[0].kinds
    assert found[0].minutes_free < found[0].minutes_needed


def test_the_due_day_itself_does_not_count():
    """Due 8 AM Friday cannot be done on Friday evening. Counting it was false comfort."""
    thursday = MONDAY + timedelta(days=3)
    friday = MONDAY + timedelta(days=4)
    busy = [school(day, 100 + i) for i, day in enumerate((MONDAY, thursday))]
    gaps = free_gaps(AARAV, busy, MONDAY, friday)
    assert all(gap.start.date() < friday for gap in gaps)


def test_a_warning_carries_the_slot_that_would_save_it():
    """A warning with a slot is something a parent can say yes to.

    This is the case the first design could not express: a task with a big enough gap was by
    definition not at risk, so a warning could never carry a repair. The risk is that nothing is
    booked, and the slot is what to book.
    """
    friday = MONDAY + timedelta(days=4)
    busy = []
    for offset in range(4):
        day = MONDAY + timedelta(days=offset)
        busy.append(Commitment(100 + offset, "cricket", at(day, 7), at(day, 21, 30), 5,
                               (AARAV,), "activity") if offset != 2 else school(day, 100 + offset))
    # Due Friday with three prep days, so the window opens on Tuesday and not before.
    found = scan([project(friday)], busy, MONDAY + timedelta(days=1))
    assert len(found) == 1
    assert found[0].kinds == ("unbooked",)
    assert found[0].slot is not None
    assert found[0].slot.minutes >= 180
    assert found[0].slot.start.date() == MONDAY + timedelta(days=2), "Wednesday is the only gap"


def test_a_task_with_time_already_set_aside_is_not_at_risk():
    """Whatever the rest of the calendar looks like. Warning about it would be noise."""
    friday = MONDAY + timedelta(days=4)
    task = project(friday)
    assert scan([task], [], MONDAY, booked=[task.id]) == []


def test_nothing_is_warned_about_before_its_prep_window_opens():
    """What stops this nagging about every task every day."""
    due = MONDAY + timedelta(days=10)
    task = Task(id=14, title="history essay", due=at(due, 8), est_minutes=60, owner_id=AARAV,
                prep_days=2, category="study")
    assert scan([task], [], MONDAY) == []
    assert scan([task], [], due - timedelta(days=2)) != []


def test_a_study_rule_shortens_the_evening_and_brings_the_warning_forward():
    """The reason storing rules is worth anything: a 9 PM rule makes the week genuinely tighter."""
    friday = MONDAY + timedelta(days=4)
    busy = []
    for offset in range(4):
        day = MONDAY + timedelta(days=offset)
        busy.append(school(day, 100 + offset))
        busy.append(Commitment(200 + offset, "cricket", at(day, 15), at(day, 18, 10), 5,
                               (AARAV,), "activity"))

    task = project(friday, est_minutes=180)
    loose = scan([task], busy, MONDAY, rules=())
    tight = scan([task], busy, MONDAY, rules=(NO_LATE_STUDY,))
    assert not loose, "without the rule the evenings are long enough"
    assert tight, "with the rule they are not, and the parent should hear about it"


def test_a_rule_about_another_category_is_left_alone():
    friday = MONDAY + timedelta(days=4)
    other = {"type": "latest_end", "params": {"category": "activity", "latest_end": "17:00"}}
    task = project(friday)
    assert scan([task], [school(MONDAY)], MONDAY, rules=(other,)) == []


def test_a_passed_prep_day_says_so_in_the_sentence():
    """The parent hears that it is already late, not just that it is unbooked."""
    due = MONDAY + timedelta(days=1)
    task = Task(id=11, title="costume", due=at(due, 8), est_minutes=30, owner_id=AARAV,
                prep_days=5, category="other")
    found = scan([task], [], MONDAY)
    assert len(found) == 1
    assert found[0].kinds == ("unbooked",)
    assert "should have started already" in found[0].detail


def test_a_done_task_is_not_a_risk():
    friday = MONDAY + timedelta(days=4)
    done = Task(id=12, title="done thing", due=at(friday, 8), est_minutes=600, owner_id=AARAV,
                status="done")
    assert scan([done], [], MONDAY) == []


def test_days_of_warning_is_measured_by_replaying_the_scan():
    """The number is the product's own behaviour, not a second opinion about it."""
    friday = MONDAY + timedelta(days=4)
    busy = []
    for offset in range(5):
        day = MONDAY + timedelta(days=offset)
        busy.append(school(day, 100 + offset))
        busy.append(Commitment(200 + offset, "cricket", at(day, 15), at(day, 21, 30), 5,
                               (AARAV,), "activity"))
    first = first_warning_day(project(friday), busy)
    assert first is not None
    assert first <= MONDAY, "a week this full should have been flagged on Monday or earlier"


def test_a_household_task_is_blocked_by_everybody():
    """No owner means it is the family's, so anything in the calendar is in the way."""
    friday = MONDAY + timedelta(days=4)
    somebody_else = Commitment(300, "work", at(MONDAY, 7), at(MONDAY, 21, 30), 2, (99,), "work")
    task = Task(id=13, title="fee payment", due=at(friday, 8), est_minutes=30, owner_id=None)
    gaps = free_gaps(None, [somebody_else], MONDAY, MONDAY + timedelta(days=1))
    assert gaps == [] or all(gap.minutes < 30 for gap in gaps)
    assert task.start_by == friday
