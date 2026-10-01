"""Turns an utterance into a spoken answer, cards and a debug record.

This increment matches a few fixed phrases and calls MCP tools directly. That keeps the whole chain
-- browser, WebSocket, MCP client, server, database -- provable before any model call, and costs
nothing to run. The Strands agent replaces `respond()` later; everything around it stays.
"""

import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta

from lifepilot_shared.clock import today as clock_today
from lifepilot_shared.speech import plural, say_list, say_span, say_window
from lifepilot_shared.week import demo_week

# The week the seeded data covers. Follows the real calendar so "tomorrow" means something; pinned
# by LIFEPILOT_WEEK=fixed for tests and the recorded demo.
WEEK_START, WEEK_END = demo_week()

HELP = (
    "Try: any problems this week, who is in the family, what is happening this week, "
    "or switch speaker to see a different view."
)


@dataclass
class Turn:
    """One exchange. `speak` is the product; cards support it and never replace it."""

    speak: str
    cards: list[dict] = field(default_factory=list)
    debug: dict = field(default_factory=dict)


WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

# Said about yourself rather than about the household. "My schedule" and "what's happening" are
# different questions and answering the first with the second buries what was asked for.
MINE = ("my ", " i ", "i have", "i got", "am i", "do i", "mine")

# The offline path cannot ask the server who is in the family before working out what was asked, so
# the seeded names are listed here. The model path has no such limit; this is the fallback being
# honest about being a fallback.
KNOWN_NAMES = ("Dad", "Mom", "Aarav", "Anaya", "Grandpa")


def respond(mcp, speaker: str, text: str) -> Turn:
    """Answer one utterance for one speaker."""
    asked = f" {text.lower().strip()} "

    if _mentions(asked, "problem", "wrong", "broken", "work out", "any issues"):
        return _problems(mcp, speaker)
    if _mentions(asked, "family", "who is in", "who's in", "members"):
        return _family(mcp, speaker)
    if _mentions(asked, "week", "schedule", "happening", "calendar", "doing", "on today",
                 "tomorrow", "today", *WEEKDAYS):
        start, end = _window(asked)
        return _schedule(mcp, speaker, start, end, about=_subject(asked, speaker))
    return Turn(speak=HELP, debug={"tool": None, "note": "no matching phrase"})


def _mentions(text: str, *phrases: str) -> bool:
    return any(phrase in text for phrase in phrases)


def _window(asked: str) -> tuple[date, date]:
    """Which days were asked about. Falls back to the loaded week when nothing says otherwise."""
    today = clock_today()
    if "tomorrow" in asked:
        day = today + timedelta(days=1)
        return day, day
    if "today" in asked or "tonight" in asked:
        return today, today
    for index, name in enumerate(WEEKDAYS):
        if name in asked:
            day = _named_weekday(index)
            if day is not None:
                return day, day
    return WEEK_START, WEEK_END


def _named_weekday(index: int) -> date | None:
    """The day with that name inside the loaded week, so "Thursday" means the demo's Thursday."""
    for day in (WEEK_START + timedelta(days=offset) for offset in range(7)):
        if day.weekday() == index and WEEK_START <= day <= WEEK_END:
            return day
    return None


def call_tool(mcp, tool: str, arguments: dict) -> tuple[dict, dict]:
    """Call one MCP tool. Returns the parsed result and a debug record."""
    started = time.perf_counter()
    result = mcp.call_tool_sync(str(uuid.uuid4()), tool, arguments)
    elapsed_ms = round((time.perf_counter() - started) * 1000)

    debug = {
        "tool": tool,
        "arguments": arguments,
        "status": result["status"],
        "tool_ms": elapsed_ms,
        # No model call on this path. The counter is here from the start so the cost discipline is
        # visible to anyone watching the drawer.
        "model_calls": 0,
        "estimated_cost_usd": 0.0,
    }
    if result["status"] != "success":
        # Keep what the server said. "I could not reach that" told a tester nothing, while the
        # server had already explained itself: "rejected arguments: ['end', 'start']". Throwing
        # that away turned a precise complaint into a shrug.
        debug["error"] = "".join(block.get("text", "") for block in result["content"])[:300]
        return {}, debug

    text = "".join(block.get("text", "") for block in result["content"])
    return json.loads(text), debug


