"""The Bedrock path's non-model parts. Offline and free: no Bedrock call here.

What the model is allowed to influence, and what it is not, is the whole point of these.
"""

from simulator.agent import _facts, _safe_arguments, answer
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
    assert "1 other blocks of time belong to other people" in joined
    assert "15:45" not in joined
    assert "redacted" not in joined.lower()


def test_transport_need_reaches_the_facts():
    facts = _facts("get_schedule", SCHEDULE, "Dad")
    assert any("needs a lift" in f for f in facts)


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
            "detail": "Dad is down for this and arrives 17:25, needs 17:00",
            "could_cover": ["Mom"],
        },
        {
            "kind": "rule_clash",
            "title": "science project block",
            "when": "2026-10-08T20:00",
            "detail": "science project block runs to 21:30, past your rule of 21:00",
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
    late = next(f for f in facts if "21:30" in f)
    assert late.count("science project block") == 1


def test_every_conflict_reaches_the_facts_with_its_cover_option():
    from simulator.agent import _conflict_facts

    facts = _conflict_facts(CONFLICTS)
    assert facts[0] == "There are 2 problems this week."
    assert "Mom could cover it instead." in facts
    assert any("football practice pickup" in f for f in facts)
    assert any("past your rule of 21:00" in f for f in facts)


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
