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
    return monday_of(today or _today())


def demo_week(today: date | None = None) -> tuple[date, date]:
    """Monday to Friday of the demo week, which is the span the seeded data covers."""
    monday = demo_monday(today)
    return monday, monday + timedelta(days=4)
