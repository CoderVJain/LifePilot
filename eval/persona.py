"""The scripted parent for experiment 3: rules in their head, and a yes or no.

The persona is deterministic on purpose. "Would a parent accept this?" is the question experiment 3
turns on, and asking a model would mean the thing under test also marks the paper. So the persona is
a function: it holds the family's rules, reads a proposal, and says no if the proposal breaks one.

The rules live **only** in the persona. Whether LifePilot has been told them is the experiment's
independent variable, so every judgement is made against the persona's copy and never against
whatever the system happened to have stored. A plan is never marked by its own homework.

Each breach is reported by rule type, so the result says *which* rule gets broken when LifePilot does
not know it, rather than only how often something went wrong.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from eval.plans import moved_something_immovable, remaining_problems
from lifepilot.engine.conflicts import Week
from lifepilot.engine.reachability import assess


@dataclass(frozen=True)
class Review:
    """One parent's verdict on one proposal."""

    accepted: bool
    violations: tuple[str, ...]

    @property
    def clean(self) -> bool:
        return not self.violations


def review(truth: Week, changes: Sequence[dict]) -> Review:
    """What the parent makes of this plan, judged against the rules they actually hold.

    `truth` is the week as the family understands it: their rules, and the events they consider
    fixed. A proposal is accepted only if it breaks none of them -- a parent who would accept a plan
    that moves piano does not have a rule about piano.
    """
    found: list[str] = []

    if moved_something_immovable(truth, changes):
        found.append("immovable_event")

    found.extend(_rules_broken(truth, changes))
    found.extend(_ineligible_assignees(truth, changes))

    ordered = tuple(sorted(set(found)))
    return Review(accepted=not ordered, violations=ordered)


def _rules_broken(truth: Week, changes: Sequence[dict]) -> list[str]:
    """Which stated rules the applied plan breaches, by type.

    Attribution is structural: the week is handed to the detector once per rule, carrying only that
    rule, so any clash it reports belongs to it. Reading the rule out of the detector's sentence
    would work until somebody rewords the sentence, and the anchor's own name appears in it.
    """
    found = []
    for rule in truth.rules:
        if rule["type"] not in ("latest_end", "buffer_after"):
            continue
        alone = _only_rule(truth, rule)
        if any(problem.kind == "rule_clash" for problem in remaining_problems(alone, changes)):
            found.append(rule["type"])
    return found


def _only_rule(truth: Week, rule: Mapping) -> Week:
    """The same week carrying exactly one of its rules."""
    return Week(
        people=truth.people,
        commitments=truth.commitments,
        needs=truth.needs,
        travel=truth.travel,
        driven=truth.driven,
        assigned=truth.assigned,
        rules=(rule,),
    )


def _ineligible_assignees(truth: Week, changes: Sequence[dict]) -> list[str]:
    """Lifts the plan handed to somebody the family's own rules rule out.

    Judged with the product's own `assess`, carrying the persona's eligibility rules: if the person
    the plan chose is not among the candidates those rules allow, the plan used someone the family
    said not to use. Reusing `assess` matters -- a second implementation here could disagree with
    the one the product ships and the experiment would be measuring the disagreement.
    """
    eligibility = [rule["params"] for rule in truth.rules if rule["type"] == "eligibility"]
    if not eligibility:
        return []

    needs = {need.event_id: need for need in truth.needs}
    found = []
    for change in changes:
        if change.get("kind") != "assign":
            continue
        need = needs.get(change.get("event_id"))
        if need is None:
            continue
        allowed = {
            candidate.person_id
            for candidate in assess(
                need, truth.people, truth.commitments, truth.travel, truth.driven, eligibility
            )
            if candidate.reachable
        }
        if change.get("person_id") not in allowed:
            found.append("eligibility")
    return found


def strip_rules(week: Week, keep: Sequence[str] = ()) -> Week:
    """The same week as LifePilot would hold it having never been told the family's rules.

    Two things go, because a rule stated once leaves two marks: the rule rows themselves, and the
    `movable = False` flags that an `immovable_event` rule is stored as. Dropping only the rows
    would leave piano pinned for a reason the system could no longer explain, and the arm would
    quietly keep half the knowledge it is supposed to be missing.
    """
    kept = tuple(rule for rule in week.rules if rule["type"] in keep)
    pinned = _pinned_without_a_rule(week, kept)
    commitments = [
        commitment if commitment.id in pinned else _as_movable(commitment)
        for commitment in week.commitments
    ]
    return Week(
        people=week.people,
        commitments=commitments,
        needs=week.needs,
        travel=week.travel,
        driven=week.driven,
        assigned=week.assigned,
        rules=kept,
    )


def _pinned_without_a_rule(week: Week, kept: Sequence[Mapping]) -> set[int]:
    """Events still legitimately fixed: work and school are facts, not family rules.

    A parent does not state a rule that the office exists. Only the events an `immovable_event` rule
    accounts for are unpinned here, so the arm is missing the family's rules and nothing else.
    """
    titles = {
        str(rule["params"].get("title", "")).lower()
        for rule in week.rules
        if rule["type"] == "immovable_event"
    }
    titles |= {
        str(rule["params"].get("title", "")).lower()
        for rule in kept
        if rule["type"] == "immovable_event"
    }
    return {
        commitment.id
        for commitment in week.commitments
        if not commitment.movable and commitment.title.lower() not in titles
    }


def _as_movable(commitment):
    from dataclasses import replace

    return replace(commitment, movable=True)
