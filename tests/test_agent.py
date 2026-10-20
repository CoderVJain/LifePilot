"""The Bedrock path's non-model parts. Offline and free: no Bedrock call here.

What the model is allowed to influence, and what it is not, is the whole point of these.
"""

from datetime import date

import pytest

from simulator.agent import _event_fact, _facts, _money_is_declined, _safe_arguments, answer
from simulator.conversation import Turn

SCHEDULE = {
    "speaker": {"name": "Dad", "role": "parent"},
    "from": "2026-10-05",
    "to": "2026-10-09",
    "events": [
        {
            "title": "work",
            "start": "2026-10-05T09:00",
            "location": "mom office",
            "members": ["Mom"],
            "needs_transport": False,
            "redacted": False,
        },
        {
            "title": "football practice",
            "start": "2026-10-08T16:00",
            "location": "football ground",
            "members": ["Aarav"],
            "needs_transport": True,
            "redacted": False,
        },
        {"title": "Busy", "start": "2026-10-08T15:45", "redacted": True},
    ],
    "tasks": [],
}

FAMILY = {
    "speaker": {"name": "Dad", "role": "parent"},
    "members": [
        {"name": "Dad", "role": "parent", "can_drive": True, "is_you": True},
        {"name": "Mom", "role": "parent", "can_drive": True, "is_you": False},
        {"name": "Aarav", "role": "child", "can_drive": False, "is_you": False},
    ],
    "locations": ["home"],
}


def test_every_event_fact_names_whose_it_is():
    """Without the owner, a summary attaches every event to whoever asked. That happened."""
    one_day = {**SCHEDULE, "from": "2026-10-08", "to": "2026-10-08"}
    facts = _facts("get_schedule", one_day, "Dad")
    assert any(f.startswith("Mom: work") for f in facts)
    assert any(f.startswith("Aarav: football practice") for f in facts)


def test_a_whole_week_is_summarised_rather_than_recited():
    """Nineteen events read aloud is a recital, and it ran past the token limit mid-sentence.
    A week gets its shape plus the parts that need a person to drive."""
    facts = _facts("get_schedule", SCHEDULE, "Dad")
    joined = " ".join(facts)

    assert any(f.startswith("Aarav: football practice") for f in facts), "lifts still get named"
    assert not any(f.startswith("Mom: work") for f in facts), "routine work is not recited"
    assert "the usual work and school" in joined


def test_a_single_day_is_given_in_full_and_spoken_not_formatted():
    one_day = {**SCHEDULE, "from": "2026-10-08", "to": "2026-10-08"}
    facts = _facts("get_schedule", one_day, "Dad")
    joined = " ".join(facts)
    assert "9 AM" in joined, "times are said, not printed"
    assert "2026-10-08" not in joined, "no timestamps survive into something spoken aloud"
    assert "T16:00" not in joined


def test_hidden_events_are_counted_but_never_described():
    facts = _facts("get_schedule", SCHEDULE, "Dad")
    joined = " ".join(facts)
    # Singular. This assertion used to pin "1 other blocks", which is the "1 things" fault a tester
    # reported elsewhere, written into a test.
    assert "1 other block of time belong" in joined
    assert "15:45" not in joined
    assert "redacted" not in joined.lower()


def test_transport_need_reaches_the_facts():
    """A tester asked what "needs a lift" meant, so the facts now say who has to be moved."""
    facts = _facts("get_schedule", SCHEDULE, "Dad")
    assert any("someone has to drive" in f or "someone has to collect" in f for f in facts)
    assert not any("needs a lift" in f for f in facts), "our jargon, not a parent's"


def test_family_facts_skip_the_speaker_and_keep_roles():
    facts = _facts("get_family", FAMILY, "Dad")
    assert facts[0] == "You are speaking to Dad."
    assert "Mom is a parent, can drive." in facts
    assert "Aarav is a child." in facts
    assert not any(f.startswith("Dad is a") for f in facts)


def test_model_cannot_choose_the_speaker():
    """The privacy boundary: the session decides who is asking, never the model."""
    assert _safe_arguments("get_schedule", {"speaker": "Dad", "start": "a", "end": "b"}) == {
        "start": "a",
        "end": "b",
    }
    assert _safe_arguments("get_family", {"speaker": "Dad"}) == {}


def test_model_cannot_smuggle_unknown_arguments():
    assert _safe_arguments("get_schedule", {"start": "a", "end": "b", "drop_table": "x"}) == {
        "start": "a",
        "end": "b",
    }


def test_cannot_help_answers_without_calling_a_tool(monkeypatch):
    import simulator.agent as agent_module

    monkeypatch.setattr(
        agent_module, "choose_tool", lambda text, budget, speaker=None: ("cannot_help", {"reason": "booking"})
    )

    def explode(*args, **kwargs):
        raise AssertionError("no tool should be called")

    turn = answer(None, "Dad", "book me a flight", explode)
    assert isinstance(turn, Turn)
    assert "cannot do that one yet" in turn.speak
    assert turn.debug["tool"] is None
    assert turn.debug["note"] == "booking"


def test_the_session_speaker_overrides_whatever_the_model_sent(monkeypatch):
    import simulator.agent as agent_module

    monkeypatch.setattr(
        agent_module,
        "choose_tool",
        lambda text, budget, speaker=None: (
            "get_schedule",
            {"speaker": "Dad", "start": "2026-10-05", "end": "2026-10-09"},
        ),
    )
    monkeypatch.setattr(agent_module, "phrase", lambda text, facts, budget: "ok")

    seen = {}

    def fake_call(mcp, tool, arguments):
        seen.update(arguments)
        return SCHEDULE, {"tool": tool, "status": "success", "tool_ms": 1}

    answer(None, "Aarav", "what's on?", fake_call)
    assert seen["speaker"] == "Aarav"


CONFLICTS = {
    "from": "2026-10-05",
    "to": "2026-10-09",
    "checked": {"events": 19, "lifts_needed": 2, "rules": 5},
    "conflicts": [
        {
            "kind": "unreachable",
            "title": "football practice pickup",
            "when": "2026-10-08T17:00",
            "detail": "Dad is down for this and arrives 5:25 PM, needs 5 PM",
            "could_cover": ["Mom"],
        },
        {
            "kind": "rule_clash",
            "title": "science project block",
            "when": "2026-10-08T20:00",
            "detail": "science project block runs to 9:30 PM, past your rule of 9 PM",
            "could_cover": [],
        },
    ],
}


def test_conflict_facts_are_spoken_not_formatted():
    """These are read aloud. "2026-10-08 at 17:00" is not something a person says."""
    from simulator.agent import _conflict_facts

    facts = _conflict_facts(CONFLICTS)
    joined = " ".join(facts)
    assert "5 PM" in joined
    assert "2026-10-08" not in joined


def test_a_title_is_not_repeated_when_the_detail_already_opens_with_it():
    from simulator.agent import _conflict_facts

    facts = _conflict_facts(CONFLICTS)
    late = next(f for f in facts if "9:30 PM" in f)
    assert late.count("science project block") == 1


def test_every_conflict_reaches_the_facts_with_its_cover_option():
    from simulator.agent import _conflict_facts

    facts = _conflict_facts(CONFLICTS)
    assert facts[0] == "There are 2 problems this week."
    assert "Mom could cover it instead." in facts
    assert any("football practice pickup" in f for f in facts)
    assert any("past your rule of 9 PM" in f for f in facts)


def test_a_clean_week_says_what_was_checked():
    from simulator.agent import _conflict_facts

    facts = _conflict_facts({**CONFLICTS, "conflicts": []})
    assert "Nothing is broken" in facts[0]
    assert "19 events, 2 lifts and 5 family rules" in facts[1]


# --------------------------------------------------------------------------- rule confirmation


def _rule_agent(monkeypatch, route):
    import simulator.agent as agent_module

    monkeypatch.setattr(agent_module, "choose_tool", lambda text, budget, speaker=None: route)
    monkeypatch.setattr(agent_module, "phrase", lambda text, facts, budget: "ok")
    return agent_module


def test_a_rule_is_read_back_and_held_pending(monkeypatch):
    agent_module = _rule_agent(
        monkeypatch,
        ("remember_rule", {"rule_type": "latest_end", "params": {"latest_end": "21:00"}}),
    )
    calls = []

    def fake_call(mcp, tool, arguments):
        calls.append((tool, arguments))
        return (
            {
                "stored": False,
                "needs_confirmation": True,
                "type": "latest_end",
                "params": {"latest_end": "21:00"},
                "readback": "Nothing after 21:00.",
                "say": "Nothing after 21:00. Shall I remember that?",
            },
            {"tool": tool, "status": "success", "tool_ms": 1},
        )

    state = {}
    turn = agent_module.answer(None, "Dad", "no homework after nine", fake_call, state)

    assert calls[0][1]["confirmed"] is False
    assert turn.speak == "Nothing after 21:00. Shall I remember that?"
    assert state["pending_rule"]["Dad"]["type"] == "latest_end"


def test_saying_yes_stores_the_rule_that_was_read_back(monkeypatch):
    agent_module = _rule_agent(monkeypatch, ("cannot_help", {"reason": "should not be reached"}))
    calls = []

    def fake_call(mcp, tool, arguments):
        calls.append((tool, arguments))
        return ({"stored": True, "say": "Remembered. Nothing after 21:00."},
                {"tool": tool, "status": "success", "tool_ms": 1})

    state = {"pending_rule": {"Dad": {"type": "latest_end", "params": {"latest_end": "21:00"},
                                     "spoken_text": "no homework after nine"}}}
    turn = agent_module.answer(None, "Dad", "yes", fake_call, state)

    assert calls[0][0] == "add_rule"
    assert calls[0][1]["confirmed"] is True
    assert calls[0][1]["params"] == {"latest_end": "21:00"}
    assert calls[0][1]["spoken_text"] == "no homework after nine"
    assert "Remembered" in turn.speak
    assert state["pending_rule"] == {}


