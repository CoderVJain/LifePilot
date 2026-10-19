"""check_school_email (#7) and manage_email_access: the school's email, turned into a plan.

One tool call does the whole chain -- read the allowlisted mail, extract the task, see what it
breaks, and propose the repair -- because the alternative is three or four model calls per question
and the ceiling is three per turn.

What is kept of an email: its Gmail id, its sender, when it arrived, and the tasks extracted from
it. The subject and the body are held in memory for one extraction and then dropped. `SchoolMessage`
has no column to put them in, which is the strongest way to keep that promise.
"""

from datetime import date, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session

from lifepilot.db.models import (
    Assignment,
    EmailLink,
    Event,
    Member,
    Proposal,
    SchoolMessage,
)
from lifepilot.engine.conflicts import detect
from lifepilot.mail import allowlist, vault
from lifepilot.mail.extract import extract
from lifepilot.mail.gmail import GmailClient
from lifepilot.solver.repair import repair
from lifepilot.tools.context import resolve_viewer
from lifepilot.tools.detect_conflicts import load_week
from lifepilot_shared.clock import today as today_now
from lifepilot_shared.llm import Turn
from lifepilot_shared.speech import say_day, say_list, say_span

#: How many emails one check will read, and so the most model calls it can make. Without a bound,
#: a busy inbox is an unbounded spend: the one way this feature could cost real money.
MAX_EMAILS = 5

#: How far back a check looks. Caching is by Gmail message id, so an email inside this window that
#: has already been read costs nothing; the window only decides what is new enough to care about.
LOOKBACK_DAYS = 14


class NotAllowed(PermissionError):
    """Only a parent may read the school's email or change who may be read."""


class NotLinked(RuntimeError):
    """No Gmail account is linked, or no school senders are set."""


# --------------------------------------------------------------------------- access


def manage_email_access(
    session: Session,
    speaker: str,
    senders: list[str] | None = None,
    disconnect: bool = False,
    client=None,
) -> dict:
    """Set which senders may be read, or disconnect entirely."""
    viewer = _parent(session, speaker)
    family_id = session.get(Member, viewer.member_id).family_id
    link = _link(session, family_id, viewer.member_id)

    if disconnect:
        return _disconnect(session, family_id, link, client)

    if senders is None:
        allowed = allowlist.clean(link.allowed_senders if link else [])
        return {
            "linked": bool(link and link.encrypted_token),
            "allowed_senders": allowed,
            "say": _say_allowed(allowed, bool(link and link.encrypted_token)),
        }

    allowed = allowlist.clean(senders)
    if not allowed:
        return {
            "linked": bool(link and link.encrypted_token),
            "allowed_senders": [],
            "say": "I need an email address to allow, such as office at demo-school dot invalid.",
        }

    if link is None:
        link = EmailLink(family_id=family_id, parent_id=viewer.member_id, encrypted_token=b"")
        session.add(link)
    link.allowed_senders = allowed
    session.commit()

    return {
        "linked": bool(link.encrypted_token),
        "allowed_senders": allowed,
        "say": (
            f"I will only read email from {say_list(allowed)}."
            + ("" if link.encrypted_token else " Link Gmail once and I can start.")
        ),
    }


def link_gmail(session: Session, speaker: str, token: dict) -> dict:
    """Store a freshly granted token against this parent. Called only by the OAuth callback.

    An existing link is updated rather than replaced, so re-linking after the weekly expiry keeps
    the senders the parent already set and does not quietly widen what may be read.
    """
    viewer = _parent(session, speaker)
    family_id = session.get(Member, viewer.member_id).family_id
    link = _link(session, family_id, viewer.member_id)

    if link is None:
        link = EmailLink(family_id=family_id, parent_id=viewer.member_id, allowed_senders=[])
        session.add(link)
    link.encrypted_token = vault.seal(token)
    link.linked_at = datetime.now()
    session.commit()

    allowed = allowlist.clean(link.allowed_senders)
    return {
        "linked": True,
        "parent": viewer.name,
        "allowed_senders": allowed,
        "say": (
            f"Gmail is linked for {viewer.name}. I read email from {say_list(allowed)}, "
            "and nothing else."
            if allowed
            else f"Gmail is linked for {viewer.name}. Tell me which school address to read, "
            "and I will read only that one."
        ),
    }


