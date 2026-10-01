"""What is actually broken about this week.

Four kinds, and only the first is what an ordinary calendar can find:

    overlap            one person in two places at once
    unreachable        a child needs a lift and no eligible adult can get there in time
    no_eligible_adult  someone could physically make it, but a family rule forbids them
    rule_clash         an event breaks a rule the family stated, like homework after 9pm

Pure, like reachability: values in, values out. Every conflict carries the per-candidate reasons, so
"why not Grandpa?" is a lookup and never a guess.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

from lifepilot.engine.reachability import (
    Candidate,
    Commitment,
    Person,
    TransportNeed,
    assess,
    reachable,
)
from lifepilot_shared.speech import say_span


@dataclass(frozen=True)
class Conflict:
    kind: str
    title: str
    when: datetime
    detail: str
    event_id: int | None = None
    candidates: tuple[Candidate, ...] = ()
    could_cover: tuple[str, ...] = ()
    assigned_to: str | None = None

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "title": self.title,
            "when": self.when.isoformat(timespec="minutes"),
            "detail": self.detail,
            "event_id": self.event_id,
            "assigned_to": self.assigned_to,
            "could_cover": list(self.could_cover),
            "candidates": [
                {
                    "name": c.name,
                    "reachable": c.reachable,
                    "reason": c.reason,
                    "arrival": c.arrival.isoformat(timespec="minutes") if c.arrival else None,
                }
                for c in self.candidates
            ],
        }


@dataclass
class Week:
    """Everything the checks need, already loaded. Keeps this module free of the database."""

    people: Sequence[Person]
    commitments: Sequence[Commitment]
    needs: Sequence[TransportNeed]
    travel: Mapping[tuple[int, int], int]
    driven: Mapping[int, frozenset[int]] = field(default_factory=dict)
    assigned: Mapping[int, int] = field(default_factory=dict)
    rules: Sequence[Mapping] = ()


def detect(week: Week) -> list[Conflict]:
    """Every conflict in the week, earliest first."""
    found = [
        *_overlaps(week),
        *_transport(week),
        *_rule_clashes(week),
    ]
    return sorted(found, key=lambda c: (c.when, c.kind, c.title))


def _overlaps(week: Week) -> list[Conflict]:
    """One person in two places at once. The only kind a shared calendar already finds."""
    names = {person.id: person.name for person in week.people}
    found = []
    for i, a in enumerate(week.commitments):
        for b in week.commitments[i + 1:]:
            shared = set(a.member_ids) & set(b.member_ids)
            if not shared or a.end <= b.start or b.end <= a.start:
                continue
            for member_id in sorted(shared):
                found.append(
                    Conflict(
                        kind="overlap",
                        title=f"{a.title} and {b.title}",
                        when=max(a.start, b.start),
                        # With the hours. "You are in two places at once" is a verdict; "the
                        # review runs 3:45 to 4:45" is the thing someone asking whether four
                        # o'clock is free actually needs to hear.
                        detail=(
                            f"{names.get(member_id, 'someone')} is in two places at once: "
                            f"{a.title} {say_span(a.start, a.end, with_day=False)} "
                            f"and {b.title} {say_span(b.start, b.end, with_day=False)}"
                        ),
                        event_id=a.id,
                    )
                )
    return found


def _transport(week: Week) -> list[Conflict]:
    """A child who needs a lift, and whether anyone eligible can actually get there."""
    eligibility = [rule["params"] for rule in week.rules if rule["type"] == "eligibility"]
    names = {person.id: person.name for person in week.people}
    found = []

    for need in week.needs:
        candidates = assess(
            need, week.people, week.commitments, week.travel, week.driven, eligibility
        )
        free = reachable(candidates)
        assignee_id = week.assigned.get(need.event_id)
        assignee = names.get(assignee_id) if assignee_id else None

        if free:
            # Someone can go. It is still broken if the person actually assigned cannot.
            if assignee and not any(c.person_id == assignee_id for c in free):
                blocked = next(c for c in candidates if c.person_id == assignee_id)
                found.append(
                    Conflict(
                        kind="unreachable",
                        title=need.title,
                        when=need.moment,
                        detail=f"{assignee} is down for it but {blocked.reason}",
                        event_id=need.event_id,
                        candidates=tuple(candidates),
                        could_cover=tuple(c.name for c in free),
                        assigned_to=assignee,
                    )
                )
            continue

        blocked_by_rule = [c for c in candidates if c.reason.startswith("rule:")]
        kind = "no_eligible_adult" if blocked_by_rule else "unreachable"
        detail = (
            f"nobody can get {need.title} covered at {need.moment.strftime('%H:%M')}"
            if kind == "unreachable"
            else f"the only people free are not allowed to cover {need.title}"
        )
        found.append(
            Conflict(
                kind=kind,
                title=need.title,
                when=need.moment,
                detail=detail,
                event_id=need.event_id,
                candidates=tuple(candidates),
                assigned_to=assignee,
            )
        )
    return found


def _rule_clashes(week: Week) -> list[Conflict]:
    """Events that break a rule the family stated out loud."""
    found = []
    for rule in week.rules:
        if rule["type"] == "latest_end":
            found.extend(_latest_end(week, rule))
        elif rule["type"] == "buffer_after":
            found.extend(_buffer_after(week, rule))
    return found


def _latest_end(week: Week, rule: Mapping) -> list[Conflict]:
    params = rule["params"]
    category = params.get("category")
    limit = _parse_clock(params["latest_end"])
    found = []
    for commitment in week.commitments:
        if category and commitment.category != category:
            continue
        if commitment.end.time() > limit:
            found.append(
                Conflict(
                    kind="rule_clash",
                    title=commitment.title,
                    when=commitment.start,
                    detail=(
                        f"{commitment.title} runs to {commitment.end.strftime('%H:%M')}, "
                        f"past your rule of {params['latest_end']}"
                    ),
                    event_id=commitment.id,
                )
            )
    return found


def _buffer_after(week: Week, rule: Mapping) -> list[Conflict]:
    """A required gap after something, for example rest after school."""
    params = rule["params"]
    person = next((p for p in week.people if p.name == params.get("member")), None)
    if person is None:
        return []

    gap = timedelta(minutes=params["minutes"])
    anchors = [
        c for c in week.commitments if c.title == params.get("after") and person.id in c.member_ids
    ]
    found = []
    for anchor in anchors:
        for other in week.commitments:
            if other.id == anchor.id or person.id not in other.member_ids:
                continue
            if anchor.end <= other.start < anchor.end + gap:
                found.append(
                    Conflict(
                        kind="rule_clash",
                        title=other.title,
                        when=other.start,
                        detail=(
                            f"{person.name} needs {params['minutes']} minutes after "
                            f"{anchor.title}, and {other.title} starts at "
                            f"{other.start.strftime('%H:%M')}"
                        ),
                        event_id=other.id,
                    )
                )
    return found


def _parse_clock(value: str) -> time:
    hour, _, minute = value.partition(":")
    return time(int(hour), int(minute or 0))
