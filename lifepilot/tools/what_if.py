"""what_if (#5): show the ripple before anything happens.

Read-only by construction. The hypothetical is applied to an in-memory copy of the week, the copy is
examined, and the copy is discarded. Nothing in this module opens a write.
"""

from datetime import date

from sqlalchemy.orm import Session

from lifepilot.db.models import Member
from lifepilot.engine.conflicts import detect
from lifepilot.engine.whatif import UnknownHypothetical, apply_hypothetical, ripple
from lifepilot.solver.repair import repair
from lifepilot.tools.context import resolve_viewer
from lifepilot.tools.detect_conflicts import load_week


def what_if(session: Session, speaker: str, start: date, end: date, change: dict) -> dict:
    """What this change would do, and what would fix it. Changes nothing."""
    viewer = resolve_viewer(session, speaker)
    family_id = session.get(Member, viewer.member_id).family_id
    week = load_week(session, family_id, start, end)

    change = {**change, "for_member": [viewer.member_id]}
    if change.get("kind") == "new_event" and not change.get("member_ids"):
        # "Can I say yes to a six o'clock?" means the person asking, unless they said otherwise.
        change["member_ids"] = [viewer.member_id]

    try:
        hypothetical = apply_hypothetical(week, change)
    except UnknownHypothetical as refusal:
        return {"understood": False, "say": str(refusal)}

    before = detect(week)
    after = detect(hypothetical)
    effect = ripple(before, after)

    result = {
        "understood": True,
        "changed_anything": False,
        "ripple": effect.as_dict(),
        "say": _describe(effect, change),
    }

    # Only bother solving when the answer is "that breaks something": the fix is the useful part.
    if effect.breaks:
        fix = repair(hypothetical)
        result["fix"] = {
            "change_count": fix.change_count,
            "changes": [c.as_dict() for c in fix.changes],
            "unfixable": fix.unfixable,
            "solve_ms": fix.solve_ms,
        }
        result["say"] += _fix_sentence(fix)

    return result


def _describe(effect, change: dict) -> str:
    if effect.is_safe and not effect.resolves:
        return "That works. Nothing new breaks."
    if effect.is_safe and effect.resolves:
        freed = ", ".join(c.title for c in effect.resolves)
        return f"That actually helps: it clears {freed}."

    first = effect.breaks[0]
    opening = (
        "That breaks one thing"
        if len(effect.breaks) == 1
        else f"That breaks {len(effect.breaks)} things"
    )
    return f"{opening}. {first.detail}."


def _fix_sentence(fix) -> str:
    if fix.unfixable:
        return " I could not find a way round it."
    if not fix.changes:
        return ""
    parts = [
        f"{c.now} takes {c.title}" if c.kind == "assign" else f"{c.title} moves to {c.now}"
        for c in fix.changes
    ]
    return f" You could fix it with {len(fix.changes)}: {', and '.join(parts)}."
