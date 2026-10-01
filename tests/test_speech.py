"""Saying dates and times the way a person would. Pure, offline, free."""

from datetime import date, datetime

import pytest

from lifepilot_shared.speech import (
    plural,
    say_day,
    say_list,
    say_span,
    say_time,
    say_when,
    say_window,
)

TODAY = date(2026, 10, 1)


@pytest.mark.parametrize(
    ("moment", "spoken"),
    [
        (datetime(2026, 10, 8, 16, 0), "4 PM"),
        (datetime(2026, 10, 8, 16, 30), "4:30 PM"),
        (datetime(2026, 10, 8, 8, 0), "8 AM"),
        (datetime(2026, 10, 8, 0, 0), "12 AM"),
        (datetime(2026, 10, 8, 12, 0), "12 PM"),
        (datetime(2026, 10, 8, 9, 5), "9:05 AM"),
    ],
)
def test_times_are_said_the_way_people_say_them(moment, spoken):
    assert say_time(moment) == spoken


@pytest.mark.parametrize(
    ("day", "spoken"),
    [
        (date(2026, 10, 1), "today"),
        (date(2026, 10, 2), "tomorrow"),
        (date(2026, 9, 30), "yesterday"),
        (date(2026, 10, 5), "Monday"),
        (date(2026, 10, 8), "next Thursday"),
        (date(2026, 11, 20), "Friday 20 November"),
    ],
)
def test_days_near_today_are_relative_and_far_ones_are_dated(day, spoken):
    assert say_day(day, TODAY) == spoken


def test_a_whole_moment_reads_as_one_phrase():
    assert say_when("2026-10-02T16:00", TODAY) == "tomorrow at 4 PM"
    assert say_when("2026-10-08T16:30", TODAY) == "next Thursday at 4:30 PM"


def test_the_day_can_be_left_off_when_it_is_already_understood():
    assert say_when("2026-10-08T16:00", TODAY, with_day=False) == "4 PM"


def test_a_window_never_says_the_same_day_twice():
    """"between October 8 and October 8" was the actual output, and it reads as a mistake."""
    assert say_window("2026-10-02", "2026-10-02", TODAY) == "tomorrow"
    assert say_window("2026-10-05", "2026-10-09", TODAY) == "Monday to Friday"


def test_lists_are_joined_the_way_they_are_spoken():
    assert say_list([]) == ""
    assert say_list(["school"]) == "school"
    assert say_list(["school", "football"]) == "school and football"
    assert say_list(["a", "b", "c"]) == "a, b and c"


def test_counts_agree_with_their_noun():
    assert plural(1, "thing") == "1 thing"
    assert plural(2, "thing") == "2 things"
    assert plural(0, "thing") == "0 things"
    assert plural(1, "person", "people") == "1 person"
    assert plural(3, "person", "people") == "3 people"


def test_no_iso_formatting_survives_into_speech():
    """The thing being fixed: an answer read aloud must contain no timestamps."""
    spoken = say_when("2026-10-08T16:00", TODAY)
    assert "2026" not in spoken
    assert "2026-10-08" not in spoken
    assert ":" not in spoken


def test_a_span_says_when_something_starts_and_ends():
    """"School at 8 AM" does not answer "what are the school timings", which is a question about
    when to collect someone."""
    assert say_span("2026-10-02T08:00", "2026-10-02T15:00", TODAY) == "tomorrow at 8 AM to 3 PM"
    assert say_span("2026-10-02T08:00", "2026-10-02T15:00", TODAY, with_day=False) == "8 AM to 3 PM"


def test_a_span_that_crosses_midnight_says_both_days():
    assert say_span("2026-10-02T22:00", "2026-10-03T01:00", TODAY) == (
        "tomorrow at 10 PM to Saturday at 1 AM"
    )


def test_a_span_with_no_end_is_just_the_start():
    assert say_span("2026-10-02T08:00", None, TODAY) == "tomorrow at 8 AM"


def test_a_day_in_the_week_we_are_in_is_just_its_name():
    """"Work last Monday" said while listing Monday to Friday of this week reads as though the week
    being described is already over."""
    thursday = date(2026, 10, 8)

    assert say_day(date(2026, 10, 5), thursday) == "Monday", "earlier this week, not last week"
    assert say_day(date(2026, 10, 6), thursday) == "Tuesday"
    # Relative days still win where they apply: they are what somebody would actually say.
    assert say_day(date(2026, 10, 7), thursday) == "yesterday"
    assert say_day(date(2026, 10, 9), thursday) == "tomorrow"
    # Ten days back is far enough that a bare weekday would be ambiguous, so it gets a date.
    assert say_day(date(2026, 9, 28), thursday) == "Monday 28 September"
