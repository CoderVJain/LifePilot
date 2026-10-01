"""Golden transcripts: what a family actually says, and what a right answer looks like.

Everything until now tested a layer. These test the product: the words someone says, the tool that
should be chosen, the arguments it should be chosen with, and whether the sentence that comes back
answers the question. Four rounds of bugs reached a human tester because nothing covered this, and
every one of them was a true statement that did not answer what was asked.

Checks are deterministic on purpose. "Does the reply mention 3:45 PM" is a fact; "is the reply good"
is a judgement, and a judgement needs a model, which costs money and can itself be wrong. Where a
judgement is genuinely needed it is written as a `must_say` on the thing that must appear.

Dates are written as tokens, because "tomorrow" is a different date every day:

    @today @tomorrow @yesterday   relative to the day the eval runs
    @mon .. @fri                  the demo week, which the eval pins
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

from lifepilot_shared.clock import today as clock_today
from lifepilot_shared.week import demo_week

DAY_TOKENS = ("@mon", "@tue", "@wed", "@thu", "@fri")


@dataclass(frozen=True)
class Exchange:
    """One thing said, and what a correct response to it looks like."""

    said: str
    speaker: str = "Dad"
    #: One tool, or several when more than one route produces a correct answer.
    tool: str | tuple[str, ...] | None = None
    args: dict = field(default_factory=dict)
    must_say: tuple[str, ...] = ()
    must_not_say: tuple[str, ...] = ()
    #: True when this follows on from the line before and shares its conversation. "Why not
    #: Grandpa?" names no lift because the lift was named a sentence ago.
    follows_on: bool = False
    #: Set when this is known to route wrongly today. The eval still scores it as a miss; the test
    #: suite allows it, so CI catches new breakage rather than re-reporting an old one.
    known_miss: str = ""
    why: str = ""

    def expected_args(self, today: date | None = None) -> dict:
        return {key: resolve(value, today) for key, value in self.args.items()}

    def expected_say(self, today: date | None = None) -> tuple[str, ...]:
        return tuple(resolve(phrase, today) for phrase in self.must_say)


def resolve(value, today: date | None = None):
    """Turn a date token into the date it means on the day the eval runs."""
    if not isinstance(value, str) or not value.startswith("@"):
        return value
    today = today or clock_today()
    monday, _ = demo_week(today)
    table = {
        "@today": today,
        "@tomorrow": today + timedelta(days=1),
        "@yesterday": today - timedelta(days=1),
        **{token: monday + timedelta(days=offset) for offset, token in enumerate(DAY_TOKENS)},
    }
    found = table.get(value)
    return found.isoformat() if found else value


# --------------------------------------------------------------------------- the transcripts

#: Reported by a human tester as wrong. Each one is a bug that reached a person.
FROM_TESTING = (
    Exchange(
        said="what is Aarav's school timing tomorrow",
        tool="get_schedule",
        args={"about": "Aarav", "start": "@tomorrow", "end": "@tomorrow"},
        must_not_say=("performance review", "2026-"),
        why="answered with Dad's day, for today, as a count with no end times",
    ),
    Exchange(
        said="what is my schedule for tomorrow",
        tool="get_schedule",
        args={"about": "Dad", "start": "@tomorrow", "end": "@tomorrow"},
        must_not_say=("2026-",),
        why="answered with all nineteen family events",
    ),
    Exchange(
        said="I want to schedule a meeting for today at 4 PM, do I have any work at that time?",
        # what_if answers it directly; listing the day answers it too, if less neatly.
        tool=("what_if", "get_schedule"),
        args={},
        must_say=("performance review",),
        must_not_say=("2026-",),
        why="listed the whole day instead of answering whether 4 PM was free",
    ),
    Exchange(
        said="I want to schedule the meeting at 4:00 p.m. do I have any work schedule at that time",
        tool=("what_if", "get_schedule"),
        args={},
        must_not_say=("could not", "2026-"),
        why="get_schedule was sent a timestamp where a day belonged and rejected the call",
    ),
    Exchange(
        said="do I have any work at 4 pm",
        tool=("what_if", "get_schedule"),
        args={},
        must_not_say=("could not", "2026-"),
        why="what_if arrived with HTML-escaped newlines in its optional fields",
    ),
    Exchange(
        said="I want to schedule a meeting at 5 PM today, do I have anything at that time",
        tool=("what_if", "get_schedule"),
        args={},
        must_say=("5 PM",),
        must_not_say=("could not", "2026-", "9:30"),
        why="answered a question about 5 PM by listing the whole day, work included",
    ),
    Exchange(
        said="what is happening this week",
        tool="get_schedule",
        args={"start": "@mon", "end": "@fri"},
        must_not_say=("2026-", "line below", "Each line"),
        why="recited nineteen events and ran past the token limit mid-sentence",
    ),
)

#: The differentiators. If these break, the product has no reason to exist.
HEADLINE = (
    Exchange(
        said="any problems this week",
        tool="detect_conflicts",
        args={"start": "@mon", "end": "@fri"},
        must_say=("football",),
        must_not_say=("2026-",),
        why="#1: a pickup nobody assigned can reach, while nothing overlaps",
    ),
    Exchange(
        said="who should pick up Aarav",
        tool="suggest_responsible",
        args={},
        must_say=("Mom",),
        why="#2: ranked, with the reason she beat the others",
    ),
    Exchange(
        said="why not Grandpa",
        tool="explain_choice",
        args={"person": "Grandpa"},
        must_say=("rule",),
        follows_on=True,
        why="#3: the reason recorded when the decision was made, carried from the line before",
    ),
    Exchange(
        said="fix our week",
        tool="fix_week",
        args={},
        must_say=("Mom",),
        why="#4: the smallest repair, awaiting approval",
    ),
    Exchange(
        said="what if my four o'clock runs until half five",
        tool="what_if",
        args={},
        why="#5: the ripple, changing nothing",
    ),
    Exchange(
        said="what are our rules",
        tool="list_rules",
        args={},
        must_say=("piano",),
        why="#8: rules read back in the family's own words",
    ),
)

#: Ordinary days. Nothing clever, just the things people say.
EVERYDAY = (
    Exchange(said="what have I got today", tool="get_schedule",
             args={"about": "Dad", "start": "@today", "end": "@today"}),
    Exchange(said="what's on tomorrow", tool="get_schedule",
             args={"start": "@tomorrow", "end": "@tomorrow"}),
    Exchange(said="what is Anaya doing on Thursday", tool="get_schedule",
             args={"about": "Anaya", "start": "@thu", "end": "@thu"}),
    Exchange(said="when does Mom finish work on Friday", tool="get_schedule",
             args={"about": "Mom"}),
    Exchange(said="who is in the family", tool="get_family", args={}),
    Exchange(said="can I say yes to a six o'clock meeting on Friday", tool="what_if", args={}),
    Exchange(said="what if football is cancelled", tool="what_if", args={}),
    Exchange(said="is anything broken on Thursday", tool="detect_conflicts", args={}),
)

#: A child and a carer get different answers to the same words. This is differentiator #9.
ROLES = (
    Exchange(
        said="what have I got today",
        speaker="Aarav",
        tool="get_schedule",
        args={"about": "Aarav", "start": "@today", "end": "@today"},
        must_not_say=("performance review",),
        why="#9: a child never hears a parent's meeting",
    ),
    Exchange(
        said="what is happening this week",
        speaker="Aarav",
        tool="get_schedule",
        must_not_say=("performance review",),
        why="#9: parents' work shows as Busy",
    ),
)

#: Things LifePilot does not do. Saying so plainly is the right answer.
OUT_OF_SCOPE = (
    Exchange(said="book me a flight to Goa", tool="cannot_help", args={}),
    Exchange(said="what is the weather tomorrow", tool="cannot_help", args={}),
    Exchange(said="order milk", tool="cannot_help", args={}),
    Exchange(said="how much did we spend on football this month", tool="cannot_help", args={}),
)

ALL: tuple[Exchange, ...] = FROM_TESTING + HEADLINE + EVERYDAY + ROLES + OUT_OF_SCOPE


def by_name(name: str) -> tuple[Exchange, ...]:
    groups = {
        "testing": FROM_TESTING,
        "headline": HEADLINE,
        "everyday": EVERYDAY,
        "roles": ROLES,
        "scope": OUT_OF_SCOPE,
        "all": ALL,
    }
    return groups[name]
