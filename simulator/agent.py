"""The Bedrock path: Nova Micro picks a tool, the server answers, Nova phrases the reply.

Two model calls per turn, which is what the cost table in CLAUDE.md is built on, and both go through
`lifepilot_shared.llm` so there is one file that spends money.

The model's job is language only. It chooses which tool fits and fills the dates; it never decides who
may see what, whether the week works, or who should cover a pickup. In particular `speaker` is removed
from every schema before the model sees it and injected from the session afterwards -- a model that
cannot name the speaker cannot hand a child a parent's view.
"""

import logging
import re
import time
from datetime import timedelta

from botocore.exceptions import ClientError

from lifepilot_shared.clock import today as clock_today
from lifepilot_shared.llm import Turn as Budget
from lifepilot_shared.llm import converse
from lifepilot_shared.speech import plural, say_list, say_span, say_when, say_window
from simulator.conversation import WEEK_END, WEEK_START, Turn

logger = logging.getLogger(__name__)

# Chosen by the model, executed by us. `speaker` is deliberately absent from both.
TOOL_SCHEMAS = [
    {
        "toolSpec": {
            "name": "get_family",
            "description": "Who is in the family, their roles, who can drive, and the places they go.",
            "inputSchema": {"json": {"type": "object", "properties": {}, "required": []}},
        }
    },
    {
        "toolSpec": {
            "name": "get_schedule",
            "description": (
                "What is already on. Use for a day, a week, or a single named time."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "start": {"type": "string", "description": "First day, YYYY-MM-DD."},
                        "end": {"type": "string", "description": "Last day, YYYY-MM-DD."},
                        "at": {
                            "type": "string",
                            "description": "One named time, HH:MM. Set it whenever they name a time.",
                        },
                        "about": {
                            "type": "string",
                            "description": "Whose day. Resolve 'my' and 'I' to the speaker's own name; "
                                "otherwise whoever they named. Omit for everyone.",
                        },
                    },
                    "required": ["start", "end"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "detect_conflicts",
            "description": (
                "What is broken: a lift nobody can make, a clash, a rule broken."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "start": {"type": "string", "description": "First day, YYYY-MM-DD."},
                        "end": {"type": "string", "description": "Last day, YYYY-MM-DD."},
                    },
                    "required": ["start", "end"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "remember_rule",
            "description": (
                "A standing rule the family is stating: 'no homework after nine', 'never "
                "move piano', 'grandparents only when we are both busy'."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "rule_type": {
                            "type": "string",
                            "enum": [
                                "immovable_event",
                                "latest_end",
                                "buffer_after",
                                "eligibility",
                                "load_balance",
                            ],
                        },
                        "params": {
                            "type": "object",
                            "description": (
                                "immovable_event {title}; latest_end {category, latest_end HH:MM}; "
                                "buffer_after {member, after, minutes}; eligibility {role, "
                                "only_if}; load_balance {between}."
                            ),
                        },
                    },
                    "required": ["rule_type", "params"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "list_rules",
            "description": (
                "What rules already exist. Not for stating a new one."
            ),
            "inputSchema": {"json": {"type": "object", "properties": {}, "required": []}},
        }
    },
    {
        "toolSpec": {
            "name": "suggest_responsible",
            "description": (
                "Who should cover a lift, ranked, with the reason."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": (
                                "What identifies the lift: the event, such as football or piano, "
                                "or the child being collected, such as Aarav."
                            ),
                        }
                    },
                    "required": [],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "explain_choice",
            "description": (
                "Why a person was or was not chosen for a lift: 'why not Grandpa'."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "person": {
                            "type": "string",
                            "description": "Who is being asked about, such as Grandpa or Mom.",
                        },
                        "title": {
                            "type": "string",
                            "description": (
                                "What identifies the lift, if they said: the event, or the child "
                                "being collected."
                            ),
                        },
                    },
                    "required": ["person"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "fix_week",
            "description": (
                "Repair the week with the fewest changes, for a parent to approve."
            ),
            "inputSchema": {"json": {"type": "object", "properties": {}, "required": []}},
        }
    },
    {
        "toolSpec": {
            "name": "what_if",
            "description": (
                "What WOULD happen if something changed: 'what if my four o'clock runs "
                "late', 'what if football is cancelled', 'can I say yes to a six o'clock'. "
                "Anything hypothetical is this, never get_schedule. Changes nothing."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": ["runs_late", "new_event", "cancelled"]},
                        "title": {
                            "type": "string",
                            "description": "The event: the existing one, or a name for the new one.",
                        },
                        "until": {
                            "type": "string",
                            "description": "runs_late: new finish, 24-hour HH:MM.",
                        },
                        "at": {
                            "type": "string",
                            "description": "Which event, by when it starts: YYYY-MM-DDTHH:MM.",
                        },
                        "start": {
                            "type": "string",
                            "description": "For new_event: YYYY-MM-DDTHH:MM.",
                        },
                        "end": {"type": "string", "description": "For new_event: YYYY-MM-DDTHH:MM."},
                    },
                    "required": ["kind"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "cannot_help",
            "description": (
                "Anything outside this family's calendar: booking, buying, money, "
                "weather, messaging, general knowledge. Use it rather than "
                "answering with something adjacent."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {"reason": {"type": "string"}},
                    "required": ["reason"],
                }
            },
        }
    },
]

def route_system(speaker: str) -> list[dict]:
    """Built per call, because it carries today's date and who is talking.

    Without it the model cannot resolve "tomorrow" at all -- it was quietly answering with today,
    which looks like the product ignoring half the question. Nothing in a prompt can make up for a
    fact the prompt does not contain.
    """
    today = clock_today()
    return [
        {
            "text": (
                f"You route {speaker}'s request to one LifePilot tool. {speaker} is the person "
                f"speaking, so \"my schedule\" and \"what have I got\" are about {speaker}. "
                f"Today is {DAY_NAMES[today.weekday()]} {today.isoformat()}. "
                f"Tomorrow is {(today + timedelta(days=1)).isoformat()} and yesterday was "
                f"{(today - timedelta(days=1)).isoformat()}. "
                f"The family's week runs {WEEK_START.isoformat()} to {WEEK_END.isoformat()}. "
                "Work out the dates the request actually asks for; only use the whole week when no "
                "day is named. Choose exactly one tool. Never answer from your own knowledge."
            )
        }
    ]


DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

PHRASE_SYSTEM = [
    {
        "text": (
            "You are LifePilot, speaking aloud to a family member. You are given a short list of "
            "facts. Say them naturally and briefly. Use ONLY those facts. Never add a name, a "
            "time, a place or an activity that is not in the list, and never attach an activity "
            "to a person the list does not attach it to. A line beginning 'Name:' means the thing "
            "belongs to that person. Cover every fact in the list, in the order given; do not drop "
            "one to be brief. Say what the facts say, never how they are written: no mentioning "
            "lines, lists or formatting. Do not use the words redacted, JSON, tool or data."
        )
    }
]

# Same utterance, same speaker, same route. Routing does not depend on the data, so this is safe to
# cache and it keeps a repeated demo utterance from spending anything.
_route_cache: dict[str, tuple[str, dict]] = {}


def choose_tool(text: str, budget: Budget, speaker: str = "Dad") -> tuple[str, dict]:
    """Ask Nova which tool fits. Returns the tool name and its arguments.

    Keyed by speaker as well as words: "my schedule" routes to a different person depending on who
    said it, so one cache entry cannot serve both.
    """
    key = f"{speaker}|{clock_today().isoformat()}|{text.strip().lower()}"
    if key in _route_cache:
        return _route_cache[key]

    response = _route_once(text, speaker, budget)
    blocks = response["output"]["message"]["content"]
    uses = [block["toolUse"] for block in blocks if "toolUse" in block]
    if not uses:
        return "cannot_help", {"reason": "the model returned no tool call"}

    chosen = (uses[0]["name"], uses[0].get("input") or {})
    _route_cache[key] = chosen
    return chosen


def _route_once(text: str, speaker: str, budget: Budget):
    """One routing call, retried once if the model emits malformed tool use.

    Nova occasionally returns "Model produced invalid sequence as part of ToolUse" -- a formatting
    failure, not a decision. Retrying is honest where re-asking the same question is honest, and the
    turn's call ceiling is what stops it becoming a loop: it is already counted, so a second attempt
    spends budget rather than escaping it.
    """
    for attempt in range(2):
        try:
            return converse(
                messages=[{"role": "user", "content": [{"text": text}]}],
                system=route_system(speaker),
                tool_config={"tools": TOOL_SCHEMAS, "toolChoice": {"any": {}}},
                turn=budget,
                max_tokens=256,
            )
        except ClientError as malformed:
            if attempt or "ToolUse" not in str(malformed):
                raise
            logger.warning("the model emitted malformed tool use; asking once more")
    raise RuntimeError("unreachable")


def phrase(text: str, facts: list[str], budget: Budget) -> str:
    """Ask Nova to word a list of facts we computed. It adds no information of its own.

    Handing the model raw tool JSON produced confident falsehoods -- an event attached to the wrong
    child, a date range that did not exist, locations turned into claims about where people were.
    A short fact list removes the room to infer.
    """
    listed = "\n".join(f"- {fact}" for fact in facts)
    response = converse(
        messages=[
            {
                "role": "user",
                "content": [{"text": f"They asked: {text}\n\nFacts:\n{listed}\n\nSay this aloud."}]
            }
        ],
        system=PHRASE_SYSTEM,
        turn=budget,
        max_tokens=160,
    )
    blocks = response["output"]["message"]["content"]
    return "".join(block.get("text", "") for block in blocks).strip()


# Answering a read-back question is a yes/no, not a request. Deciding it in code costs nothing and
# cannot drift, where a model call could read "no, wait" as agreement.
YES = {"yes", "yeah", "yep", "sure", "ok", "okay", "please do", "go ahead", "correct",
       "that's right", "do it", "make them", "approve", "agreed"}
NO = {"no", "nope", "cancel", "forget it", "don't", "do not", "wait", "not now", "leave it"}

# People say "yes please" and "no thanks". Requiring the bare word turned a plain yes into an
# unrecognised request, which then got routed somewhere else entirely.
POLITENESS = ("please", "thanks", "thank you", "then")


def _decision(text: str) -> str | None:
    """"yes", "no", or None when this is not an answer to the question we just asked."""
    said = text.strip().lower().rstrip(".!?")
    for word in POLITENESS:
        for shape in (f" {word}", f"{word} "):
            if said.startswith(shape.strip() + " ") or said.endswith(shape):
                said = said.replace(word, "").strip(" ,")
    said = " ".join(said.split())
    if said in YES:
        return "yes"
    if said in NO:
        return "no"
    return None


def answer(mcp, speaker: str, text: str, call_tool, state: dict | None = None) -> Turn:
    """One voice turn: route, execute, phrase. `call_tool` runs the MCP call and returns (data, debug)."""
    budget = Budget()
    started = time.perf_counter()
    state = state if state is not None else {}

    # Held per speaker: the browser sends the speaker per message on one socket, so Dad's
    # half-agreed rule must not be confirmable by whoever speaks next.
    waiting = state.get("pending_proposal", {}).get(speaker)
    if waiting:
        settled = _settle_proposal(mcp, speaker, text, call_tool, state, waiting, budget, started)
        if settled is not None:
            return settled

    pending = state.get("pending_rule", {}).get(speaker)
    if pending:
        settled = _settle_pending_rule(mcp, speaker, text, call_tool, state, pending, budget, started)
        if settled is not None:
            return settled

    tool, arguments = choose_tool(text, budget, speaker)
    state["routed"] = tool

    if tool == "what_if":
        return _try_it_out(mcp, speaker, text, arguments, call_tool, budget, started)

    if tool == "fix_week":
        return _propose_fix(mcp, speaker, call_tool, state, budget, started)

    if tool in {"suggest_responsible", "explain_choice"}:
        return _decide(mcp, speaker, tool, arguments, call_tool, state, budget, started)

    if tool == "remember_rule":
        return _propose_rule(mcp, speaker, text, arguments, call_tool, state, budget, started)

    if tool == "cannot_help":
        return Turn(
            speak="I can tell you who is in the family and what is on this week. I cannot do that one yet.",
            debug=_debug(None, arguments, budget, started, note=arguments.get("reason", "")),
        )

    # The session decides who is asking. The model never does.
    arguments = {"speaker": speaker, **_safe_arguments(tool, arguments, speaker)}

    # A named time is the question when somebody names one. The model picks get_schedule for "do I
    # have anything at five" but often leaves `at` empty, and the answer becomes the whole day.
    if tool == "get_schedule" and not arguments.get("at"):
        spoken_at = named_time(text)
        if spoken_at:
            arguments["at"] = spoken_at
    data, tool_debug = call_tool(mcp, tool, arguments)
    if not data:
        return Turn(
            speak=_blocked(tool_debug, "reach that"),
            debug={**tool_debug, **_debug(tool, arguments, budget, started)},
        )

    spoken = phrase(text, _facts(tool, data, speaker), budget)
    cards = _cards(tool, data)
    return Turn(
        speak=spoken,
        cards=cards,
        debug={**tool_debug, **_debug(tool, arguments, budget, started)},
    )


def _propose_fix(mcp, speaker, call_tool, state, budget, started):
    """Ask the server for the smallest repair and hold it for a yes. Nothing is changed here."""
    result, debug = call_tool(
        mcp,
        "fix_week",
        {"speaker": speaker, "start": WEEK_START.isoformat(), "end": WEEK_END.isoformat()},
    )
    if not result:
        return Turn(speak=_blocked(debug, "work out a fix"), debug=debug)

    cards = []
    if result.get("proposal_id"):
        state.setdefault("pending_proposal", {})[speaker] = result["proposal_id"]
        cards = [{"kind": "proposal", "title": "Proposed changes", "proposal": result}]

    # The server already wrote the diff as a sentence. Rewording a list of changes a parent is about
    # to approve is exactly where a model should not be trusted.
    return Turn(
        speak=result["say"],
        cards=cards,
        debug={**debug, **_debug("fix_week", {}, budget, started)},
    )


def _settle_proposal(mcp, speaker, text, call_tool, state, proposal_id, budget, started):
    """A yes approves the diff the parent just heard; a no leaves the week alone."""
    decision = _decision(text)
    if decision is None:
        return None

    state.get("pending_proposal", {}).pop(speaker, None)
    tool = "approve_proposal" if decision == "yes" else "reject_proposal"
    result, debug = call_tool(mcp, tool, {"speaker": speaker, "proposal_id": proposal_id})
    say = result.get("say") if result else None
    return Turn(
        speak=say or "I could not do that.",
        debug={**debug, **_debug(tool, {"proposal_id": proposal_id}, budget, started)},
    )


def _decide(mcp, speaker, tool, arguments, call_tool, state, budget, started):
    """Who should go, and why not someone else. Both answers are the server's, said as written.

    The reason a person was ruled out was recorded when the decision was made. Rewording it risks
    saying something the solver did not decide, which is the one thing these answers must never do.
    """
    clean = _safe_arguments(tool, arguments, speaker)
    remembered = state.get("last_lift")

    def ask(arguments: dict):
        return call_tool(
            mcp,
            tool,
            {
                "speaker": speaker,
                "start": WEEK_START.isoformat(),
                "end": WEEK_END.isoformat(),
                **arguments,
            },
        )

    if not clean.get("title") and remembered:
        clean["title"] = remembered

    result, debug = ask(clean)

    # "Why not Grandpa?" names no lift, because the lift was named a sentence ago -- and the model
    # fills the field with the question itself rather than leaving it empty, so an empty check is
    # not enough. If what it gave matches nothing, fall back to what was being discussed. One more
    # call to the server, no model call, and only when the first answer was "which lift?".
    if remembered and not result.get("found", True) and clean.get("title") != remembered:
        result, debug = ask({**clean, "title": remembered})

    if not result:
        return Turn(speak=_blocked(debug, "work that out"), debug=debug)
    if result.get("title"):
        state["last_lift"] = result["title"]

    if tool == "explain_choice":
        return Turn(
            speak=result.get("say", "I could not work that out."),
            debug={**debug, **_debug(tool, clean, budget, started)},
        )

    if not result.get("found"):
        return Turn(speak=result.get("say", "I could not tell which lift you meant."), debug=debug)

    ranked = result.get("ranked") or []
    if not ranked:
        ruled = ", ".join(f"{r['name']} {r['reason']}" for r in result.get("ruled_out", [])[:3])
        speak = f"Nobody can cover {result['title']}. {ruled}." if ruled else "Nobody can cover it."
    else:
        best = ranked[0]
        speak = f"{best['name']}, because {best['reason']}."
        if result.get("assigned_to") and result["assigned_to"] != best["name"]:
            speak = (
                f"{best['name']} should, because {best['reason']}. "
                f"{result['assigned_to']} is down for it at the moment."
            )

    return Turn(
        speak=speak,
        cards=[{"kind": "decision", "title": result["title"], "ranked": ranked,
                "ruled_out": result.get("ruled_out", []), "assigned_to": result.get("assigned_to")}],
        debug={**debug, **_debug(tool, clean, budget, started)},
    )


def _try_it_out(mcp, speaker, text, arguments, call_tool, budget, started):
    """A what-if answers itself: the server already wrote the sentence, and it must not be softened."""
    clean = _safe_arguments("what_if", arguments, speaker)
    result, debug = call_tool(
        mcp,
        "what_if",
        {
            "speaker": speaker,
            "start": WEEK_START.isoformat(),
            "end": WEEK_END.isoformat(),
            "change": clean,
        },
    )
    if not result:
        return Turn(speak=_blocked(debug, "work that one out"), debug=debug)

    cards = []
    if result.get("understood") and result.get("ripple"):
        cards = [{
            "kind": "whatif",
            "title": "If that happened",
            "asked": clean,
            "ripple": result["ripple"],
            "fix": result.get("fix"),
        }]
    return Turn(
        speak=result["say"],
        cards=cards,
        debug={**debug, **_debug("what_if", clean, budget, started)},
    )


def _settle_pending_rule(mcp, speaker, text, call_tool, state, pending, budget, started):
    """A yes stores the rule the parent just heard; a no drops it. Anything else is a new request."""
    decision = _decision(text)
    if decision == "yes":
        state.get("pending_rule", {}).pop(speaker, None)
        stored, debug = call_tool(
            mcp,
            "add_rule",
            {
                "speaker": speaker,
                "rule_type": pending["type"],
                "params": pending["params"],
                "spoken_text": pending["spoken_text"],
                "confirmed": True,
            },
        )
        say = stored.get("say", "I could not store that.") if stored else "I could not store that."
        return Turn(speak=say, debug={**debug, **_debug("add_rule", pending, budget, started)})

    if decision == "no":
        state.get("pending_rule", {}).pop(speaker, None)
        return Turn(
            speak="Alright, I won't remember that.",
            debug=_debug(None, {}, budget, started, note="rule declined"),
        )
    return None


def _propose_rule(mcp, speaker, text, arguments, call_tool, state, budget, started):
    """Validate the rule on the server and read it back. Nothing is stored yet."""
    clean = _safe_arguments("remember_rule", arguments, speaker)
    result, debug = call_tool(
        mcp,
        "add_rule",
        {
            "speaker": speaker,
            "rule_type": clean.get("rule_type", ""),
            "params": clean.get("params") or {},
            "spoken_text": text,
            "confirmed": False,
        },
    )
    if not result:
        return Turn(speak=_blocked(debug, "check that rule"), debug=debug)

    if result.get("needs_confirmation"):
        state.setdefault("pending_rule", {})[speaker] = {
            "type": result["type"],
            "params": result["params"],
            "spoken_text": text,
        }

    # The read-back is spoken exactly as the server wrote it. A rule the parent agrees to must be
    # the sentence they actually heard, not a rewording of it.
    return Turn(
        speak=result["say"],
        cards=[{"kind": "rule", "title": "New rule", "readback": result.get("readback"),
                "spoken_text": text, "pending": bool(result.get("needs_confirmation"))}],
        debug={**debug, **_debug("add_rule", clean, budget, started)},
    )


ALLOWED_ARGUMENTS = {
    "get_schedule": {"start", "end", "about", "at"},
    "detect_conflicts": {"start", "end"},
    "get_family": set(),
    "list_rules": set(),
    "remember_rule": {"rule_type", "params"},
    "what_if": {"kind", "title", "until", "at", "start", "end"},
    "fix_week": set(),
    "suggest_responsible": {"title"},
    "explain_choice": {"person", "title"},
}

#: Tools whose start and end are whole days. `what_if` is deliberately absent: a hypothetical
#: happens at a time of day, so trimming its timestamps would throw away the question.
WHOLE_DAY_ARGUMENTS = {"get_schedule": {"start", "end"}, "detect_conflicts": {"start", "end"}}

#: Words that mean the person speaking. The model passes them through however the schema is worded,
#: so they are resolved here instead of being asked for.
SELF_WORDS = {"my", "me", "i", "mine", "myself", "my own", "self"}

#: Spoken hours. People say "five o'clock" as often as "5 PM", and a named time is the whole point
#: of the question when they name one.
SPOKEN_HOURS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}

#: "at 5 PM", "5:00 p.m.", "17:00", "five o'clock".
NAMED_TIME = re.compile(
    r"(?:(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\.?"
    r"|(\d{1,2}):(\d{2})"
    r"|(" + "|".join(SPOKEN_HOURS) + r")\s*o.?clock)",
    re.IGNORECASE,
)

#: What a model emits for an optional field it has nothing to put in. Seen in the wild: HTML-escaped
#: newlines. They reach the tool as a time that is not a time and the whole turn fails.
NOT_REALLY_VALUES = {"", "null", "none", "n/a", "na", "&#xa;", "&#xd;", "\\n", "-", "?"}


def _blocked(debug: dict, what: str) -> str:
    """Say what went wrong, not merely that something did.

    A tester hearing "I could not reach that" has nothing to act on, while the server had already
    said exactly what it objected to.
    """
    reason = (debug or {}).get("error")
    if not reason:
        return f"I could not {what}."
    return f"I could not {what}: {reason.strip()}"


def _safe_arguments(tool: str, arguments: dict, speaker: str | None = None) -> dict:
    """Keep only what the schema allows, drop what is not a value, and fit what is.

    The model is a probabilistic producer and the tool is a typed contract; this is the seam. Two
    real failures came through it: a full timestamp where a date was wanted, and placeholder junk in
    optional fields. Both reached the server as a rejected call and the person as "I could not reach
    that", which explains nothing to anybody.
    """
    allowed = ALLOWED_ARGUMENTS[tool]
    whole_day = WHOLE_DAY_ARGUMENTS.get(tool, set())

    clean = {}
    for key, value in arguments.items():
        if key not in allowed:
            continue
        usable = _usable(value)
        if usable is None:
            continue
        if key in {"about", "person"} and str(usable).strip().lower() in SELF_WORDS:
            usable = speaker or usable
        clean[key] = _as_day(usable) if key in whole_day else usable
    return clean


def named_time(text: str) -> str | None:
    """The clock time somebody named, as HH:MM, or None if they named none.

    Asked "do I have anything at five", the model picks get_schedule but often leaves `at` empty,
    and the answer becomes the whole day -- true, and not what was asked. Reading the time from the
    words is deterministic, so it does not depend on the model remembering to fill the field.
    """
    match = NAMED_TIME.search(text)
    if match is None:
        return None

    hour12, minute12, meridiem, hour24, minute24, spoken = match.groups()
    if hour24 is not None:
        return f"{int(hour24):02d}:{minute24}"
    if spoken is not None:
        hour = SPOKEN_HOURS[spoken.lower()]
        # An unqualified spoken hour in a family's day means the afternoon far more often than dawn.
        return f"{hour + 12 if hour < 8 else hour:02d}:00"

    hour = int(hour12) % 12 + (12 if meridiem.lower() == "p" else 0)
    return f"{hour:02d}:{minute12 or '00'}"


def _usable(value):
    """The value, or None when it is a placeholder rather than an answer."""
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    text = value.strip()
    return None if text.lower() in NOT_REALLY_VALUES else text


def _as_day(value):
    """A whole day. "2026-10-01T16:00" asked about a day, and said so with a time attached."""
    if isinstance(value, str) and "T" in value:
        return value.split("T", 1)[0]
    return value


def _facts(tool: str, data: dict, speaker: str) -> list[str]:
    """The facts, already decided, in plain English. Everything the model is allowed to say."""
    if tool == "list_rules":
        rules = data["rules"]
        if not rules:
            return ["No rules have been set yet."]
        return [f"There are {len(rules)} rules."] + [r["readback"] for r in rules]
    if tool == "detect_conflicts":
        return _conflict_facts(data)
    if tool == "get_family":
        facts = [f"You are speaking to {speaker}."]
        for member in data["members"]:
            if member["is_you"]:
                continue
            drives = ", can drive" if member["can_drive"] else ""
            facts.append(f"{member['name']} is a {member['role']}{drives}.")
        return facts

    # A question about one moment gets an answer about that moment, not the day it falls in.
    if data.get("at_that_time"):
        return _moment_facts(data, speaker)

    events = data["events"]
    mine = [e for e in events if not e.get("redacted")]
    hidden = len(events) - len(mine)

    one_day = data["from"] == data["to"]
    window = say_window(data["from"], data["to"])
    subject = data.get("about")
    mine_only = bool(subject) and subject == speaker

    if not events:
        if mine_only:
            nothing = "You have nothing on"
        elif subject:
            nothing = f"{subject} has nothing on"
        else:
            nothing = "There is nothing at all"
        return [
            f"{nothing} {window}.",
            f"The week that is loaded is {say_window(WEEK_START, WEEK_END)}, "
            "so anything outside it will look empty.",
        ]

    if mine_only:
        owner = "You have"
    elif subject:
        owner = f"{subject} has"
    else:
        owner = f"{speaker} can see"
    facts = [f"{owner} {plural(len(mine), 'thing')} {window}."]
    if hidden:
        facts.append(
            f"{hidden} other blocks of time belong to other people; you cannot say what they are."
        )

    # Reading out nineteen events is a recital, not an answer, and it ran past the token limit
    # mid-sentence. Your own day is listed in full, because you asked for it. The family's week gets
    # its shape plus the parts that need somebody to drive.
    listed = mine if (one_day or subject) else [e for e in mine if e.get("needs_transport")]
    for event in listed[:8]:
        # Whose it is has already been said once; repeating it on every line is how a robot talks.
        facts.append(_event_fact(event, with_day=not one_day, mine_only=bool(subject)))

    rest = len(mine) - len(listed[:8])
    if rest > 0:
        facts.append(
            f"The other {rest} are the usual work and school."
            if not (one_day or subject)
            else f"{rest} more are not listed here."
        )
    return facts


def _moment_facts(data: dict, speaker: str) -> list[str]:
    """Asked about one moment, answer about that moment.

    Listing the whole day is true and leaves the person to work it out. What finishes exactly then
    is said separately, because "football finishes at five" is why five o'clock is not really free
    even though nothing runs through it.
    """
    then = data["at_that_time"]
    spoken = say_when(data["at"])
    subject = data.get("about")
    you = "You" if subject == speaker else (subject or "The family")

    busy = then["running"] + then["starting"]
    facts = []
    if busy:
        facts.append(f"{you} are busy {spoken}.")
        facts.extend(_event_fact(event, with_day=False, mine_only=True) for event in busy)
    else:
        facts.append(f"{you} have nothing on {spoken}.")

    for event in then["finishing"]:
        lift = ", so somebody has to collect them" if event.get("needs_transport") else ""
        facts.append(f"{event['title']} finishes exactly then{lift}.")

    named = {id(e) for e in busy + then["finishing"]}
    others = [e for e in data["events"] if id(e) not in named]
    if others:
        facts.append(f"There {'is' if len(others) == 1 else 'are'} "
                     f"{plural(len(others), 'other thing')} that day, at other times.")
    return facts


def _event_fact(event: dict, with_day: bool, mine_only: bool = False) -> str:
    # The span, not just the start: "school at 8 AM" does not tell a parent when to collect anyone,
    # and "what are the school timings" is exactly that question.
    when = say_span(event["start"], event.get("end"), with_day=with_day)
    where = f" at {event['location']}" if event.get("location") else ""
    lift = ", needs a lift" if event.get("needs_transport") else ""
    if mine_only:
        # Already established as yours; naming yourself on every line is how a robot talks.
        return f"{event['title']} {when}{where}{lift}."
    whose = say_list(event.get("members") or []) or "the family"
    return f"{whose}: {event['title']} {when}{where}{lift}."


def _conflict_facts(data: dict) -> list[str]:
    """Conflicts are the product. The model may reword them but must not soften or invent one."""
    conflicts = data["conflicts"]
    checked = data["checked"]
    if not conflicts:
        return [
            f"Nothing is broken between {data['from']} and {data['to']}.",
            f"{checked['events']} events, {checked['lifts_needed']} lifts and "
            f"{checked['rules']} family rules were checked.",
        ]

    count = len(conflicts)
    plural = "problem" if count == 1 else "problems"
    verb = "is" if count == 1 else "are"
    facts = [f"There {verb} {count} {plural} this week."]
    for conflict in conflicts[:4]:
        when = f"On {say_when(conflict['when'])}"
        # The title has to be named: "detail" says "down for this", and without it the model has
        # nothing to point at and says "Dad was supposed to be down" on its own. Skip the prefix
        # when the detail already opens with the title, or it is said twice.
        detail = conflict["detail"]
        subject = "" if detail.startswith(conflict["title"]) else f"{conflict['title']}: "
        facts.append(f"{when}, {subject}{detail}.")
        if conflict["could_cover"]:
            facts.append(f"{' or '.join(conflict['could_cover'])} could cover it instead.")
    return facts



def _cards(tool: str, data: dict) -> list[dict]:
    if tool == "list_rules":
        return [{"kind": "rules", "title": "Your rules", "rules": data["rules"]}]
    if tool == "detect_conflicts":
        return [{"kind": "conflicts", "title": f"{data['from']} to {data['to']}",
                 "conflicts": data["conflicts"], "checked": data["checked"]}]
    if tool == "get_family":
        return [{"kind": "family", "title": "Your family", "members": data["members"],
                 "locations": data["locations"]}]
    return [{"kind": "schedule", "title": f"{data['from']} to {data['to']}",
             "events": data["events"], "tasks": data["tasks"]}]


def _debug(tool: str | None, arguments: dict, budget: Budget, started: float, note: str = "") -> dict:
    debug = {
        "tool": tool,
        "arguments": arguments,
        "model_calls": budget.calls,
        "input_tokens": budget.input_tokens,
        "output_tokens": budget.output_tokens,
        "estimated_cost_usd": round(budget.cost_usd, 8),
        "turn_ms": round((time.perf_counter() - started) * 1000),
    }
    if note:
        debug["note"] = note
    return debug
