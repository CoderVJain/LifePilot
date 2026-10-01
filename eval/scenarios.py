"""Labelled weeks for experiment 1: some broken in a known way, some deliberately fine.

Every scenario carries the exact set of conflicts a correct detector should report, so precision and
recall are both measurable. The near-misses matter as much as the plants: a detector that calls
everything broken has perfect recall and is useless, and only the clean cases expose that.

Seeded and deterministic: the same seed builds the same weeks, so a result can be reproduced.
"""

import random
from dataclasses import dataclass
from datetime import datetime, timedelta

from lifepilot.engine.conflicts import Week
from lifepilot.engine.reachability import Commitment, Person, TransportNeed

HOME, DAD_OFFICE, MOM_OFFICE, SCHOOL, GROUND, PIANO, GRANDPA_HOME = 1, 2, 3, 4, 5, 6, 7

BASE_TRAVEL = {
    (HOME, DAD_OFFICE): 35,
    (HOME, MOM_OFFICE): 20,
    (HOME, SCHOOL): 12,
    (HOME, GROUND): 15,
    (HOME, PIANO): 10,
    (HOME, GRANDPA_HOME): 8,
    (DAD_OFFICE, MOM_OFFICE): 25,
    (DAD_OFFICE, SCHOOL): 38,
    (DAD_OFFICE, GROUND): 40,
    (DAD_OFFICE, PIANO): 35,
    (DAD_OFFICE, GRANDPA_HOME): 40,
    (MOM_OFFICE, SCHOOL): 22,
    (MOM_OFFICE, GROUND): 25,
    (MOM_OFFICE, PIANO): 15,
    (MOM_OFFICE, GRANDPA_HOME): 25,
    (SCHOOL, GROUND): 10,
    (SCHOOL, PIANO): 14,
    (SCHOOL, GRANDPA_HOME): 15,
    (GROUND, PIANO): 10,
    (GROUND, GRANDPA_HOME): 18,
    (PIANO, GRANDPA_HOME): 12,
}

DAD = Person(1, "Dad", "parent", True, HOME)
MOM = Person(2, "Mom", "parent", True, HOME)
AARAV = Person(3, "Aarav", "child", False, HOME)
ANAYA = Person(4, "Anaya", "child", False, HOME)
GRANDPA = Person(5, "Grandpa", "caregiver", True, GRANDPA_HOME)
PEOPLE = (DAD, MOM, AARAV, ANAYA, GRANDPA)

ELIGIBILITY = {"type": "eligibility", "params": {"role": "caregiver", "only_if": "no_parent_free"}}
LATEST_END = {"type": "latest_end", "params": {"category": "study", "latest_end": "21:00"}}
RULES = (ELIGIBILITY, LATEST_END)

DAY = datetime(2026, 10, 8)


def travel_table() -> dict[tuple[int, int], int]:
    """Symmetric, with a zero diagonal, the way the seeded database stores it."""
    table: dict[tuple[int, int], int] = {}
    for (a, b), minutes in BASE_TRAVEL.items():
        table[(a, b)] = minutes
        table[(b, a)] = minutes
    for place in (HOME, DAD_OFFICE, MOM_OFFICE, SCHOOL, GROUND, PIANO, GRANDPA_HOME):
        table[(place, place)] = 0
    return table


def at(hour: int, minute: int = 0) -> datetime:
    return DAY.replace(hour=hour, minute=minute)


@dataclass(frozen=True)
class Scenario:
    """One week, and the conflicts a correct detector should report as (kind, event_id) pairs.

    `fixable` is ground truth about whether a repair exists at all. Some weeks genuinely cannot be
    saved -- every adult is busy through the pickup and the event is pinned by the lift -- and a
    repairer that admits it should not be marked down beside one that invents a driver.
    """

    name: str
    planted: str
    week: Week
    expected: frozenset[tuple[str, int]]
    fixable: bool = True


def _week(commitments, needs=(), assigned=None, driven=None, rules=RULES) -> Week:
    return Week(
        people=PEOPLE,
        commitments=list(commitments),
        needs=list(needs),
        travel=travel_table(),
        driven={k: frozenset(v) for k, v in (driven or {}).items()},
        assigned=assigned or {},
        rules=rules,
    )


def _school(child: Person, event_id: int) -> Commitment:
    return Commitment(event_id, "school", at(8), at(15), SCHOOL, (child.id,), "school", False)


def build(seed: int = 7, per_kind: int = 5) -> list[Scenario]:
    """A deterministic mix of planted conflicts and near-misses."""
    rng = random.Random(seed)
    scenarios: list[Scenario] = []
    for index in range(per_kind):
        scenarios.append(_overlap(rng, index))
        scenarios.append(_unreachable(rng, index))
        scenarios.append(_nobody_can_reach(rng, index))
        scenarios.append(_rule_clash(rng, index))
        scenarios.append(_clean_tight_but_feasible(rng, index))
        scenarios.append(_clean_adjacent_not_overlapping(rng, index))
        scenarios.append(_clean_rule_exactly_met(rng, index))
    return scenarios


