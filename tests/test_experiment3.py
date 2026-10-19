"""Experiment 3: storing the family's rules has to change what gets proposed.

The trap this guards is the persona marking its own homework. Every judgement must be made against
the rules the parent holds, never against whatever the system was given -- otherwise the arm that
knows nothing has nothing to fail and scores perfectly.
"""

from eval.experiment3 import run
from eval.persona import review, strip_rules
from eval.rulescenarios import build
from lifepilot.solver.repair import repair


def test_stripping_rules_removes_both_the_rows_and_the_pins():
    """A rule stated once leaves two marks: the rule row, and the movable=False it implies."""
    piano_week = next(s.week for s in build(per_kind=1) if s.rule_type == "immovable_event")
    blind = strip_rules(piano_week)

    assert piano_week.rules and not blind.rules
    piano = next(c for c in blind.commitments if c.title == "piano class")
    assert piano.movable is True, "the pin outlived the rule that explains it"


def test_stripping_rules_keeps_pins_that_are_not_family_rules():
    """Work and school are facts, not rules. Unpinning them would make the arm miss more than
    the rules it is supposed to be missing."""
    week = next(s.week for s in build(per_kind=1) if s.rule_type == "eligibility")
    blind = strip_rules(week)
    for title in ("work", "school"):
        for commitment in blind.commitments:
            if commitment.title == title:
                assert commitment.movable is False, title


def test_every_scenario_actually_bites():
    """A scenario where the rule does not matter proves nothing about storing it, because both
    arms return the same plan. This is the assertion that keeps the experiment meaningful.

    Every draw, not just the first: this ran at `per_kind=1` and missed a later draw whose blind
    arm had a second, equally cheap repair that respected the rule by luck. The solver returned
    either plan, and the experiment failed about one run in six.
    """
    for scenario in build(per_kind=5):
        truth = scenario.week
        blind = strip_rules(truth)
        if scenario.path != "repair":
            continue
        changes = [c.as_dict() for c in repair(blind).changes]
        verdict = review(truth, changes)
        assert scenario.rule_type in verdict.violations, (
            f"{scenario.name}: the blind arm respected the rule anyway, so it measures nothing"
        )


def test_the_same_scenarios_repair_the_same_way_every_time():
    """A flaky headline is not a headline. Two equally cheap plans with nothing to choose between
    them made this experiment non-deterministic until the ambiguity was taken out of the week."""
    runs = {
        tuple((arm.setting, arm.accepted, arm.with_a_violation, arm.left_broken) for arm in run(per_kind=5))
        for _ in range(4)
    }
    assert len(runs) == 1, f"the experiment is not reproducible: {runs}"


def test_knowing_the_rules_is_what_makes_a_plan_acceptable():
    stored, blind = run(per_kind=5)
    assert stored.setting == "rules stored"
    assert stored.acceptance == 1.0
    assert stored.violation_rate == 0.0
    assert blind.acceptance == 0.0
    assert blind.violation_rate == 1.0


def test_the_rule_aware_arm_refuses_rather_than_breaking_a_promise():
    """The immovable weeks have no legal repair. Reporting that is correct, and it is why
    "left broken" is published beside violations -- a clean sheet from proposing nothing is not
    a success."""
    stored, _ = run(per_kind=5)
    assert stored.proposed_nothing > 0
    assert 0.0 < stored.still_broken_rate < 1.0


def test_an_eligibility_rule_keeps_a_barred_carer_off_the_shortlist():
    stored, blind = run(per_kind=5)
    assert stored.offered_someone_barred == 0
    assert blind.barred_rate == 1.0