def test_saying_no_drops_it_without_calling_anything(monkeypatch):
    agent_module = _rule_agent(monkeypatch, ("cannot_help", {"reason": "x"}))

    def explode(*args, **kwargs):
        raise AssertionError("nothing should be stored")

    state = {"pending_rule": {"Dad": {"type": "latest_end", "params": {}, "spoken_text": "x"}}}
    turn = agent_module.answer(None, "Dad", "no", explode, state)

    assert "won't remember" in turn.speak
    assert state["pending_rule"] == {}


def test_another_speaker_cannot_confirm_a_rule_they_never_heard(monkeypatch):
    """Dad's half-agreed rule must not be finished by whoever speaks next."""
    agent_module = _rule_agent(monkeypatch, ("cannot_help", {"reason": "x"}))

    def fake_call(mcp, tool, arguments):
        return ({}, {"tool": tool, "status": "success", "tool_ms": 1})

    state = {"pending_rule": {"Dad": {"type": "latest_end", "params": {}, "spoken_text": "x"}}}
    agent_module.answer(None, "Mom", "yes", fake_call, state)

    assert "Dad" in state["pending_rule"]


def test_a_refused_rule_type_is_spoken_and_nothing_is_held(monkeypatch):
    agent_module = _rule_agent(
        monkeypatch, ("remember_rule", {"rule_type": "no_screens", "params": {}})
    )

    def fake_call(mcp, tool, arguments):
        return (
            {"stored": False, "needs_confirmation": False,
             "problem": "'no_screens' is not a rule LifePilot can enforce.",
             "say": "'no_screens' is not a rule LifePilot can enforce."},
            {"tool": tool, "status": "success", "tool_ms": 1},
        )

    state = {}
    turn = agent_module.answer(None, "Dad", "no screens at dinner", fake_call, state)

    assert "not a rule LifePilot can enforce" in turn.speak
    assert state.get("pending_rule", {}) == {}


# --------------------------------------------------------------------------- approving a fix


PROPOSAL = {
    "needed": True,
    "solved": True,
    "proposal_id": 7,
    "change_count": 2,
    "changes": [{"kind": "assign", "title": "football practice pickup", "was": "Dad", "now": "Mom",
                 "reason": "Dad cannot get there in time", "event_id": 12, "person_id": 2}],
    "say": "2 changes: Mom takes football practice pickup. Shall I make them?",
}


def test_a_fix_is_offered_and_held_for_a_yes(monkeypatch):
    agent_module = _rule_agent(monkeypatch, ("fix_week", {}))
    calls = []

    def fake_call(mcp, tool, arguments):
        calls.append((tool, arguments))
        return PROPOSAL, {"tool": tool, "status": "success", "tool_ms": 1}

    state = {}
    turn = agent_module.answer(None, "Dad", "fix our week", fake_call, state)

    assert calls[0][0] == "fix_week"
    assert turn.speak == PROPOSAL["say"], "the server's diff is spoken as written, not reworded"
    assert state["pending_proposal"]["Dad"] == 7
    assert turn.cards[0]["kind"] == "proposal"


def test_saying_yes_approves_the_proposal_that_was_offered(monkeypatch):
    agent_module = _rule_agent(monkeypatch, ("cannot_help", {"reason": "unused"}))
    calls = []

    def fake_call(mcp, tool, arguments):
        calls.append((tool, arguments))
        return {"approved": True, "say": "Done. Mom has football practice."}, {
            "tool": tool, "status": "success", "tool_ms": 1
        }

    state = {"pending_proposal": {"Dad": 7}}
    turn = agent_module.answer(None, "Dad", "yes please", fake_call, state)

    assert calls[0] == ("approve_proposal", {"speaker": "Dad", "proposal_id": 7})
    assert "Done." in turn.speak
    assert state["pending_proposal"] == {}


def test_saying_no_rejects_it(monkeypatch):
    agent_module = _rule_agent(monkeypatch, ("cannot_help", {"reason": "unused"}))
    calls = []

    def fake_call(mcp, tool, arguments):
        calls.append((tool, arguments))
        return {"rejected": True, "say": "Alright, I have left everything as it was."}, {
            "tool": tool, "status": "success", "tool_ms": 1
        }

    agent_module.answer(None, "Dad", "no thanks", fake_call, {"pending_proposal": {"Dad": 7}})
    assert calls[0][0] == "reject_proposal"


def test_a_different_speaker_cannot_approve_what_they_did_not_hear(monkeypatch):
    agent_module = _rule_agent(monkeypatch, ("cannot_help", {"reason": "unused"}))

    def fake_call(mcp, tool, arguments):
        return {}, {"tool": tool, "status": "success", "tool_ms": 1}

    state = {"pending_proposal": {"Dad": 7}}
    agent_module.answer(None, "Aarav", "yes", fake_call, state)
    assert state["pending_proposal"] == {"Dad": 7}


def test_anything_other_than_yes_or_no_is_a_new_request(monkeypatch):
    """"What's on Thursday" while a fix is pending must not count as agreement."""
    agent_module = _rule_agent(monkeypatch, ("get_schedule", {"start": "2026-10-05", "end": "2026-10-09"}))
    calls = []

    def fake_call(mcp, tool, arguments):
        calls.append(tool)
        return SCHEDULE, {"tool": tool, "status": "success", "tool_ms": 1}

    state = {"pending_proposal": {"Dad": 7}}
    agent_module.answer(None, "Dad", "what is on thursday", fake_call, state)

    assert "approve_proposal" not in calls
    assert state["pending_proposal"] == {"Dad": 7}


def test_a_conditional_yes_is_not_a_yes(monkeypatch):
    """"Yes, but move it to Friday" is a new request. Treating it as approval would execute a diff
    the parent was in the middle of amending."""
    from simulator.agent import _decision

    assert _decision("yes") == "yes"
    assert _decision("yes please") == "yes"
    assert _decision("no thanks") == "no"
    assert _decision("yes but move it to friday") is None
    assert _decision("maybe") is None


def test_a_window_with_no_data_says_which_week_is_loaded():
    """"What's on tomorrow" against a demo week that does not include tomorrow answered "you have 0
    things on", which reads as an empty diary rather than a gap in the data."""
    from simulator.agent import _facts
    from simulator.conversation import WEEK_START

    empty = {"from": "2026-10-01", "to": "2026-10-01", "events": [], "tasks": []}
    facts = _facts("get_schedule", empty, "Dad")
    joined = " ".join(facts)

    assert "nothing at all" in joined
    assert "week that is loaded" in joined
    assert "0 things" not in joined
    assert WEEK_START.isoformat() not in joined, "spoken aloud, so no timestamps"


def test_the_summary_line_reads_naturally_for_one_day_and_one_thing():
    """Spoken aloud, so "1 things between October 8 and October 8" will not do."""
    from simulator.agent import _facts

    one = {
        "from": "2026-10-08",
        "to": "2026-10-08",
        "events": [{"title": "school", "start": "2026-10-08T08:00", "members": ["Aarav"],
                    "redacted": False}],
        "tasks": [],
    }
    assert _facts("get_schedule", one, "Dad")[0].startswith("Dad can see 1 thing ")

    week = {**one, "to": "2026-10-09", "events": one["events"] * 2}
    assert _facts("get_schedule", week, "Dad")[0].startswith("Dad can see 2 things ")

    mine = {**one, "about": "Dad"}
    assert _facts("get_schedule", mine, "Dad")[0].startswith("You have 1 thing ")


def test_the_route_prompt_tells_the_model_the_date_and_who_is_speaking():
    """Without today's date the model answered "tomorrow" with today; without the speaker's name it
    could not work out whose day "my schedule" meant."""
    from lifepilot_shared.clock import today
    from simulator.agent import route_system

    text = route_system("Mom")[0]["text"]
    assert "Mom is the person speaking" in text
    assert today().isoformat() in text
    assert "Tomorrow is" in text


def test_the_route_cache_is_keyed_by_speaker_and_day():
    """"My schedule" is a different question depending on who asks and when, so one cached answer
    must not serve both."""
    from simulator.agent import _route_cache, choose_tool

    _route_cache.clear()
    calls = []

    class Counting:
        max_calls = 9
        calls = 0
        cache_hits = input_tokens = output_tokens = 0

        def spend(self):
            Counting.calls += 1

        def record(self, usage):
            pass

    import simulator.agent as agent_module

    def fake_converse(**kwargs):
        calls.append(kwargs["system"][0]["text"])
        return {
            "output": {
                "message": {
                    "content": [{"toolUse": {"name": "get_family", "input": {}}}]
                }
            }
        }

    original = agent_module.converse
    agent_module.converse = fake_converse
    try:
        choose_tool("what is my schedule", Counting(), "Dad")
        choose_tool("what is my schedule", Counting(), "Mom")
        choose_tool("what is my schedule", Counting(), "Dad")
    finally:
        agent_module.converse = original

    assert len(calls) == 2, "Dad and Mom need separate answers; Dad's repeat comes from the cache"
    assert "Dad is the person speaking" in calls[0]
    assert "Mom is the person speaking" in calls[1]


# --------------------------------------------------------------------------- model output, typed


def test_a_timestamp_where_a_day_was_wanted_is_trimmed():
    """Reported from testing: get_schedule rejected ['start', 'end'] because the model answered a
    question about a time with a full timestamp, and the person was told "I could not reach that"."""
    from simulator.agent import _safe_arguments

    clean = _safe_arguments(
        "get_schedule", {"start": "2026-10-01T16:00", "end": "2026-10-01T16:00", "about": "Dad"}
    )
    assert clean == {"start": "2026-10-01", "end": "2026-10-01", "about": "Dad"}


def test_placeholder_junk_in_optional_fields_is_dropped():
    """Also reported: what_if arrived with at='&#xA;', until='&#xA;', end='&#xA;' -- the model's way
    of saying it had nothing to put there."""
    from simulator.agent import _safe_arguments

    clean = _safe_arguments(
        "what_if",
        {"kind": "new_event", "start": "2026-10-01T16:00", "at": "&#xA;", "until": "&#xA;",
         "end": "&#xA;", "title": "work"},
    )
    assert clean == {"kind": "new_event", "start": "2026-10-01T16:00", "title": "work"}


