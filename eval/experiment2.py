"""Experiment 2: plan feasibility. AI only vs AI + solver.

Both repairers get the same broken weeks and return changes in the same shape. Both plans are then
applied and handed to the same conflict detector, so neither is marked by its own homework.

Reported: how often a plan still breaks a family rule, how often it leaves the week broken at all,
how many changes it takes, and how long the solver needs -- median and p95, because a voice turn
cannot wait on the tail.
"""

import csv
import os
import statistics
import time
from collections.abc import Sequence
from dataclasses import dataclass, field

from eval.experiment1 import RESULTS_DIR, provenance
from eval.plans import breaks_a_rule, is_applicable, moved_something_immovable, remaining_problems
from eval.scenarios import Scenario, build
from lifepilot.solver.repair import repair


@dataclass
class Outcome:
    repairer: str
    weeks: int = 0
    fixable_weeks: int = 0
    failed_to_fix: int = 0
    still_broken: int = 0
    broke_a_rule: int = 0
    moved_something_fixed: int = 0
    impossible: int = 0
    changes: list[int] = field(default_factory=list)
    solve_ms: list[int] = field(default_factory=list)

    def _share(self, count: int) -> float:
        return count / self.weeks if self.weeks else 0.0

    @property
    def rule_breaking_share(self) -> float:
        return self._share(self.broke_a_rule)

    @property
    def failed_to_fix_share(self) -> float:
        """Of the weeks that could be fixed, how many were left broken. The fair denominator."""
        return self.failed_to_fix / self.fixable_weeks if self.fixable_weeks else 0.0

    @property
    def mean_changes(self) -> float:
        return statistics.mean(self.changes) if self.changes else 0.0

    @property
    def median_ms(self) -> float:
        return statistics.median(self.solve_ms) if self.solve_ms else 0.0

    @property
    def p95_ms(self) -> float:
        if not self.solve_ms:
            return 0.0
        ordered = sorted(self.solve_ms)
        return ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]


def solver_plans(scenarios: Sequence[Scenario]) -> tuple[list[list[dict]], list[int]]:
    plans, timings = [], []
    for scenario in scenarios:
        if not scenario.expected:
            plans.append([])
            timings.append(0)
            continue
        result = repair(scenario.week)
        plans.append([c.as_dict() for c in result.changes])
        timings.append(result.solve_ms)
    return plans, timings


def score(
    repairer: str, scenarios: Sequence[Scenario], plans: Sequence[Sequence[dict]],
    timings: Sequence[int] | None = None,
) -> Outcome:
    outcome = Outcome(repairer)
    for index, (scenario, plan) in enumerate(zip(scenarios, plans, strict=True)):
        if not scenario.expected:
            continue  # nothing to repair; those weeks are experiment 1's job
        outcome.weeks += 1
        outcome.changes.append(len(plan))
        if scenario.fixable:
            outcome.fixable_weeks += 1
        if timings:
            outcome.solve_ms.append(timings[index])

        if not is_applicable(scenario.week, plan):
            outcome.impossible += 1
            outcome.still_broken += 1
            if scenario.fixable:
                outcome.failed_to_fix += 1
            continue
        if moved_something_immovable(scenario.week, plan):
            outcome.moved_something_fixed += 1
        if remaining_problems(scenario.week, plan):
            outcome.still_broken += 1
            if scenario.fixable:
                outcome.failed_to_fix += 1
        if breaks_a_rule(scenario.week, plan):
            outcome.broke_a_rule += 1
    return outcome


def print_table(outcomes: Sequence[Outcome]) -> None:
    total, fixable = outcomes[0].weeks, outcomes[0].fixable_weeks
    print(f"\n{total} broken weeks, of which {fixable} can actually be repaired\n")
    print(f"{'repairer':<16}{'breaks a rule':>15}{'left broken':>13}{'changes':>10}"
          f"{'median ms':>11}{'p95 ms':>9}")
    print("-" * 74)
    for o in outcomes:
        print(
            f"{o.repairer:<16}{o.rule_breaking_share:>14.1%}{o.failed_to_fix_share:>13.1%}"
            f"{o.mean_changes:>10.1f}{o.median_ms:>11.0f}{o.p95_ms:>9.0f}"
        )
    print('"left broken" counts only the weeks a repair existed for.')
    print("\nplans that could not even be carried out, and plans that moved something fixed")
    print("-" * 75)
    for o in outcomes:
        print(
            f'{o.repairer:<16}{o.impossible:>3} impossible   '
            f'{o.moved_something_fixed:>3} moved a fixed event'
        )


def write_csv(outcomes: Sequence[Outcome], meta: dict):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / "experiment2.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["# experiment", "2 - plan feasibility"])
        for key, value in meta.items():
            writer.writerow([f"# {key}", value])
        writer.writerow(["# broken weeks", outcomes[0].weeks])
        writer.writerow(["# of those, repairable", outcomes[0].fixable_weeks])
        writer.writerow([])
        writer.writerow([
            "repairer", "rule_breaking_share", "failed_to_fix_share", "mean_changes",
            "median_solve_ms", "p95_solve_ms", "impossible_plans", "moved_a_fixed_event",
        ])
        for o in outcomes:
            writer.writerow([
                o.repairer,
                f"{o.rule_breaking_share:.3f}",
                f"{o.failed_to_fix_share:.3f}",
                f"{o.mean_changes:.2f}",
                f"{o.median_ms:.0f}",
                f"{o.p95_ms:.0f}",
                o.impossible,
                o.moved_something_fixed,
            ])
    return path


def run(with_llm: bool = False, per_kind: int = 5) -> list[Outcome]:
    scenarios = build(per_kind=per_kind)
    started = time.perf_counter()
    plans, timings = solver_plans(scenarios)
    outcomes = [score("lifepilot", scenarios, plans, timings)]
    model_id = None

    if with_llm:
        from eval.llm_repair import estimate_calls, repair_all

        print(f"model repairer: about {estimate_calls(scenarios)} calls to Bedrock")
        ai_plans, model_id = repair_all(scenarios)
        outcomes.append(score("ai-only", scenarios, ai_plans))

    meta = provenance(model_id)
    meta["solver_wall_seconds"] = round(time.perf_counter() - started, 2)
    print_table(outcomes)
    path = write_csv(outcomes, meta)
    print(f"\nwrote {path}")
    return outcomes


if __name__ == "__main__":
    run(with_llm=os.environ.get("EVAL_WITH_LLM") == "1")
