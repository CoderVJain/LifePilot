"""Experiment 3: family rules, stored versus not stored.

The same weeks twice. One arm has been told the family's rules; the other has not. A scripted parent
with the rules in their head reads each proposal and accepts or refuses it. Nothing else differs, so
every refusal is attributable to the missing rule.

Both arms are judged against the persona's copy of the rules, never against whatever the system had
stored -- otherwise the arm that knows nothing has nothing to fail, which is the whole trap. See
`eval/persona.py`.

Two metrics, because one of them alone lies. **Violations** say whether the plan broke a promise.
**Left broken** says whether it fixed anything: told the rule, the solver sometimes reports that it
cannot repair the week without breaking it, which is correct behaviour and scores no violations --
and a clean sheet earned by proposing nothing is not a success. `CLAUDE.md` is explicit that
LifePilot never quietly drops a rule to make a plan fit.

Eligibility is judged on the decide path rather than the repair path, because a repair cannot
breach it at all; `eval/rulescenarios.py` explains why.
"""

import csv
import os
from collections.abc import Sequence
from dataclasses import dataclass, field

from eval.experiment1 import RESULTS_DIR, provenance
from eval.persona import review, strip_rules
from eval.plans import remaining_problems
from eval.rulescenarios import build
from lifepilot.engine.allocation import rank
from lifepilot.engine.reachability import assess
from lifepilot.solver.repair import repair


@dataclass
class Arm:
    """One setting: every scenario run with the rules stored, or with them missing."""

    setting: str
    weeks: int = 0
    accepted: int = 0
    with_a_violation: int = 0
    left_broken: int = 0
    proposed_nothing: int = 0
    by_rule: dict[str, int] = field(default_factory=dict)
    decided: int = 0
    offered_someone_barred: int = 0

    def _share(self, count: int, of: int | None = None) -> float:
        total = self.weeks if of is None else of
        return count / total if total else 0.0

    @property
    def acceptance(self) -> float:
        return self._share(self.accepted)

    @property
    def violation_rate(self) -> float:
        return self._share(self.with_a_violation)

    @property
    def still_broken_rate(self) -> float:
        return self._share(self.left_broken)

    @property
    def barred_rate(self) -> float:
        return self._share(self.offered_someone_barred, self.decided)


def _run_repair(arm: Arm, truth, given) -> None:
    plan = repair(given)
    changes = [change.as_dict() for change in plan.changes]
    verdict = review(truth, changes)

    arm.weeks += 1
    if verdict.accepted:
        arm.accepted += 1
    if verdict.violations:
        arm.with_a_violation += 1
    for rule_type in verdict.violations:
        arm.by_rule[rule_type] = arm.by_rule.get(rule_type, 0) + 1
    if not changes:
        arm.proposed_nothing += 1
    if remaining_problems(truth, changes):
        arm.left_broken += 1


def _run_decide(arm: Arm, truth, given) -> None:
    """Who the ranking would offer. A rule the family stated must keep them off the list."""
    eligibility = [rule["params"] for rule in given.rules if rule["type"] == "eligibility"]
    barred = {
        person.id
        for person in truth.people
        if any(
            person.role == rule["params"].get("role")
            for rule in truth.rules
            if rule["type"] == "eligibility"
        )
    }

    arm.decided += 1
    for need in given.needs:
        candidates = assess(
            need, given.people, given.commitments, given.travel, given.driven, eligibility
        )
        offered = rank(candidates, loads={}, balance_load=False)
        parent_offered = any(
            person.role == "parent"
            for choice in offered
            for person in truth.people
            if person.id == choice.person_id
        )
        chosen_barred = [c for c in offered if c.person_id in barred]
        # Only a breach while a parent could have gone: the rule is "last resort", not "never".
        if chosen_barred and parent_offered:
            arm.offered_someone_barred += 1
            arm.by_rule["eligibility"] = arm.by_rule.get("eligibility", 0) + 1
            break


def run(with_llm: bool = False, per_kind: int = 5, **_ignored) -> list[Arm]:
    """Both arms over the same scenarios. No model calls: rules are solver and engine work."""
    scenarios = build(per_kind=per_kind)
    arms = []
    for setting, stored in (("rules stored", True), ("rules not stored", False)):
        arm = Arm(setting=setting)
        for scenario in scenarios:
            truth = scenario.week
            given = truth if stored else strip_rules(truth)
            if scenario.path == "repair":
                _run_repair(arm, truth, given)
            else:
                _run_decide(arm, truth, given)
        arms.append(arm)

    print_report(arms, scenarios)
    meta = provenance(None)
    meta["scenarios"] = len(scenarios)
    meta["per_kind"] = per_kind
    path = write_csv(arms, meta)
    print(f"wrote {path}")
    return arms


def print_report(arms: Sequence[Arm], scenarios: Sequence) -> None:
    repairs = sum(1 for s in scenarios if s.path == "repair")
    decides = len(scenarios) - repairs
    print(f"\n{len(scenarios)} scenarios: {repairs} repairs, {decides} decisions, both ways\n")
    print(f"{'setting':<20}{'accepted':>10}{'broke a rule':>14}{'left broken':>13}"
          f"{'proposed nothing':>19}")
    print("-" * 76)
    for arm in arms:
        print(
            f"{arm.setting:<20}{arm.acceptance:>10.1%}{arm.violation_rate:>14.1%}"
            f"{arm.still_broken_rate:>13.1%}{arm.proposed_nothing:>19}"
        )

    print("\non the decide path, how often somebody the rules bar was offered anyway")
    for arm in arms:
        print(f"  {arm.setting:<20}{arm.barred_rate:>8.1%}  ({arm.decided} decisions)")

    print("\nwhich rule got broken, by arm")
    every = sorted({rule for arm in arms for rule in arm.by_rule})
    if not every:
        print("  none, in either arm")
    for rule_type in every:
        counts = "  ".join(f"{arm.setting}: {arm.by_rule.get(rule_type, 0)}" for arm in arms)
        print(f"  {rule_type:<18}{counts}")


def write_csv(arms: Sequence[Arm], meta: dict):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / "experiment3.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["# experiment", "3 - family rules, stored versus not stored"])
        for key, value in meta.items():
            writer.writerow([f"# {key}", value])
        writer.writerow([])
        writer.writerow(["setting", "weeks", "acceptance", "violation_rate", "still_broken_rate",
                         "proposed_nothing", "decisions", "offered_someone_barred"])
        for arm in arms:
            writer.writerow([
                arm.setting,
                arm.weeks,
                f"{arm.acceptance:.3f}",
                f"{arm.violation_rate:.3f}",
                f"{arm.still_broken_rate:.3f}",
                arm.proposed_nothing,
                arm.decided,
                arm.offered_someone_barred,
            ])
        writer.writerow([])
        writer.writerow(["rule_type", "setting", "times_broken"])
        for rule_type in sorted({rule for arm in arms for rule in arm.by_rule}):
            for arm in arms:
                writer.writerow([rule_type, arm.setting, arm.by_rule.get(rule_type, 0)])
    return path


if __name__ == "__main__":
    run(with_llm=os.environ.get("EVAL_WITH_LLM") == "1")
