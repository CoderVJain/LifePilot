"""What is broken about the week, and of what kind. Pure, offline, free.

The seeded Thursday is the fixture because it is the demo: a pickup nobody assigned can reach, while
no two events overlap at all.
"""

from datetime import datetime

from lifepilot.engine.conflicts import Week, detect
from lifepilot.engine.reachability import Commitment, Person, TransportNeed

HOME, DAD_OFFICE, MOM_OFFICE, GROUND, PIANO = 1, 2, 3, 4, 5
GRANDPA_HOME = 6

TRAVEL = {
    (DAD_OFFICE, GROUND): 40, (GROUND, DAD_OFFICE): 40,
    (PIANO, GROUND): 10, (GROUND, PIANO): 10,
    (GRANDPA_HOME, GROUND): 18, (GROUND, GRANDPA_HOME): 18,
    (HOME, GROUND): 15, (GROUND, HOME): 15,
    (MOM_OFFICE, GROUND): 25, (GROUND, MOM_OFFICE): 25,
    (MOM_OFFICE, PIANO): 15, (PIANO, MOM_OFFICE): 15,
}

DAD = Person(1, "Dad", "parent", True, HOME)
MOM = Person(2, "Mom", "parent", True, HOME)
AARAV = Person(3, "Aarav", "child", False, HOME)
ANAYA = Person(4, "Anaya", "child", False, HOME)
GRANDPA = Person(5, "Grandpa", "caregiver", True, GRANDPA_HOME)
PEOPLE = [DAD, MOM, AARAV, ANAYA, GRANDPA]


def at(hour, minute=0):
    return datetime(2026, 10, 8, hour, minute)


REVIEW = Commitment(10, "performance review", at(15, 45), at(16, 45), DAD_OFFICE, (DAD.id,), "work")
PIANO_CLASS = Commitment(11, "piano class", at(16), at(16, 45), PIANO, (ANAYA.id,), "activity")
FOOTBALL = Commitment(12, "football practice", at(16), at(17), GROUND, (AARAV.id,), "activity")
PROJECT = Commitment(13, "science project block", at(20), at(21, 30), HOME, (AARAV.id,), "study")

RULES = [
    {"type": "eligibility", "params": {"role": "caregiver", "only_if": "no_parent_free"}},
    {"type": "latest_end", "params": {"category": "study", "latest_end": "21:00"}},
    {"type": "buffer_after", "params": {"member": "Aarav", "after": "school", "minutes": 30}},
]

PICKUP = TransportNeed(FOOTBALL.id, "football pickup", AARAV.id, at(17), GROUND)


def week(**overrides) -> Week:
    base = dict(
        people=PEOPLE,
        commitments=[REVIEW, PIANO_CLASS, FOOTBALL, PROJECT],
        needs=[PICKUP],
        travel=TRAVEL,
        driven={MOM.id: frozenset({PIANO_CLASS.id})},
        assigned={FOOTBALL.id: DAD.id},
        rules=RULES,
    )
    base.update(overrides)
    return Week(**base)


def kinds(conflicts):
    return [c.kind for c in conflicts]


def test_the_seeded_week_has_no_overlaps_at_all():
    """The whole premise: a calendar overlap check finds nothing wrong with this week."""
    assert "overlap" not in kinds(detect(week()))


def test_the_thursday_pickup_is_reported_unreachable_for_the_assigned_parent():
    found = [c for c in detect(week()) if c.kind == "unreachable"]
    assert len(found) == 1
    conflict = found[0]
    assert conflict.assigned_to == "Dad"
    assert "arrives 17:25, needs 17:00" in conflict.detail
    assert conflict.could_cover == ("Mom",)


def test_every_candidate_reason_is_recorded_for_why_not_questions():
    conflict = next(c for c in detect(week()) if c.kind == "unreachable")
    reasons = {c.name: c.reason for c in conflict.candidates}
    assert reasons["Dad"] == "arrives 17:25, needs 17:00"
    assert reasons["Aarav"] == "cannot drive"
    assert reasons["Grandpa"] == "rule: only when no parent is free"
    assert "10 minutes away" in reasons["Mom"]


