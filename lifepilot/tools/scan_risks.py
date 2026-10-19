"""scan_risks: "what am I forgetting?", and the slot that answers it.

Tool-side chaining, for the same reason `check_school_email` does it: one result carries the task,
the risk, and a pending proposal for the time that would save it, so a voice turn needs one tool
call and stays inside the three-call ceiling.

The proposal is a `task` worth of time expressed as an `add` change, which `approve.py` already
knows how to apply. A parent still has to say yes -- nothing goes in the diary on the scan's own
say-so.
"""

from datetime import date, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session

from lifepilot.db.models import Event, Member, Proposal, Rule
from lifepilot.db.models import Task as TaskRow
from lifepilot.engine.reachability import Commitment
from lifepilot.engine.risk import Risk, Task, scan
from lifepilot.tools.context import resolve_viewer
from lifepilot_shared.clock import today as clock_today
from lifepilot_shared.speech import say_span


class NotAllowed(Exception):
    """The speaker may not do this."""


def scan_risks(session: Session, speaker: str, on: date | None = None) -> dict:
    """What is at risk, and a proposal for the first thing worth booking.

    A child sees only their own tasks; a caregiver has none, because tasks are not assigned to
    them. The visibility rules are the same ones `get_schedule` applies, enforced here rather than
    asked of a prompt.
    """
    viewer = resolve_viewer(session, speaker)
    member = session.get(Member, viewer.member_id)
    family_id = member.family_id
    today = on or clock_today()

    tasks = _tasks(session, family_id, viewer)
    commitments = _commitments(session, family_id)
    rules = _rules(session, family_id)
    booked = _already_booked(tasks, commitments)

    risks = scan(tasks, commitments, today, rules, booked=booked)
    if not risks:
        return {
            "at_risk": [],
            "say": "Nothing is at risk. Everything with a deadline still has room for it.",
        }

    worst = risks[0]
    proposal = _propose_time(session, family_id, viewer.member_id, tasks, worst)
    result = {
        "at_risk": [_as_dict(risk) for risk in risks],
        "say": _say(risks, worst, proposal is not None),
    }
    if proposal is not None:
        result["proposal_id"] = proposal.id
        result["changes"] = proposal.changes
    return result


def _tasks(session: Session, family_id: int, viewer) -> list[Task]:
    rows = session.scalars(
        sa.select(TaskRow).where(TaskRow.family_id == family_id).order_by(TaskRow.due, TaskRow.id)
    ).all()
    if viewer.role == "caregiver":
        return []
    if viewer.role == "child":
        rows = [row for row in rows if row.owner_id == viewer.member_id]
    return [
        Task(
            id=row.id,
            title=row.title,
            due=row.due,
            est_minutes=row.est_minutes,
            owner_id=row.owner_id,
            prep_days=row.prep_days,
            category=row.category,
            status=row.status,
            source=row.source,
        )
        for row in rows
    ]


def _commitments(session: Session, family_id: int) -> list[Commitment]:
    events = session.scalars(
        sa.select(Event).where(Event.family_id == family_id).order_by(Event.start, Event.id)
    ).all()
    return [
        Commitment(e.id, e.title, e.start, e.end, e.location_id, tuple(e.member_ids or ()),
                   e.category, bool(e.movable))
        for e in events
    ]


def _rules(session: Session, family_id: int) -> list[dict]:
    rows = session.scalars(
        sa.select(Rule).where(Rule.family_id == family_id, Rule.active.is_(True))
    ).all()
    return [{"type": row.type, "params": row.params or {}} for row in rows]


def _already_booked(tasks: list[Task], commitments: list[Commitment]) -> list[int]:
    """Tasks that already have time set aside, matched by name.

    The data model has no link between a task and the event booked for it, so the match is on
    words: the seeded family's "science project model" task and its "science project block" event
    are the same piece of work, and warning about it would be noise. Matching on the longest shared
    run of words rather than equality, because nobody books an event under the task's exact title.
    """
    booked = []
    for task in tasks:
        words = _words(task.title)
        if not words:
            continue
        for commitment in commitments:
            if task.owner_id is not None and task.owner_id not in commitment.member_ids:
                continue
            if commitment.end > task.due:
                continue
            shared = words & _words(commitment.title)
            if len(shared) >= 2 or (len(words) == 1 and shared):
                booked.append(task.id)
                break
    return booked


def _words(title: str) -> set[str]:
    skip = {"the", "a", "an", "of", "for", "block", "time", "session"}
    return {word for word in title.lower().split() if word not in skip}


def _propose_time(
    session: Session, family_id: int, created_by: int, tasks: list[Task], risk: Risk
) -> Proposal | None:
    """A pending proposal for the slot that would save this task, or None when there is no slot."""
    if risk.slot is None:
        return None

    task = next((t for t in tasks if t.id == risk.task_id), None)
    owner_ids = [task.owner_id] if task and task.owner_id else []
    # Book exactly what the task needs, not the whole gap: a three-hour job does not take the
    # evening, and claiming the lot would make the next thing look impossible.
    booked_end = min(risk.slot.start + timedelta(minutes=risk.minutes_needed), risk.slot.end)

    proposal = Proposal(
        family_id=family_id,
        kind="task",
        created_by=created_by,
        changes=[
            {
                "kind": "add",
                "title": f"{risk.title} time",
                "was": "nothing set aside",
                "now": say_span(risk.slot.start.isoformat(), booked_end.isoformat()),
                "reason": risk.detail,
                "start_iso": risk.slot.start.isoformat(),
                "end_iso": booked_end.isoformat(),
                "member_ids": owner_ids,
                "category": task.category if task else "other",
            }
        ],
        violations=[],
        status="pending",
        needs_approval_from=None,
    )
    session.add(proposal)
    session.commit()
    return proposal



def _as_dict(risk: Risk) -> dict:
    return {
        "task_id": risk.task_id,
        "title": risk.title,
        "due": risk.due.isoformat(timespec="minutes"),
        "kinds": list(risk.kinds),
        "minutes_needed": risk.minutes_needed,
        "minutes_free": risk.minutes_free,
        "detail": risk.detail,
        "slot": (
            {"start": risk.slot.start.isoformat(timespec="minutes"),
             "end": risk.slot.end.isoformat(timespec="minutes")}
            if risk.slot
            else None
        ),
    }


def _say(risks: list[Risk], worst: Risk, proposed: bool) -> str:
    """The spoken answer. The risk first, the offer second, never a list of everything."""
    opening = worst.detail
    if len(risks) > 1:
        others = len(risks) - 1
        opening += f". {others} other{'s' if others > 1 else ''} need watching too"
    if not proposed:
        return f"{opening}. There is no free stretch long enough, so something has to move."
    return f"{opening}. Shall I put it in?"

