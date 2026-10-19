"""Experiment 6: does the soft load_balance rule actually even the pickups out?

Same weeks, repaired twice: once with the family's `load_balance` rule stated, once without it.
Nothing else differs, so the spread between the two parents is attributable to the rule alone.

The weeks hand the solver lifts nobody is assigned to yet and two parents who can both reach them.
That is the only shape where load can decide anything: a lift only one adult can reach is settled by
reachability, and `fix_week` minimises change far more strongly than it evens load, so it will never
shuffle a week that already works just to tidy the split. Measuring on free choices is measuring the
rule; measuring on forced ones would report the travel table.

Reported as `CLAUDE.md` asks: spread as max - min, and standard deviation. Reported, never
headlined -- a load balancer is not what LifePilot is.
"""

import csv
import os
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import timedelta

from eval.experiment1 import RESULTS_DIR, provenance
from eval.scenarios import (
    DAD,
    GROUND,
    MOM,
    PEOPLE,
    PIANO,
    SCHOOL,
    at,
    travel_table,
)
from lifepilot.engine.conflicts import Week
from lifepilot.engine.reachability import Commitment, TransportNeed
from lifepilot.solver.repair import repair

LOAD_BALANCE = {"type": "load_balance", "params": {"between": ["Dad", "Mom"]}}
ELIGIBILITY = {"type": "eligibility", "params": {"role": "caregiver", "only_if": "no_parent_free"}}

#: Where the afternoon lifts are, and how many minutes before the pickup each parent gets free.
#: Both are reachable from both offices, which is the point: the choice is free.
PICKUP_PLACES = (GROUND, PIANO, SCHOOL)


@dataclass
class Outcome:
    """One arm: the same weeks repaired under one rule setting."""

    setting: str
    weeks: int = 0
    spreads: list[int] = field(default_factory=list)
    dad: list[int] = field(default_factory=list)
    mom: list[int] = field(default_factory=list)
    unassigned: int = 0

    @property
    def mean_spread(self) -> float:
        return statistics.fmean(self.spreads) if self.spreads else 0.0

    @property
    def spread_stdev(self) -> float:
        return statistics.pstdev(self.spreads) if len(self.spreads) > 1 else 0.0

    @property
    def worst_spread(self) -> int:
        return max(self.spreads) if self.spreads else 0

    @property
    def share_to_busiest(self) -> float:
        """What fraction of all lifts landed on whichever parent took more of them."""
        total = sum(self.dad) + sum(self.mom)
        if not total:
            return 0.0
        return max(sum(self.dad), sum(self.mom)) / total


def build_week(lifts: int, with_rule: bool) -> Week:
    """A day with `lifts` pickups nobody is assigned to, both parents free in time for all of them.

    Each parent works a morning that ends well before the first pickup, so arrival is never the
    binding constraint and the solver is choosing purely on change count, load and the tie-break.
    """
    first_pickup = 16
    commitments = [
        Commitment(
            id=900 + index,
            title="work",
            start=at(9, 0),
            end=at(12, 0),
            location_id=parent.home_location_id,
            member_ids=(parent.id,),
            category="work",
            movable=False,
        )
        for index, parent in enumerate((DAD, MOM))
    ]

    needs = []
    for index in range(lifts):
        moment = at(first_pickup) + timedelta(minutes=90 * index)
        needs.append(
            TransportNeed(
                event_id=100 + index,
                title=f"pickup {index + 1}",
                child_id=3,
                moment=moment,
                location_id=PICKUP_PLACES[index % len(PICKUP_PLACES)],
            )
        )

    rules = [ELIGIBILITY] + ([LOAD_BALANCE] if with_rule else [])
    return Week(
        people=PEOPLE,
        commitments=commitments,
        needs=needs,
        travel=travel_table(),
        driven={},
        assigned={},
        rules=tuple(rules),
    )


def _pickups(week: Week, plan) -> tuple[int, int, int]:
    """How many lifts each parent ends up with, and how many nobody took."""
    final = dict(week.assigned)
    for change in plan.changes:
        if change.kind == "assign":
            final[change.event_id] = change.person_id

    dad = sum(1 for assignee in final.values() if assignee == DAD.id)
    mom = sum(1 for assignee in final.values() if assignee == MOM.id)
    nobody = len(week.needs) - len(final)
    return dad, mom, nobody


def run(with_llm: bool = False, per_kind: int = 5, **_ignored) -> list[Outcome]:
    """Both arms over the same weeks. No model calls at all: this is solver work."""
    sizes = [2, 3, 4, 5, 6, 7, 8]
    arms = []
    for setting, with_rule in (("with load_balance", True), ("without the rule", False)):
        outcome = Outcome(setting=setting)
        for lifts in sizes:
            week = build_week(lifts, with_rule=with_rule)
            plan = repair(week)
            dad, mom, nobody = _pickups(week, plan)

            outcome.weeks += 1
            outcome.dad.append(dad)
            outcome.mom.append(mom)
            outcome.unassigned += nobody
            outcome.spreads.append(abs(dad - mom))
        arms.append(outcome)

    print_report(arms, sizes)
    meta = provenance(None)
    meta["weeks_per_arm"] = len(sizes)
    meta["lifts_per_week"] = ",".join(str(size) for size in sizes)
    path = write_csv(arms, sizes, meta)
    print(f"wrote {path}")
    return arms


def print_report(arms: Sequence[Outcome], sizes: Sequence[int]) -> None:
    print(f"\n{len(sizes)} weeks per arm, {sizes[0]} to {sizes[-1]} lifts, same weeks both ways\n")
    print(f"{'setting':<20}{'mean spread':>13}{'std dev':>10}{'worst':>8}{'busiest share':>16}")
    print("-" * 67)
    for arm in arms:
        print(
            f"{arm.setting:<20}{arm.mean_spread:>13.2f}{arm.spread_stdev:>10.2f}"
            f"{arm.worst_spread:>8}{arm.share_to_busiest:>15.1%}"
        )

    print("\nlifts each parent ended up with, by week size")
    print(f"{'lifts':<8}", end="")
    for arm in arms:
        print(f"{arm.setting:>22}", end="")
    print()
    print("-" * 52)
    for index, size in enumerate(sizes):
        print(f"{size:<8}", end="")
        for arm in arms:
            print(f"{f'Dad {arm.dad[index]} / Mom {arm.mom[index]}':>22}", end="")
        print()

    stranded = sum(arm.unassigned for arm in arms)
    print(f"\nlifts nobody was given: {stranded}")


def write_csv(arms: Sequence[Outcome], sizes: Sequence[int], meta: dict):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / "experiment6.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["# experiment", "6 - load balancing, before and after the soft rule"])
        for key, value in meta.items():
            writer.writerow([f"# {key}", value])
        writer.writerow([])
        writer.writerow(["setting", "weeks", "mean_spread", "spread_stdev", "worst_spread",
                         "busiest_share", "lifts_nobody_took"])
        for arm in arms:
            writer.writerow([
                arm.setting,
                arm.weeks,
                f"{arm.mean_spread:.3f}",
                f"{arm.spread_stdev:.3f}",
                arm.worst_spread,
                f"{arm.share_to_busiest:.3f}",
                arm.unassigned,
            ])
        writer.writerow([])
        writer.writerow(["lifts_in_week", "setting", "dad", "mom", "spread"])
        for index, size in enumerate(sizes):
            for arm in arms:
                writer.writerow([
                    size, arm.setting, arm.dad[index], arm.mom[index], arm.spreads[index],
                ])
    return path


if __name__ == "__main__":
    run(with_llm=os.environ.get("EVAL_WITH_LLM") == "1")
