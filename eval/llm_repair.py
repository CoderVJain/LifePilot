"""The AI-only repairer for experiment 2: Nova Micro given a broken week, asked to fix it.

It gets the same information the solver gets, and returns changes in the same shape, so both are
applied and scored by the same detector. One call per week, through `lifepilot_shared.llm`.
"""

import os
from collections.abc import Sequence

from eval.llm_baseline import describe
from eval.scenarios import Scenario
from lifepilot_shared.llm import Turn as Budget
from lifepilot_shared.llm import converse, model_id

PLAN_TOOL = {
    "toolSpec": {
        "name": "propose_plan",
        "description": "Propose the smallest set of changes that makes this week work.",
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {
                    "changes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "kind": {"type": "string", "enum": ["assign", "move"]},
                                "event_id": {"type": "integer"},
                                "person": {
                                    "type": "string",
                                    "description": "For 'assign': who should cover the lift.",
                                },
                                "start": {
                                    "type": "string",
                                    "description": (
                                        "For 'move': the new start, as YYYY-MM-DDTHH:MM."
                                    ),
                                },
                            },
                            "required": ["kind", "event_id"],
                        },
                    }
                },
                "required": ["changes"],
            }
        },
    }
}

SYSTEM = [
    {
        "text": (
            "You repair a family's week. Change as little as possible: every change has to be lived "
            "with, so a plan with two changes beats one with five. You may reassign who covers a "
            "lift, and you may move an event that is marked movable. You may never move an event "
            "marked fixed. Only adults who can drive may cover a lift. Count travel time between "
            "places, and obey every family rule listed. Call propose_plan exactly once."
        )
    }
]


def estimate_calls(scenarios: Sequence[Scenario]) -> int:
    return sum(1 for s in scenarios if s.expected) + 1  # one extra for the plumbing check below


def can_propose(budget: Budget) -> bool:
    """Can the model propose a change at all, when told exactly what to propose?

    A repairer that proposes nothing twenty times running looks identical to a broken tool binding.
    This separates "the model found no fix" from "the harness never let it offer one".
    """
    response = converse(
        messages=[
            {
                "role": "user",
                "content": [
                    {"text": "Propose exactly one change: kind assign, event_id 112, person Mom."}
                ],
            }
        ],
        system=[{"text": "You propose plans using the tool."}],
        tool_config={"tools": [PLAN_TOOL], "toolChoice": {"tool": {"name": "propose_plan"}}},
        turn=budget,
        max_tokens=300,
    )
    blocks = response["output"]["message"]["content"]
    uses = [block["toolUse"] for block in blocks if "toolUse" in block]
    if not uses:
        return False
    return bool((uses[0].get("input") or {}).get("changes"))


def describe_for_repair(scenario: Scenario) -> str:
    """The week, plus which events may be moved and today's date, which a repair needs."""
    lines = [describe(scenario)]
    movable = [c for c in scenario.week.commitments if c.movable]
    fixed = [c for c in scenario.week.commitments if not c.movable]
    lines.append("MAY BE MOVED")
    lines.extend(f"  id={c.id} {c.title} (currently {c.start:%Y-%m-%dT%H:%M})" for c in movable)
    lines.append("MUST NOT MOVE")
    lines.extend(f"  id={c.id} {c.title}" for c in fixed)
    lines.append("The day being planned is " + f"{scenario.week.commitments[0].start:%Y-%m-%d}.")
    return "\n".join(lines)


def repair_all(scenarios: Sequence[Scenario]) -> tuple[list[list[dict]], str]:
    """One call per broken week. Clean weeks are skipped: there is nothing to repair."""
    ceiling = int(os.environ.get("EVAL_MAX_CALLS", "200"))
    needed = estimate_calls(scenarios)
    if needed > ceiling:
        raise RuntimeError(f"{needed} calls needed but EVAL_MAX_CALLS is {ceiling}")

    budget = Budget(max_calls=ceiling)
    if not can_propose(budget):
        raise RuntimeError(
            "the model could not propose a change even when told exactly what to propose; "
            "fix the harness before reporting a score"
        )

    plans = []
    for scenario in scenarios:
        plans.append(_repair_one(scenario, budget) if scenario.expected else [])

    print(
        f"  model repairer used {budget.calls} calls, "
        f"{budget.input_tokens} in / {budget.output_tokens} out, ${budget.cost_usd:.6f}"
    )
    return plans, model_id()


def _repair_one(scenario: Scenario, budget: Budget) -> list[dict]:
    response = converse(
        messages=[{"role": "user", "content": [{"text": describe_for_repair(scenario)}]}],
        system=SYSTEM,
        tool_config={"tools": [PLAN_TOOL], "toolChoice": {"tool": {"name": "propose_plan"}}},
        turn=budget,
        max_tokens=500,
    )
    blocks = response["output"]["message"]["content"]
    uses = [block["toolUse"] for block in blocks if "toolUse" in block]
    if not uses:
        return []
    return _to_changes(scenario, (uses[0].get("input") or {}).get("changes") or [])


def _to_changes(scenario: Scenario, proposed: list) -> list[dict]:
    """Names to ids, so the model's plan can be applied exactly like the solver's.

    A name nobody has, or a missing time, is left as-is and fails when applied. That is the plan's
    failure, not the evaluation's, and it is scored as one.
    """
    by_name = {p.name.lower(): p.id for p in scenario.week.people}
    changes = []
    for item in proposed:
        if not isinstance(item, dict):
            continue
        change = {"kind": item.get("kind"), "event_id": item.get("event_id")}
        if change["kind"] == "assign":
            change["person_id"] = by_name.get(str(item.get("person", "")).strip().lower())
        elif change["kind"] == "move":
            change["start_iso"] = item.get("start")
        changes.append(change)
    return changes