def test_a_hypothetical_keeps_its_time_of_day():
    """Trimming what_if's timestamps would throw away the entire question."""
    from simulator.agent import _safe_arguments

    clean = _safe_arguments("what_if", {"kind": "runs_late", "at": "2026-10-01T15:45",
                                        "until": "17:30"})
    assert clean["at"] == "2026-10-01T15:45"
    assert clean["until"] == "17:30"


def test_empty_and_whitespace_values_never_reach_a_tool():
    from simulator.agent import _safe_arguments

    assert _safe_arguments("explain_choice", {"person": "Grandpa", "title": "   "}) == {
        "person": "Grandpa"
    }
    assert _safe_arguments("get_schedule", {"about": "null", "start": "2026-10-01"}) == {
        "start": "2026-10-01"
    }


# --------------------------------------------------------------------------- saying it plainly


def test_a_lift_names_who_has_to_be_moved():
    """"Needs a lift" is our word. A tester asked what it meant."""
    from lifepilot_shared.speech import say_lift

    assert say_lift(["Aarav"]) == "someone has to drive Aarav"
    assert say_lift(["Aarav"], collecting=True) == "someone has to collect Aarav"
    assert say_lift(["Aarav", "Anaya"]) == "someone has to drive Aarav and Anaya"
    assert say_lift([]) == "someone has to drive somebody"


def test_a_moment_answer_names_the_child_not_them():
    """Reported verbatim: "Football practice finishes exactly then, so somebody has to collect them."""
    data = {
        "from": "2026-10-08", "to": "2026-10-08", "about": "Dad", "at": "2026-10-08T17:00",
        "title": None,
        "at_that_time": {
            "free": True, "running": [], "starting": [],
            "finishing": [{
                "title": "football practice", "start": "2026-10-08T16:00",
                "end": "2026-10-08T17:00", "needs_transport": True, "members": ["Aarav"],
            }],
        },
        "events": [], "tasks": [],
    }
    spoken = " ".join(_facts("get_schedule", data, "Dad"))
    assert "collect Aarav" in spoken
    assert "them" not in spoken.split()


def test_the_privacy_note_comes_after_the_answer():
    """Aarav asking about football heard "12 other blocks of time belong to other people" first,
    which reads as a refusal to a question nobody asked."""
    data = {
        "from": "2026-10-08", "to": "2026-10-08", "about": None, "at": None, "title": None,
        "at_that_time": None,
        "events": [
            {"title": "football practice", "start": "2026-10-08T16:00", "end": "2026-10-08T17:00",
             "needs_transport": True, "members": ["Aarav"], "redacted": False, "location": None},
            {"title": "Busy", "start": "2026-10-08T09:00", "end": "2026-10-08T17:00",
             "needs_transport": False, "members": [], "redacted": True, "location": None},
        ],
        "tasks": [],
    }
    facts = _facts("get_schedule", data, "Aarav")
    note = next(i for i, f in enumerate(facts) if "belong to other people" in f)
    answer = next(i for i, f in enumerate(facts) if "football" in f)
    assert answer < note, "the answer must come before the caveat"
    assert note == len(facts) - 1


def test_a_named_event_answer_has_no_household_preamble():
    data = {
        "from": "2026-10-05", "to": "2026-10-09", "about": None, "at": None, "title": "piano",
        "at_that_time": None,
        "events": [{
            "title": "piano class", "start": "2026-10-08T16:00", "end": "2026-10-08T16:45",
            "location": "piano school", "needs_transport": True, "members": ["Anaya"],
            "redacted": False,
        }],
        "tasks": [],
    }
    facts = _facts("get_schedule", data, "Mom")
    assert facts[0].startswith("Anaya's piano class is")
    assert "4 PM to 4:45 PM" in facts[0]
    assert not any("things" in f for f in facts), "no 19-event recital"
    assert "collect Anaya" in facts[1], "and not 'anaya'"


# --------------------------------------------------------------------------- deciding, in code


def test_a_decision_can_be_said_twice_over():
    """"No, leave it" is one refusal said twice, and whole-string matching heard neither word."""
    from simulator.agent import _decision

    assert _decision("no, leave it") == "no"
    assert _decision("yes, do it") == "yes"
    assert _decision("yes please") == "yes"
    assert _decision("no thanks") == "no"
    assert _decision("cancel") == "no"


def test_a_question_that_merely_starts_with_no_is_still_a_question():
    """The guard that keeps the above from swallowing real requests."""
    from simulator.agent import _decision

    assert _decision("no problems this week") is None
    assert _decision("any problems this week") is None
    assert _decision("what is on Friday") is None


def test_settling_a_proposal_records_which_tool_it_used():
    """It skips the router, so nothing else records it; the drawer and the eval both reported the
    tool from the previous turn instead."""
    from simulator.agent import _settle_proposal

    state = {"pending_proposal": {"Dad": 7}}
    calls = []

    def call_tool(mcp, tool, arguments):
        calls.append(tool)
        return {"say": "Done."}, {"tool": tool}

    class Budget:
        calls = cache_hits = input_tokens = output_tokens = 0
        cost_usd = 0.0

    _settle_proposal(None, "Dad", "yes", call_tool, state, 7, Budget(), 0.0)

    assert calls == ["approve_proposal"]
    assert state["routed"] == "approve_proposal"


def test_a_hypothetical_is_never_answered_by_listing_the_thing():
    """"What if football is cancelled" answered with football's timing is a true sentence that says
    nothing about what happens if it goes away."""
    from simulator.agent import _hypothetical_wins

    assert _hypothetical_wins("get_schedule", {"title": "football"},
                              "what if football is cancelled") == (
        "what_if", {"kind": "cancelled", "title": "football"}
    )
    assert _hypothetical_wins("get_schedule", {}, "what if my four o'clock runs late")[0] == "what_if"


def test_a_plain_question_about_a_named_event_is_left_alone():
    from simulator.agent import _hypothetical_wins

    assert _hypothetical_wins("get_schedule", {"title": "football"},
                              "what is the football timing")[0] == "get_schedule"
    # No kind can be read out of this, and a confident refusal is worse than a partial answer.
    assert _hypothetical_wins("get_schedule", {}, "what if the weather is bad")[0] == "get_schedule"


def test_a_new_event_lands_on_the_day_that_was_named():
    """Reported from the eval: "at 10 on Friday" was written as next Thursday. Writing into a
    family's calendar on the wrong day is worse than refusing."""
    from simulator.agent import _correct_the_day

    fixed = _correct_the_day(
        {"title": "dentist", "start": "2026-10-15T10:00", "end": "2026-10-15T11:00"},
        "book a dentist appointment at 10 on Friday",
    )
    assert fixed["start"] == "2026-10-09T10:00"
    assert fixed["end"] == "2026-10-09T11:00"


def test_no_day_named_means_the_model_is_left_to_it():
    from simulator.agent import _correct_the_day

    same = {"title": "x", "start": "2026-10-09T10:00"}
    assert _correct_the_day(same, "book something at 10") == same


def test_a_lift_is_said_as_your_errand_not_as_the_event():
    """Reported: a parent's day listed "school 8 AM to 3 PM", which reads as being there all day. The
    useful fact is the time at the gate."""
    event = {
        "title": "school", "start": "2026-10-08T08:00", "end": "2026-10-08T15:00",
        "location": "school", "needs_transport": True, "members": ["Aarav"],
        "redacted": False, "driving": True, "lift": "pickup",
    }
    said = _event_fact(event, with_day=False, mine_only=True)

    assert said == "You collect Aarav from school at 3 PM (school)."
    assert "8 AM" not in said, "the start is not the parent's problem on a pickup"


def test_a_drop_off_is_said_at_the_start():
    event = {
        "title": "school", "start": "2026-10-08T08:00", "end": "2026-10-08T15:00",
        "location": "school", "needs_transport": True, "members": ["Aarav", "Anaya"],
        "redacted": False, "driving": True, "lift": "drop",
    }
    said = _event_fact(event, with_day=False, mine_only=True)

    assert said == "You drop off Aarav and Anaya at school at 8 AM (school)."


def test_an_event_you_attend_is_still_said_as_an_event():
    event = {
        "title": "work", "start": "2026-10-08T09:00", "end": "2026-10-08T17:00",
        "location": "office", "needs_transport": False, "members": ["Dad"],
        "redacted": False, "driving": False, "lift": None,
    }
    assert _event_fact(event, with_day=False, mine_only=True).startswith("work 9 AM to 5 PM")


def test_a_lift_question_is_answered_with_a_name_and_an_hour():
    """Reported: "at what time do I have to collect Aarav from school" was answered with the whole
    family's day. "Someone has to collect them" answers neither half of the question."""
    data = {
        "from": "2026-10-09", "to": "2026-10-09", "about": None, "at": None, "title": "school",
        "at_that_time": None, "tasks": [],
        "events": [{
            "title": "school", "start": "2026-10-09T08:00", "end": "2026-10-09T15:00",
            "location": "school", "needs_transport": True, "members": ["Aarav", "Anaya"],
            "redacted": False, "driving": False, "lift": None, "lift_by": "Mom",
        }],
    }
    said = " ".join(_facts("get_schedule", data, "Dad"))

    assert "Mom collects Aarav and Anaya" in said
    assert "3 PM" in said
    assert "Someone has to" not in said
    assert "at today at" not in said, "say_when already supplies the preposition"


def test_the_same_question_says_you_when_it_is_your_errand():
    data = {
        "from": "2026-10-06", "to": "2026-10-06", "about": None, "at": None, "title": "school",
        "at_that_time": None, "tasks": [],
        "events": [{
            "title": "school", "start": "2026-10-06T08:00", "end": "2026-10-06T15:00",
            "location": "school", "needs_transport": True, "members": ["Aarav", "Anaya"],
            "redacted": False, "driving": True, "lift": "pickup", "lift_by": "Dad",
        }],
    }
    said = " ".join(_facts("get_schedule", data, "Dad"))
    assert "You collect Aarav and Anaya" in said


