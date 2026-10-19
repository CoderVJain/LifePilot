"""Weeks for experiment 3, each one where the cheapest repair breaks a rule unless it is known.

A scenario is only informative if the rule actually bites. A week where the obvious repair happens
to respect the rule proves nothing about storing it, because both arms would return the same plan.
So each of these is built so that the plan the solver prefers on change count alone is the one the
parent would refuse, and only knowing the rule steers it elsewhere.

One kind per rule type the project supports and the solver can act on: `immovable_event`,
`latest_end`, `buffer_after`, `eligibility`. `load_balance` is soft and has experiment 6.

Seeded and deterministic, like `eval/scenarios.py`, which this borrows its family and travel table
from so the two experiments cannot disagree about how far anything is.
"""

import random
from dataclasses import dataclass
from datetime import timedelta

from eval.scenarios import (
    AARAV,
    ANAYA,
    DAD,
    DAD_OFFICE,
    GRANDPA,
    GRANDPA_HOME,
    GROUND,
    HOME,
    MOM,
    MOM_OFFICE,
    PEOPLE,
    PIANO,
    SCHOOL,
    at,
    travel_table,
)
from lifepilot.engine.conflicts import Week
from lifepilot.engine.reachability import Commitment, TransportNeed

IMMOVABLE_PIANO = {"type": "immovable_event", "params": {"title": "piano class"}}
NO_LATE_STUDY = {"type": "latest_end", "params": {"category": "study", "latest_end": "21:00"}}
REST_AFTER_SCHOOL = {
    "type": "buffer_after",
    "params": {"member": "Aarav", "after": "school", "minutes": 30},
}
GRANDPA_LAST = {"type": "eligibility", "params": {"role": "caregiver", "only_if": "no_parent_free"}}


@dataclass(frozen=True)
class RuleScenario:
    """One week, and the rule the parent holds about it.

    `week` is the truth: the family's rules, and the events they consider fixed. The experiment
    strips that down for the arm that has not been told, and judges both against this.
    """

    name: str
    rule_type: str
    week: Week
    #: "repair" judges what `fix_week` proposes; "decide" judges who `suggest_responsible` offers.
    #: Eligibility cannot be breached by a repair at all -- see `_eligibility`.
    path: str = "repair"


def _week(commitments, needs=(), assigned=None, driven=None, rules=()) -> Week:
    return Week(
        people=PEOPLE,
        commitments=list(commitments),
        needs=list(needs),
        travel=travel_table(),
        driven={k: frozenset(v) for k, v in (driven or {}).items()},
        assigned=assigned or {},
        rules=tuple(rules),
    )


def _work(event_id: int, person, place: int, until_hour: int, until_minute: int = 0) -> Commitment:
    return Commitment(
        event_id, "work", at(9), at(until_hour, until_minute), place, (person.id,), "work", False
    )


def _school(child, event_id: int, ends_hour: int = 15) -> Commitment:
    return Commitment(
        event_id, "school", at(8), at(ends_hour), SCHOOL, (child.id,), "school", False
    )


def _immovable(rng: random.Random, index: int) -> RuleScenario:
    """Anaya's piano clashes with her own dentist, and moving piano is the cheaper repair.

    Both are hers, so the overlap must be resolved by moving one of them. The dentist is pinned, so
    with no rule about piano the solver moves piano -- one change, perfectly rational, and the thing
    the parent said never to do.
    """
    start = at(16, rng.choice([0, 15]))
    piano = Commitment(200, "piano class", start, start + timedelta(minutes=45), PIANO,
                       (ANAYA.id,), "activity", False)
    # Pinned: a booked appointment. So moving piano is the only single change available, and the
    # arm that knows the rule has to report that it cannot fix the week rather than break it. That
    # is the correct behaviour, which is why this experiment reports "left broken" beside
    # violations -- a clean sheet earned by proposing nothing is not a success.
    dentist = Commitment(201, "dentist", start + timedelta(minutes=15),
                         start + timedelta(minutes=75), HOME, (ANAYA.id,), "other", False)
    week = _week(
        [_school(ANAYA, 202), piano, dentist],
        rules=(IMMOVABLE_PIANO,),
    )
    return RuleScenario(f"immovable-{index}", "immovable_event", week)


