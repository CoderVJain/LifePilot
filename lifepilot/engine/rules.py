"""The five rule types, and nothing else.

A rule the family states out loud becomes a structured constraint the solver enforces on every plan.
The model's job is to propose which of the five shapes the speech fits; this module decides whether it
really does. Speech that fits none is refused and queried -- never bent into the nearest type, because
a rule that is silently reinterpreted is worse than one that was never stored.

Pure: no database, no model call. `validate` normalises and raises; `readback` turns a stored rule
back into a sentence a parent can confirm.
"""

import re
from collections.abc import Mapping
from typing import Any

RULE_TYPES = ("immovable_event", "latest_end", "buffer_after", "eligibility", "load_balance")

# Only load balancing is a preference; the rest are promises.
SOFT_TYPES = frozenset({"load_balance"})

ROLES = ("parent", "child", "caregiver")

# People say "grandparents", not "caregiver". Mapping the everyday word to the role we store is
# normalisation, not invention: the rule type and its meaning are unchanged, and anything not on this
# list is still refused.
ROLE_WORDS = {
    "grandparent": "caregiver",
    "grandparents": "caregiver",
    "grandma": "caregiver",
    "grandpa": "caregiver",
    "granny": "caregiver",
    "nana": "caregiver",
    "carer": "caregiver",
    "carers": "caregiver",
    "caregiver": "caregiver",
    "parent": "parent",
    "parents": "parent",
    "child": "child",
    "children": "child",
    "kids": "child",
}
ELIGIBILITY_CONDITIONS = ("no_parent_free",)

# The categories events actually carry. A rule about "homework" would store cleanly and then match
# nothing, which looks like it worked and silently does not, so the everyday words map to the real
# category and anything else is refused.
CATEGORIES = ("work", "school", "activity", "study", "other")
CATEGORY_WORDS = {
    "homework": "study",
    "studying": "study",
    "study": "study",
    "revision": "study",
    "school": "school",
    "class": "school",
    "classes": "school",
    "work": "work",
    "job": "work",
    "meetings": "work",
    "activity": "activity",
    "activities": "activity",
    "club": "activity",
    "clubs": "activity",
    "sport": "activity",
    "sports": "activity",
    "practice": "activity",
    "other": "other",
}

CLOCK = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


class UnsupportedRule(ValueError):
    """The speech does not fit any supported rule type. Ask, do not guess."""


class InvalidRule(ValueError):
    """The right type, but the details are wrong or missing."""


def validate(rule_type: str, params: Mapping[str, Any]) -> dict:
    """Normalised params for a supported rule, or an exception explaining what is wrong."""
    if rule_type not in RULE_TYPES:
        raise UnsupportedRule(
            f"{rule_type!r} is not a rule LifePilot can enforce. "
            f"It knows: {', '.join(RULE_TYPES)}."
        )
    return _VALIDATORS[rule_type](params)


def is_hard(rule_type: str) -> bool:
    return rule_type not in SOFT_TYPES


def readback(rule_type: str, params: Mapping[str, Any]) -> str:
    """One sentence, for a parent to say yes or no to before the rule binds."""
    return _READBACKS[rule_type](params)


# --------------------------------------------------------------------------- validators


def _immovable_event(params: Mapping[str, Any]) -> dict:
    title = _text(params, "title", "which event can never move")
    return {"title": title}


def _latest_end(params: Mapping[str, Any]) -> dict:
    clock = _text(params, "latest_end", "the latest time it may run to, like 21:00")
    if not CLOCK.match(clock):
        raise InvalidRule(f"{clock!r} is not a time of day. Use a 24-hour time like 21:00.")
    out = {"latest_end": clock}
    if params.get("category"):
        spoken = _text(params, "category", "which kind of activity")
        category = CATEGORY_WORDS.get(spoken.lower())
        if category is None:
            raise InvalidRule(
                f"I do not track anything called {spoken!r}. I can apply this to: "
                f"{', '.join(CATEGORIES)}."
            )
        out["category"] = category
    return out


def _buffer_after(params: Mapping[str, Any]) -> dict:
    minutes = params.get("minutes")
    if not isinstance(minutes, int) or isinstance(minutes, bool) or minutes <= 0:
        raise InvalidRule("A buffer needs a number of minutes greater than zero.")
    if minutes > 12 * 60:
        raise InvalidRule("A buffer of more than twelve hours is not something I can plan around.")
    return {
        "member": _text(params, "member", "who the rest is for"),
        "after": _text(params, "after", "what it comes after, like school"),
        "minutes": minutes,
    }


def _eligibility(params: Mapping[str, Any]) -> dict:
    spoken_role = _text(params, "role", "which role the rule is about")
    role = ROLE_WORDS.get(spoken_role.lower(), spoken_role.lower())
    if role not in ROLES:
        raise InvalidRule(
            f"{spoken_role!r} is not a role in this family. Roles are: {', '.join(ROLES)}."
        )
    condition = _text(params, "only_if", "when they may step in")
    if condition not in ELIGIBILITY_CONDITIONS:
        raise UnsupportedRule(
            f"I can only enforce {' or '.join(ELIGIBILITY_CONDITIONS)} for now, not {condition!r}."
        )
    return {"role": role, "only_if": condition}


def _load_balance(params: Mapping[str, Any]) -> dict:
    between = params.get("between")
    if not isinstance(between, list | tuple) or len(between) < 2:
        raise InvalidRule("Balancing needs at least two people to balance between.")
    names = [str(name).strip() for name in between if str(name).strip()]
    if len(names) < 2:
        raise InvalidRule("Balancing needs at least two people to balance between.")
    return {"between": names}


_VALIDATORS = {
    "immovable_event": _immovable_event,
    "latest_end": _latest_end,
    "buffer_after": _buffer_after,
    "eligibility": _eligibility,
    "load_balance": _load_balance,
}


def _text(params: Mapping[str, Any], key: str, what: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        raise InvalidRule(f"I need to know {what}.")
    return value.strip()


# --------------------------------------------------------------------------- readbacks

_ROLE_WORDS = {"parent": "a parent", "child": "a child", "caregiver": "a grandparent or carer"}


def _readback_immovable(params: Mapping[str, Any]) -> str:
    return f"I will never move {params['title']}."


def _readback_latest_end(params: Mapping[str, Any]) -> str:
    category = params.get("category")
    if not category:
        return f"Nothing after {params['latest_end']}."
    return f"No {category} after {params['latest_end']}."


def _readback_buffer(params: Mapping[str, Any]) -> str:
    return (
        f"{params['member']} gets {params['minutes']} minutes after {params['after']} "
        "before anything else."
    )


def _readback_eligibility(params: Mapping[str, Any]) -> str:
    who = _ROLE_WORDS.get(params["role"], params["role"])
    return f"I will only ask {who} to cover when no parent is free."


def _readback_load_balance(params: Mapping[str, Any]) -> str:
    return f"I will try to keep pickups even between {' and '.join(params['between'])}."


_READBACKS = {
    "immovable_event": _readback_immovable,
    "latest_end": _readback_latest_end,
    "buffer_after": _readback_buffer,
    "eligibility": _readback_eligibility,
    "load_balance": _readback_load_balance,
}
