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
from lifepilot_shared.week import demo_span, demo_week

DAY_TOKENS = ("@mon", "@tue", "@wed", "@thu", "@fri")

#: The weekend running into the week, which the seed covers too. `@sat` is the loaded window's
#: first day, so it is what "this week" spans.
WEEKEND_TOKENS = ("@sat", "@sun")


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
    saturday, _ = demo_span(today)
    table = {
        "@today": today,
        "@tomorrow": today + timedelta(days=1),
        "@yesterday": today - timedelta(days=1),
        **{token: monday + timedelta(days=offset) for offset, token in enumerate(DAY_TOKENS)},
        **{token: saturday + timedelta(days=offset) for offset, token in enumerate(WEEKEND_TOKENS)},
    }
    found = table.get(value)
    return found.isoformat() if found else value


# --------------------------------------------------------------------------- the transcripts

#: Reported by a human tester as wrong. Each one is a bug that reached a person.
FROM_TESTING = (
    Exchange(
        said="at what time do I have to collect Aarav from school",
        tool="get_schedule",
        args={"title": "school"},
        must_say=("3 PM",),
        must_not_say=("Someone has to", "2026-", "Mom works", "Dad works"),
        why="answered with the whole family's day and never said who collects or when",
    ),
    Exchange(
        said="what is the piano class timing and day",
        speaker="Mom",
        tool="get_schedule",
        args={"title": "piano"},
        must_say=("4 PM",),
        must_not_say=("19", "blocks of time", "2026-"),
        why="answered with 'Mom can see 19 things Monday to Friday' and the timing was buried",
    ),
    Exchange(
        said="what is the football's timing",
        speaker="Aarav",
        tool="get_schedule",
        args={"title": "football"},
        must_say=("4 PM",),
        must_not_say=("blocks of time", "cannot say what they are", "2026-"),
        why="led with '12 other blocks of time belong to other people', before answering",
    ),
    Exchange(
        said="what is my schedule",
        tool="get_schedule",
        args={"about": "Dad"},
        must_not_say=("worked", "yesterday", "2026-"),
        why="read out days already gone: 'you worked yesterday from 9 AM to 4 PM'",
    ),
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
        must_say=("5 PM", "Aarav"),
        must_not_say=("could not", "2026-", "9:30", "collect them"),
        why="listed the whole day, and said 'somebody has to collect them' with no name",
    ),
    Exchange(
        # Asked midweek, "this week" means the part still to come: the window is pulled to today.
        said="what is happening this week",
        tool="get_schedule",
        args={"start": "@today", "end": "@fri"},
        must_not_say=("2026-", "line below", "Each line"),
        why="recited nineteen events and ran past the token limit mid-sentence",
    ),
)