def _problems(mcp, speaker: str) -> Turn:
    found, debug = call_tool(
        mcp,
        "detect_conflicts",
        {"speaker": speaker, "start": WEEK_START.isoformat(), "end": WEEK_END.isoformat()},
    )
    if not found:
        return Turn(speak="I could not check the week.", debug=debug)

    conflicts = found["conflicts"]
    if not conflicts:
        return Turn(speak="Nothing is broken this week.", debug=debug)

    first = conflicts[0]
    speak = f"{len(conflicts)} problems. {first['detail']}"
    if first["could_cover"]:
        speak += f". {' or '.join(first['could_cover'])} could cover it"
    card = {
        "kind": "conflicts",
        "title": f"{found['from']} to {found['to']}",
        "conflicts": conflicts,
        "checked": found["checked"],
    }
    return Turn(speak=speak + ".", cards=[card], debug=debug)


def _family(mcp, speaker: str) -> Turn:
    family, debug = call_tool(mcp, "get_family", {"speaker": speaker})
    if not family:
        return Turn(speak="I could not reach the family record.", debug=debug)

    others = [m for m in family["members"] if not m["is_you"]]
    names = ", ".join(f"{m['name']} ({m['role']})" for m in others)
    speak = f"You are {speaker}, a {family['speaker']['role']}. The others are {names}."
    card = {
        "kind": "family",
        "title": "Your family",
        "members": family["members"],
        "locations": family["locations"],
    }
    return Turn(speak=speak, cards=[card], debug=debug)


def _nothing_for(about: str | None, speaker: str) -> str:
    if about == speaker:
        return "You have nothing on"
    if about:
        return f"{about} has nothing on"
    return "There is nothing on"


def _subject(asked: str, speaker: str) -> str | None:
    """Whose day was asked about: a family member named out loud, or the speaker for "my"."""
    for name in KNOWN_NAMES:
        if name.lower() in asked:
            return name
    return speaker if _mentions(asked, *MINE) else None


def _say_event(event: dict, with_name: bool) -> str:
    """One event as it would be said. The span, because "timing" is a question about hours."""
    when = say_span(event["start"], event.get("end"), with_day=False)
    members = event.get("members") or []
    if not (with_name and members):
        return f"{event['title']} {when}"
    has = "have" if len(members) > 1 else "has"
    return f"{say_list(members)} {has} {event['title']} {when}"


def _schedule(
    mcp, speaker: str, start: date | None = None, end: date | None = None, about: str | None = None
) -> Turn:
    start = start or WEEK_START
    end = end or WEEK_END
    schedule, debug = call_tool(
        mcp,
        "get_schedule",
        {
            "speaker": speaker,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "about": about,
        },
    )
    if not schedule:
        return Turn(speak="I could not reach the schedule.", debug=debug)

    events = schedule["events"]
    hidden = sum(1 for e in events if e.get("redacted"))
    visible = len(events) - hidden
    window = say_window(start, end)

    shown = [e for e in events if not e.get("redacted")]

    if not events:
        speak = (
            f"{_nothing_for(about, speaker)} {window}. "
            f"The week that is loaded is {say_window(WEEK_START, WEEK_END)}."
        )
    elif about or start == end:
        # Name them. "There are 3 things on tomorrow" answers how many, which is never the question;
        # somebody asking about school timings wants the hours, so give the span.
        mine = about == speaker
        listed = [_say_event(e, with_name=not about) for e in shown[:6]]
        if mine:
            opening = "You have"
        elif about:
            opening = f"{about} has"
        else:
            opening = "There is" if visible == 1 else "There are"
        speak = f"{opening} {plural(visible, 'thing')} {window}: {say_list(listed)}."
        if visible > 6:
            speak += f" And {visible - 6} more."
        if hidden:
            speak += f" {hidden} more belong to someone else."
    else:
        speak = f"There {'is' if visible == 1 else 'are'} {plural(visible, 'thing')} on {window}"
        if hidden:
            speak += f", and {hidden} more where someone else is busy"
        speak += "."

    card = {
        "kind": "schedule",
        "title": window,
        "events": events,
        "tasks": schedule["tasks"],
    }
    return Turn(speak=speak, cards=[card], debug=debug)
