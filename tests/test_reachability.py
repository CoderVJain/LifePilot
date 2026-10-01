"""Can an eligible adult actually get there? Pure functions, no DB, no model, no clock.

The scenario is the seeded Thursday, because it is the one the demo turns on:

    Aarav's football pickup is 17:00 at the ground.
    Dad's review ends 16:45 at the office, 40 minutes away  -> arrives 17:25, too late.
    Mom finishes piano at 16:45, 10 minutes away            -> arrives 16:55, in time.
    Grandpa is free at home, 18 minutes away                -> could make it, but the rule stops him.

No two events overlap, so an overlap check finds nothing wrong. That gap is the point.
"""

from datetime import datetime

from lifepilot.engine.reachability import (
    Candidate,
    Commitment,
    Person,
    TransportNeed,
    assess,
    reachable,
)

HOME, DAD_OFFICE, MOM_OFFICE, GROUND, PIANO, GRANDPA_HOME = 1, 2, 3, 4, 5, 6

TRAVEL = {
    (DAD_OFFICE, GROUND): 40,
    (PIANO, GROUND): 10,
    (GRANDPA_HOME, GROUND): 18,
    (HOME, GROUND): 15,
    (MOM_OFFICE, GROUND): 25,
    (GROUND, HOME): 15,
    (GROUND, PIANO): 10,
    (GROUND, DAD_OFFICE): 40,
}

DAD = Person(1, "Dad", "parent", can_drive=True, home_location_id=HOME)
MOM = Person(2, "Mom", "parent", can_drive=True, home_location_id=HOME)
AARAV = Person(3, "Aarav", "child", can_drive=False, home_location_id=HOME)
GRANDPA = Person(5, "Grandpa", "caregiver", can_drive=True, home_location_id=GRANDPA_HOME)
PEOPLE = [DAD, MOM, AARAV, GRANDPA]


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, 8, hour, minute)


REVIEW = Commitment(10, "performance review", at(15, 45), at(16, 45), DAD_OFFICE, (DAD.id,))
PIANO_CLASS = Commitment(11, "piano class", at(16, 0), at(16, 45), PIANO, (4,))
FOOTBALL = Commitment(12, "football practice", at(16, 0), at(17, 0), GROUND, (AARAV.id,))

# Mom is not a member of piano; she drives it. That is why `driven` exists.
DRIVEN = {MOM.id: frozenset({PIANO_CLASS.id})}

PICKUP = TransportNeed(FOOTBALL.id, "football practice", AARAV.id, at(17, 0), GROUND)

ELIGIBILITY = [{"role": "caregiver", "only_if": "no_parent_free"}]


def by_name(candidates) -> dict[str, Candidate]:
    return {c.name: c for c in candidates}


def test_dad_cannot_reach_the_pickup_and_the_reason_says_why():
    who = by_name(assess(PICKUP, PEOPLE, [REVIEW, PIANO_CLASS, FOOTBALL], TRAVEL, DRIVEN, ELIGIBILITY))
    assert who["Dad"].reachable is False
    assert who["Dad"].reason == "arrives 17:25, needs 17:00"
    assert who["Dad"].arrival == at(17, 25)


def test_mom_can_reach_it_after_piano():
    who = by_name(assess(PICKUP, PEOPLE, [REVIEW, PIANO_CLASS, FOOTBALL], TRAVEL, DRIVEN, ELIGIBILITY))
    assert who["Mom"].reachable is True
    assert who["Mom"].arrival == at(16, 55)
    assert who["Mom"].slack_minutes == 5


def test_a_child_is_never_a_candidate():
    who = by_name(assess(PICKUP, PEOPLE, [REVIEW, PIANO_CLASS, FOOTBALL], TRAVEL, DRIVEN, ELIGIBILITY))
    assert who["Aarav"].reachable is False
    assert who["Aarav"].reason == "cannot drive"


def test_grandpa_is_blocked_by_the_rule_not_by_distance():
    """He could physically make it. The rule is what stops him, and the reason must say so."""
    who = by_name(assess(PICKUP, PEOPLE, [REVIEW, PIANO_CLASS, FOOTBALL], TRAVEL, DRIVEN, ELIGIBILITY))
    assert who["Grandpa"].reachable is False
    assert who["Grandpa"].reason == "rule: only when no parent is free"
    assert who["Grandpa"].arrival == at(17, 0)


def test_grandpa_becomes_eligible_once_no_parent_can_go():
    """Same rule, opposite outcome: Mom now has a clash, so the caregiver is allowed."""
    mom_stuck = Commitment(13, "late meeting", at(16, 30), at(17, 30), MOM_OFFICE, (MOM.id,))
    who = by_name(
        assess(PICKUP, PEOPLE, [REVIEW, PIANO_CLASS, FOOTBALL, mom_stuck], TRAVEL, {}, ELIGIBILITY)
    )
    assert who["Mom"].reachable is False
    assert who["Grandpa"].reachable is True


def test_the_event_being_staffed_does_not_count_as_being_there():
    """Whoever is already assigned must not appear to be at the ground already. This was a real bug."""
    already = {DAD.id: frozenset({FOOTBALL.id})}
    who = by_name(assess(PICKUP, PEOPLE, [REVIEW, PIANO_CLASS, FOOTBALL], TRAVEL, already, ELIGIBILITY))
    assert who["Dad"].reachable is False
    assert who["Dad"].arrival == at(17, 25)


def test_the_return_leg_is_checked_too():
    """Reaching the pickup is not enough if it strands them from the next thing."""
    dinner = Commitment(14, "parents evening", at(17, 10), at(18, 0), DAD_OFFICE, (MOM.id,))
    who = by_name(
        assess(PICKUP, PEOPLE, [PIANO_CLASS, FOOTBALL, dinner], TRAVEL, DRIVEN, ELIGIBILITY)
    )
    assert who["Mom"].reachable is False
    assert "would reach parents evening at 17:45" in who["Mom"].reason
    assert "starts 17:10" in who["Mom"].reason


def test_an_unknown_route_is_refused_not_guessed():
    nowhere = TransportNeed(99, "chess club", AARAV.id, at(17, 0), 42)
    who = by_name(assess(nowhere, PEOPLE, [REVIEW, PIANO_CLASS], TRAVEL, DRIVEN, ELIGIBILITY))
    assert who["Dad"].reason == "no known route to the place"


def test_someone_with_nothing_on_starts_from_home_and_is_not_held_up():
    who = by_name(assess(PICKUP, [GRANDPA], [], TRAVEL, {}, ()))
    assert who["Grandpa"].reachable is True
    assert who["Grandpa"].arrival == at(17, 0)


def test_the_shortlist_is_ranked_by_slack():
    candidates = [
        Candidate(1, "Dad", True, "", arrival=at(16, 55), slack_minutes=5),
        Candidate(2, "Mom", True, "", arrival=at(16, 30), slack_minutes=30),
        Candidate(5, "Grandpa", False, "rule: only when no parent is free"),
    ]
    assert [c.name for c in reachable(candidates)] == ["Mom", "Dad"]


def test_someone_busy_at_that_exact_moment_is_ruled_out_before_any_travel_maths():
    """A meeting running straight through the pickup. Looking only at what ends earlier misses it."""
    straddling = Commitment(15, "late meeting", at(16, 30), at(17, 30), MOM_OFFICE, (MOM.id,))
    who = by_name(assess(PICKUP, [MOM], [FOOTBALL, straddling], TRAVEL, {}, ()))
    assert who["Mom"].reachable is False
    assert who["Mom"].reason == "is at late meeting until 17:30"