def test_a_lift_nobody_is_down_for_says_so():
    data = {
        "from": "2026-10-09", "to": "2026-10-09", "about": None, "at": None, "title": "swimming",
        "at_that_time": None, "tasks": [],
        "events": [{
            "title": "swimming", "start": "2026-10-09T18:00", "end": "2026-10-09T19:00",
            "location": None, "needs_transport": True, "members": ["Aarav"],
            "redacted": False, "driving": False, "lift": None, "lift_by": None,
        }],
    }
    said = " ".join(_facts("get_schedule", data, "Dad"))
    assert "Nobody is down to collect Aarav yet." in said


# --------------------------------------------------------------------------- asking who drives


def test_a_question_about_a_lift_is_about_the_thing_not_the_asker():
    """Reported: "at what time do I have to collect Aarav from school" was answered with Dad's whole
    day, which never mentioned school. The model hears "I" and narrows to the speaker."""
    from simulator.agent import _lift_question, _ways_of_saying

    known = set()
    for name in ("school", "work", "piano class", "football practice", "football ground"):
        known |= _ways_of_saying(name)
    known -= {"dad", "mom", "aarav", "anaya"}

    assert _lift_question({"about": "Dad"}, "at what time do I have to collect Aarav from school",
                          known) == {"title": "school"}
    assert _lift_question({"about": "Dad"}, "who picks up Aarav from football", known) == {
        "title": "football"
    }
    assert _lift_question({"about": "Dad"}, "am I dropping Anaya at piano", known) == {
        "title": "piano"
    }


def test_a_question_with_no_lift_in_it_is_left_alone():
    """The guard. Without it, "do I have any work at 4" becomes a question about work in general."""
    from simulator.agent import _lift_question, _ways_of_saying

    known = _ways_of_saying("work") | _ways_of_saying("school")

    assert _lift_question({"about": "Dad", "at": "16:00"}, "do I have any work at 4 pm", known) == {
        "about": "Dad", "at": "16:00"
    }
    assert _lift_question({"about": "Dad"}, "what is my schedule", known) == {"about": "Dad"}
    assert _lift_question({"about": "Aarav"}, "what is Aarav's school timing tomorrow", known) == {
        "about": "Aarav"
    }


def test_the_shorter_word_people_actually_use_is_indexed():
    """Nobody says "collect him from football practice"; they say "from football"."""
    from simulator.agent import _ways_of_saying

    assert _ways_of_saying("football practice") == {"football practice", "football"}
    assert _ways_of_saying("piano class") == {"piano class", "piano"}
    assert _ways_of_saying("school") == {"school"}
    assert _ways_of_saying("dad office") == {"dad office"}, "office alone names nothing"


def test_the_vocabulary_comes_from_the_family_not_from_the_code():
    """A family with swimming and chess gets the same behaviour with no code change."""
    from simulator.agent import _known_things

    def call_tool(mcp, tool, arguments):
        if tool == "get_schedule":
            return {"events": [
                {"title": "swimming lesson", "location": "leisure centre", "redacted": False},
                {"title": "Busy", "location": None, "redacted": True},
            ]}, {}
        return {"members": [{"name": "Ana"}], "locations": ["leisure centre"]}, {}

    state: dict = {}
    known = _known_things(None, "Ana", call_tool, state)

    assert "swimming" in known
    assert "swimming lesson" in known
    assert "leisure centre" in known
    assert "busy" not in known, "a redacted event must not leak its title into the vocabulary"
    assert "ana" not in known, "a person is not a thing to ask the schedule about"
    assert state["known_things"] is known, "read once per session"


# --------------------------------------------------------------------------- told, not asked


def test_an_instruction_to_book_is_recognised():
    """Reported: "schedule my meeting at 4 PM today" was answered "you have nothing on today at 4
    PM". True, unasked for, and the meeting still was not in the diary."""
    from simulator.agent import _is_booking

    assert _is_booking("schedule my meeting at 4:00 p.m. today with President of Trump")
    assert _is_booking("can you schedule a meeting at 5 pm today")
    assert _is_booking("book a dentist appointment at 10 on Friday")
    assert _is_booking("add swimming for Aarav on Monday at 6 PM")
    assert _is_booking("I want to put a meeting in at 4")


def test_the_time_may_come_before_the_verb():
    """Reported from testing: "at 3:00 p.m. schedule a meeting" was answered "you have nothing on
    today at 3 PM" and booked nothing. People put the time first as often as last, and requiring
    the verb at the head of the sentence read both of these as questions about the diary."""
    from simulator.agent import _is_booking

    assert _is_booking("at 3:00 p.m. schedule a meeting")
    assert _is_booking("for tomorrow schedule the meeting at 3:00 p.m. with President of America")
    assert _is_booking("on Friday set up a call at 11")
    assert _is_booking("tomorrow morning book a dentist at 10")


def test_only_a_time_may_come_before_the_verb():
    """What may precede the verb is when, never who or what. "my", "the" and "a" are deliberately
    absent from the allowed words, because that is the whole of what keeps "what is my schedule" a
    question rather than an instruction."""
    from simulator.agent import _is_booking

    assert not _is_booking("Aarav and Anaya schedule")
    assert not _is_booking("what is the schedule this week")
    assert not _is_booking("tell me the schedule for Friday")


def test_an_intention_wrapped_round_a_question_is_still_a_question():
    """"I want to schedule a meeting at 4, do I have any work at that time?" asks whether four is
    free. Booking it would answer a question nobody asked by changing the diary."""
    from simulator.agent import _is_booking

    assert not _is_booking("I want to schedule a meeting for today at 4 PM, do I have any work at "
                           "that time?")
    assert not _is_booking("I want to schedule a meeting at 5 PM today, do I have anything at that "
                           "time")
    assert not _is_booking("can I say yes to a six o'clock meeting on Friday")


def test_a_question_about_the_week_is_never_a_booking():
    from simulator.agent import _is_booking

    assert not _is_booking("what is my schedule")
    assert not _is_booking("what is my schedule for tomorrow")
    assert not _is_booking("any problems this week")


def test_something_out_of_scope_stays_out_of_scope():
    """"Book me a flight to Goa" is declined by the model, and that judgement stands. Overriding it
    put a midnight-to-midnight "flight to Goa" in the family's week."""
    from simulator.agent import _booking_wins

    tool, arguments = _booking_wins(
        "cannot_help", {"reason": "not about this family"}, "book me a flight to Goa", "Dad", None
    )
    assert tool == "cannot_help", "no model call, no override"
    assert arguments == {"reason": "not about this family"}


# --------------------------------------------------------------------------- school email (#7)

SCHOOL_RESULT = {
    "read": 1,
    "new_tasks": 1,
    "tasks": [{"title": "farmer costume", "child": "Aarav", "due": "2026-10-09"}],
    "proposal_id": 7,
    "status": "pending",
    "change_count": 1,
    "changes": [{"kind": "task", "title": "farmer costume", "was": "not on the list",
                 "now": "due Friday", "reason": "the school asked for it"}],
    "breaks": [{"detail": "nobody can collect Aarav from football"}],
    "say": "One new email from school: Aarav needs a farmer costume by Friday.",
}


def test_the_school_email_answer_is_the_servers_own_sentence(monkeypatch):
    """The server extracted it, checked it and worked out the repair. A model must not reword a
    change a parent is about to approve."""
    agent_module = _rule_agent(monkeypatch, ("check_school_email", {}))

    def fake_call(mcp, tool, arguments):
        assert tool == "check_school_email"
        assert arguments == {"speaker": "Dad"}
        return (SCHOOL_RESULT, {"tool": tool, "status": "success", "tool_ms": 1})

    state = {}
    turn = agent_module.answer(None, "Dad", "any news from school?", fake_call, state)

    assert turn.speak == SCHOOL_RESULT["say"]
    assert state["pending_proposal"]["Dad"] == 7
    assert turn.cards[0]["simulated"] is True


def test_saying_yes_to_a_school_task_approves_that_proposal(monkeypatch):
    agent_module = _rule_agent(monkeypatch, ("cannot_help", {"reason": "should not be reached"}))
    calls = []

    def fake_call(mcp, tool, arguments):
        calls.append((tool, arguments))
        return ({"approved": True, "say": "Done."}, {"tool": tool, "status": "success", "tool_ms": 1})

    state = {"pending_proposal": {"Dad": 7}}
    agent_module.answer(None, "Dad", "yes please", fake_call, state)

    assert calls[0][0] == "approve_proposal"
    assert calls[0][1]["proposal_id"] == 7


def test_the_email_access_answer_is_the_servers_own_sentence(monkeypatch):
    """A sentence about what LifePilot may read must not be paraphrased: a model could soften or
    widen the promise it describes."""
    agent_module = _rule_agent(
        monkeypatch,
        ("manage_email_access", {"senders": ["office@demo-school.invalid"]}),
    )
    said = "I read email from office@demo-school.invalid, and nothing else."

    def fake_call(mcp, tool, arguments):
        assert tool == "manage_email_access"
        assert arguments["senders"] == ["office@demo-school.invalid"]
        return ({"linked": True, "say": said}, {"tool": tool, "status": "success", "tool_ms": 1})

    turn = agent_module.answer(None, "Dad", "only read emails from the school office", fake_call, {})
    assert turn.speak == said


def test_disconnecting_is_not_held_for_a_second_yes(monkeypatch):
    """The escape hatch. Nobody should agree twice to stop LifePilot reading their email."""
    agent_module = _rule_agent(monkeypatch, ("manage_email_access", {"disconnect": True}))
    calls = []

    def fake_call(mcp, tool, arguments):
        calls.append((tool, arguments))
        return ({"linked": False, "say": "Email disconnected."}, {"tool": tool, "status": "ok"})

    state = {}
    turn = agent_module.answer(None, "Dad", "disconnect my email", fake_call, state)

    assert calls[0][1]["disconnect"] is True
    assert turn.speak == "Email disconnected."
    assert "pending_proposal" not in state


