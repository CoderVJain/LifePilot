"""Experiment 5: warning early is the claim, so the test is about *when*, not whether."""

from eval.experiment5 import build, run


def test_the_planted_set_has_both_kinds():
    """Only the genuinely-fine tasks expose a scanner that flags everything."""
    planted = build()
    assert sum(1 for p in planted if p.at_risk) >= 4
    assert sum(1 for p in planted if not p.at_risk) >= 3


def test_every_fine_task_is_fine_because_time_is_set_aside_or_it_is_done():
    """An open, unbooked task is never "fine": warning about it is correct, and counting that as
    a false alarm would understate the product and flatter the baseline at the same time."""
    for item in build():
        if item.at_risk:
            continue
        assert item.booked or item.task.status == "done", item.name


def test_lifepilot_catches_everything_and_cries_wolf_at_nothing():
    lifepilot, _ = run()
    assert lifepilot.catch_rate == 1.0
    assert lifepilot.false_alarm_rate == 0.0


def test_the_warning_arrives_days_earlier_than_a_deadline_reminder():
    """The headline. A warning you cannot act on is not help."""
    lifepilot, deadline = run()
    assert lifepilot.mean_warning > deadline.mean_warning
    assert lifepilot.median_warning >= 3


def test_a_reminder_app_never_sees_a_task_that_only_exists_in_an_email():
    """Differentiator #7's whole reason for existing, as a number."""
    _, deadline = run()
    assert deadline.invisible >= 2
    assert deadline.catch_rate < 1.0


def test_most_warnings_come_with_a_slot_to_book():
    """A warning with a slot is something a parent can say yes to. A deadline knows the date,
    not the week, so it can offer nothing."""
    lifepilot, _ = run()
    assert lifepilot.offered_a_slot >= 3
