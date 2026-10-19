"""The coarse routing set stands in for the full one, and the two cannot drift apart."""

import pytest

from simulator.toolsets import COARSE_SCHEMAS, COVERS, coarse, translate


@pytest.fixture(autouse=True)
def unpinned(monkeypatch):
    monkeypatch.delenv("TOOLSET", raising=False)


def test_the_coarse_set_is_nine_tools():
    """CLAUDE.md's comparison is 9 against the full set. The count is the experiment."""
    assert len(COARSE_SCHEMAS) == 9


def test_every_coarse_tool_is_named_in_covers():
    names = {t["toolSpec"]["name"] for t in COARSE_SCHEMAS}
    assert names == set(COVERS)


def test_the_coarse_set_covers_every_tool_the_model_can_route_to():
    """The sync check. A schema added to the full set and forgotten here fails loudly, which is
    what `CLAUDE.md`'s "keep both sets in sync" has to mean in practice."""
    from simulator.agent import TOOL_SCHEMAS

    full = {t["toolSpec"]["name"] for t in TOOL_SCHEMAS}
    covered = {name for names in COVERS.values() for name in names}
    assert full - covered == set(), f"not reachable through the coarse set: {sorted(full - covered)}"
    assert covered - full == set(), f"coarse set claims tools that do not exist: {sorted(covered - full)}"


def test_coarse_is_off_unless_the_variable_says_so(monkeypatch):
    assert coarse() is False
    monkeypatch.setenv("TOOLSET", "full")
    assert coarse() is False
    monkeypatch.setenv("TOOLSET", "coarse")
    assert coarse() is True
    monkeypatch.setenv("TOOLSET", "COARSE")
    assert coarse() is True


@pytest.mark.parametrize(
    "tool,arguments,expected",
    [
        ("get_context", {}, "get_family"),
        ("get_context", {"start": "2026-10-05", "end": "2026-10-09"}, "get_schedule"),
        ("update_rules", {}, "list_rules"),
        ("update_rules", {"rule_type": "latest_end", "params": {}}, "remember_rule"),
        ("find_problems", {"start": "a", "end": "b"}, "detect_conflicts"),
        ("decide_and_explain", {}, "suggest_responsible"),
        ("decide_and_explain", {"person": "Grandpa"}, "explain_choice"),
        ("plan_changes", {}, "fix_week"),
        ("plan_changes", {"kind": "runs_late"}, "what_if"),
        ("update_schedule", {"title": "dentist", "start": "x"}, "add_event"),
        ("school_email", {}, "check_school_email"),
        ("school_email", {"disconnect": True}, "manage_email_access"),
        ("school_email", {"senders": ["a@b.c"]}, "manage_email_access"),
        ("request_swap", {"partner": "Mom"}, "request_swap"),
        ("cannot_help", {"reason": "money"}, "cannot_help"),
    ],
)
def test_each_coarse_call_reaches_the_right_fine_grained_tool(tool, arguments, expected):
    assert translate(tool, arguments)[0] == expected


def test_a_fine_grained_tool_passes_straight_through():
    """The translation runs in front of both sets, so it must not touch the full set's own names."""
    for tool in ("get_schedule", "detect_conflicts", "fix_week", "explain_choice"):
        assert translate(tool, {"start": "x"}) == (tool, {"start": "x"})


def test_who_should_go_does_not_carry_a_person_through():
    """suggest_responsible has no `person` argument; passing one would be rejected as unknown."""
    _, arguments = translate("decide_and_explain", {"title": "football", "person": ""})
    assert "person" not in arguments


def test_the_agent_offers_the_set_the_variable_asks_for(monkeypatch):
    from simulator.agent import TOOL_SCHEMAS, schemas_for_model

    assert schemas_for_model() is TOOL_SCHEMAS
    monkeypatch.setenv("TOOLSET", "coarse")
    assert schemas_for_model() is COARSE_SCHEMAS
    assert len(schemas_for_model()) == 9


def test_a_coarse_choice_is_translated_before_any_handler_sees_it(monkeypatch):
    """Everything downstream of routing is written once and knows nothing about toolsets."""
    import simulator.agent as agent_module

    monkeypatch.setenv("TOOLSET", "coarse")
    agent_module._route_cache.clear()
    monkeypatch.setattr(
        agent_module,
        "_tool_use",
        lambda response: ("plan_changes", {"kind": "runs_late", "until": "17:30"}),
    )
    monkeypatch.setattr(agent_module, "_route_once", lambda text, speaker, budget: None)

    tool, arguments = agent_module.choose_tool("what if my four runs late", agent_module.Budget())
    assert tool == "what_if"
    assert arguments["kind"] == "runs_late"


def test_the_two_sets_never_share_a_routing_cache_entry(monkeypatch):
    """Same words, different schema block, different answer. One cache entry cannot serve both."""
    import simulator.agent as agent_module

    agent_module._route_cache.clear()
    monkeypatch.setattr(agent_module, "_route_once", lambda text, speaker, budget: None)
    monkeypatch.setattr(agent_module, "_tool_use", lambda response: ("get_family", {}))
    agent_module.choose_tool("who is in the family", agent_module.Budget())

    monkeypatch.setenv("TOOLSET", "coarse")
    monkeypatch.setattr(agent_module, "_tool_use", lambda response: ("get_context", {}))
    agent_module.choose_tool("who is in the family", agent_module.Budget())

    settings = {key.split("|")[0] for key in agent_module._route_cache}
    assert settings == {"full", "coarse"}


def test_a_half_bounded_schedule_is_completed_rather_than_rejected():
    """`get_schedule` requires both days and `get_context` cannot. Asked "what have I got today"
    the model filled start and left end out, and the missing field reached the speaker as a
    pydantic validation error."""
    tool, arguments = translate("get_context", {"start": "2026-10-08"})
    assert tool == "get_schedule"
    assert arguments["start"] == "2026-10-08"
    assert arguments["end"] == "2026-10-08"

    tool, arguments = translate("get_context", {"end": "2026-10-08"})
    assert arguments["start"] == "2026-10-08"
    assert arguments["end"] == "2026-10-08"


def test_a_fully_bounded_schedule_is_left_exactly_as_it_was():
    _, arguments = translate("get_context", {"start": "2026-10-05", "end": "2026-10-09"})
    assert (arguments["start"], arguments["end"]) == ("2026-10-05", "2026-10-09")


def test_what_am_i_forgetting_reaches_the_risk_scan():
    """The coarse `find_problems` answers two different questions, told apart by its arguments."""
    assert translate("find_problems", {"forgetting": True}) == ("scan_risks", {})

    tool, arguments = translate("find_problems", {"start": "2026-10-19", "end": "2026-10-23"})
    assert tool == "detect_conflicts"
    assert arguments == {"start": "2026-10-19", "end": "2026-10-23"}


def test_a_conflict_check_with_no_days_is_completed_not_rejected():
    """`detect_conflicts` requires both days and the coarse schema cannot, because the same
    schema also answers "what am I forgetting", which takes none."""
    tool, arguments = translate("find_problems", {})
    assert tool == "detect_conflicts"
    assert arguments["start"] and arguments["end"]
