"""Experiment 1's scenarios and scoring. Offline and free: no model call here.

Testing the measuring instrument, not the thing being measured.
"""

from eval.experiment1 import lifepilot, overlap_only, score
from eval.scenarios import Scenario, build


def test_scenarios_are_deterministic():
    assert [s.name for s in build(seed=7)] == [s.name for s in build(seed=7)]
    assert [sorted(s.expected) for s in build(seed=7)] == [sorted(s.expected) for s in build(seed=7)]


def test_the_set_is_balanced_between_broken_and_fine_weeks():
    """Without clean weeks, a detector that shouts at everything scores perfect recall."""
    scenarios = build()
    clean = [s for s in scenarios if not s.expected]
    broken = [s for s in scenarios if s.expected]
    assert len(clean) >= len(scenarios) // 3
    assert {s.planted for s in broken} == {"overlap", "unreachable", "rule_clash"}


def test_the_overlap_baseline_only_ever_reports_overlaps():
    for scenario in build():
        assert all(kind == "overlap" for kind, _ in overlap_only(scenario.week))


def test_the_overlap_baseline_is_silent_on_travel_and_rules():
    """The gap this experiment exists to measure."""
    for scenario in build():
        if scenario.planted in {"unreachable", "rule_clash"}:
            assert overlap_only(scenario.week) == set()


def test_neither_detector_raises_a_false_alarm_on_a_clean_week():
    for scenario in build():
        if scenario.expected:
            continue
        assert overlap_only(scenario.week) == set(), scenario.name
        assert lifepilot(scenario.week) == set(), scenario.name


def test_scoring_counts_a_perfect_detector_correctly():
    scenarios = build()
    result = score("lifepilot", scenarios, [lifepilot(s.week) for s in scenarios])
    assert result.false_positives == 0
    assert result.false_negatives == 0
    assert result.precision == 1.0
    assert result.recall == 1.0
    assert result.f1 == 1.0


def test_scoring_punishes_a_detector_that_calls_everything_broken():
    """The check that makes the clean scenarios earn their place."""
    scenarios = build()
    shouty = [{("overlap", c.id) for c in s.week.commitments} for s in scenarios]
    result = score("shouty", scenarios, shouty)
    assert result.precision < 0.2
    assert result.clean_weeks_called_broken == len([s for s in scenarios if not s.expected])


def test_scoring_handles_a_detector_that_says_nothing():
    scenarios = build()
    result = score("silent", scenarios, [set() for _ in scenarios])
    assert result.recall == 0.0
    assert result.f1 == 0.0
    assert result.clean_weeks_called_broken == 0


def test_per_kind_recall_is_tracked_separately():
    scenarios = build()
    result = score("overlap-only", scenarios, [overlap_only(s.week) for s in scenarios])
    assert result.by_kind_found.get("overlap") == result.by_kind_total["overlap"]
    assert result.by_kind_found.get("unreachable", 0) == 0
    assert result.by_kind_found.get("rule_clash", 0) == 0


def test_an_expected_label_is_a_kind_and_an_event_id():
    for scenario in build():
        assert isinstance(scenario, Scenario)
        for kind, event_id in scenario.expected:
            assert kind in {"overlap", "unreachable", "rule_clash"}
            assert any(c.id == event_id for c in scenario.week.commitments)