def _overlap(rng: random.Random, index: int) -> Scenario:
    """One child in two places at once. The only kind a shared calendar can find."""
    start = at(16, rng.choice([0, 15, 30]))
    football = Commitment(100, "football practice", start, start + timedelta(hours=1), GROUND,
                          (AARAV.id,), "activity")
    dentist = Commitment(101, "dentist", start + timedelta(minutes=30),
                         start + timedelta(minutes=90), HOME, (AARAV.id,), "other", False)
    week = _week([_school(AARAV, 102), football, dentist])
    return Scenario(f"overlap-{index}", "overlap", week, frozenset({("overlap", 100)}))


def _unreachable(rng: random.Random, index: int) -> Scenario:
    """The assigned parent cannot cover the travel, though someone else could."""
    pickup_at = at(17, rng.choice([0, 15]))
    review = Commitment(110, "performance review", pickup_at - timedelta(minutes=75),
                        pickup_at - timedelta(minutes=15), DAD_OFFICE, (DAD.id,), "work", False)
    piano = Commitment(111, "piano class", pickup_at - timedelta(hours=1),
                       pickup_at - timedelta(minutes=15), PIANO, (ANAYA.id,), "activity", False)
    football = Commitment(112, "football practice", pickup_at - timedelta(hours=1), pickup_at,
                          GROUND, (AARAV.id,), "activity")
    need = TransportNeed(112, "football practice pickup", AARAV.id, pickup_at, GROUND)
    week = _week(
        [review, piano, football],
        needs=[need],
        assigned={112: DAD.id},
        driven={MOM.id: {111}},
    )
    return Scenario(f"unreachable-{index}", "unreachable", week, frozenset({("unreachable", 112)}))


def _nobody_can_reach(rng: random.Random, index: int) -> Scenario:
    """Every adult is tied up through the pickup, so there is genuinely no one to send.

    Note on a label that was wrong first time round: an earlier version left Grandpa free and
    expected a conflict, reasoning that the grandparent rule would block him. It does not. The rule
    is "only when both parents are busy", and both parents being busy is exactly this case, so the
    rule *admits* him and nothing is broken. The detector was right and the label was wrong.
    """
    pickup_at = at(17, rng.choice([0, 30]))
    late = pickup_at + timedelta(minutes=30)
    dad_busy = Commitment(120, "client visit", at(9), late, DAD_OFFICE, (DAD.id,), "work", False)
    mom_busy = Commitment(121, "workshop", at(9), late, MOM_OFFICE, (MOM.id,), "work", False)
    grandpa_busy = Commitment(123, "hospital appointment", at(9), late, GRANDPA_HOME,
                              (GRANDPA.id,), "other", False)
    football = Commitment(122, "football practice", pickup_at - timedelta(hours=1), pickup_at,
                          GROUND, (AARAV.id,), "activity")
    need = TransportNeed(122, "football practice pickup", AARAV.id, pickup_at, GROUND)
    week = _week([dad_busy, mom_busy, grandpa_busy, football], needs=[need])
    return Scenario(
        f"unreachable-nobody-{index}",
        "unreachable",
        week,
        frozenset({("unreachable", 122)}),
        fixable=False,
    )


def _rule_clash(rng: random.Random, index: int) -> Scenario:
    """Homework running past the family's stated cut-off."""
    end_minutes = rng.choice([15, 30, 45])
    study = Commitment(130, "science project block", at(20), at(21, end_minutes), HOME,
                       (AARAV.id,), "study")
    week = _week([_school(AARAV, 131), study])
    return Scenario(f"rule-clash-{index}", "rule_clash", week, frozenset({("rule_clash", 130)}))


def _clean_tight_but_feasible(rng: random.Random, index: int) -> Scenario:
    """Mom arrives with minutes to spare. Nothing is broken, and saying so is the hard part."""
    pickup_at = at(17, 0)
    spare = rng.choice([5, 10, 20])
    piano = Commitment(140, "piano class", pickup_at - timedelta(hours=1),
                       pickup_at - timedelta(minutes=10 + spare), PIANO, (ANAYA.id,), "activity", False)
    football = Commitment(141, "football practice", pickup_at - timedelta(hours=1), pickup_at,
                          GROUND, (AARAV.id,), "activity")
    need = TransportNeed(141, "football practice pickup", AARAV.id, pickup_at, GROUND)
    week = _week([piano, football], needs=[need], assigned={141: MOM.id}, driven={MOM.id: {140}})
    return Scenario(f"clean-tight-{index}", "none", week, frozenset())


def _clean_adjacent_not_overlapping(rng: random.Random, index: int) -> Scenario:
    """Back-to-back events that touch but do not overlap. A careless check calls this a clash."""
    gap = rng.choice([0, 5, 15])
    first = Commitment(150, "art club", at(15, 30), at(16, 30), SCHOOL, (ANAYA.id,), "activity")
    second = Commitment(151, "piano class", at(16, 30) + timedelta(minutes=gap),
                        at(17, 30) + timedelta(minutes=gap), PIANO, (ANAYA.id,), "activity", False)
    week = _week([_school(ANAYA, 152), first, second])
    return Scenario(f"clean-adjacent-{index}", "none", week, frozenset())


def _clean_rule_exactly_met(rng: random.Random, index: int) -> Scenario:
    """Homework ending exactly on the limit. Off-by-one territory, and it is not a breach."""
    start_hour = rng.choice([19, 20])
    study = Commitment(160, "homework", at(start_hour), at(21), HOME, (AARAV.id,), "study")
    week = _week([_school(AARAV, 161), study])
    return Scenario(f"clean-on-the-limit-{index}", "none", week, frozenset())