def _disconnect(session: Session, family_id: int, link, client) -> dict:
    """Revoke with Google, then delete the token and every stored school message."""
    if link is None:
        return {"linked": False, "say": "There is no email account linked."}

    revoked = _revoke(link, client)
    messages = session.scalars(
        sa.select(SchoolMessage).where(SchoolMessage.family_id == family_id)
    ).all()
    for message in messages:
        session.delete(message)
    session.delete(link)
    session.commit()

    return {
        "linked": False,
        "revoked": revoked,
        "deleted_messages": len(messages),
        "say": "Email disconnected. I have revoked the token and deleted everything I had kept.",
    }


def _revoke(link, client) -> bool:
    """Best effort with Google, then delete regardless: the stored rows go either way."""
    if not link.encrypted_token:
        return False
    try:
        (client or GmailClient(vault.unseal(link.encrypted_token))).revoke()
    except Exception:
        return False
    return True


# --------------------------------------------------------------------------- reading


def check_school_email(
    session: Session, speaker: str, client=None, today: date | None = None
) -> dict:
    """New school email as tasks, with what each one breaks and how to repair it."""
    viewer = _parent(session, speaker)
    family_id = session.get(Member, viewer.member_id).family_id
    link = _link(session, family_id, viewer.member_id)
    day = today or today_now()

    if link is None or not link.encrypted_token:
        raise NotLinked("No email account is linked yet. Link Gmail once and I can read the school.")
    allowed = allowlist.clean(link.allowed_senders)
    if not allowed:
        raise NotLinked("Tell me which school address to read, and I will only read that one.")

    reader = client or GmailClient(vault.unseal(link.encrypted_token))
    query = allowlist.query(allowed, after=day - timedelta(days=LOOKBACK_DAYS))
    messages = reader.search(query, allowed, limit=MAX_EMAILS)

    turn = Turn(max_calls=MAX_EMAILS)
    findings: list[dict] = []
    fresh = 0
    for message in messages:
        if _already_read(session, message.id):
            continue
        fresh += 1
        found = extract(
            message.subject, message.body, day, turn=turn, children=_children(session, family_id)
        )
        session.add(
            SchoolMessage(
                family_id=family_id,
                gmail_message_id=message.id,
                sender=allowlist.address_of(message.sender),
                received_at=message.received_at,
                extracted_tasks=found,
                status="extracted",
            )
        )
        findings.extend(found)

    link.last_checked_at = datetime.combine(day, datetime.min.time())
    session.commit()

    tasks = [f for f in findings if f["kind"] == "task"]
    closures = [f for f in findings if f["kind"] == "closure"]

    if not findings:
        return {
            "read": len(messages),
            "new_messages": fresh,
            "new_tasks": 0,
            "tasks": [],
            "model_calls": turn.calls,
            "say": _nothing_to_do(fresh),
        }

    cleared = [c for closure in closures for c in _clears(session, family_id, closure, day)]
    # The answer is built from the changes, not from the raw findings: the change is where a child's
    # name has been checked against the family, and the sentence must say what will be written.
    booked = [_change(session, family_id, t, day) for t in tasks]
    changes = booked + cleared

    # A closure that matches nothing in the calendar is news, not a change. Proposing an empty diff
    # would ask a parent to approve nothing.
    if not changes:
        return {
            "read": len(messages),
            "new_messages": fresh,
            "new_tasks": 0,
            "tasks": [],
            "closures": closures,
            "model_calls": turn.calls,
            "say": _nothing_to_clear(closures, day),
        }

    unnamed = _unnamed(booked, session, family_id)
    effect = _effect(session, family_id, tasks, day) if tasks else _no_effect(day)
    proposal = Proposal(
        family_id=family_id,
        kind="closure" if closures and not tasks else "task",
        created_by=viewer.member_id,
        changes=changes,
        violations=effect["breaks"],
        status="pending",
    )
    session.add(proposal)
    session.commit()

    return {
        "read": len(messages),
        "new_messages": fresh,
        "new_tasks": len(tasks),
        "tasks": tasks,
        "closures": closures,
        "proposal_id": proposal.id,
        "status": "pending",
        "change_count": len(changes),
        "changes": changes,
        "model_calls": turn.calls,
        "needs_child": unnamed,
        **effect,
        "say": _describe(booked, closures, cleared, effect, day, unnamed),
    }