def _latest_end(rng: random.Random, index: int) -> RuleScenario:
    """Aarav's project block overlaps his cricket, and the free slot is after nine.

    The evening is full until late, so the nearest place to put the study block runs past the 9 PM
    rule. Knowing the rule, the solver has to move cricket instead.
    """
    cricket_at = at(19, rng.choice([0, 30]))
    # Fixed, like any coached session. Movable, it gave the solver a second one-change repair that
    # happened to respect the rule, so on some draws the blind arm came out clean by luck and the
    # scenario measured nothing. Worse, the two plans cost exactly the same and the solver returned
    # either one, which made the experiment flaky about once in six runs.
    cricket = Commitment(210, "cricket practice", cricket_at, cricket_at + timedelta(hours=1),
                         GROUND, (AARAV.id,), "activity", False)
    project = Commitment(211, "science project block", cricket_at + timedelta(minutes=30),
                         cricket_at + timedelta(minutes=120), HOME, (AARAV.id,), "study")
    week = _week(
        [_school(AARAV, 212), cricket, project],
        rules=(NO_LATE_STUDY,),
    )
    return RuleScenario(f"latest-end-{index}", "latest_end", week)


def _buffer_after(rng: random.Random, index: int) -> RuleScenario:
    """Aarav's tuition overlaps football, and the only gap left is the minute school ends.

    School finishes at three and he is owed half an hour. Cricket pins the evening, so sliding
    tuition back into the 3 o'clock gap is both the single cheapest change and the nearest slot to
    where it already was -- and it breaks the rest he is owed.
    """
    football = Commitment(220, "football practice", at(16), at(17), GROUND,
                          (AARAV.id,), "activity")
    tuition = Commitment(221, "maths tuition", at(15, 45), at(16, 45), HOME,
                         (AARAV.id,), "other")
    # The evening is taken, so the only gap left is the one school just ended into. Sliding tuition
    # back there is the single cheapest change, and the nearest slot to where it already was.
    cricket = Commitment(223, "cricket practice", at(17), at(19, rng.choice([0, 30])), GROUND,
                         (AARAV.id,), "activity", False)
    week = _week(
        [_school(AARAV, 222), football, tuition, cricket],
        rules=(REST_AFTER_SCHOOL,),
    )
    return RuleScenario(f"buffer-{index}", "buffer_after", week)


def _eligibility(rng: random.Random, index: int) -> RuleScenario:
    """Grandpa is free and nearest; Mom is free too. The family said he goes last.

    Judged on the **decide** path, because a repair cannot breach this rule at all. `parent_free` is
    worked out per lift from physical reachability: if a parent can reach it the rule removes
    Grandpa, whom the tie-break would not have chosen anyway, and if no parent can reach it the rule
    permits him. It only ever removes a candidate the solver did not want.

    Where it does bite is "who should go" and "why not Grandpa" -- differentiators #2 and #3. So the
    question here is whether Grandpa is *offered*: without the rule he leads the ranking, because he
    is doing nothing and is eighteen minutes away while Mom is twenty-five.
    """
    pickup_at = at(17, rng.choice([0, 15]))
    dad_work = _work(230, DAD, DAD_OFFICE, pickup_at.hour, pickup_at.minute)
    # Mom finishes in time to reach the ground, so a parent is free and the rule applies.
    mom_work = _work(231, MOM, MOM_OFFICE, pickup_at.hour - 1)
    football = Commitment(232, "football practice", pickup_at - timedelta(hours=1), pickup_at,
                          GROUND, (AARAV.id,), "activity")
    need = TransportNeed(232, "football practice pickup", AARAV.id, pickup_at, GROUND)
    week = _week(
        [_school(AARAV, 233), dad_work, mom_work, football],
        needs=[need],
        assigned={232: DAD.id},
        rules=(GRANDPA_LAST,),
    )
    return RuleScenario(f"eligibility-{index}", "eligibility", week, path="decide")


def build(seed: int = 7, per_kind: int = 5) -> list[RuleScenario]:
    """A deterministic set, one week per rule type per round."""
    rng = random.Random(seed)
    scenarios: list[RuleScenario] = []
    for index in range(per_kind):
        scenarios.append(_immovable(rng, index))
        scenarios.append(_latest_end(rng, index))
        scenarios.append(_buffer_after(rng, index))
        scenarios.append(_eligibility(rng, index))
    return scenarios


__all__ = ["RuleScenario", "build", "GRANDPA", "GRANDPA_HOME"]
