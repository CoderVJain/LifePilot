"""The simulator's router. Offline and free: a fake MCP client, no server, no model."""

import json

import pytest

from simulator.conversation import HELP, respond


class FakeMCP:
    """Records what was asked for and replays canned tool results."""

    def __init__(self, results: dict):
        self.results = results
        self.calls: list[tuple[str, dict]] = []

    def call_tool_sync(self, _id: str, name: str, arguments: dict) -> dict:
        self.calls.append((name, arguments))
        if name not in self.results:
            return {"status": "error", "content": [{"text": "no such tool"}]}
        return {"status": "success", "content": [{"text": json.dumps(self.results[name])}]}


FAMILY = {
    "speaker": {"name": "Dad", "role": "parent"},
    "members": [
        {"id": 1, "name": "Dad", "role": "parent", "can_drive": True, "is_you": True},
        {"id": 2, "name": "Mom", "role": "parent", "can_drive": True, "is_you": False},
        {"id": 3, "name": "Aarav", "role": "child", "can_drive": False, "is_you": False},
    ],
    "locations": ["home", "school"],
}

SCHEDULE = {
    "speaker": {"name": "Aarav", "role": "child"},
    "from": "2026-10-05",
    "to": "2026-10-09",
    "events": [
        {"id": 1, "title": "football practice", "start": "2026-10-08T16:00", "redacted": False},
        {"id": 2, "title": "Busy", "start": "2026-10-08T09:30", "redacted": True},
        {"id": 3, "title": "Busy", "start": "2026-10-08T15:45", "redacted": True},
    ],
    "tasks": [],
}


def test_unknown_phrase_offers_help_without_calling_a_tool():
    mcp = FakeMCP({})
    turn = respond(mcp, "Dad", "make me a sandwich")
    assert turn.speak == HELP
    assert mcp.calls == []
    assert turn.debug["tool"] is None


@pytest.mark.parametrize("utterance", ["who is in the family?", "family", "list the members"])
def test_family_phrases_reach_get_family(utterance):
    mcp = FakeMCP({"get_family": FAMILY})
    turn = respond(mcp, "Dad", utterance)
    assert mcp.calls == [("get_family", {"speaker": "Dad"})]
    assert "Mom (parent)" in turn.speak
    assert "Dad" not in turn.speak.split("others are")[1]  # you are not listed among the others
    assert turn.cards[0]["kind"] == "family"


@pytest.mark.parametrize("utterance", ["what's happening this week?", "show my schedule", "thursday"])
def test_schedule_phrases_reach_get_schedule(utterance):
    mcp = FakeMCP({"get_schedule": SCHEDULE})
    turn = respond(mcp, "Aarav", utterance)
    name, arguments = mcp.calls[0]
    assert name == "get_schedule"
    assert arguments["speaker"] == "Aarav"
    assert turn.cards[0]["kind"] == "schedule"


def test_naming_a_day_asks_about_that_day_not_the_whole_week():
    """"What's on Thursday" answered with the entire week is not an answer to the question."""
    mcp = FakeMCP({"get_schedule": SCHEDULE})
    respond(mcp, "Aarav", "what's on thursday")
    _, arguments = mcp.calls[0]
    assert arguments["start"] == arguments["end"] == "2026-10-08"


def test_asking_about_your_own_day_asks_for_only_yours():
    """The complaint that prompted this: Dad asking for his schedule got all nineteen family
    events."""
    mcp = FakeMCP({"get_schedule": SCHEDULE})
    respond(mcp, "Dad", "what is my schedule for thursday")
    assert mcp.calls[0][1]["about"] == "Dad"

    mcp = FakeMCP({"get_schedule": SCHEDULE})
    respond(mcp, "Dad", "what is happening this week")
    assert mcp.calls[0][1]["about"] is None

    mcp = FakeMCP({"get_schedule": SCHEDULE})
    respond(mcp, "Dad", "what is aarav's school timing on thursday")
    assert mcp.calls[0][1]["about"] == "Aarav", "asked about Aarav, so answer about Aarav"


def test_nothing_spoken_contains_a_timestamp():
    """These are read aloud. "2026-10-08" is not something anyone says."""
    mcp = FakeMCP({"get_schedule": SCHEDULE})
    spoken = respond(mcp, "Aarav", "what's happening this week").speak
    assert "2026" not in spoken


def test_redacted_events_are_counted_separately_in_speech():
    """A child hears how much is hidden, never what it is."""
    mcp = FakeMCP({"get_schedule": SCHEDULE})
    turn = respond(mcp, "Aarav", "what's happening this week?")
    assert "1 thing" in turn.speak and "1 things" not in turn.speak
    assert "2 more where someone else is busy" in turn.speak


def test_a_failed_tool_call_is_reported_not_swallowed():
    mcp = FakeMCP({})
    turn = respond(mcp, "Dad", "who is in the family?")
    assert "could not reach" in turn.speak
    assert turn.debug["status"] == "error"


def test_debug_record_carries_the_cost_counters():
    """The drawer shows these from the first turn, so the cost discipline is visible."""
    mcp = FakeMCP({"get_family": FAMILY})
    turn = respond(mcp, "Dad", "family")
    assert turn.debug["model_calls"] == 0
    assert turn.debug["estimated_cost_usd"] == 0.0
    assert turn.debug["tool_ms"] >= 0


# --------------------------------------------------------------------------- saying the answer


DAY = {
    "speaker": {"name": "Dad", "role": "parent"},
    "from": "2026-10-02",
    "to": "2026-10-02",
    "about": None,
    "events": [
        {"title": "school", "start": "2026-10-02T08:00", "end": "2026-10-02T15:00",
         "members": ["Aarav", "Anaya"], "redacted": False},
        {"title": "work", "start": "2026-10-02T09:30", "end": "2026-10-02T16:30",
         "members": ["Dad"], "redacted": False},
    ],
    "tasks": [],
}


def test_a_single_day_is_named_not_counted():
    """"There are 3 things on tomorrow" answers how many, which was never the question."""
    mcp = FakeMCP({"get_schedule": DAY})
    spoken = respond(mcp, "Dad", "what is happening tomorrow").speak

    assert "school" in spoken
    assert "work" in spoken
    assert spoken != "There are 2 things on tomorrow."


def test_school_timings_include_when_it_ends():
    """Asked for the school timing, "8 AM" does not say when to collect anyone."""
    mcp = FakeMCP({"get_schedule": DAY})
    spoken = respond(mcp, "Dad", "what is the school timing tomorrow").speak

    assert "8 am to 3 pm" in spoken.lower()


def test_who_an_event_belongs_to_is_said_when_it_is_not_your_own_day():
    mcp = FakeMCP({"get_schedule": DAY})
    spoken = respond(mcp, "Dad", "what is happening tomorrow").speak
    assert "Aarav and Anaya have school" in spoken


def test_your_own_day_does_not_repeat_your_name_on_every_line():
    mine = {**DAY, "about": "Dad", "events": [DAY["events"][1]]}
    mcp = FakeMCP({"get_schedule": mine})
    spoken = respond(mcp, "Dad", "what is my schedule tomorrow").speak

    assert spoken.startswith("You have 1 thing")
    assert "Dad have" not in spoken


def test_one_person_has_and_two_people_have():
    """Said aloud, "Mom have work" is the kind of thing that makes a product sound unfinished."""
    mcp = FakeMCP({"get_schedule": DAY})
    spoken = respond(mcp, "Dad", "what is happening tomorrow").speak

    assert "Aarav and Anaya have school" in spoken
    assert "Dad has work" in spoken
    assert "have work" not in spoken
