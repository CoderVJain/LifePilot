"""Experiment 6: the soft load_balance rule has to actually change the split.

The rule was the one the solver applied whether or not the family had stated it, so these also pin
that it is now conditional -- a rule that is always on cannot be measured with-versus-without.
"""

from eval.experiment6 import build_week, run
from lifepilot.solver.repair import _balances_load, repair


def test_the_rule_is_only_applied_when_the_family_stated_it():
    assert _balances_load(build_week(4, with_rule=True)) is True
    assert _balances_load(build_week(4, with_rule=False)) is False


def test_both_arms_leave_every_lift_covered():
    """A split is only comparable if both arms actually assigned everything."""
    for with_rule in (True, False):
        week = build_week(6, with_rule=with_rule)
        plan = repair(week)
        assigned = {c.event_id for c in plan.changes if c.kind == "assign"}
        assert len(assigned) == len(week.needs), with_rule


def test_the_rule_evens_the_pickups_out():
    """The experiment's claim, as a test: stating the rule narrows the spread."""
    with_rule, without = run()
    assert with_rule.setting.startswith("with")
    assert with_rule.mean_spread < without.mean_spread
    assert with_rule.worst_spread <= 1


def test_without_the_rule_one_parent_takes_everything():
    """Not malice: with nothing to prefer Mom by, the deterministic tie-break orders by person id.
    That is the honest baseline, and it is why the rule is worth stating."""
    _, without = run()
    assert without.share_to_busiest == 1.0


def test_the_same_week_always_splits_the_same_way():
    """Reruns are stable, or the spread is noise rather than a result."""
    first = [repair(build_week(n, True)).change_count for n in (3, 5, 7)]
    second = [repair(build_week(n, True)).change_count for n in (3, 5, 7)]
    assert first == second
