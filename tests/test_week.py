"""Which week the demo is about.

The seeded data covers one Monday-to-Friday span. If that span is chosen wrongly the product looks
broken rather than empty: every event has already happened, and "what is on tomorrow" answers
nothing with complete confidence.
"""

from datetime import date

import pytest

from lifepilot_shared.week import FIXED_MONDAY, demo_monday, demo_span, demo_week

MONDAY = date(2026, 10, 5)
WEDNESDAY = date(2026, 10, 7)
FRIDAY = date(2026, 10, 9)
SATURDAY = date(2026, 10, 10)
SUNDAY = date(2026, 10, 11)


@pytest.fixture(autouse=True)
def unpinned(monkeypatch):
    monkeypatch.delenv("LIFEPILOT_WEEK", raising=False)


def test_a_weekday_uses_the_week_it_is_in():
    assert demo_monday(WEDNESDAY) == MONDAY
    assert demo_week(WEDNESDAY) == (MONDAY, FRIDAY)


def test_monday_and_friday_are_both_their_own_week():
    assert demo_monday(MONDAY) == MONDAY
    assert demo_monday(FRIDAY) == MONDAY


@pytest.mark.parametrize("weekend", [SATURDAY, SUNDAY])
def test_a_weekend_looks_forward_to_the_week_about_to_start(weekend):
    """Asked on a Sunday, the calendar's answer is the week that has just finished -- so every event
    is in the past and the demo has nothing in it. Found on a Sunday, on real data."""
    assert demo_monday(weekend) == date(2026, 10, 12)
    assert demo_week(weekend) == (date(2026, 10, 12), date(2026, 10, 16))


def test_the_demo_week_is_never_already_over():
    """The property that matters, for every day of a year: the week still has a day left in it."""
    day = date(2026, 1, 1)
    while day < date(2027, 1, 1):
        _, friday = demo_week(day)
        assert friday >= day, f"on {day} ({day:%A}) the whole demo week had already passed"
        day = date.fromordinal(day.toordinal() + 1)


def test_the_span_adds_the_weekend_running_into_the_week():
    assert demo_span(WEDNESDAY) == (date(2026, 10, 3), FRIDAY)


@pytest.mark.parametrize("weekend", [SATURDAY, SUNDAY])
def test_the_span_covers_the_weekend_it_is_asked_on(weekend):
    """The reason the span exists: asked on a Saturday, demo_week starts two days later, so today
    has nothing in it and the product reads as broken rather than empty."""
    start, end = demo_span(weekend)
    assert start <= weekend <= end


def test_today_is_always_inside_the_span():
    """For every day of a year. The one property the span is for."""
    day = date(2026, 1, 1)
    while day < date(2027, 1, 1):
        start, end = demo_span(day)
        assert start <= day <= end, f"on {day} ({day:%A}) today fell outside the seeded span"
        day = date.fromordinal(day.toordinal() + 1)


def test_fixed_still_pins_the_recorded_week(monkeypatch):
    monkeypatch.setenv("LIFEPILOT_WEEK", "fixed")
    assert demo_monday(SUNDAY) == FIXED_MONDAY


def test_an_explicit_date_picks_its_own_monday(monkeypatch):
    monkeypatch.setenv("LIFEPILOT_WEEK", "2026-11-18")
    assert demo_monday(SUNDAY) == date(2026, 11, 16)
