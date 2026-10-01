"""suggest_responsible (#2) and explain_choice (#3).

Both read the reasons reachability already recorded. "Why not Grandpa?" is a lookup, not a fresh
judgement and not a model call, so the answer cannot contradict the decision it explains.
"""

from datetime import date

import sqlalchemy as sa
from sqlalchemy.orm import Session

from lifepilot.db.models import Assignment, Member, Rule
from lifepilot.engine.allocation import rank
from lifepilot.engine.reachability import assess
from lifepilot.tools.context import resolve_viewer
from lifepilot.tools.detect_conflicts import load_week


def _family_id(session: Session, member_id: int) -> int:
    return session.get(Member, member_id).family_id


def _loads(session: Session, family_id: int) -> dict[int, int]:
    """How many lifts each person already holds. The soft balance rule reads this."""
    counts: dict[int, int] = {}
    member_ids = {
        m.id for m in session.scalars(sa.select(Member).where(Member.family_id == family_id))
    }
    for assignment in session.scalars(sa.select(Assignment)):
        if assignment.member_id in member_ids:
            counts[assignment.member_id] = counts.get(assignment.member_id, 0) + 1
    return counts


def _balances_load(session: Session, family_id: int) -> bool:
    return (
        session.scalars(
            sa.select(Rule).where(
                Rule.family_id == family_id,
                Rule.type == "load_balance",
                Rule.active.is_(True),
            )
        ).first()
        is not None
    )


def _find_need(week, event_id: int | None, title: str | None):
    """Which lift was meant: by id, by what it is called, or by whose lift it is.

    "Who should pick up Aarav" names the child, not the event. Matching only titles answered that
    with "I could not tell which lift you meant", which is true and useless.
    """
    if event_id is not None:
        return next((n for n in week.needs if n.event_id == event_id), None)

    if title:
        wanted = title.strip().lower()
        by_title = [n for n in week.needs if wanted in n.title.lower()]
        if by_title:
            return min(by_title, key=lambda n: n.moment)

        children = {p.id: p.name.lower() for p in week.people}
        by_child = [n for n in week.needs if children.get(n.child_id) == wanted]
        if by_child:
            return min(by_child, key=lambda n: n.moment)

    return week.needs[0] if len(week.needs) == 1 else None


def suggest_responsible(
    session: Session,
    speaker: str,
    start: date,
    end: date,
    event_id: int | None = None,
    title: str | None = None,
) -> dict:
    """Who should cover a lift, ranked, each with the reason they beat the next best."""
    viewer = resolve_viewer(session, speaker)
    family_id = _family_id(session, viewer.member_id)
    week = load_week(session, family_id, start, end)

    need = _find_need(week, event_id, title)
    if need is None:
        return {
            "found": False,
            "say": "I could not tell which lift you meant.",
            "lifts": [{"event_id": n.event_id, "title": n.title} for n in week.needs],
        }

    eligibility = [rule["params"] for rule in week.rules if rule["type"] == "eligibility"]
    candidates = assess(need, week.people, week.commitments, week.travel, week.driven, eligibility)
    choices = rank(
        candidates,
        _loads(session, family_id),
        balance_load=_balances_load(session, family_id),
    )

    names = {p.id: p.name for p in week.people}
    assigned_to = names.get(week.assigned.get(need.event_id))

    return {
        "found": True,
        "event_id": need.event_id,
        "title": need.title,
        "when": need.moment.isoformat(timespec="minutes"),
        "assigned_to": assigned_to,
        "ranked": [
            {
                "name": c.name,
                "reason": c.reason,
                "deciding_factor": c.deciding_factor,
                "travel_minutes": c.travel_minutes,
                "slack_minutes": c.slack_minutes,
                "load": c.load,
            }
            for c in choices
        ],
        "ruled_out": [
            {"name": c.name, "reason": c.reason} for c in candidates if not c.reachable
        ],
    }


def explain_choice(
    session: Session,
    speaker: str,
    start: date,
    end: date,
    person: str,
    event_id: int | None = None,
    title: str | None = None,
) -> dict:
    """Why this person, or why not. Reads the reason recorded when the decision was made."""
    viewer = resolve_viewer(session, speaker)
    family_id = _family_id(session, viewer.member_id)
    week = load_week(session, family_id, start, end)

    need = _find_need(week, event_id, title)
    if need is None:
        return {"found": False, "say": "I could not tell which lift you meant."}

    eligibility = [rule["params"] for rule in week.rules if rule["type"] == "eligibility"]
    candidates = assess(need, week.people, week.commitments, week.travel, week.driven, eligibility)

    wanted = person.strip().lower()
    match = next((c for c in candidates if c.name.lower() == wanted), None)
    if match is None:
        known = ", ".join(c.name for c in candidates)
        return {
            "found": False,
            "say": f"I do not know anyone called {person}. This family is: {known}.",
        }

    if match.reachable:
        choices = rank(candidates, _loads(session, family_id), _balances_load(session, family_id))
        position = next(
            (i for i, c in enumerate(choices) if c.person_id == match.person_id), None
        )
        ahead = [c.name for c in choices[:position]] if position else []
        return {
            "found": True,
            "person": match.name,
            "can_do_it": True,
            "reason": match.reason,
            "ahead_of_them": ahead,
            "say": (
                f"{match.name} could: {match.reason}."
                if not ahead
                else f"{match.name} could, but {' and '.join(ahead)} came first."
            ),
        }

    return {
        "found": True,
        "person": match.name,
        "can_do_it": False,
        "reason": match.reason,
        "say": f"Not {match.name}: {match.reason}.",
    }