#: What a closure may take out of the calendar. School only: a school saying it is shut is an
#: authority on school and on nothing else. Without this bound, "we are closed tomorrow" could
#: propose clearing a parent's work, and an email is the one input we must assume is hostile.
CLEARABLE = ("school",)


def _clears(session: Session, family_id: int, closure: dict, day: date) -> list[dict]:
    """The changes a closure implies: school off that day, and the lifts that served it.

    Only events in `CLEARABLE` on that one date, and only this family's. A past date clears nothing,
    so a forwarded notice about last Tuesday cannot delete history.
    """
    when = date.fromisoformat(closure["date"])
    if when < day:
        return []

    events = session.scalars(
        sa.select(Event)
        .where(
            Event.family_id == family_id,
            Event.category.in_(CLEARABLE),
            Event.start >= datetime.combine(when, datetime.min.time()),
            Event.start <= datetime.combine(when, datetime.max.time()),
        )
        .order_by(Event.start, Event.id)
    ).all()

    return [
        {
            "kind": "remove",
            "event_id": event.id,
            "title": event.title,
            "when": say_span(event.start, event.end),
            "was": say_span(event.start, event.end),
            "now": "cleared",
            "frees": _frees(session, event),
            "reason": f"school is closed: {closure['title']}",
        }
        for event in events
    ]


def _frees(session: Session, event: Event) -> list[str]:
    """Who stops having to drive if this event goes. The part a parent actually cares about."""
    assignments = session.scalars(
        sa.select(Assignment).where(Assignment.event_id == event.id)
    ).all()
    names = [session.get(Member, a.member_id).name for a in assignments]
    return sorted(set(names))


def _no_effect(day: date) -> dict:
    """A closure removes work; it cannot break the week, so there is nothing to repair."""
    return {"from": day.isoformat(), "to": day.isoformat(), "breaks": [], "fix": None}


def _nothing_to_clear(closures: list[dict], day: date) -> str:
    """A closure for a day the family has nothing booked on is news, not a change."""
    first = closures[0]
    when = say_day(date.fromisoformat(first["date"]), day)
    return f"School says it is closed {when}: {first['title']}. Nothing in your week changes."


def _nothing_to_do(fresh: int) -> str:
    """"Nothing new from school" and "nothing in it for you" are different answers.

    A tester sent a school closure notice, got "Nothing new from school", and reasonably concluded
    LifePilot had not read it. It had, and had correctly decided an announcement asks nobody to do
    anything. Saying which of the two happened is the difference between a working product and one
    that looks broken.
    """
    if not fresh:
        return "Nothing new from school."
    read = "one email" if fresh == 1 else f"{fresh} emails"
    return f"I read {read} from school, and there is nothing you need to do."


def _already_read(session: Session, gmail_message_id: str) -> bool:
    """One model call per email, ever. The stored row is the cache."""
    return (
        session.scalars(
            sa.select(SchoolMessage).where(SchoolMessage.gmail_message_id == gmail_message_id)
        ).first()
        is not None
    )


def _only_child(session: Session, family_id: int):
    """The one child, when there is only one. Then there is nothing to ask about."""
    children = session.scalars(
        sa.select(Member).where(Member.family_id == family_id, Member.role == "child")
    ).all()
    return children[0] if len(children) == 1 else None