# --------------------------------------------------------------------------- tasks are spoken

SCHEDULE_WITH_TASK = {
    "speaker": {"name": "Dad", "role": "parent"},
    "from": "2026-10-06",
    "to": "2026-10-06",
    "about": "Dad",
    "events": [],
    "tasks": [
        {
            "title": "Fancy Dress Competition",
            "due": "2026-10-06T00:00",
            "owner": None,
            "category": "event",
        }
    ],
}


def test_a_task_is_spoken_not_only_fetched():
    """Reported: a task was extracted from a school email, approved, written to the database -- and
    then absent from every answer about the day it was due. Tasks were fetched, handed to the card
    and never said."""
    facts = _facts("get_schedule", SCHEDULE_WITH_TASK, "Dad")
    joined = " ".join(facts)

    assert "Fancy Dress Competition" in joined
    assert "nothing on" not in joined.lower() or "but there are things due" in joined


def test_a_deadline_is_said_as_a_date_not_a_time():
    """A task is stored at midnight on its due date. "Tuesday at 12 AM" is a time nobody said."""
    from simulator.agent import _task_fact

    assert _task_fact(SCHEDULE_WITH_TASK["tasks"][0]) == "Fancy Dress Competition is due Tuesday."
    owned = {**SCHEDULE_WITH_TASK["tasks"][0], "owner": "Aarav"}
    assert _task_fact(owned) == "Aarav needs Fancy Dress Competition by Tuesday."


def test_a_named_task_answers_the_question_it_was_asked():
    """"The fancy dress competition is on which date" named a task LifePilot had written down
    itself, and was answered "there is no fancy dress competition in the week"."""
    named = {**SCHEDULE_WITH_TASK, "title": "fancy dress competition"}
    facts = _facts("get_schedule", named, "Dad")

    assert any("Fancy Dress Competition is due Tuesday" in f for f in facts)
    assert not any("There is no" in f for f in facts)


def test_a_day_with_events_still_mentions_what_is_due():
    one_day = {**SCHEDULE_WITH_TASK, "events": SCHEDULE["events"][:1]}
    facts = _facts("get_schedule", one_day, "Dad")

    assert any("Fancy Dress Competition" in f for f in facts)


# --------------------------------------------------------------------------- the day they named


def test_one_named_weekday_is_the_day_asked_about():
    """Reported: "give me the tuesday's schedule" was answered with Monday, and "give me the
    monday's schedule" with today. The day was only read from the words when a time was named too."""
    from simulator.agent import _the_one_named_day

    assert _the_one_named_day("give me the tuesday's schedule") == date(2026, 10, 6)
    assert _the_one_named_day("give me the monday's schedule") == date(2026, 10, 5)
    assert _the_one_named_day("what is Anaya doing on Thursday") == date(2026, 10, 8)


def test_two_named_weekdays_mean_a_span_not_a_day():
    """"What have I got Monday to Friday" wants the week. Collapsing it to Monday would answer a
    narrower question than the one asked."""
    from simulator.agent import _the_one_named_day

    assert _the_one_named_day("what have I got Monday to Friday") is None
    assert _the_one_named_day("what have I got today") is None


# --------------------------------------------------------------------------- which child?


def test_a_name_after_the_question_is_read_as_the_answer(monkeypatch):
    """"Which child is it for, Aarav or Anaya?" then "Aarav". That is an answer, not a new request,
    and reading it as one costs no model call."""
    agent_module = _rule_agent(monkeypatch, ("cannot_help", {"reason": "should not be reached"}))
    calls = []

    def fake_call(mcp, tool, arguments):
        calls.append((tool, arguments))
        return ({"named": True, "say": "Aarav, then. Shall I put it on the list?"},
                {"tool": tool, "status": "success", "tool_ms": 1})

    state = {"pending_child": {"Dad": {"proposal_id": 4, "children": ["Aarav", "Anaya"]}},
             "pending_proposal": {"Dad": 4}}
    turn = agent_module.answer(None, "Dad", "it's for Aarav", fake_call, state)

    assert calls[0][0] == "name_task_child"
    assert calls[0][1] == {"speaker": "Dad", "proposal_id": 4, "child": "Aarav"}
    assert "Shall I" in turn.speak
    assert state["pending_child"] == {}
    assert state["pending_proposal"]["Dad"] == 4, "still waiting on a yes"


def test_saying_no_to_the_question_still_rejects_the_task(monkeypatch):
    """A refusal is not a name. It has to reach the proposal, or the task is stuck forever."""
    agent_module = _rule_agent(monkeypatch, ("cannot_help", {"reason": "x"}))
    calls = []

    def fake_call(mcp, tool, arguments):
        calls.append((tool, arguments))
        return ({"rejected": True, "say": "Alright, I have left everything as it was."},
                {"tool": tool, "status": "success", "tool_ms": 1})

    state = {"pending_child": {"Dad": {"proposal_id": 4, "children": ["Aarav", "Anaya"]}},
             "pending_proposal": {"Dad": 4}}
    agent_module.answer(None, "Dad", "no, leave it", fake_call, state)

    assert calls[0][0] == "reject_proposal"


def test_another_speaker_cannot_answer_a_question_they_were_not_asked(monkeypatch):
    agent_module = _rule_agent(monkeypatch, ("cannot_help", {"reason": "x"}))

    def explode(*args, **kwargs):
        raise AssertionError("Mom was not asked")

    state = {"pending_child": {"Dad": {"proposal_id": 4, "children": ["Aarav", "Anaya"]}}}
    turn = agent_module.answer(None, "Mom", "Aarav", explode, state)

    assert "cannot do that one" in turn.speak


SWAP_PROPOSED = {
    "proposed": True,
    "feasible": True,
    "proposal_id": 7,
    "awaiting": "Mom",
    "changes": [
        {"title": "football practice pickup", "to": "Mom", "reason": "Mom is 10 minutes away"},
        {"title": "cricket practice pickup", "to": "Dad", "reason": "Dad is 30 minutes away"},
    ],
    "say": "I have asked Mom to take football practice pickup on Thursday, with you taking "
           "cricket practice pickup on Tuesday. It works for both of you. Mom has to agree "
           "before anything changes.",
}


def _swap_session(monkeypatch, result):
    """Dad asks for a swap. Returns the shared state and what reached the tool."""
    import simulator.agent as agent_module

    agent_module._route_cache.clear()
    monkeypatch.setattr(
        agent_module,
        "choose_tool",
        lambda text, budget, speaker=None: (
            "request_swap",
            {"partner": "Mom", "give_day": "2026-10-08", "take_day": "2026-10-06"},
        ),
    )
    seen = {}

    def fake_call(mcp, tool, arguments):
        seen.update({"tool": tool, **arguments})
        return result, {"tool": tool, "status": "success", "tool_ms": 1}

    state = {}
    turn = answer(None, "Dad", "ask Mom to take Thursday, I'll take Tuesday", fake_call, state)
    return turn, state, seen


def test_a_swap_request_reaches_the_tool_with_both_days(monkeypatch):
    turn, _, seen = _swap_session(monkeypatch, SWAP_PROPOSED)
    assert seen["tool"] == "request_swap"
    assert seen["speaker"] == "Dad"
    assert seen["partner"] == "Mom"
    assert seen["give_day"] == "2026-10-08"
    assert seen["take_day"] == "2026-10-06"


def test_the_swap_sentence_is_spoken_as_the_server_wrote_it(monkeypatch):
    """A model must not reword a change somebody is about to agree to."""
    turn, _, _ = _swap_session(monkeypatch, SWAP_PROPOSED)
    assert turn.speak == SWAP_PROPOSED["say"]


def test_a_swap_waits_on_the_partner_not_the_asker(monkeypatch):
    """The point of #6: two people, two sessions. Keying this by the speaker would have let Dad
    approve his own swap."""
    _, state, _ = _swap_session(monkeypatch, SWAP_PROPOSED)
    assert state["pending_proposal"] == {"Mom": 7}
    assert "Dad" not in state["pending_proposal"]


def test_a_refused_swap_proposes_nothing_and_keeps_the_reason(monkeypatch):
    refused = {
        "proposed": False,
        "feasible": False,
        "say": "Dad cannot reach cricket practice by 6 PM: he is at the office until 4:30, "
               "30 minutes away.",
    }
    turn, state, _ = _swap_session(monkeypatch, refused)
    assert turn.speak == refused["say"]
    assert state.get("pending_proposal", {}) == {}
    assert turn.cards == []


def test_a_swap_with_nobody_named_asks_who(monkeypatch):
    import simulator.agent as agent_module

    agent_module._route_cache.clear()
    monkeypatch.setattr(
        agent_module, "choose_tool", lambda text, budget, speaker=None: ("request_swap", {})
    )
    called = []

    def fake_call(mcp, tool, arguments):
        called.append(tool)
        return {}, {"tool": tool, "status": "success", "tool_ms": 1}

    turn = answer(None, "Dad", "can we swap", fake_call, {})
    assert "Who should I ask?" in turn.speak
    assert called == [], "nothing is proposed until a partner is named"


def test_a_question_about_problems_is_a_conflict_check_whatever_was_chosen():
    """A fourteenth tool schema pushed "any problems this week" to get_schedule, which recited
    Thursday at somebody asking whether Thursday works. The words name the question."""
    from simulator.agent import _trouble_wins

    for said in (
        "any problems this week",
        "is anything broken on Thursday",
        "anything wrong with our week",
        "does the week work",
    ):
        tool, args = _trouble_wins("get_schedule", {"start": "x", "end": "y"}, said)
        assert tool == "detect_conflicts", said
        assert args["start"] and args["end"]


def test_the_conflict_override_leaves_decisions_and_writes_alone():
    """Narrow on purpose: it only overrides a tool answering from the week's own data."""
    from simulator.agent import _trouble_wins

    for tool in ("approve_proposal", "add_event", "cannot_help", "request_swap", "fix_week"):
        assert _trouble_wins(tool, {}, "any problems this week")[0] == tool


