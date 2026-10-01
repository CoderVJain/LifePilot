"""add_rule, list_rules, remove_rule.

A rule binds in two steps. The first call parses and validates it and hands back one sentence to say
out loud; nothing is stored. The second call, with `confirmed=True`, stores it. A parent who never
heard the rule read back never agreed to it, and a rule nobody agreed to should not shape the week.

Only a parent may change the rules. That is checked here, not asked of a prompt.
"""

import sqlalchemy as sa
from sqlalchemy.orm import Session

from lifepilot.db.models import Member, Rule
from lifepilot.engine.rules import InvalidRule, UnsupportedRule, is_hard, readback, validate
from lifepilot.tools.context import resolve_viewer


class NotAllowed(PermissionError):
    """Only parents may change the family's rules."""


def _parent_only(session: Session, speaker: str):
    viewer = resolve_viewer(session, speaker)
    if viewer.role != "parent":
        raise NotAllowed(f"{viewer.name} is a {viewer.role}; only a parent can change family rules.")
    return viewer


def _family_id(session: Session, member_id: int) -> int:
    return session.get(Member, member_id).family_id


def add_rule(
    session: Session,
    speaker: str,
    rule_type: str,
    params: dict,
    spoken_text: str,
    confirmed: bool = False,
) -> dict:
    """Validate a rule and read it back, or store it once a parent has confirmed it."""
    viewer = _parent_only(session, speaker)

    try:
        clean = validate(rule_type, params)
        clean = _resolve_names(session, viewer, rule_type, clean)
    except (UnsupportedRule, InvalidRule) as refusal:
        return {
            "stored": False,
            "needs_confirmation": False,
            "problem": str(refusal),
            "say": str(refusal),
        }

    sentence = readback(rule_type, clean)
    if not confirmed:
        return {
            "stored": False,
            "needs_confirmation": True,
            "type": rule_type,
            "params": clean,
            "readback": sentence,
            "say": f"{sentence} Shall I remember that?",
        }

    family_id = _family_id(session, viewer.member_id)
    existing = _find(session, family_id, rule_type, clean)
    if existing is not None:
        return {
            "stored": False,
            "needs_confirmation": False,
            "rule_id": existing.id,
            "say": f"You already told me: {sentence}",
        }

    rule = Rule(
        family_id=family_id,
        type=rule_type,
        hard=is_hard(rule_type),
        params=clean,
        spoken_text=spoken_text,
        confirmed_by=viewer.member_id,
        active=True,
    )
    session.add(rule)
    session.commit()
    return {
        "stored": True,
        "needs_confirmation": False,
        "rule_id": rule.id,
        "type": rule_type,
        "params": clean,
        "readback": sentence,
        "say": f"Remembered. {sentence}",
    }


SELF_WORDS = {"me", "i", "myself", "my"}


def _resolve_names(session: Session, viewer, rule_type: str, params: dict) -> dict:
    """Turn the names in a rule into real family members, or refuse.

    A rule about "Priya" when nobody in the family is called Priya would be stored and then quietly
    never apply, which is worse than not storing it. "me" means whoever is speaking.
    """
    if rule_type == "buffer_after":
        return {**params, "member": _one_name(session, viewer, params["member"])}
    if rule_type == "load_balance":
        names = [_one_name(session, viewer, name) for name in params["between"]]
        if len(set(names)) < 2:
            raise InvalidRule("Balancing needs two different people.")
        return {**params, "between": names}
    return params


def _one_name(session: Session, viewer, spoken: str) -> str:
    family_id = _family_id(session, viewer.member_id)
    if spoken.strip().lower() in SELF_WORDS:
        return viewer.name

    members = session.scalars(sa.select(Member).where(Member.family_id == family_id)).all()
    for member in members:
        if member.name.lower() == spoken.strip().lower():
            return member.name
    known = ", ".join(m.name for m in members)
    raise InvalidRule(f"I do not know anyone called {spoken!r}. This family is: {known}.")


def list_rules(session: Session, speaker: str) -> dict:
    """Every rule in force, in the family's own words and in LifePilot's."""
    viewer = resolve_viewer(session, speaker)
    family_id = _family_id(session, viewer.member_id)
    rules = session.scalars(
        sa.select(Rule)
        .where(Rule.family_id == family_id, Rule.active.is_(True))
        .order_by(Rule.id)
    ).all()
    return {
        "speaker": {"name": viewer.name, "role": viewer.role},
        "rules": [
            {
                "id": rule.id,
                "type": rule.type,
                "hard": bool(rule.hard),
                "params": rule.params,
                "spoken_text": rule.spoken_text,
                "readback": readback(rule.type, rule.params),
            }
            for rule in rules
        ],
    }


def remove_rule(session: Session, speaker: str, rule_id: int, confirmed: bool = False) -> dict:
    """Retire a rule, read back first so nobody drops one by accident."""
    viewer = _parent_only(session, speaker)
    family_id = _family_id(session, viewer.member_id)

    rule = session.get(Rule, rule_id)
    if rule is None or rule.family_id != family_id or not rule.active:
        return {"removed": False, "say": "I could not find that rule."}

    sentence = readback(rule.type, rule.params)
    if not confirmed:
        return {
            "removed": False,
            "needs_confirmation": True,
            "rule_id": rule.id,
            "readback": sentence,
            "say": f"That rule says: {sentence} Shall I forget it?",
        }

    # Kept as a row, marked inactive: the week's history should still explain itself.
    rule.active = False
    session.commit()
    return {
        "removed": True,
        "rule_id": rule.id,
        "say": f"Forgotten. I will no longer apply: {sentence}",
    }


def _find(session: Session, family_id: int, rule_type: str, params: dict) -> Rule | None:
    """A rule already in force with the same meaning, so nothing is stored twice."""
    for rule in session.scalars(
        sa.select(Rule).where(
            Rule.family_id == family_id, Rule.type == rule_type, Rule.active.is_(True)
        )
    ):
        if rule.params == params:
            return rule
    return None
