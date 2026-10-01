"""approve_proposal and reject_proposal: the only place LifePilot changes a family's plan.

Every write in the system funnels through here. Tools propose; this executes, and only when a parent
says so. Keeping it to one module means the question "what can alter our schedule?" has a short,
checkable answer.

Three things are enforced in code, not asked of a prompt:

    only a parent may decide
    when a proposal names who must approve it, only that person may
    a proposal is decided once, and applying it is all-or-nothing
"""

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session

from lifepilot.db.models import Assignment, Event, Member, Proposal
from lifepilot.tools.context import resolve_viewer


class NotAllowed(PermissionError):
    """This person may not decide this proposal."""


class CannotApply(RuntimeError):
    """The proposal no longer describes something that can be carried out."""


def approve_proposal(session: Session, speaker: str, proposal_id: int) -> dict:
    """Carry out a proposal, if this speaker is allowed to say yes to it."""
    viewer, proposal = _check(session, speaker, proposal_id)

    try:
        applied = _apply(session, proposal)
    except CannotApply as problem:
        session.rollback()
        return {
            "approved": False,
            "proposal_id": proposal.id,
            "say": f"I could not make that change: {problem}",
        }

    proposal.status = "approved"
    proposal.decided_by = viewer.member_id
    session.commit()

    return {
        "approved": True,
        "proposal_id": proposal.id,
        "applied": applied,
        "change_count": len(applied),
        "say": _confirmation(applied),
    }


def reject_proposal(session: Session, speaker: str, proposal_id: int) -> dict:
    """Decline a proposal. Nothing is carried out and the plan stands as it was."""
    viewer, proposal = _check(session, speaker, proposal_id)

    proposal.status = "rejected"
    proposal.decided_by = viewer.member_id
    session.commit()

    return {
        "approved": False,
        "rejected": True,
        "proposal_id": proposal.id,
        "say": "Alright, I have left everything as it was.",
    }


def list_proposals(session: Session, speaker: str) -> dict:
    """What is waiting on a decision, for this speaker."""
    viewer = resolve_viewer(session, speaker)
    family_id = session.get(Member, viewer.member_id).family_id

    waiting = session.scalars(
        sa.select(Proposal)
        .where(Proposal.family_id == family_id, Proposal.status == "pending")
        .order_by(Proposal.id)
    ).all()

    names = {
        m.id: m.name for m in session.scalars(sa.select(Member).where(Member.family_id == family_id))
    }
    return {
        "speaker": {"name": viewer.name, "role": viewer.role},
        "proposals": [
            {
                "id": p.id,
                "kind": p.kind,
                "created_by": names.get(p.created_by),
                "needs_approval_from": names.get(p.needs_approval_from),
                "yours_to_decide": _may_decide(viewer, p),
                "change_count": len(p.changes or []),
                "changes": p.changes,
            }
            for p in waiting
        ],
    }


# --------------------------------------------------------------------------- checks


def _check(session: Session, speaker: str, proposal_id: int) -> tuple:
    viewer = resolve_viewer(session, speaker)
    proposal = session.get(Proposal, proposal_id)

    if proposal is None:
        raise CannotApply("there is no such proposal")
    if proposal.family_id != session.get(Member, viewer.member_id).family_id:
        raise NotAllowed("that proposal belongs to another family")
    if proposal.status != "pending":
        raise CannotApply(f"that was already {proposal.status}")
    if not _may_decide(viewer, proposal):
        raise NotAllowed(_why_not(viewer, proposal, session))
    return viewer, proposal


def _may_decide(viewer, proposal: Proposal) -> bool:
    if proposal.needs_approval_from is not None:
        return viewer.member_id == proposal.needs_approval_from
    return viewer.role == "parent"


def _why_not(viewer, proposal: Proposal, session: Session) -> str:
    if proposal.needs_approval_from is not None:
        owner = session.get(Member, proposal.needs_approval_from)
        return f"only {owner.name} can answer that one"
    return f"{viewer.name} is a {viewer.role}; only a parent can approve a change"


# --------------------------------------------------------------------------- carrying it out


def _apply(session: Session, proposal: Proposal) -> list[dict]:
    """Make every change, or none. The caller rolls back if this raises."""
    applied = []
    for change in proposal.changes or []:
        kind = change.get("kind")
        if kind == "assign":
            applied.append(_apply_assign(session, change))
        elif kind == "move":
            applied.append(_apply_move(session, change))
        else:
            raise CannotApply(f"I do not know how to make a {kind!r} change")
    session.flush()
    return applied


def _apply_assign(session: Session, change: dict) -> dict:
    event_id, person_id = change.get("event_id"), change.get("person_id")
    event = session.get(Event, event_id)
    person = session.get(Member, person_id) if person_id else None
    if event is None:
        raise CannotApply(f"{change.get('title')} is no longer in the calendar")
    if person is None:
        raise CannotApply("that person is no longer in the family")

    assignment = session.scalars(
        sa.select(Assignment).where(Assignment.event_id == event_id)
    ).first()
    if assignment is None:
        session.add(Assignment(event_id=event_id, member_id=person_id, kind="pickup"))
    else:
        assignment.member_id = person_id
    return {"kind": "assign", "title": event.title, "now": person.name}


def _apply_move(session: Session, change: dict) -> dict:
    event = session.get(Event, change.get("event_id"))
    if event is None:
        raise CannotApply(f"{change.get('title')} is no longer in the calendar")
    if not event.movable:
        raise CannotApply(f"{event.title} cannot be moved")

    start_iso = change.get("start_iso")
    if not start_iso:
        raise CannotApply(f"I do not know when to move {event.title} to")
    try:
        start = datetime.fromisoformat(start_iso)
    except ValueError as bad:
        raise CannotApply(f"{start_iso!r} is not a time") from bad

    length = event.end - event.start
    event.start = start
    event.end = start + length
    return {"kind": "move", "title": event.title, "now": change.get("now") or start_iso}


def _confirmation(applied: list[dict]) -> str:
    if not applied:
        return "There was nothing to change."
    parts = [
        f"{c['now']} has {c['title']}" if c["kind"] == "assign" else f"{c['title']} is now {c['now']}"
        for c in applied
    ]
    return "Done. " + ", and ".join(parts) + "."
