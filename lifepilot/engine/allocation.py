"""Who should do it, and why, in one sentence.

The ranking is an explicit tuple sort over reachable candidates. The reason is derived from the sort
rather than written beside it: whichever factor first separates the winner from the runner-up is the
one we say out loud. An explanation produced any other way is free to drift from the decision, and a
family will notice long before a test does.

Pure: candidates and loads in, a ranked list out. No database, no model call.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from lifepilot.engine.reachability import Candidate

# Order matters: this is the family's priority, not an implementation detail. Fewer pickups first
# only when the family asked for balance; then whoever is nearest; then whoever has most room.
FACTORS = ("load", "travel", "slack")

FACTOR_REASONS = {
    "load": "{name} has done fewer pickups this week",
    "travel": "{name} is only {travel} minutes away",
    "slack": "{name} has the most room either side",
}


@dataclass(frozen=True)
class Choice:
    name: str
    person_id: int
    reason: str
    deciding_factor: str
    load: int
    travel_minutes: int | None
    slack_minutes: int | None


def rank(
    candidates: Sequence[Candidate],
    loads: Mapping[int, int] | None = None,
    balance_load: bool = True,
) -> list[Choice]:
    """Reachable candidates, best first, each carrying why it beat the next one.

    `balance_load` is on only when the family has a load_balance rule; without it, proximity leads.
    """
    loads = loads or {}
    free = [c for c in candidates if c.reachable]
    if not free:
        return []

    ordered = sorted(free, key=lambda c: _key(c, loads, balance_load))
    choices = []
    for position, candidate in enumerate(ordered):
        runner_up = ordered[position + 1] if position + 1 < len(ordered) else None
        factor = _deciding_factor(candidate, runner_up, loads, balance_load)
        choices.append(
            Choice(
                name=candidate.name,
                person_id=candidate.person_id,
                reason=_reason(candidate, factor, loads),
                deciding_factor=factor,
                load=loads.get(candidate.person_id, 0),
                travel_minutes=candidate.travel_minutes,
                slack_minutes=candidate.slack_minutes,
            )
        )
    return choices


def _key(candidate: Candidate, loads: Mapping[int, int], balance_load: bool) -> tuple:
    return (
        loads.get(candidate.person_id, 0) if balance_load else 0,
        candidate.travel_minutes if candidate.travel_minutes is not None else 10**6,
        -_slack(candidate),
        candidate.name,
    )


def _slack(candidate: Candidate) -> int:
    """`None` means nothing holds them beforehand, which is the freest case, not the tightest."""
    return 10**6 if candidate.slack_minutes is None else candidate.slack_minutes


def _deciding_factor(
    winner: Candidate, runner_up: Candidate | None, loads: Mapping[int, int], balance_load: bool
) -> str:
    """The first factor on which the winner actually beat the next best. `tie` when none did."""
    if runner_up is None:
        return "only_one"
    a = _key(winner, loads, balance_load)
    b = _key(runner_up, loads, balance_load)
    for index, factor in enumerate(FACTORS):
        if a[index] != b[index]:
            return factor
    return "tie"


def _reason(candidate: Candidate, factor: str, loads: Mapping[int, int]) -> str:
    if factor == "only_one":
        return f"{candidate.name} is the only one who can get there"
    if factor == "tie":
        return f"{candidate.name} can get there, and so could the others"
    template = FACTOR_REASONS[factor]
    return template.format(
        name=candidate.name,
        travel=candidate.travel_minutes,
        load=loads.get(candidate.person_id, 0),
    )
