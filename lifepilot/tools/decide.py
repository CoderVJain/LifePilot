"""suggest_responsible (#2) and explain_choice (#3).

Both read the reasons reachability already recorded. "Why not Grandpa?" is a lookup, not a fresh
judgement and not a model call, so the answer cannot contradict the decision it explains.
"""

from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session

from lifepilot.db.models import Assignment, Member, Rule
from lifepilot.engine.allocation import rank
from lifepilot.engine.reachability import assess, reachable
from lifepilot.tools.context import resolve_viewer
from lifepilot.tools.detect_conflicts import load_week
from lifepilot_shared.clock import today as clock_today
from lifepilot_shared.speech import say_list, say_reason


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
            return _soonest(by_title)

        children = {p.id: p.name.lower() for p in week.people}
        by_child = [n for n in week.needs if children.get(n.child_id) == wanted]
        if by_child:
            return _soonest(by_child)

    return week.needs[0] if len(week.needs) == 1 else None


def _soonest(needs: list):
    """The next of these lifts, preferring one that has not happened yet.

    Plain `min` by moment takes the earliest in the window, and the window reaches back over the
    weekend running into the week. Asked on a Thursday who should collect Aarav, that answered about
    Saturday's match -- a lift already driven, by an adult who could reach that one and cannot reach
    the one being asked about. Nobody asks who should cover a pickup that is over.
    """
    start_of_today = datetime.combine(clock_today(), datetime.min.time())
    upcoming = [n for n in needs if n.moment >= start_of_today]
    return min(upcoming or needs, key=lambda n: n.moment)


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

    instead = [c.name for c in reachable(candidates)]
    return {
        "found": True,
        "person": match.name,
        "can_do_it": False,
        "reason": match.reason,
        "could_instead": instead,
        "say": _why_not(match.name, match.reason, instead),
    }


def _why_not(name: str, reason: str, instead: list[str]) -> str:
    """A refusal that reads as a sentence, and names who can instead.

    "Not Grandpa: rule: only when no parent is free" was two colons and a fragment, and it is the
    0:15-0:50 shot. Naming who can is the other half of the answer a parent wants.
    """
    because = say_reason(reason)
    if instead:
        return f"Not {name}, because {because}. {say_list(instead)} can."
    return f"Not {name}, because {because}."