def test_an_ordinary_question_is_not_turned_into_a_conflict_check():
    from simulator.agent import _trouble_wins

    tool, _ = _trouble_wins("get_schedule", {}, "what is on tomorrow")
    assert tool == "get_schedule"


def test_a_named_day_in_a_hypothetical_is_read_from_the_sentence():
    """Nova Micro resolved "Thursday" to 2026-10-21, a Wednesday, and the what-if then asked about a
    day the speaker never mentioned. The day is in the sentence, so it is read from it -- the rule
    `days_named_in_order` already applies to a swap."""
    from simulator.agent import _pin_day

    pinned = _pin_day(
        {"kind": "runs_late", "start": "2026-10-21T16:00", "until": "2026-10-21T17:30"},
        "what if my 4 pm runs till 5:30 on Thursday",
    )
    assert pinned["start"] == "2026-10-08T16:00", "Thursday in the loaded window"
    assert pinned["until"] == "2026-10-08T17:30", "the end moves with it"


def test_pinning_a_day_leaves_the_time_of_day_alone():
    from simulator.agent import _pin_day

    pinned = _pin_day({"kind": "runs_late", "at": "2026-10-21T15:45"}, "what if Monday's 3:45 runs on")
    assert pinned["at"] == "2026-10-05T15:45"


def test_a_hypothetical_naming_no_day_is_left_as_it_came():
    """Only the day is read from the sentence. Naming none is not a reason to invent one."""
    from simulator.agent import _pin_day

    change = {"kind": "runs_late", "start": "2026-10-08T16:00", "until": "2026-10-08T17:30"}
    assert _pin_day(dict(change), "what if my four o'clock runs until half five") == change


def test_pinning_a_day_ignores_fields_that_carry_no_date():
    from simulator.agent import _pin_day

    pinned = _pin_day({"kind": "runs_late", "title": "review", "until": "17:30"}, "on Thursday")
    assert pinned == {"kind": "runs_late", "title": "review", "until": "17:30"}


def test_a_title_the_model_invented_is_replaced_from_the_sentence():
    """Asked "what if my performance review runs till 5:30", Nova Micro answered title="my" and the
    what-if went looking for an event called "my". The title is in the sentence and the family's own
    event names are already loaded, so it is read from there -- the same rule as the day."""
    from simulator.agent import _correct_title

    known = {"performance review", "performance", "review", "football practice", "football"}
    fixed = _correct_title(
        {"kind": "runs_late", "title": "my", "until": "17:30"},
        "what if my performance review runs till 5:30",
        known,
    )
    assert fixed["title"] == "performance review"


def test_a_title_the_family_recognises_is_left_alone():
    from simulator.agent import _correct_title

    known = {"performance review", "review", "football practice", "football"}
    change = {"kind": "cancelled", "title": "football practice"}
    assert _correct_title(dict(change), "what if football practice is cancelled", known) == change


def test_an_unknown_title_survives_when_the_sentence_names_nothing():
    """"I cannot find 'badminton'. That week has: ..." is a better answer than "which event do you
    mean", so a title that matches nothing is left to produce it."""
    from simulator.agent import _correct_title

    change = {"kind": "runs_late", "title": "badminton", "until": "18:00"}
    assert _correct_title(dict(change), "what if badminton runs late", {"football"}) == change


def test_the_time_something_runs_until_is_read_from_the_sentence():
    """"Runs till 5:30" carries its end time, but the model filled the kind and the title and left
    `until` empty, so the what-if asked for a time the speaker had already given."""
    from simulator.agent import _until_time

    assert _until_time("what if my performance review runs till 5:30") == "17:30"
    assert _until_time("what if my 4 PM runs till 5:30 on Thursday") == "17:30", "the second time"
    assert _until_time("what if it runs until 6 pm") == "18:00"


def test_no_until_is_read_when_the_sentence_names_none():
    from simulator.agent import _until_time

    assert _until_time("what if football is cancelled") is None
    assert _until_time("what if my 4 PM runs late") is None


def test_an_overrun_keeps_the_until_the_model_gave():
    """Only a missing one is filled in. The model's own answer is not second-guessed."""
    from simulator.agent import _fill_until

    change = {"kind": "runs_late", "title": "review", "until": "18:00"}
    assert _fill_until(dict(change), "runs till 5:30")["until"] == "18:00"


def test_a_missing_until_is_filled_from_the_sentence():
    from simulator.agent import _fill_until

    filled = _fill_until({"kind": "runs_late", "title": "review"}, "what if review runs till 5:30")
    assert filled["until"] == "17:30"


def test_only_an_overrun_gets_an_until():
    """A cancellation has no end time, and inventing one would change the question."""
    from simulator.agent import _fill_until

    change = {"kind": "cancelled", "title": "football"}
    assert _fill_until(dict(change), "what if football is cancelled till 5:30") == change


def test_an_until_with_a_morning_meridiem_is_left_alone():
    """The afternoon rule must not turn a stated morning into the evening."""
    from simulator.agent import _until_time

    assert _until_time("what if the night shift runs until 7 am") == "07:00"


BUSY_ONLY = {
    "speaker": {"name": "Aarav", "role": "child"},
    "from": "2026-10-08",
    "to": "2026-10-08",
    "about": "Dad",
    "events": [
        {"title": "Busy", "start": "2026-10-08T09:30", "end": "2026-10-08T15:45", "redacted": True},
        {"title": "Busy", "start": "2026-10-08T15:45", "end": "2026-10-08T16:45", "redacted": True},
    ],
    "tasks": [],
}


def test_a_child_asking_about_a_parent_is_told_they_are_busy():
    """The worst find of the browser run. The card showed two Busy blocks and the spoken answer was
    "Dad has nothing scheduled on Thursday afternoon", because the hidden count is suppressed when a
    subject is named and the redacted blocks were filtered out -- so the facts were literally
    "Dad has 0 things on Thursday". Asked about one person, a blocked-out hour IS the answer."""
    facts = _facts("get_schedule", BUSY_ONLY, "Aarav")
    joined = " ".join(facts).lower()
    assert "nothing" not in joined, "two busy blocks is not nothing"
    assert "busy" in joined
    assert "2 things" in joined


def test_a_child_is_never_told_what_the_parent_is_doing():
    """The other half of #9: Busy means busy. No title, no place, no other people."""
    facts = _facts("get_schedule", BUSY_ONLY, "Aarav")
    joined = " ".join(facts).lower()
    for secret in ("work", "performance review", "office"):
        assert secret not in joined


def test_a_general_question_still_summarises_other_peoples_time():
    """Without a subject the redacted blocks stay a one-line summary, which is what stopped Aarav
    hearing "12 other blocks of time belong to other people" before his football answer."""
    general = {**BUSY_ONLY, "about": None}
    facts = _facts("get_schedule", general, "Aarav")
    joined = " ".join(facts).lower()
    assert "belong to other people" in joined


WAITING_SWAP = {
    "speaker": {"name": "Mom", "role": "parent"},
    "proposals": [{
        "id": 11,
        "kind": "swap",
        "created_by": "Dad",
        "needs_approval_from": "Mom",
        "yours_to_decide": True,
        "change_count": 2,
        "changes": [
            {"title": "football practice", "was": "Dad", "now": "Mom", "reason": "Mom is free"},
            {"title": "cricket practice", "was": "Mom", "now": "Dad", "reason": "Dad is free"},
        ],
    }],
}


def test_asking_what_is_waiting_reads_the_proposal_back_without_a_model_call(monkeypatch):
    """Mom can ask what she is being asked before she says yes, and it mints nothing new."""
    agent_module = _rule_agent(monkeypatch, ("fix_week", {}))
    calls = []

    def fake_call(mcp, tool, arguments):
        calls.append((tool, arguments))
        return WAITING_SWAP, {"tool": tool, "status": "success", "tool_ms": 1}

    state = {}
    turn = agent_module.answer(None, "Mom", "anything waiting for me?", fake_call, state)

    assert calls == [("list_proposals", {"speaker": "Mom"})], "no second proposal is minted"
    assert "Dad asked you to take" in turn.speak
    assert "football practice" in turn.speak and "cricket practice" in turn.speak
    assert turn.cards[0]["proposal"]["proposal_id"] == 11
    assert turn.debug["model_calls"] == 0
    assert state["pending_proposal"]["Mom"] == 11, "a yes now settles it"


def test_the_read_back_arms_the_yes(monkeypatch):
    agent_module = _rule_agent(monkeypatch, ("fix_week", {}))
    replies = {
        "list_proposals": WAITING_SWAP,
        "approve_proposal": {"approved": True, "say": "Done. Mom has football practice."},
    }

    def fake_call(mcp, tool, arguments):
        return replies[tool], {"tool": tool, "status": "success", "tool_ms": 1}

    state = {}
    agent_module.answer(None, "Mom", "do I have anything to approve", fake_call, state)
    turn = agent_module.answer(None, "Mom", "yes", fake_call, state)

    assert "Done." in turn.speak
    assert state["pending_proposal"] == {}


def test_nothing_of_mine_is_waiting_says_so(monkeypatch):
    agent_module = _rule_agent(monkeypatch, ("fix_week", {}))
    nothing = {"speaker": {"name": "Dad", "role": "parent"}, "proposals": []}

    def fake_call(mcp, tool, arguments):
        return nothing, {"tool": tool, "status": "success", "tool_ms": 1}

    turn = agent_module.answer(None, "Dad", "anything waiting for me?", fake_call, {})
    assert turn.speak == "There is nothing waiting for a yes or no."


def test_the_asker_is_told_whose_call_it_is(monkeypatch):
    """Dad's "yes" to his own swap is refused -- and hearing nothing is waiting reads like a bug."""
    agent_module = _rule_agent(monkeypatch, ("cannot_help", {"reason": "unused"}))

    def fake_call(mcp, tool, arguments):
        raise AssertionError("a decision nobody owes is settled without the server")

    state = {"pending_proposal": {"Mom": 11}}
    turn = agent_module.answer(None, "Dad", "yes", fake_call, state)

    assert turn.speak == "That one is Mom's to answer."
    assert turn.debug["model_calls"] == 0
    assert state["pending_proposal"] == {"Mom": 11}, "Mom's yes is still owed"