def _change(session: Session, family_id: int, task: dict, day: date) -> dict:
    """The task as a pending change. Nothing is written until a parent approves it.

    `was` and `now` are what the proposal card reads, the same two fields a repair writes, so the
    card needs no idea that this change came from an email.
    """
    # An unmatched name is no name. With a single child there is no ambiguity to resolve, so the
    # task is theirs; with more than one, `needs_child` makes LifePilot ask instead of guess.
    child = _member(session, family_id, task.get("child")) or _only_child(session, family_id)
    due = date.fromisoformat(task["due"])
    return {
        "kind": "task",
        "title": task["title"],
        "category": task.get("category") or "event",
        "due_iso": task["due"],
        "prep_days": int(task.get("prep_days") or 0),
        "owner_id": child.id if child else None,
        # Only a real family member. The model once answered the word "child", and the sentence
        # came out as "child needs Fancy Dress Competition"; an unmatched name is no name.
        "child": child.name if child else None,
        "source": "email",
        "was": "not on the list",
        "now": f"due {say_day(due, day)}",
        "reason": "the school asked for it",
    }


def name_task_child(session: Session, speaker: str, proposal_id: int, child: str) -> dict:
    """Say which child a pending school task is for, before anybody approves it.

    A school email often names no child, or names one we cannot match. With one child there is
    nothing to resolve; with two there is, and guessing would put a costume on the wrong child's
    name. So LifePilot asks, and the answer amends the proposal rather than writing anything: the
    parent still has to say yes afterwards.
    """
    viewer = _parent(session, speaker)
    family_id = session.get(Member, viewer.member_id).family_id
    proposal = session.get(Proposal, proposal_id)

    if proposal is None or proposal.family_id != family_id or proposal.status != "pending":
        return {"named": False, "say": "There is nothing waiting for a name."}

    named = _member(session, family_id, child)
    if named is None or named.role != "child":
        children = _children(session, family_id)
        return {"named": False, "say": f"I do not know that child. It is {say_list(children)}."}

    # Reassigned, not merged: a JSON column needs a new list before SQLAlchemy sees a change.
    amended = [
        {**change, "owner_id": named.id, "child": named.name}
        if change.get("kind") == "task"
        else change
        for change in proposal.changes or []
    ]
    proposal.changes = amended
    session.commit()

    first = next((c for c in amended if c.get("kind") == "task"), None)
    title = first["title"] if first else "it"
    return {
        "named": True,
        "proposal_id": proposal.id,
        "child": named.name,
        "say": f"{named.name}, then. Shall I put {title} on the list?",
    }


def _unnamed(booked: list[dict], session: Session, family_id: int) -> list[str]:
    """Which children a task could be for, when the email named none we recognise.

    Empty when every task has a child, or when the family has only one and it is already theirs.
    """
    if all(change.get("owner_id") for change in booked):
        return []
    return _children(session, family_id)


def _children(session: Session, family_id: int) -> list[str]:
    """The children's names, for the extraction prompt. Read once per check, not once per email."""
    return [
        m.name
        for m in session.scalars(
            sa.select(Member).where(Member.family_id == family_id, Member.role == "child")
        )
    ]


def _member(session: Session, family_id: int, name: str | None):
    wanted = (name or "").strip().lower()
    if not wanted:
        return None
    for member in session.scalars(sa.select(Member).where(Member.family_id == family_id)):
        if member.name.lower() == wanted:
            return member
    return None


# --------------------------------------------------------------------------- what it breaks


def _effect(session: Session, family_id: int, tasks: list[dict], day: date) -> dict:
    """Whether the days a task has to be done on already have a problem, and how to repair it.

    A task is not an event, so it cannot clash with one. What it can do is land on a day the family
    already cannot get through -- which is precisely the costume-by-Friday case -- so the window
    that matters runs from the first day work could start to the day it is due.
    """
    start, end = _window(tasks, day)
    week = load_week(session, family_id, start, end)
    problems = detect(week)
    if not problems:
        return {"from": start.isoformat(), "to": end.isoformat(), "breaks": [], "fix": None}

    result = repair(week)
    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "breaks": [c.as_dict() for c in problems],
        "fix": {
            "change_count": result.change_count,
            "changes": [c.as_dict() for c in result.changes],
            "unfixable": result.unfixable,
        },
    }


