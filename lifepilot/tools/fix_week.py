"""fix_week (#4): propose the smallest set of changes that makes the week work.

Nothing is executed here. The repair becomes a pending proposal that a parent approves, because
LifePilot never changes a family's plan on its own. Phase 10 adds the approving side.
"""

from datetime import date

from sqlalchemy.orm import Session

from lifepilot.db.models import Member, Proposal
from lifepilot.engine.conflicts import detect
from lifepilot.solver.repair import repair
from lifepilot.tools.context import resolve_viewer
from lifepilot.tools.detect_conflicts import load_week


class NotAllowed(PermissionError):
    """Only parents may propose changes to the family's plan."""


def fix_week(session: Session, speaker: str, start: date, end: date) -> dict:
    """Find the nearest week that works, and hold it as a proposal awaiting a parent's yes."""
    viewer = resolve_viewer(session, speaker)
    if viewer.role != "parent":
        raise NotAllowed(f"{viewer.name} is a {viewer.role}; only a parent can change the plan.")

    family_id = session.get(Member, viewer.member_id).family_id
    week = load_week(session, family_id, start, end)
    problems = detect(week)

    if not problems:
        return {
            "needed": False,
            "change_count": 0,
            "changes": [],
            "say": "Nothing needs changing. The week works as it is.",
        }

    result = repair(week)
    if result.status == "infeasible" or (not result.changes and result.unfixable):
        return {
            "needed": True,
            "solved": False,
            "change_count": 0,
            "changes": [],
            "unfixable": result.unfixable,
            "solve_ms": result.solve_ms,
            "say": _cannot_fix(result.unfixable),
        }

    proposal = Proposal(
        family_id=family_id,
        kind="fix",
        created_by=viewer.member_id,
        changes=[c.as_dict() for c in result.changes],
        violations=[c.as_dict() for c in problems],
        solve_ms=result.solve_ms,
        status="pending",
    )
    session.add(proposal)
    session.commit()

    return {
        "needed": True,
        "solved": True,
        "proposal_id": proposal.id,
        "change_count": result.change_count,
        "changes": [c.as_dict() for c in result.changes],
        "fixes": [c.as_dict() for c in problems],
        "unfixable": result.unfixable,
        "solve_ms": result.solve_ms,
        "status": "pending",
        "say": _describe(result),
    }


def _describe(result) -> str:
    count = result.change_count
    if count == 0:
        return "I could not find anything to change."
    opening = "One change" if count == 1 else f"{count} changes"
    parts = []
    for change in result.changes:
        if change.kind == "assign":
            parts.append(f"{change.now} takes {change.title}")
        else:
            parts.append(f"{change.title} moves to {change.now}")
    return f"{opening}: {', and '.join(parts)}. Shall I make them?"


def _cannot_fix(unfixable: list[str]) -> str:
    if not unfixable:
        return "I could not find a way to make this week work."
    return "I cannot fix this one: " + "; ".join(unfixable) + "."