def test_the_swap_wins_over_a_week_fix_any_parent_could_decide(monkeypatch):
    """Two pending: the one addressed to Mom by name is the one she is being asked about."""
    agent_module = _rule_agent(monkeypatch, ("fix_week", {}))
    both = {
        "speaker": {"name": "Mom", "role": "parent"},
        "proposals": [
            {"id": 4, "kind": "fix", "created_by": "Dad", "needs_approval_from": None,
             "yours_to_decide": True, "change_count": 1,
             "changes": [{"title": "science project", "was": "8 PM", "now": "7:30 PM",
                          "reason": "past the 9 PM rule"}]},
            WAITING_SWAP["proposals"][0],
        ],
    }

    def fake_call(mcp, tool, arguments):
        return both, {"tool": tool, "status": "success", "tool_ms": 1}

    state = {}
    turn = agent_module.answer(None, "Mom", "anything waiting for me?", fake_call, state)

    assert state["pending_proposal"]["Mom"] == 11
    assert "science project" not in turn.speak


CANCELLED = {
    "proposal_id": 9,
    "status": "pending",
    "title": "football practice",
    "when": "Thursday at 4 PM to 5 PM",
    "also_loses_it": ["Aarav"],
    "frees": [],
    "strands": [],
    "lifts_no_longer_needed": ["football practice pickup"],
    "say": "Cancelling football practice, Thursday at 4 PM to 5 PM. Shall I cancel it?",
}


def test_cancelling_names_the_day_from_the_sentence(monkeypatch):
    """The day is what separates two of Mom's meetings, so reading it from the model would cancel
    the wrong one. Same rule as `_correct_the_day` and `_pin_day`."""
    agent_module = _rule_agent(monkeypatch, ("cancel_event", {"title": "work", "day": "2026-10-05"}))
    calls = []

    def fake_call(mcp, tool, arguments):
        calls.append((tool, arguments))
        return CANCELLED, {"tool": tool, "status": "success", "tool_ms": 1}

    state = {}
    turn = agent_module.answer(None, "Mom", "cancel my meeting on Thursday", fake_call, state)

    assert calls[0][1]["day"] == "2026-10-08", "Thursday, not the Monday the model offered"
    assert turn.speak == CANCELLED["say"], "the server's sentence is spoken as written"
    assert state["pending_proposal"]["Mom"] == 9, "nothing goes until a parent says yes"
    assert turn.cards[0]["proposal"]["change_count"] == 1


def test_the_cancel_card_fills_the_contract_every_proposal_card_shares(monkeypatch):
    """A third card drifting off this contract is how the swap card rendered "undefined changes"."""
    agent_module = _rule_agent(monkeypatch, ("cancel_event", {"title": "football practice"}))

    def fake_call(mcp, tool, arguments):
        return CANCELLED, {"tool": tool, "status": "success", "tool_ms": 1}

    turn = agent_module.answer(None, "Dad", "cancel football practice", fake_call, {})
    change = turn.cards[0]["proposal"]["changes"][0]

    assert change["was"] == "Thursday at 4 PM to 5 PM"
    assert change["now"] == "cancelled"
    assert change["reason"] == "nobody needs to drive football practice pickup"


def test_cancelling_something_is_not_refusing_a_proposal(monkeypatch):
    """The word collision. "cancel" is in the NO set, so "cancel football practice" could read as
    refusing whatever was last offered -- and would misfire exactly when a proposal is pending."""
    agent_module = _rule_agent(monkeypatch, ("cancel_event", {"title": "football practice"}))
    calls = []

    def fake_call(mcp, tool, arguments):
        calls.append(tool)
        return CANCELLED, {"tool": tool, "status": "success", "tool_ms": 1}

    state = {"pending_proposal": {"Dad": 7}}
    agent_module.answer(None, "Dad", "cancel football practice", fake_call, state)

    assert calls == ["cancel_event"], "naming what to cancel is a request, not a refusal"
    assert "reject_proposal" not in calls


def test_a_bare_cancel_still_refuses_what_was_just_offered(monkeypatch):
    """The other side of the collision, and the reason it is not worth "fixing": said straight
    after "shall I put it in?", "cancel" means no."""
    agent_module = _rule_agent(monkeypatch, ("cannot_help", {"reason": "unused"}))
    calls = []

    def fake_call(mcp, tool, arguments):
        calls.append(tool)
        return {"rejected": True, "say": "Alright, I have left everything as it was."}, {
            "tool": tool, "status": "success", "tool_ms": 1
        }

    agent_module.answer(None, "Dad", "cancel", fake_call, {"pending_proposal": {"Dad": 7}})
    assert calls == ["reject_proposal"]


def test_overriding_a_rule_has_to_be_said_in_so_many_words(monkeypatch):
    """Never inferred from a parent asking twice."""
    agent_module = _rule_agent(monkeypatch, ("cancel_event", {"title": "piano class"}))
    sent = []

    def fake_call(mcp, tool, arguments):
        sent.append(arguments)
        return CANCELLED, {"tool": tool, "status": "success", "tool_ms": 1}

    agent_module.answer(None, "Dad", "cancel piano class", fake_call, {})
    agent_module.answer(None, "Dad", "cancel piano class anyway", fake_call, {})

    assert "override" not in sent[0]
    assert sent[1]["override"] is True


def test_cancelling_nothing_in_particular_asks_what(monkeypatch):
    agent_module = _rule_agent(monkeypatch, ("cancel_event", {}))

    def fake_call(mcp, tool, arguments):
        raise AssertionError("nothing is named, so there is nothing to ask the server")

    turn = agent_module.answer(None, "Dad", "cancel it", fake_call, {})
    assert turn.speak == "Cancel what?"


@pytest.mark.parametrize("said", ["order milk", "buy bread", "add milk to the shopping list"])
def test_an_errand_is_declined_whatever_tool_was_chosen(monkeypatch, said):
    """LifePilot is not a grocery list. A sixteenth tool schema pushed "order milk" to
    `cancel_event`, which then recited the whole diary at somebody asking for milk."""
    agent_module = _rule_agent(monkeypatch, ("cancel_event", {"title": "milk"}))

    def fake_call(mcp, tool, arguments):
        raise AssertionError("an errand reaches no tool")

    turn = agent_module.answer(None, "Dad", said, fake_call, {})
    assert "cannot do that one yet" in turn.speak


def test_asking_what_order_to_do_things_in_is_still_a_question(monkeypatch):
    """The guard reads the head of the sentence, so a noun that happens to be a verb is safe."""
    agent_module = _rule_agent(monkeypatch, ("get_schedule", {"start": "2026-10-08", "end": "2026-10-08"}))
    calls = []

    def fake_call(mcp, tool, arguments):
        calls.append(tool)
        return SCHEDULE, {"tool": tool, "status": "success", "tool_ms": 1}

    agent_module.answer(None, "Dad", "what order do I do these in", fake_call, {})
    assert calls[0] == "get_schedule", "a noun that happens to be a verb is not an errand"


def test_a_day_the_sentence_never_named_is_dropped(monkeypatch):
    """Found in the browser. Asked to "cancel Anaya's piano class", which names no day, the model
    filled in the Tuesday. Piano is on Thursday, so the answer was "I cannot find piano class"
    followed by a list of the diary with piano class in it."""
    agent_module = _rule_agent(
        monkeypatch, ("cancel_event", {"title": "piano class", "day": "2026-10-06"})
    )
    sent = []

    def fake_call(mcp, tool, arguments):
        sent.append(arguments)
        return CANCELLED, {"tool": tool, "status": "success", "tool_ms": 1}

    agent_module.answer(None, "Dad", "cancel Anaya's piano class", fake_call, {})
    assert "day" not in sent[0], "a day nobody said narrows the search to the wrong day"


def test_a_time_the_sentence_never_named_is_dropped(monkeypatch):
    agent_module = _rule_agent(
        monkeypatch, ("cancel_event", {"title": "piano class", "at": "2026-10-06T16:00"})
    )
    sent = []

    def fake_call(mcp, tool, arguments):
        sent.append(arguments)
        return CANCELLED, {"tool": tool, "status": "success", "tool_ms": 1}

    agent_module.answer(None, "Dad", "cancel piano class", fake_call, {})
    assert "at" not in sent[0]


def test_a_time_the_sentence_does_name_is_kept(monkeypatch):
    agent_module = _rule_agent(
        monkeypatch, ("cancel_event", {"title": "meeting", "at": "2026-10-08T16:00"})
    )
    sent = []

    def fake_call(mcp, tool, arguments):
        sent.append(arguments)
        return CANCELLED, {"tool": tool, "status": "success", "tool_ms": 1}

    agent_module.answer(None, "Dad", "cancel my 4 PM meeting", fake_call, {})
    assert sent[0]["at"] == "2026-10-08T16:00"


WHICH_ONE = {
    "cancelled": False,
    "options": [
        {"event_id": 7, "title": "work", "when": "Wednesday at 9:30 AM to 4:30 PM"},
        {"event_id": 10, "title": "work", "when": "Thursday at 9:30 AM to 3:45 PM"},
    ],
    "say": "Which one: work Wednesday at 9:30 AM to 4:30 PM or work Thursday at 9:30 AM to 3:45 PM?",
}


def test_naming_the_day_settles_which_one_was_meant(monkeypatch):
    """"Which one?" expects a day back, so the next thing said is an answer, not a fresh request."""
    agent_module = _rule_agent(monkeypatch, ("cancel_event", {"title": "work"}))
    calls = []

    def fake_call(mcp, tool, arguments):
        calls.append((tool, arguments))
        return (WHICH_ONE if len(calls) == 1 else CANCELLED), {
            "tool": tool, "status": "success", "tool_ms": 1
        }

    state = {}
    agent_module.answer(None, "Dad", "cancel my work", fake_call, state)
    assert state["pending_choice"]["Dad"] == WHICH_ONE["options"]

    turn = agent_module.answer(None, "Dad", "Thursday", fake_call, state)

    assert calls[1] == ("cancel_event", {"speaker": "Dad", "event_id": 10})
    assert turn.speak == CANCELLED["say"]
    assert turn.debug["model_calls"] == 0, "the day is matched here, not asked of the model"
    assert "Dad" not in state.get("pending_choice", {})
    assert state["pending_proposal"]["Dad"] == 9