def _window(tasks: list[dict], day: date) -> tuple[date, date]:
    """From the earliest day work could start to the last day something is due, never the past."""
    dues = [date.fromisoformat(t["due"]) for t in tasks]
    preps = [
        due - timedelta(days=int(task.get("prep_days") or 0))
        for due, task in zip(dues, tasks, strict=True)
    ]
    return max(day, min(preps)), max(max(dues), day)


def _describe(
    booked: list[dict],
    closures: list[dict],
    cleared: list[dict],
    effect: dict,
    day: date,
    unnamed: list[str] | None = None,
) -> str:
    """The answer. A closure and a task are different news, so they get different sentences."""
    if closures and not booked:
        return _describe_closure(closures[0], cleared, day)

    said = _describe_tasks(booked, effect, day, unnamed)
    if closures:
        said += " " + _describe_closure(closures[0], cleared, day)
    return said


def _describe_closure(closure: dict, cleared: list[dict], day: date) -> str:
    """What a closure takes off, and who it lets off. The second half is the useful half."""
    when = say_day(date.fromisoformat(closure["date"]), day)
    opening = f"School says it is closed {when}: {closure['title']}."
    if not cleared:
        return f"{opening} Nothing in your week changes."

    what = say_list([c["title"] for c in cleared])
    freed = say_list(sorted({name for c in cleared for name in c.get("frees") or []}))
    relief = f" That frees {freed} from the run." if freed else ""
    return f"{opening} I can take {what} off {when}.{relief} Shall I clear it?"


def _describe_tasks(
    booked: list[dict], effect: dict, day: date, unnamed: list[str] | None = None
) -> str:
    count = "One new email" if len(booked) == 1 else f"{len(booked)} new things"
    first = booked[0]
    when = say_day(date.fromisoformat(first["due_iso"]), day)
    who = f"{first['child']} needs" if first.get("child") else "You need"
    opening = f"{count} from school: {who} {first['title']} by {when}."

    # Asked before anything else, because the answer changes whose task it is. Guessing between two
    # children would put a costume on the wrong name, and the parent is the one who knows.
    if unnamed:
        return (
            f"{count} from school: {first['title']} by {when}. "
            f"The email does not say which child. Is it {say_list(unnamed, joiner='or')}?"
        )

    if not effect["breaks"]:
        return f"{opening} Nothing in the week breaks. Shall I add it?"

    problem = effect["breaks"][0]
    fix = effect.get("fix") or {}
    if fix.get("changes"):
        change = fix["changes"][0]
        how = (
            f"{change['now']} takes {change['title']}"
            if change["kind"] == "assign"
            else f"{change['title']} moves to {change['now']}"
        )
        return f"{opening} That week is already in trouble: {problem['detail']}. I can fix it: {how}."
    return f"{opening} Be careful: {problem['detail']}."


# --------------------------------------------------------------------------- shared


def _parent(session: Session, speaker: str):
    viewer = resolve_viewer(session, speaker)
    if viewer.role != "parent":
        raise NotAllowed(f"{viewer.name} is a {viewer.role}; only a parent can read school email.")
    return viewer


def _link(session: Session, family_id: int, parent_id: int):
    return session.scalars(
        sa.select(EmailLink).where(
            EmailLink.family_id == family_id, EmailLink.parent_id == parent_id
        )
    ).first()


def _say_allowed(allowed: list[str], linked: bool) -> str:
    if not allowed:
        return "I am not reading any email. Tell me the school's address and I will read only that."
    where = say_list(allowed)
    linked_note = "" if linked else " Gmail is not linked yet."
    return f"I read email from {where}, and nothing else.{linked_note}"
