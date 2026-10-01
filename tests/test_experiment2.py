"""Experiment 2's plan applier and scoring. Offline and free: testing the instrument."""

import pytest

from eval.experiment2 import score, solver_plans
from eval.plans import (
    ImpossibleChange,
    apply_changes,
    breaks_a_rule,
    is_applicable,
    moved_something_immovable,
    remaining_problems,
)
from eval.scenarios import build


def a_scenario(name_starts: str):
    return next(s for s in build(per_kind=1) if s.name.startswith(name_starts))


def test_applying_a_reassignment_changes_who_drives():
    scenario = a_scenario("unreachable-0")
    mom = next(p for p in scenario.week.people if p.name == "Mom")
    after = apply_changes(scenario.week, [{"kind": "assign", "event_id": 112, "person_id": mom.id}])
    assert after.assigned[112] == mom.id
    assert 112 in after.driven[mom.id]


def test_applying_a_move_shifts_the_event_and_keeps_its_length():
    scenario = a_scenario("rule-clash-0")
    before = next(c for c in scenario.week.commitments if c.id == 130)
    after = apply_changes(
        scenario.week, [{"kind": "move", "event_id": 130, "start_iso": "2026-10-08T18:00"}]
    )
    moved = next(c for c in after.commitments if c.id == 130)
    assert moved.start.hour == 18
    assert moved.end - moved.start == before.end - before.start


def test_the_original_week_is_never_mutated():
    """Scoring one plan must not change the week the next plan is scored against."""
    scenario = a_scenario("rule-clash-0")
    before = [(c.id, c.start) for c in scenario.week.commitments]
    apply_changes(scenario.week, [{"kind": "move", "event_id": 130, "start_iso": "2026-10-08T18:00"}])
    assert [(c.id, c.start) for c in scenario.week.commitments] == before


@pytest.mark.parametrize(
    "change",
    [
        {"kind": "assign", "event_id": 112, "person_id": 999},
        {"kind": "move", "event_id": 999, "start_iso": "2026-10-08T18:00"},
        {"kind": "move", "event_id": 130, "start_iso": "not a time"},
        {"kind": "move", "event_id": 130},
        {"kind": "teleport", "event_id": 130},
    ],
)
def test_a_plan_that_cannot_be_carried_out_is_refused(change):
    scenario = a_scenario("rule-clash-0")
    with pytest.raises(ImpossibleChange):
        apply_changes(scenario.week, [change])
    assert is_applicable(scenario.week, [change]) is False


def test_moving_something_fixed_is_refused_and_flagged():
    scenario = a_scenario("rule-clash-0")
    plan = [{"kind": "move", "event_id": 131, "start_iso": "2026-10-08T18:00"}]  # school
    assert moved_something_immovable(scenario.week, plan) is True
    assert is_applicable(scenario.week, plan) is False


def test_an_impossible_plan_is_scored_as_fixing_nothing():
    """It must not accidentally look like a success by throwing during evaluation."""
    scenario = a_scenario("rule-clash-0")
    left = remaining_problems(scenario.week, [{"kind": "move", "event_id": 999}])
    assert left, "an impossible plan leaves the week exactly as broken as it was"


def test_doing_nothing_leaves_a_broken_week_broken():
    scenario = a_scenario("unreachable-0")
    assert remaining_problems(scenario.week, [])
    assert score("silent", [scenario], [[]]).failed_to_fix == 1


def test_a_plan_that_leaves_a_rule_broken_is_detected():
    scenario = a_scenario("rule-clash-0")
    assert breaks_a_rule(scenario.week, []) is True


def test_the_solver_fixes_every_week_that_can_be_fixed():
    scenarios = build()
    plans, timings = solver_plans(scenarios)
    outcome = score("lifepilot", scenarios, plans, timings)

    assert outcome.fixable_weeks == 15
    assert outcome.failed_to_fix == 0
    assert outcome.broke_a_rule == 0
    assert outcome.moved_something_fixed == 0
    assert outcome.impossible == 0


def test_the_solver_stays_fast_enough_for_voice():
    scenarios = build()
    plans, timings = solver_plans(scenarios)
    outcome = score("lifepilot", scenarios, plans, timings)
    assert outcome.p95_ms < 1000


def test_weeks_with_no_possible_repair_are_not_counted_against_a_repairer():
    """Admitting defeat honestly must not score worse than inventing a driver."""
    scenarios = build()
    assert sum(1 for s in scenarios if s.expected and not s.fixable) == 5
    plans, timings = solver_plans(scenarios)
    outcome = score("lifepilot", scenarios, plans, timings)
    assert outcome.weeks == 20
    assert outcome.fixable_weeks == 15