def test_an_answer_naming_none_of_them_is_a_fresh_request(monkeypatch):
    """Falls through, so changing the subject still works rather than being eaten as a choice."""
    agent_module = _rule_agent(monkeypatch, ("detect_conflicts", {"start": "a", "end": "b"}))
    calls = []

    def fake_call(mcp, tool, arguments):
        calls.append(tool)
        return CONFLICTS, {"tool": tool, "status": "success", "tool_ms": 1}

    state = {"pending_choice": {"Dad": WHICH_ONE["options"]}}
    agent_module.answer(None, "Dad", "any problems this week", fake_call, state)

    assert calls[0] == "detect_conflicts"


def test_who_should_go_says_the_name_once():
    """Every reason `allocation` records opens with the name, so "X, because <reason>" said it
    twice: "Mom, because Mom is the only one who can get there"."""
    from simulator.agent import _why_them

    assert _why_them({"name": "Mom", "reason": "Mom is the only one who can get there"}) == (
        "Mom is the only one who can get there."
    )
    assert _why_them({"name": "Mom", "reason": "Mom is only 10 minutes away"}) == (
        "Mom is only 10 minutes away."
    )


def test_a_conflict_on_today_drops_the_preposition():
    """"On today at 5 PM" is not English. Every other day keeps it."""
    from simulator.agent import _on

    assert _on("today at 5 PM") == "Today at 5 PM"
    assert _on("tomorrow at 9 AM") == "Tomorrow at 9 AM"
    assert _on("Thursday at 5 PM") == "On Thursday at 5 PM"


def test_someone_elses_event_in_your_day_says_whose_it_is():
    """Asked when Mom finishes work, the children's school is in her day because she drives them.
    With the names left off it became "Mom has school from 8 AM to 3 PM"."""
    data = {
        "from": "2026-10-09", "to": "2026-10-09", "about": "Mom",
        "events": [
            {"title": "school", "start": "2026-10-09T08:00", "end": "2026-10-09T15:00",
             "members": ["Aarav", "Anaya"], "needs_transport": True},
            {"title": "work", "start": "2026-10-09T09:00", "end": "2026-10-09T14:30",
             "members": ["Mom"], "location": "her office"},
        ],
        "tasks": [],
    }
    facts = _facts("get_schedule", data, "Dad")
    school = next(f for f in facts if "school" in f)
    work = next(f for f in facts if "work" in f)

    assert school.startswith("Aarav and Anaya:"), "a line about somebody else has to say who"
    assert work.startswith("work"), "her own is still said without repeating her name"


def test_who_the_replacement_is_with_is_read_from_the_sentence(monkeypatch):
    """"Book lunch with Mom instead" names her, and the model left her out: the replacement came
    back "for Dad". Only the tail after "with" is scanned, because "lunch at Grandpa's" names him
    as part of what is being cancelled, not as a guest at what replaces it."""
    agent_module = _rule_agent(
        monkeypatch,
        ("cancel_event", {"title": "lunch at grandpa's", "replace_with": "lunch with Mom"}),
    )
    sent = []

    def fake_call(mcp, tool, arguments):
        sent.append((tool, arguments))
        if tool == "get_family":
            return {"members": [{"name": n} for n in ("Dad", "Mom", "Aarav", "Anaya", "Grandpa")],
                    "locations": []}, {"tool": tool, "status": "success", "tool_ms": 1}
        if tool == "get_schedule":
            return {"events": []}, {"tool": tool, "status": "success", "tool_ms": 1}
        return CANCELLED, {"tool": tool, "status": "success", "tool_ms": 1}

    agent_module.answer(
        None, "Dad", "cancel our lunch at grandpa's and book lunch with Mom instead", fake_call, {}
    )
    asked = next(args for tool, args in sent if tool == "cancel_event")

    assert asked["replace_members"] == ["Mom"], "Grandpa is what is being cancelled, not a guest"


def test_a_plain_cancellation_never_reads_the_roster(monkeypatch):
    """The two extra tool calls only happen when something is being put in its place."""
    agent_module = _rule_agent(monkeypatch, ("cancel_event", {"title": "football practice"}))
    calls = []

    def fake_call(mcp, tool, arguments):
        calls.append(tool)
        return CANCELLED, {"tool": tool, "status": "success", "tool_ms": 1}

    agent_module.answer(None, "Dad", "cancel football practice", fake_call, {})
    assert calls == ["cancel_event"]


def test_tomorrow_narrows_a_cancellation_like_a_weekday_does(monkeypatch):
    """Reported from the browser. "Cancel the work event for tomorrow" named a day, but `named_day`
    only knew weekday names, so the day was dropped and five identical "work" rows made it a
    question instead of an answer."""
    agent_module = _rule_agent(monkeypatch, ("cancel_event", {"title": "work event"}))
    sent = []

    def fake_call(mcp, tool, arguments):
        sent.append(arguments)
        return CANCELLED, {"tool": tool, "status": "success", "tool_ms": 1}

    agent_module.answer(None, "Dad", "cancel the work event for tomorrow", fake_call, {})
    assert sent[0]["day"] == "2026-10-09", "the day after the pinned today"


def test_a_title_the_model_invented_is_retried_with_the_one_the_sentence_names(monkeypatch):
    """Reported from the browser. "Work for Tuesday 9:30 to 2:15 p.m. cancel it" came back with the
    whole time phrase as the title while the diary plainly had one called work. The retry happens
    only on a miss, so an ordinary cancellation never pays for it."""
    agent_module = _rule_agent(
        monkeypatch, ("cancel_event", {"title": "Tuesday 9:30 to 2:15 p.m."})
    )
    sent = []

    def fake_call(mcp, tool, arguments):
        sent.append((tool, arguments))
        if tool == "get_family":
            return {"members": [{"name": "Dad"}], "locations": []}, {
                "tool": tool, "status": "success", "tool_ms": 1}
        if tool == "get_schedule":
            return {"events": [{"title": "work"}]}, {"tool": tool, "status": "success",
                                                     "tool_ms": 1}
        if len([t for t, _ in sent if t == "cancel_event"]) == 1:
            return {"cancelled": False, "found": False, "say": "I cannot find that."}, {
                "tool": tool, "status": "success", "tool_ms": 1}
        return CANCELLED, {"tool": tool, "status": "success", "tool_ms": 1}

    turn = agent_module.answer(
        None, "Dad", "work for Tuesday 9:30 to 2:15 p.m. cancel it", fake_call, {}
    )
    asked = [args for tool, args in sent if tool == "cancel_event"]

    assert asked[0]["title"] == "Tuesday 9:30 to 2:15 p.m.", "the model's guess goes first"
    assert asked[1]["title"] == "work", "then the word the sentence actually names"
    assert turn.speak == CANCELLED["say"]
    assert turn.debug["model_calls"] == 0, "recovering costs tool calls, never a model call"


def test_asking_when_one_thing_is_does_not_recite_the_week(monkeypatch):
    """Reported from the browser. "When do I have lunch with Mom" was answered with eight work
    blocks, because the model filled start, end and `about` and left `title` empty."""
    agent_module = _rule_agent(
        monkeypatch,
        ("get_schedule", {"about": "Dad", "start": "2026-10-05", "end": "2026-10-09"}),
    )
    sent = []

    def fake_call(mcp, tool, arguments):
        sent.append((tool, arguments))
        if tool == "get_family":
            return {"members": [{"name": "Dad"}], "locations": []}, {
                "tool": tool, "status": "success", "tool_ms": 1}
        if tool == "get_schedule" and "title" not in arguments and len(sent) < 3:
            return {"events": [{"title": "lunch at grandpa's"}]}, {
                "tool": tool, "status": "success", "tool_ms": 1}
        return SCHEDULE, {"tool": tool, "status": "success", "tool_ms": 1}

    agent_module.answer(None, "Dad", "when do I have lunch with mom", fake_call, {})
    asked = [args for tool, args in sent if tool == "get_schedule"][-1]

    assert asked["title"] == "lunch", "the question is about lunch, not about the week"
    assert asked["about"] == "Dad", "and still about the person who asked"


def test_asking_for_the_whole_day_is_still_the_whole_day(monkeypatch):
    """The narrowing must not fire on "what have I got today", which asks for the day."""
    agent_module = _rule_agent(
        monkeypatch,
        ("get_schedule", {"about": "Dad", "start": "2026-10-08", "end": "2026-10-08"}),
    )
    sent = []

    def fake_call(mcp, tool, arguments):
        sent.append((tool, arguments))
        return SCHEDULE, {"tool": tool, "status": "success", "tool_ms": 1}

    agent_module.answer(None, "Dad", "what have I got today", fake_call, {})
    asked = [args for tool, args in sent if tool == "get_schedule"][-1]
    assert "title" not in asked


@pytest.mark.parametrize(
    "said",
    [
        "when is the farmer costume due",
        "the costumes are ready",
        "is the costume sorted",
    ],
)
def test_a_costume_is_not_a_question_about_money(said):
    """"cost" inside "costume" declined a school task LifePilot had written down itself.

    The match is on whole words, so the family's own vocabulary survives the money guard.
    """
    tool, _ = _money_is_declined("get_schedule", {"about": "Aarav"}, said)
    assert tool == "get_schedule"


@pytest.mark.parametrize(
    "said",
    [
        "how much did football cost this month",
        "what did we spend on piano",
        "the fee for annual day",
    ],
)
def test_a_real_question_about_money_is_still_declined(said):
    """The guard still earns its place: LifePilot stores no amounts."""
    tool, arguments = _money_is_declined("get_schedule", {}, said)
    assert tool == "cannot_help"
    assert "money" in arguments["reason"]