#: The differentiators. If these break, the product has no reason to exist.
HEADLINE = (
    Exchange(
        said="any problems this week",
        tool="detect_conflicts",
        # The loaded window opens on the Saturday running into the week, and detection sees all of
        # it rather than only from today.
        args={"start": "@sat", "end": "@fri"},
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
        must_say=("football practice pickup",),
        must_not_say=("Done", "Shall I", "2026-", "That works"),
        why="#5: the ripple, changing nothing -- and a worsened problem is not 'that works'",
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
             args={"about": "Dad", "start": "@today", "end": "@today"},
             must_say=("performance review",),
             must_not_say=("nothing on", "2026-", "piano"),
             why="Dad's own day, in full, and nobody else's"),
    Exchange(said="what's on tomorrow", tool="get_schedule",
             args={"start": "@tomorrow", "end": "@tomorrow"},
             must_not_say=("nothing on", "2026-", "today")),
    Exchange(said="what is Anaya doing on Thursday", tool="get_schedule",
             args={"about": "Anaya", "start": "@thu", "end": "@thu"},
             must_say=("piano",),
             must_not_say=("nothing on", "2026-", "performance review"),
             why="#9 from the other side: a parent asking about a child gets the child's day"),
    Exchange(
        # Her day holds the children's school because she drives them. With the names left off that
        # line it read "Mom has school from 8 AM to 3 PM", which is not true of anybody.
        said="when does Mom finish work on Friday",
        tool="get_schedule",
        args={"about": "Mom"},
        must_say=("2:30 PM",),
        must_not_say=("nothing on", "2026-", "she has school", "Mom has school"),
        why="the finishing time is the question; the school run is hers to drive, not to attend",
    ),
    Exchange(said="who is in the family", tool="get_family", args={},
             must_say=("Grandpa",),
             must_not_say=("2026-", "nothing")),
    Exchange(
        # Either route answers it: what_if reasons about the ripple, get_schedule says Friday at six
        # is free. Both are true answers, so both pass; the day must be Friday, not today.
        said="can I say yes to a six o'clock meeting on Friday",
        tool=("what_if", "get_schedule"),
        args={},
        must_not_say=("today",),
    ),
    Exchange(said="what if football is cancelled", tool="what_if", args={},
             must_say=("Nothing new breaks",),
             must_not_say=("Done", "Shall I", "2026-"),
             why="#5 is read-only: a hypothetical must never sound like it did something"),
    Exchange(said="is anything broken on Thursday", tool="detect_conflicts", args={},
             must_say=("football practice pickup", "9 PM"),
             must_not_say=("On today", "2026-", "Nothing is broken"),
             why="#1: the unreachable pickup and the rule breach, and never 'On today'"),
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
#: A refusal is an answer, so it is asserted like one. Routing alone scored "order milk" as correct
#: while it recited the whole diary at somebody asking for milk: `cannot_help` was what it *should*
#: have chosen, and the verdict only ever looked at the name of the tool.
DECLINED = ("cannot do that one yet",)
#: What declining must never do: answer from the family's data anyway.
IMPROVISED = ("school", "football", "piano", "Shall I", "2026-")

OUT_OF_SCOPE = (
    Exchange(said="book me a flight to Goa", tool="cannot_help", args={},
             must_say=DECLINED, must_not_say=IMPROVISED),
    Exchange(said="what is the weather tomorrow", tool="cannot_help", args={},
             must_say=DECLINED, must_not_say=IMPROVISED),
    Exchange(said="order milk", tool="cannot_help", args={},
             must_say=DECLINED, must_not_say=IMPROVISED,
             why="declined in code: a sixteenth schema sent this to cancel_event"),
    Exchange(said="how much did we spend on football this month", tool="cannot_help", args={},
             must_say=DECLINED,
             must_not_say=("Shall I", "2026-", "piano", "school"),
             why="LifePilot stores no amounts, so there is nothing to answer from"),
)

#: Putting something in the calendar. A tester asked how data would ever be added; these are the
#: words that add it. The line between "would this work" and "do it" is the thing being tested: the
#: first must never write, and the second must never write without a yes.
#: Cancelling, the half of the write path that was missing. Order matters: the whole run shares one
#: database, and `WRITES` books a meeting over Dad's Thursday review, which replaces it. Run after
#: that, the repair case below has no review left to cancel. Each exchange asserts the **answer**,
#: not just the routing (Lesson 2).
CANCELS = (
    Exchange(
        said="cancel Aarav's football practice on Thursday",
        tool="cancel_event",
        args={},
        must_say=("football practice", "Shall I cancel"),
        must_not_say=("2026-", "Done", "could not"),
        why="a planner that only adds is not a planner",
    ),
    Exchange(
        said="no, leave it",
        tool="reject_proposal",
        args={},
        follows_on=True,
        must_say=("left everything as it was",),
        must_not_say=("Done", "Shall I"),
        why="a cancellation is held for a yes like every other change",
    ),
    Exchange(
        said="cancel Anaya's piano class",
        tool="cancel_event",
        args={},
        must_say=("cannot move",),
        must_not_say=("Done", "Shall I cancel it?"),
        why="cancelling what a family rule pins is a stronger act than moving it",
    ),
    Exchange(
        said="cancel piano class anyway",
        tool="cancel_event",
        args={},
        follows_on=True,
        must_say=("Shall I cancel",),
        must_not_say=("Done",),
        why="a parent who says it in so many words is still the authority",
    ),
    Exchange(
        said="no, leave it",
        tool="reject_proposal",
        args={},
        follows_on=True,
        must_say=("left everything as it was",),
        must_not_say=("Done", "Shall I"),
    ),
    Exchange(
        # The differentiator. Dad's review is what makes Thursday's football pickup unreachable, so
        # cancelling it does not just delete something -- it repairs the week, and says so.
        said="cancel my performance review on Thursday",
        tool="cancel_event",
        args={},
        must_say=("fixes football practice pickup",),
        must_not_say=("2026-", "could not"),
        why="#1 and #4: a cancellation can repair the week, and saying so is the point",
    ),
    Exchange(
        said="yes",
        tool="approve_proposal",
        args={},
        follows_on=True,
        must_say=("Done",),
    ),
)


WRITES = (
    Exchange(
        # Reported: answered "you have nothing on today at 4 PM" and booked nothing. True, unasked
        # for, and the meeting still is not in the diary.
        said="schedule my meeting at 4:00 p.m. today with President of Trump",
        tool="add_event",
        args={},
        must_say=("Shall I",),
        must_not_say=("2026-", "nothing on", "cannot do that one"),
        why="an instruction to create was answered as a question about the week",
    ),
    Exchange(
        said="yes",
        tool="approve_proposal",
        args={},
        follows_on=True,
        must_say=("Done",),
    ),
    Exchange(
        said="book a dentist appointment at 10 on Friday",
        tool="add_event",
        # The title is whatever they called it; pinning the exact words would be over-specifying.
        # What must be right is the day, which was once a week out, and that it asks before writing.
        args={},
        must_say=("dentist", "Shall I"),
        must_not_say=("2026-", "could not", "Thursday"),
    ),
    Exchange(
        said="yes",
        tool="approve_proposal",
        args={},
        follows_on=True,
        must_say=("Done",),
        why="the proposal from the line before is what yes refers to",
    ),
    Exchange(
        said="add swimming for Aarav on Monday at 6 PM",
        tool="add_event",
        args={"title": "swimming"},
        must_say=("swimming",),
        must_not_say=("2026-", "could not"),
    ),
    Exchange(
        # Reported: both of these were answered "you have nothing on at 3 PM" and booked nothing.
        # The verb was there; it was not at the head of the sentence, because the time was.
        said="at 3:00 p.m. schedule a meeting",
        tool="add_event",
        args={},
        must_say=("Shall I",),
        must_not_say=("nothing on", "2026-"),
        why="people put the time before the verb as often as after it",
    ),
    Exchange(
        said="no, leave it",
        tool="reject_proposal",
        args={},
        follows_on=True,
        must_say=("left everything as it was",),
        must_not_say=("Done", "Shall I"),
    ),
    Exchange(
        said="for tomorrow schedule the meeting at 3:00 p.m.",
        tool="add_event",
        args={},
        must_say=("Shall I",),
        must_not_say=("nothing on", "2026-"),
        why="a day phrase in front of the verb is still an instruction",
    ),
    Exchange(
        said="no, leave it",
        tool="reject_proposal",
        args={},
        follows_on=True,
        must_say=("left everything as it was",),
        must_not_say=("Done", "Shall I"),
    ),
    Exchange(
        # The third refusal in a row: the line before it already rejected the only pending proposal,
        # so there is nothing left to reject. Saying so is the answer; reciting the week is not.
        said="no, leave it",
        tool="nothing_pending",
        args={},
        follows_on=True,
        must_say=("nothing waiting",),
        must_not_say=("Done", "You have"),
        why="a decision with nothing pending is not a question about the schedule",
    ),
    Exchange(
        # The distinction that matters: asking whether a time works must not book anything.
        said="would a dentist appointment at 10 on Friday work",
        tool=("what_if", "get_schedule"),
        args={},
        must_not_say=("Shall I put it in", "Done"),
        why="a question about feasibility is not an instruction to write",
    ),
)

#: #6, the partner swap. Two people, two sessions, one plan: the asker cannot settle their own
#: request, and the answer only lands when the other parent agrees in their own session.
SWAP = (
    Exchange(
        said="ask Mom to take Thursday, I will take Tuesday",
        tool="request_swap",
        args={"partner": "Mom"},
        must_say=("Mom",),
        must_not_say=("Done", "2026-"),
        why="#6: both legs checked, then it waits on the other parent",
    ),
    Exchange(
        said="yes",
        speaker="Dad",
        follows_on=True,
        tool="nothing_pending",
        args={},
        must_say=("Mom's to answer",),
        must_not_say=("Done",),
        why="#6: the asker cannot approve their own swap -- it is held against Mom",
    ),
    Exchange(
        # Mom's first turn is the question, not the answer: she asks what she is being asked before
        # she agrees to it. Settled in code, so it costs no model call and mints no new proposal.
        said="anything waiting for me",
        speaker="Mom",
        follows_on=True,
        tool="list_proposals",
        args={},
        must_say=("Dad asked you to take",),
        must_not_say=("changes", "Done"),
        why="#6: the parent being asked can hear the request before she decides",
    ),
    Exchange(
        said="yes",
        speaker="Mom",
        follows_on=True,
        tool="approve_proposal",
        args={},
        must_say=("Done",),
        why="#6: she accepts in her own session and the plan changes",
    ),
)


#: #5 support: "what am I forgetting" is about deadlines with no time set aside, not about the
#: diary. The seeded family has a block booked for its one task, so the honest answer is that
#: nothing is at risk -- which is the answer that proves the scan notices its own repair.
RISK = (
    Exchange(
        said="what am I forgetting",
        tool="scan_risks",
        args={},
        must_say=("Nothing is at risk",),
        must_not_say=("2026-", "problems this week"),
        why="#5: a question about deadlines, not about clashes in the diary",
    ),
    Exchange(
        said="is anything going to slip",
        tool="scan_risks",
        args={},
        must_not_say=("2026-",),
        why="#5: the same question in other words",
    ),
)


ALL: tuple[Exchange, ...] = (
    FROM_TESTING + HEADLINE + EVERYDAY + ROLES + OUT_OF_SCOPE + CANCELS + WRITES + SWAP + RISK
)


def by_name(name: str) -> tuple[Exchange, ...]:
    groups = {
        "testing": FROM_TESTING,
        "headline": HEADLINE,
        "everyday": EVERYDAY,
        "roles": ROLES,
        "scope": OUT_OF_SCOPE,
        "writes": WRITES,
        "swap": SWAP,
        "risk": RISK,
        "cancels": CANCELS,
        "all": ALL,
    }
    return groups[name]