def test_the_late_project_block_is_a_rule_clash():
    found = [c for c in detect(week()) if c.kind == "rule_clash"]
    assert len(found) == 1
    assert "runs to 21:30, past your rule of 21:00" in found[0].detail


def test_no_eligible_adult_is_distinguished_from_simply_unreachable():
    """Grandpa could physically make it; only the rule stops him. That is a different problem."""
    mom_busy = Commitment(14, "late meeting", at(16, 30), at(17, 30), MOM_OFFICE, (MOM.id,), "work")
    dad_busy = Commitment(15, "long review", at(15, 45), at(17, 30), DAD_OFFICE, (DAD.id,), "work")
    found = detect(
        week(commitments=[PIANO_CLASS, FOOTBALL, mom_busy, dad_busy], driven={}, assigned={})
    )
    # Both parents are busy at 17:00, so the rule lets Grandpa in and nothing is broken.
    assert "no_eligible_adult" not in kinds(found)
    assert "unreachable" not in kinds(found)


def test_when_nobody_can_reach_it_at_all():
    far = Commitment(16, "all day offsite", at(9), at(18), DAD_OFFICE, (DAD.id,), "work")
    mom_far = Commitment(17, "all day offsite", at(9), at(18), MOM_OFFICE, (MOM.id,), "work")
    grandpa_far = Commitment(18, "away", at(9), at(18), GRANDPA_HOME, (GRANDPA.id,), "other")
    found = [
        c
        for c in detect(week(commitments=[FOOTBALL, far, mom_far, grandpa_far], driven={}, assigned={}))
        if c.kind == "unreachable"
    ]
    assert len(found) == 1
    assert "nobody can get football pickup covered at 17:00" in found[0].detail


def test_an_actual_overlap_is_still_caught():
    clash = Commitment(19, "dentist", at(16, 30), at(17, 30), HOME, (AARAV.id,), "other")
    found = [c for c in detect(week(commitments=[FOOTBALL, clash])) if c.kind == "overlap"]
    assert len(found) == 1
    assert "Aarav is in two places at once" in found[0].detail


def test_the_buffer_rule_catches_something_too_soon_after_school():
    school = Commitment(20, "school", at(8), at(15), HOME, (AARAV.id,), "school")
    straight_after = Commitment(21, "tuition", at(15, 10), at(16), HOME, (AARAV.id,), "study")
    found = [
        c
        for c in detect(week(commitments=[school, straight_after], needs=[], assigned={}))
        if c.kind == "rule_clash" and c.title == "tuition"
    ]
    assert len(found) == 1
    assert "needs 30 minutes after school" in found[0].detail


def test_conflicts_come_back_in_time_order():
    found = detect(week())
    assert [c.when for c in found] == sorted(c.when for c in found)


def test_a_conflict_serialises_for_the_wire():
    conflict = next(c for c in detect(week()) if c.kind == "unreachable")
    payload = conflict.as_dict()
    assert payload["kind"] == "unreachable"
    assert payload["assigned_to"] == "Dad"
    assert payload["could_cover"] == ["Mom"]
    assert {c["name"] for c in payload["candidates"]} == {"Dad", "Mom", "Aarav", "Anaya", "Grandpa"}


def test_an_overlap_says_the_hours_not_just_that_there_is_one():
    """Someone asking "do I have work at 4?" needs the hours, not a verdict."""
    clash = Commitment(22, "client call", at(16), at(17), HOME, (DAD.id,), "work")
    found = [c for c in detect(week(commitments=[REVIEW, clash], needs=[], assigned={}))
             if c.kind == "overlap"]

    assert len(found) == 1
    detail = found[0].detail
    assert "Dad is in two places at once" in detail
    assert "3:45 PM to 4:45 PM" in detail, "when the review actually runs"
    assert "4 PM to 5 PM" in detail
    assert "15:45" not in detail
