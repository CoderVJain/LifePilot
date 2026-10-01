"""Turning dates and times into something a person would actually say.

These answers are spoken aloud. "2026-10-08T16:00" is a correct answer to a question nobody asked;
"Thursday at 4 PM" is the same fact in the form it was asked for. Shared by both the model path and
the offline one so they never drift into saying it differently.

Relative days are used when the week in question is near today, because "tomorrow" is how the
question was put and answering it with a weekday makes the listener do the arithmetic back.
"""

from datetime import date, datetime, timedelta

from lifepilot_shared.clock import today as _today

DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


def say_time(moment: datetime) -> str:
    """4 PM, 4:30 PM, 8 AM. No leading zero, no 24-hour clock, no seconds."""
    hour = moment.hour % 12 or 12
    suffix = "AM" if moment.hour < 12 else "PM"
    if moment.minute == 0:
        return f"{hour} {suffix}"
    return f"{hour}:{moment.minute:02d} {suffix}"


def say_day(day: date, today: date | None = None) -> str:
    """Today, tomorrow, yesterday, a weekday within the week either side, else a plain date."""
    today = today or _today()
    delta = (day - today).days
    weekday = DAYS[day.weekday()]
    if delta == 0:
        return "today"
    if delta == 1:
        return "tomorrow"
    if delta == -1:
        return "yesterday"
    # A day in the week we are already in is just its name. "Work last Monday" said while listing
    # Monday to Friday of this week is wrong, and reads as though the week being described is over.
    same_week = day.isocalendar()[:2] == today.isocalendar()[:2]
    if same_week:
        return weekday
    if 1 < delta < 7:
        return weekday
    # Seven days out a bare weekday is ambiguous: this Thursday or the next one. Say which.
    if 7 <= delta < 14:
        return f"next {weekday}"
    if -7 < delta < -1:
        return f"last {weekday}"
    return f"{weekday} {day.day} {MONTHS[day.month - 1]}"


def say_when(value: str | datetime, today: date | None = None, with_day: bool = True) -> str:
    """A whole moment: "tomorrow at 4 PM", or just "4 PM" when the day is already understood."""
    moment = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if not with_day:
        return say_time(moment)
    return f"{say_day(moment.date(), today)} at {say_time(moment)}"


def say_span(start: str | datetime, end: str | datetime | None, today: date | None = None,
             with_day: bool = True) -> str:
    """How long something runs, which is what "timing" means.

    "School at 8 AM" answers when it starts; it does not answer when to collect anyone, which is the
    thing a parent is actually asking. A span that ends the same day says the day once.
    """
    first = start if isinstance(start, datetime) else datetime.fromisoformat(str(start))
    if end is None:
        return say_when(first, today, with_day=with_day)

    last = end if isinstance(end, datetime) else datetime.fromisoformat(str(end))
    opening = say_when(first, today, with_day=with_day)
    if last.date() == first.date():
        return f"{opening} to {say_time(last)}"
    return f"{opening} to {say_when(last, today)}"


def say_window(start: str | date, end: str | date, today: date | None = None) -> str:
    """"tomorrow", or "Monday to Friday" -- never the same date repeated twice."""
    first = start if isinstance(start, date) else date.fromisoformat(str(start))
    last = end if isinstance(end, date) else date.fromisoformat(str(end))
    if first == last:
        return say_day(first, today)
    # Within one week, plain weekday names: "Monday to next Friday" is technically precise and
    # sounds like a mistake.
    if first.isocalendar()[:2] == last.isocalendar()[:2]:
        return f"{DAYS[first.weekday()]} to {DAYS[last.weekday()]}"
    return f"{say_day(first, today)} to {say_day(last, today)}"


def say_list(items: list[str]) -> str:
    """Joined the way it would be said: a, b and c."""
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} and {items[-1]}"


def plural(count: int, one: str, many: str | None = None) -> str:
    """"1 thing", "2 things" -- said aloud, "1 things" is jarring in a way it is not on screen."""
    return f"{count} {one if count == 1 else (many or one + 's')}"


def days_between(start: date, end: date) -> list[date]:
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]
