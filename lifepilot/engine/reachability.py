"""Can an eligible adult actually get this child there, counting travel time?

Pure: plain values in, plain values out. No database, no model call, no clock. That makes it cheap to
test exhaustively and impossible for it to be wrong in a way a test cannot pin down.

A conflict in LifePilot is not "two events overlap". It is a child who needs to be somewhere and no
eligible adult who can reach them, which an overlap check cannot see.

Every candidate carries the reason they were ruled out, recorded where the decision was made. That is
what makes "why not Grandpa?" a lookup rather than a guess.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

# Minutes to hand the child over: park, find them, get them in the car. Applied on the return leg so
# an assignment cannot look feasible by assuming a teleport.
HANDOVER_MINUTES = 5


@dataclass(frozen=True)
class Person:
    id: int
    name: str
    role: str
    can_drive: bool
    home_location_id: int | None = None


@dataclass(frozen=True)
class Commitment:
    """Somewhere a person must physically be between two times."""

    id: int
    title: str
    start: datetime
    end: datetime
    location_id: int | None
    member_ids: tuple[int, ...] = ()
    category: str = ""
    movable: bool = True


@dataclass(frozen=True)
class TransportNeed:
    """A child must be at `location_id` at `moment`, and someone has to drive them."""

    event_id: int
    title: str
    child_id: int
    moment: datetime
    location_id: int
    kind: str = "pickup"


@dataclass(frozen=True)
class Candidate:
    person_id: int
    name: str
    reachable: bool
    reason: str
    arrival: datetime | None = None
    slack_minutes: int | None = None
    travel_minutes: int | None = None


def travel_minutes(travel: Mapping[tuple[int, int], int], origin: int | None, destination: int) -> int | None:
    """Minutes between two places, or None when we have no entry and must not guess."""
    if origin is None:
        return None
    if origin == destination:
        return 0
    return travel.get((origin, destination))


def assess(
    need: TransportNeed,
    people: Sequence[Person],
    commitments: Sequence[Commitment],
    travel: Mapping[tuple[int, int], int],
    driven: Mapping[int, frozenset[int]] | None = None,
    eligibility: Sequence[Mapping] = (),
) -> list[Candidate]:
    """Who could actually do this run, and for everyone else, why not.

    Physical reachability is decided first for every driver, because a rule like "grandparents only
    when both parents are busy" cannot be applied until we know whether a parent is free.
    """
    driven = driven or {}
    physical = [_assess_one(person, need, commitments, travel, driven) for person in people]
    return _apply_eligibility(physical, people, eligibility)


def _assess_one(
    person: Person,
    need: TransportNeed,
    commitments: Sequence[Commitment],
    travel: Mapping[tuple[int, int], int],
    driven: Mapping[int, frozenset[int]],
) -> Candidate:
    if not person.can_drive:
        return Candidate(person.id, person.name, False, "cannot drive")

    theirs = _commitments_of(person, commitments, driven, excluding=need.event_id)

    busy = _busy_at(theirs, need.moment)
    if busy is not None:
        return Candidate(
            person.id, person.name, False, f"is at {busy.title} until {_clock(busy.end)}"
        )

    origin, leaving = _where_they_come_from(person, theirs, need.moment)

    minutes = travel_minutes(travel, origin, need.location_id)
    if minutes is None:
        return Candidate(person.id, person.name, False, "no known route to the place")

    if leaving is None:
        # Nothing holds them beforehand, so they can arrive on time whatever the distance.
        blocked = _return_leg_problem(person, theirs, need, travel)
        if blocked is not None:
            return Candidate(person.id, person.name, False, blocked, arrival=need.moment)
        return Candidate(
            person.id,
            person.name,
            True,
            f"nothing on beforehand, {minutes} minutes away",
            arrival=need.moment,
            travel_minutes=minutes,
        )

    arrival = leaving + timedelta(minutes=minutes)
    if arrival > need.moment:
        return Candidate(
            person.id,
            person.name,
            False,
            f"arrives {_clock(arrival)}, needs {_clock(need.moment)}",
            arrival=arrival,
        )

    blocked = _return_leg_problem(person, theirs, need, travel)
    if blocked is not None:
        return Candidate(person.id, person.name, False, blocked, arrival=arrival)

    slack = int((need.moment - arrival).total_seconds() // 60)
    return Candidate(
        person.id,
        person.name,
        True,
        f"free from {_clock(leaving)}, {minutes} minutes away",
        arrival=arrival,
        slack_minutes=slack,
        travel_minutes=minutes,
    )


def _commitments_of(
    person: Person,
    commitments: Sequence[Commitment],
    driven: Mapping[int, frozenset[int]],
    excluding: int,
) -> list[Commitment]:
    """Where this person must be, and when.

    Attending something ties them up for its whole length. *Driving* someone to it does not: they
    turn up at the end to collect. Treating a collection as an hour at the touchline makes a parent
    who drives two children look doubly busy and rules out plans that work perfectly well.

    The event being staffed is excluded, or whoever holds it would count as standing there already.
    """
    drives = driven.get(person.id, frozenset())
    theirs = []
    for commitment in commitments:
        if commitment.id == excluding:
            continue
        if person.id in commitment.member_ids:
            theirs.append(commitment)
        elif commitment.id in drives:
            theirs.append(replace(commitment, start=commitment.end))
    return theirs


def _busy_at(theirs: Sequence[Commitment], moment: datetime) -> Commitment | None:
    """A commitment straddling the moment rules them out before any travel maths.

    Looking only at what ends before the moment silently ignores a meeting running straight through
    it, which is the plain-overlap case an ordinary calendar would catch.
    """
    for commitment in theirs:
        if commitment.start <= moment < commitment.end:
            return commitment
    return None


def _where_they_come_from(
    person: Person, theirs: Sequence[Commitment], moment: datetime
) -> tuple[int | None, datetime | None]:
    """Where they set off from, and when they are free to leave.

    A `None` leaving time means nothing holds them beforehand: they can set off as early as they
    like, so travel time cannot make them late.
    """
    before = [c for c in theirs if c.end <= moment]
    if not before:
        return person.home_location_id, None
    last = max(before, key=lambda c: c.end)
    return last.location_id, last.end


def _return_leg_problem(
    person: Person,
    theirs: Sequence[Commitment],
    need: TransportNeed,
    travel: Mapping[tuple[int, int], int],
) -> str | None:
    """Would taking this run make them late for whatever they have next?"""
    after = [c for c in theirs if c.start >= need.moment]
    if not after:
        return None
    nxt = min(after, key=lambda c: c.start)

    minutes = travel_minutes(travel, need.location_id, nxt.location_id)
    if minutes is None:
        return None

    back = need.moment + timedelta(minutes=HANDOVER_MINUTES + minutes)
    if back > nxt.start:
        return f"would reach {nxt.title} at {_clock(back)}, and it starts {_clock(nxt.start)}"
    return None


def _apply_eligibility(
    candidates: Sequence[Candidate], people: Sequence[Person], rules: Sequence[Mapping]
) -> list[Candidate]:
    """Rules that depend on who else is free, applied once physical reachability is known."""
    roles = {person.id: person.role for person in people}
    parent_free = any(c.reachable and roles.get(c.person_id) == "parent" for c in candidates)

    decided = []
    for candidate in candidates:
        blocked_by = _rule_blocking(candidate, roles.get(candidate.person_id), rules, parent_free)
        if candidate.reachable and blocked_by:
            decided.append(
                Candidate(
                    candidate.person_id,
                    candidate.name,
                    False,
                    blocked_by,
                    arrival=candidate.arrival,
                    slack_minutes=candidate.slack_minutes,
                    travel_minutes=candidate.travel_minutes,
                )
            )
        else:
            decided.append(candidate)
    return decided


def _rule_blocking(
    candidate: Candidate, role: str | None, rules: Sequence[Mapping], parent_free: bool
) -> str | None:
    for rule in rules:
        if rule.get("role") != role:
            continue
        if rule.get("only_if") == "no_parent_free" and parent_free:
            return "rule: only when no parent is free"
    return None


def reachable(candidates: Sequence[Candidate]) -> list[Candidate]:
    """The ones who could do it, least constrained first, so the caller has a ranked shortlist.

    `slack_minutes is None` means nothing holds them beforehand, which is the freest case of all.
    """
    return sorted(
        (c for c in candidates if c.reachable),
        key=lambda c: (0 if c.slack_minutes is None else 1, -(c.slack_minutes or 0), c.name),
    )


def _clock(moment: datetime) -> str:
    return moment.strftime("%H:%M")
