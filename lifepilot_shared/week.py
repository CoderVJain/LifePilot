"""Which week the demo is about.

The seeded family used to live permanently in 5-9 October 2026. Asking "what is on tomorrow" on any
other date then returned nothing, which looks like a broken product rather than a data window. The
demo now defaults to the current working week, so tomorrow is a real day with real events in it.

The fixed week stays available, because the tests and the recorded demo script name specific dates
and should not change meaning depending on when they run.
"""

import os
from datetime import date, timedelta

from lifepilot_shared.clock import today as _today

# The week the tests and the demo script were written against.
FIXED_MONDAY = date(2026, 10, 5)

#: Set LIFEPILOT_WEEK=fixed to pin the demo to FIXED_MONDAY, or to an ISO date to choose a Monday.
WEEK_ENV = "LIFEPILOT_WEEK"


def monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def demo_monday(today: date | None = None) -> date:
    """The Monday the demo family's week starts on."""
    setting = (os.environ.get(WEEK_ENV) or "").strip().lower()
    if setting == "fixed":
        return FIXED_MONDAY
    if setting:
        try:
            return monday_of(date.fromisoformat(setting))
        except ValueError:
            pass

    day = today or _today()
    # On a Saturday or Sunday the working week that matters is the one about to start, not the one
    # that has just finished. `monday_of` is right by the calendar and wrong here: asked on a
    # Sunday it put the whole demo in the past, so every event had already happened and "what is on
    # tomorrow" was empty -- the precise failure this module exists to prevent. Found on a Sunday,
    # three days before the weekend ahead of our own submission date.
    if day.weekday() >= 5:
        return monday_of(day) + timedelta(days=7)
    return monday_of(day)


def demo_week(today: date | None = None) -> tuple[date, date]:
    """Monday to Friday of the demo week. The working week every decision is made about."""
    monday = demo_monday(today)
    return monday, monday + timedelta(days=4)


def demo_span(today: date | None = None) -> tuple[date, date]:
    """Every day the seeded data covers: the weekend running in, then Monday to Friday.

    `demo_week` rolls forward over a weekend, so asked on a Saturday it put the whole demo two days
    into the future and "what is on today" had nothing to answer with. The seed therefore fills the
    Saturday and Sunday before the working week too, and this is the window the product reads and
    checks. Decisions still turn on the working week; this only stops today being an empty day.
    """
    monday = demo_monday(today)
    return monday - timedelta(days=2), monday + timedelta(days=4)
