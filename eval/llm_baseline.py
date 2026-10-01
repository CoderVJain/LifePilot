"""The AI-only baseline for experiment 1: Nova Micro given the same week, asked what is broken.

It gets exactly what LifePilot's engine gets -- people, events, the travel table, the family rules and
who is down for each lift -- so the comparison is about reasoning, not about information. One call per
scenario, through `lifepilot_shared.llm` like every other model call.
"""

import os
from collections.abc import Sequence

from eval.scenarios import Scenario
from lifepilot_shared.llm import Turn as Budget
from lifepilot_shared.llm import converse, model_id

PLACES = {
    1: "home",
    2: "dad office",
    3: "mom office",
    4: "school",
    5: "football ground",
    6: "piano school",
    7: "grandpa home",
}

REPORT_TOOL = {
    "toolSpec": {
        "name": "report_conflicts",
        "description": "Report every problem in this family's week. Report nothing if it all works.",
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {
                    "conflicts": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "event_id": {
                                    "type": "integer",
                                    "description": "The id of the event the problem is about.",
                                },
                                "kind": {
                                    "type": "string",
                                    "enum": ["overlap", "unreachable", "rule_clash"],
                                },
                            },
                            "required": ["event_id", "kind"],
                        },
                    }
                },
                "required": ["conflicts"],
            }
        },
    }
}

SYSTEM = [
    {
        "text": (
            "You check whether a family's week actually works. A problem is one of: "
            "'overlap' -- one person in two places at once; "
            "'unreachable' -- a child needs collecting and the adult down for it cannot get there "
            "in time once travel is counted, or nobody eligible can; "
            "'rule_clash' -- an event breaks one of the family's stated rules. "
            "Count travel time between places. Only adults who can drive may collect a child. "
            "Report a problem only when there really is one. Call report_conflicts exactly once."
        )
    }
]


def describe(scenario: Scenario) -> str:
    """The same information the engine gets, written out for a model to read."""
    week = scenario.week
    lines = ["PEOPLE"]
    for person in week.people:
        drives = "can drive" if person.can_drive else "cannot drive"
        lines.append(f"  {person.name} ({person.role}, {drives})")

    lines.append("EVENTS")
    for c in week.commitments:
        who = ", ".join(p.name for p in week.people if p.id in c.member_ids) or "family"
        where = PLACES.get(c.location_id, "unknown")
        lines.append(
            f"  id={c.id} {c.title} [{c.category}] {c.start:%a %H:%M}-{c.end:%H:%M} "
            f"at {where}, for {who}"
        )

    driving = [
        (names, event_id)
        for names, ids in (
            ((p.name,), week.driven.get(p.id, frozenset())) for p in week.people
        )
        for event_id in ids
    ]
    if driving:
        # Whoever drives an event is at its place when it ends, which decides where they set off
        # from next. Leaving this out would hand the engine information the baseline never saw.
        lines.append("WHO IS ALREADY DRIVING")
        for (name,), event_id in driving:
            event = next((c for c in week.commitments if c.id == event_id), None)
            if event is not None:
                lines.append(
                    f"  {name} is taking care of event id={event_id} ({event.title}), so at "
                    f"{event.end:%H:%M} {name} is at {PLACES.get(event.location_id)}"
                )

    if week.needs:
        lines.append("LIFTS NEEDED")
        names = {p.id: p.name for p in week.people}
        for need in week.needs:
            assigned = week.assigned.get(need.event_id)
            down_for_it = names.get(assigned, "nobody yet")
            lines.append(
                f"  event id={need.event_id}: a child must be collected from "
                f"{PLACES.get(need.location_id)} at {need.moment:%a %H:%M}. {down_for_it} is down for it."
            )

    lines.append("TRAVEL MINUTES")
    seen = set()
    for (a, b), minutes in sorted(week.travel.items()):
        if a == b or (b, a) in seen:
            continue
        seen.add((a, b))
        lines.append(f"  {PLACES.get(a)} to {PLACES.get(b)}: {minutes}")

    lines.append("FAMILY RULES")
    for rule in week.rules:
        if rule["type"] == "eligibility":
            lines.append("  a grandparent may only collect when both parents are busy")
        elif rule["type"] == "latest_end":
            lines.append(f"  no {rule['params']['category']} after {rule['params']['latest_end']}")

    return "\n".join(lines)


def estimate_calls(scenarios: Sequence[Scenario]) -> int:
    return len(scenarios) + 1  # one extra for the plumbing check below


def can_report(budget: Budget) -> bool:
    """Can the model emit a non-empty conflict list at all, when told exactly what to emit?

    A baseline that scores zero is only meaningful if it *could* have scored above zero. This
    separates "the model did not find the problems" from "the harness never let it say so", and the
    difference is the whole credibility of the comparison.
    """
    response = converse(
        messages=[
            {
                "role": "user",
                "content": [{"text": "Report exactly one conflict: event_id 100, kind overlap."}],
            }
        ],
        system=[{"text": "You report conflicts using the tool."}],
        tool_config={"tools": [REPORT_TOOL], "toolChoice": {"tool": {"name": "report_conflicts"}}},
        turn=budget,
        max_tokens=200,
    )
    blocks = response["output"]["message"]["content"]
    uses = [block["toolUse"] for block in blocks if "toolUse" in block]
    if not uses:
        return False
    return bool((uses[0].get("input") or {}).get("conflicts"))


def predict_all(scenarios: Sequence[Scenario]) -> tuple[list[set[tuple[str, int]]], str]:
    """One call per scenario, under a hard ceiling so a loop cannot run the bill up."""
    ceiling = int(os.environ.get("EVAL_MAX_CALLS", "200"))
    needed = estimate_calls(scenarios)
    if needed > ceiling:
        raise RuntimeError(f"{needed} calls needed but EVAL_MAX_CALLS is {ceiling}")

    budget = Budget(max_calls=ceiling)
    if not can_report(budget):
        raise RuntimeError(
            "the model could not emit a conflict even when told exactly what to emit; "
            "fix the harness before reporting a score"
        )

    predictions = []
    for scenario in scenarios:
        predictions.append(_predict_one(scenario, budget))

    print(
        f"  model baseline used {budget.calls} calls, "
        f"{budget.input_tokens} in / {budget.output_tokens} out, ${budget.cost_usd:.6f}"
    )
    return predictions, model_id()


def _predict_one(scenario: Scenario, budget: Budget) -> set[tuple[str, int]]:
    response = converse(
        messages=[{"role": "user", "content": [{"text": describe(scenario)}]}],
        system=SYSTEM,
        tool_config={"tools": [REPORT_TOOL], "toolChoice": {"tool": {"name": "report_conflicts"}}},
        turn=budget,
        max_tokens=400,
    )
    blocks = response["output"]["message"]["content"]
    uses = [block["toolUse"] for block in blocks if "toolUse" in block]
    if not uses:
        return set()

    reported = (uses[0].get("input") or {}).get("conflicts") or []
    found = set()
    for item in reported:
        kind, event_id = item.get("kind"), item.get("event_id")
        if isinstance(event_id, int) and kind in {"overlap", "unreachable", "rule_clash"}:
            found.add((kind, event_id))
    return found
