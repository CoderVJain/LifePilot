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
from datetime import date, timedelta

from botocore.exceptions import ClientError

from lifepilot_shared.clock import today as clock_today
from lifepilot_shared.llm import Turn as Budget
from lifepilot_shared.llm import converse
from lifepilot_shared.speech import (
    plural,
    say_day,
    say_lift,
    say_list,
    say_on,
    say_span,
    say_when,
    say_window,
)
from simulator.conversation import WEEK_END, WEEK_START, Turn
from simulator.toolsets import COARSE_SCHEMAS
from simulator.toolsets import coarse as _coarse_toolset
from simulator.toolsets import translate as _translate_toolset

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
                        "title": {
                            "type": "string",
                            "description": (
                                "One named thing, such as 'piano' or 'football'. Set it whenever "
                                "they ask about a particular class, practice or meeting rather than "
                                "a whole day."
                            ),
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
            "name": "cancel_event",
            "description": (
                "Take something out of the week when they say it is off: 'cancel football "
                "practice', 'cancel my meeting on Thursday', 'cancel our lunch at Grandpa's and "
                "book lunch with Mom instead' -- one sentence, both halves. Only "
                "for something already in the family's calendar -- never for shopping, buying, "
                "ordering or any errand. A parent approves before anything is removed. Use what_if "
                "instead when they are only asking what would happen if something were cancelled."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": (
                                "What it is called, in their words: 'football practice', "
                                "'my meeting'."
                            ),
                        },
                        "day": {
                            "type": "string",
                            "description": "The day it is on, YYYY-MM-DD, if they said which.",
                        },
                        "at": {
                            "type": "string",
                            "description": "When it starts, YYYY-MM-DDTHH:MM, if they named a time.",
                        },
                        "replace_with": {
                            "type": "string",
                            "description": (
                                "What to put in its place, when they said to book something "
                                "instead. Omit when they only want it cancelled."
                            ),
                        },
                        "replace_members": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Who the replacement is with, besides the speaker.",
                        },
                    },
                    "required": ["title"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "add_event",
            "description": (
                "Actually put something new in the week, when they have decided to: 'book a "
                "dentist at ten on Friday', 'add swimming for Aarav on Monday', 'put that in'. "
                "A parent approves before it is saved. Use what_if instead when they are only "
                "asking whether a time would work."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "What it is called, such as 'dentist' or 'team meeting'.",
                        },
                        "start": {
                            "type": "string",
                            "description": "When it starts, YYYY-MM-DDTHH:MM.",
                        },
                        "end": {
                            "type": "string",
                            "description": "When it finishes, YYYY-MM-DDTHH:MM. Omit for an hour.",
                        },
                        "members": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Whose it is. Omit for the person speaking.",
                        },
                        "location": {
                            "type": "string",
                            "description": "Where, if they said. Omit otherwise.",
                        },
                        "needs_transport": {
                            "type": "boolean",
                            "description": "True when somebody has to be driven there or collected.",
                        },
                    },
                    "required": ["title", "start"],
                }
            },
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
            "name": "check_school_email",
            "description": (
                "New email from the school: 'any news from school', 'anything from the "
                "school office', 'did the school send anything'. Reads only the allowed "
                "senders and proposes the tasks it finds."
            ),
            "inputSchema": {"json": {"type": "object", "properties": {}, "required": []}},
        }
    },
    {
        "toolSpec": {
            "name": "manage_email_access",
            "description": (
                "Change or hear which senders LifePilot may read, or disconnect email: "
                "'only read emails from the school office', 'disconnect my email', "
                "'whose email do you read'."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "senders": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "The email addresses allowed. Omit to hear the list.",
                        },
                        "disconnect": {
                            "type": "boolean",
                            "description": "True for 'disconnect my email'.",
                        },
                    },
                    "required": [],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "request_swap",
            "description": (
                "Offer to trade one of your lifts for one of the other parent's: "
                "'ask Mom to take Thursday, I'll take Tuesday'. Use it whenever one parent "
                "proposes an exchange with the other. Nothing changes until they agree."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "partner": {
                            "type": "string",
                            "description": "The other parent being asked, for example Mom or Dad.",
                        },
                        "give_day": {
                            "type": "string",
                            "description": (
                                "The day whose lift the speaker is handing over, YYYY-MM-DD. "
                                "The day they ask the other parent to take."
                            ),
                        },
                        "take_day": {
                            "type": "string",
                            "description": (
                                "The day whose lift the speaker is taking on in exchange, "
                                "YYYY-MM-DD."
                            ),
                        },
                    },
                    "required": ["partner"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "scan_risks",
            "description": (
                "What is going to be missed: 'what am I forgetting', 'anything I should be "
                "doing', 'is anything going to slip'. For deadlines and tasks with no time set "
                "aside, not for a clash in the diary."
            ),
            "inputSchema": {
                "json": {"type": "object", "properties": {}, "required": []}
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


def schemas_for_model() -> list[dict]:
    """The schemas this run offers the model: the full set, or the coarse nine.

    Read per call rather than at import, so one process can run experiment 4 over both sets. The
    schema block is part of the prompt cache key and the cassette key, so the two sets never share
    a recording -- which is correct, because they are different questions.
    """
    return COARSE_SCHEMAS if _coarse_toolset() else TOOL_SCHEMAS


def choose_tool(text: str, budget: Budget, speaker: str = "Dad") -> tuple[str, dict]:
    """Ask Nova which tool fits. Returns the tool name and its arguments.

    Keyed by speaker as well as words: "my schedule" routes to a different person depending on who
    said it, so one cache entry cannot serve both.
    """
    setting = "coarse" if _coarse_toolset() else "full"
    key = f"{setting}|{speaker}|{clock_today().isoformat()}|{text.strip().lower()}"
    if key in _route_cache:
        return _route_cache[key]

    chosen = _tool_use(_route_once(text, speaker, budget))
    if chosen is None:
        return "cannot_help", {"reason": "the model returned no tool call"}

    # A coarse choice becomes the fine-grained call it stands for here, before any override or
    # handler sees it, so everything downstream is written once and knows nothing about toolsets.
    chosen = _translate_toolset(*chosen)

    _route_cache[key] = chosen
    return chosen


def _tool_use(response) -> tuple[str, dict] | None:
    """The tool the model picked, or None when it picked none."""
    blocks = response["output"]["message"]["content"]
    uses = [block["toolUse"] for block in blocks if "toolUse" in block]
    if not uses:
        return None
    return uses[0]["name"], uses[0].get("input") or {}


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
                tool_config={"tools": schemas_for_model(), "toolChoice": {"any": {}}},
                turn=budget,
                max_tokens=256,
                # The 18 tool schemas are ~3,500 tokens and identical every turn, which is most of
                # what a routing call sends. Cached, they are read back at a tenth of the price.
                cache=True,
            )
        except ClientError as malformed:
            if attempt or "ToolUse" not in str(malformed):
                raise
            logger.warning("the model emitted malformed tool use; asking once more")
    raise RuntimeError("unreachable")


#: Room for the whole fact list. At 160 a week with seven events was cut off mid-word, and what
#: fell off the end were the deadlines, which are said last. Output tokens only, so the extra room
#: costs a few hundredths of a cent a turn.
PHRASE_MAX_TOKENS = 320


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
        max_tokens=PHRASE_MAX_TOKENS,
    )
    blocks = response["output"]["message"]["content"]
    said = "".join(block.get("text", "") for block in blocks).strip()

    # A sentence that ran out of room is worse than a plain one: it stops mid-word, and what it
    # never reached is whatever sits at the end of the list. The facts are already whole sentences,
    # so there is a correct answer to fall back to without asking the model a second time.
    if response.get("stopReason") == "max_tokens":
        logger.warning("the spoken answer hit the token limit; saying the facts as computed")
        return " ".join(facts)
    return said


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
    said = " ".join(said.replace(",", " ").split())
    if said in YES:
        return "yes"
    if said in NO:
        return "no"

    # "No, leave it" and "yes, do it" are one decision said twice, and whole-string matching heard
    # neither. A decision is only read out of a longer sentence when every remaining word is itself
    # part of agreeing or refusing: "no problems this week" stays a question about the week.
    words = said.split()
    for size in (1, 2):
        head, tail = " ".join(words[:size]), words[size:]
        verdict = "yes" if head in YES else "no" if head in NO else None
        if verdict and _all_decision_words(tail):
            return verdict
    return None


def _all_decision_words(words: list[str]) -> bool:
    """True when what follows the decision adds nothing but more agreeing or refusing."""
    remaining = " ".join(words).strip()
    if not remaining:
        return True
    return remaining in YES or remaining in NO or remaining in POLITENESS


def answer(mcp, speaker: str, text: str, call_tool, state: dict | None = None) -> Turn:
    """One voice turn: route, execute, phrase. `call_tool` runs the MCP call and returns (data, debug)."""
    budget = Budget()
    started = time.perf_counter()
    state = state if state is not None else {}

    # Held per speaker: the browser sends the speaker per message on one socket, so Dad's
    # half-agreed rule must not be confirmable by whoever speaks next.
    # Before the yes-or-no, because a name is neither. Falls through when no child is named, so
    # "no, leave it" still reaches the proposal.
    asked = state.get("pending_child", {}).get(speaker)
    if asked:
        answered = _settle_child(mcp, speaker, text, call_tool, state, asked, budget, started)
        if answered is not None:
            return answered

    offered = state.get("pending_choice", {}).get(speaker)
    if offered:
        picked = _settle_choice(mcp, speaker, text, call_tool, state, offered, budget, started)
        if picked is not None:
            return picked

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

    if _asking_what_is_waiting(text):
        return _whats_waiting(mcp, speaker, call_tool, state, budget, started)

    # A bare yes or no with nothing waiting is not a question. Without this it reached the model,
    # which sensibly picked get_schedule and recited the week at somebody saying "no, leave it".
    if _decision(text) is not None:
        state["routed"] = "nothing_pending"
        return Turn(
            speak=_nothing_to_decide(state, speaker),
            debug=_debug("nothing_pending", {}, budget, started),
        )

    tool, arguments = choose_tool(text, budget, speaker)
    tool, arguments = _hypothetical_wins(tool, arguments, text)
    tool, arguments = _booking_wins(tool, arguments, text, speaker, budget)
    tool, arguments = _money_is_declined(tool, arguments, text)
    tool, arguments = _trouble_wins(tool, arguments, text)
    tool, arguments = _errands_are_declined(tool, arguments, text)
    state["routed"] = tool

    if tool == "what_if":
        return _try_it_out(mcp, speaker, text, arguments, call_tool, state, budget, started)

    if tool == "fix_week":
        return _propose_fix(mcp, speaker, call_tool, state, budget, started)

    if tool == "add_event":
        return _propose_event(mcp, speaker, text, arguments, call_tool, state, budget, started)

    if tool == "cancel_event":
        return _propose_cancel(mcp, speaker, text, arguments, call_tool, state, budget, started)

    if tool == "check_school_email":
        return _check_school(mcp, speaker, call_tool, state, budget, started)

    if tool == "manage_email_access":
        return _email_access(mcp, speaker, arguments, call_tool, budget, started)

    if tool == "request_swap":
        return _propose_swap(mcp, speaker, text, arguments, call_tool, state, budget, started)

    if tool == "scan_risks":
        return _what_is_slipping(mcp, speaker, call_tool, state, budget, started)

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

    if tool == "get_schedule":
        known = _known_things(mcp, speaker, call_tool, state)
        arguments = _lift_question(arguments, text, known)
        arguments = _when_is_question(arguments, text, known, state.get("known_due"))

        # If they named a day, that is the day. This used to apply only when a time was named too,
        # so "can I say yes to a six o'clock on Friday" was fixed while "give me Tuesday's schedule"
        # was not: the model answered it with Monday, and "give me Monday's schedule" with today.
        # The day is in the words, so it is read from them rather than trusted to the model.
        day = _the_one_named_day(text)
        if day is not None:
            arguments["start"] = arguments["end"] = day.isoformat()
        arguments = _from_today(arguments, text)
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


def _propose_event(mcp, speaker, text, arguments, call_tool, state, budget, started):
    """Hold a new event for a yes. The only route that puts something in the calendar.

    The server has already checked it against travel times and the family's rules and written the
    answer as a sentence, including what it breaks. A model rewording a change a parent is about to
    approve is the one place rewording cannot be allowed.
    """
    clean = _correct_the_day(_safe_arguments("add_event", arguments, speaker), text)
    if not clean.get("title") or not clean.get("start"):
        return Turn(
            speak="I need to know what it is and when, before I can put it in.",
            debug=_debug("add_event", clean, budget, started),
        )

    result, debug = call_tool(mcp, "add_event", {"speaker": speaker, **clean})
    if not result:
        return Turn(speak=_blocked(debug, "add that"), debug=debug)

    cards = []
    if result.get("proposal_id"):
        state.setdefault("pending_proposal", {})[speaker] = result["proposal_id"]
        cards = [{"kind": "proposal", "title": "New event", "proposal": result}]

    return Turn(
        speak=result["say"],
        cards=cards,
        debug={**debug, **_debug("add_event", clean, budget, started)},
    )


def _propose_cancel(mcp, speaker, text, arguments, call_tool, state, budget, started):
    """Hold a cancellation for a yes. The other half of the write path.

    The server has worked out what cancelling frees, which lifts nobody needs any more and what it
    would strand, and written the answer as a sentence. Spoken as written, for the same reason a
    repair's is: a model must not reword a change a parent is about to approve.

    When more than one event answers to the words, the server asks which rather than guessing, and
    that question comes back as a sentence with no proposal behind it. Nothing is held, so the next
    turn is a fresh request naming the one they meant.
    """
    clean = _safe_arguments("cancel_event", arguments, speaker)

    # The day and the time come from the sentence or not at all -- the same rule as
    # `_correct_the_day` for a booking and `_pin_day` for a hypothetical, and here it decides which
    # event gets deleted. Asked to "cancel Anaya's piano class", which names no day, the model
    # filled in the Tuesday; piano is on Thursday, so the answer was "I cannot find piano class"
    # followed by a list of the diary with piano class in it. A day it invented narrows the search
    # to the wrong day, so a day nobody said is dropped rather than trusted.
    day = _day_meant(text)
    clean.pop("day", None)
    if day is not None:
        clean["day"] = day.isoformat()
    if not NAMED_TIME.search(text):
        clean.pop("at", None)
    if _said_anyway(text):
        clean["override"] = True

    # "Book lunch with Mom instead" names who it is with, and the model left her out -- the
    # replacement came back "for Dad". Read from the family's own roster, like every other name and
    # day in this file. Only the tail after "with" is scanned, because "lunch at Grandpa's" names
    # him as part of what is being cancelled, not as a guest at what replaces it.
    if clean.get("replace_with"):
        _known_things(mcp, speaker, call_tool, state)
        named = _people_after_with(text, state.get("known_people", {}), speaker)
        if named:
            clean["replace_members"] = named

    if not clean.get("title") and not clean.get("at"):
        return Turn(
            speak="Cancel what?",
            debug=_debug("cancel_event", clean, budget, started, note="nothing named"),
        )

    result, debug = call_tool(mcp, "cancel_event", {"speaker": speaker, **clean})
    if not result:
        return Turn(speak=_blocked(debug, "cancel that"), debug=debug)

    # Nothing matched, so try the title the sentence names rather than the one the model invented.
    # "Work for Tuesday 9:30 to 2:15 p.m. cancel it" came back with the whole time phrase as the
    # title while the diary plainly had one called work -- the same fix `what_if` needed for
    # `title: "my"`. Done only on a miss, so the common path pays nothing: one more call to the
    # server, no model call, exactly as `_decide` already recovers from "which lift?".
    if result.get("found") is False:
        better = _correct_title(clean, text, _known_things(mcp, speaker, call_tool, state))
        if better.get("title") != clean.get("title"):
            clean = better
            result, debug = call_tool(mcp, "cancel_event", {"speaker": speaker, **clean})
            if not result:
                return Turn(speak=_blocked(debug, "cancel that"), debug=debug)

    cards = []
    if result.get("proposal_id"):
        state.setdefault("pending_proposal", {})[speaker] = result["proposal_id"]
        cards = [{"kind": "proposal", "title": "Cancelling", "proposal": _cancel_card(result)}]

    # "Which one?" expects a day back, so the next thing said is read as an answer rather than
    # routed as a fresh request. Same shape as `pending_child` for "which child is it for?".
    if result.get("options"):
        state.setdefault("pending_choice", {})[speaker] = result["options"]

    return Turn(
        speak=result["say"],
        cards=cards,
        debug={**debug, **_debug("cancel_event", clean, budget, started)},
    )


#: Days people name without naming a weekday. "Cancel the work event for tomorrow" picks out one day
#: as surely as "on Thursday" does, and `named_day` only ever knew weekday names -- so the day was
#: dropped and the search ran over the whole week, where five identical "work" rows made it a
#: question instead of an answer.
RELATIVE_DAYS = {"tonight": 0, "today": 0, "tomorrow": 1, "yesterday": -1}


def _day_meant(text: str) -> date | None:
    """The day the sentence names, said either way."""
    said = text.lower()
    for word, offset in RELATIVE_DAYS.items():
        if word in said:
            return clock_today() + timedelta(days=offset)
    return _the_one_named_day(text)


def _people_after_with(text: str, people: dict, speaker: str) -> list[str]:
    """Family members named after the last "with" in the sentence.

    Scoped to that tail on purpose: "cancel our lunch at Grandpa's and book lunch with Mom instead"
    names two people, and only one of them is coming to the replacement.
    """
    said = text.lower()
    if " with " not in said:
        return []
    tail = said.rsplit(" with ", 1)[1]
    words = set(re.findall(r"[a-z]+", tail))
    return [
        name for lower, name in people.items() if lower in words and lower != speaker.lower()
    ]


#: Said after being told a family rule pins the event. Overriding a rule has to be something the
#: parent says in so many words, never something inferred from them asking twice.
ANYWAY = ("anyway", "any way", "i mean it", "do it anyway", "cancel it anyway")


def _said_anyway(text: str) -> bool:
    said = text.lower()
    return any(phrase in said for phrase in ANYWAY)


def _cancel_card(result: dict) -> dict:
    """The proposal card's contract, shared with `fix_week` and `request_swap`.

    The server returns one `remove` change; the card wants `change_count`, `was` and `now`, which is
    the contract a swap card once broke by not supplying -- it rendered "undefined changes".
    """
    changes = [{
        "title": result["title"],
        "was": result["when"],
        "now": "cancelled",
        "reason": _cancel_reason(result),
    }]
    if result.get("replaced_by"):
        changes.append({
            "title": result["replaced_by"],
            "was": "nothing",
            "now": result["when"],
            "reason": f"replaces {result['title']}",
        })
    return {
        "proposal_id": result["proposal_id"],
        "change_count": len(changes),
        "changes": changes,
    }


def _cancel_reason(result: dict) -> str:
    if result.get("frees"):
        return f"frees {say_list(result['frees'])}"
    if result.get("lifts_no_longer_needed"):
        return f"nobody needs to drive {say_list(result['lifts_no_longer_needed'])}"
    if result.get("also_loses_it"):
        return f"also comes off {say_list(result['also_loses_it'])}'s day"
    return "asked for"


def _check_school(mcp, speaker, call_tool, state, budget, started):
    """Read the school's email and hold what it asks for, ready for a yes.

    The server has already extracted the task, checked the week and worked out the repair, all in
    one call. Its sentence is spoken as written, for the same reason a repair's is: a model must not
    reword a change a parent is about to approve.
    """
    result, debug = call_tool(mcp, "check_school_email", {"speaker": speaker})
    if not result:
        return Turn(speak=_blocked(debug, "read the school's email"), debug=debug)

    cards = []
    if result.get("proposal_id"):
        state.setdefault("pending_proposal", {})[speaker] = result["proposal_id"]
        cards = [{"kind": "proposal", "title": "From school", "proposal": result, "simulated": True}]

        # The email named no child this family has, and there is more than one. The next thing said
        # is expected to be a name, so it is read as one rather than routed as a fresh request.
        if result.get("needs_child"):
            state.setdefault("pending_child", {})[speaker] = {
                "proposal_id": result["proposal_id"],
                "children": result["needs_child"],
            }

    return Turn(
        speak=result["say"],
        cards=cards,
        debug={**debug, **_debug("check_school_email", {}, budget, started)},
    )


def _propose_swap(mcp, speaker, text, arguments, call_tool, state, budget, started):
    """One parent offers to trade a lift with the other (#6).

    The proposal is held against the **partner**, not the speaker: `pending_proposal` is keyed by
    who is being asked, so Mom's "yes" settles it in her own session while Dad's would not. That
    split is the whole point of the feature -- two people, two sessions, one plan -- and keying it
    by the speaker would have let Dad approve his own swap.

    The tool's sentence is spoken as written, including a refusal, which already names the
    commitment or travel time that blocks the trade. A model must not reword a change somebody is
    about to agree to.
    """
    clean = {k: v for k, v in arguments.items() if k in ("partner", "give_day", "take_day") and v}

    # The two days are read from the sentence, in the order they were said: the first is handed
    # over, the second taken on. The model resolved "Tuesday" to a Friday and the swap was refused
    # for a lift that does not exist.
    spoken = days_named_in_order(text)
    if len(spoken) == 2:
        clean["give_day"], clean["take_day"] = (day.isoformat() for day in spoken)
    elif len(spoken) == 1:
        clean["give_day"] = spoken[0].isoformat()
        clean.pop("take_day", None)

    if not clean.get("partner"):
        return Turn(
            speak="Who should I ask?",
            debug=_debug("request_swap", clean, budget, started, note="no partner named"),
        )

    result, debug = call_tool(mcp, "request_swap", {"speaker": speaker, **clean})
    if not result:
        return Turn(speak=_blocked(debug, "arrange that swap"), debug=debug)

    cards = []
    if result.get("proposal_id") and result.get("awaiting"):
        state.setdefault("pending_proposal", {})[result["awaiting"]] = result["proposal_id"]
        cards = [{
            "kind": "proposal",
            "title": f"Swap, waiting on {result['awaiting']}",
            "proposal": result,
            "simulated": True,
        }]

    return Turn(
        speak=result["say"],
        cards=cards,
        debug={**debug, **_debug("request_swap", clean, budget, started)},
    )


def _what_is_slipping(mcp, speaker, call_tool, state, budget, started):
    """"What am I forgetting?" -- and the slot that would save the first thing (#5 support).

    The server has already found the risk, picked the gap and written the proposal, so this is one
    tool call and the sentence is spoken as written. A warning a parent can say yes to is worth
    more than a warning, and rewording an offer they are about to approve is how a proposal and
    what gets booked drift apart.
    """
    result, debug = call_tool(mcp, "scan_risks", {"speaker": speaker})
    if not result:
        return Turn(speak=_blocked(debug, "check what is at risk"), debug=debug)

    cards = []
    if result.get("proposal_id"):
        state.setdefault("pending_proposal", {})[speaker] = result["proposal_id"]
        cards = [{"kind": "proposal", "title": "At risk", "proposal": result}]

    return Turn(
        speak=result["say"],
        cards=cards,
        debug={**debug, **_debug("scan_risks", {}, budget, started)},
    )


def _settle_child(mcp, speaker, text, call_tool, state, waiting, budget, started):
    """"Aarav" after "which child is it for?" is an answer, not a new request.

    Returns None when the words name no child, so "no, leave it" still reaches the proposal and
    rejects it. Costs no model call: the candidates came from the server and are matched here.
    """
    said = text.lower()
    named = next((name for name in waiting["children"] if name.lower() in said), None)
    if named is None:
        return None

    state.get("pending_child", {}).pop(speaker, None)
    state["routed"] = "name_task_child"
    result, debug = call_tool(
        mcp,
        "name_task_child",
        {"speaker": speaker, "proposal_id": waiting["proposal_id"], "child": named},
    )
    if not result:
        return Turn(speak=_blocked(debug, "note that down"), debug=debug)

    return Turn(
        speak=result["say"],
        debug={**debug, **_debug("name_task_child", {"child": named}, budget, started)},
    )


def _settle_choice(mcp, speaker, text, call_tool, state, options, budget, started):
    """"Thursday" after "which one?" is an answer, not a new request.

    Returns None when the words name none of them, so "no, leave it" and a fresh question both
    still get through. Costs no model call: the candidates came from the server and the day is
    matched against the words here, which is the same rule every other day in this file follows.
    """
    said = text.lower()
    named = [option for option in options if _day_said(option).lower() in said]
    if len(named) != 1:
        return None

    state.get("pending_choice", {}).pop(speaker, None)
    state["routed"] = "cancel_event"
    result, debug = call_tool(
        mcp,
        "cancel_event",
        {"speaker": speaker, "event_id": named[0]["event_id"]},
    )
    if not result:
        return Turn(speak=_blocked(debug, "cancel that"), debug=debug)

    cards = []
    if result.get("proposal_id"):
        state.setdefault("pending_proposal", {})[speaker] = result["proposal_id"]
        cards = [{"kind": "proposal", "title": "Cancelling", "proposal": _cancel_card(result)}]

    return Turn(
        speak=result["say"],
        cards=cards,
        debug={**debug, **_debug("cancel_event", {"event_id": named[0]["event_id"]},
                                 budget, started)},
    )


def _day_said(option: dict) -> str:
    """The day out of "work Thursday at 9:30 AM to 4:30 PM" -- which is what distinguishes them.

    The options differ by day, never by title, because they all matched the same words. So the day
    is the answer, and "today" or "tomorrow" is as good an answer as "Thursday".
    """
    return (option.get("when") or "").split(" at ")[0].strip()


def _email_access(mcp, speaker, arguments, call_tool, budget, started):
    """Say or change which senders may be read, or disconnect.

    Spoken as the server wrote it. This is a sentence about what LifePilot may read, so a model
    paraphrasing it could soften or widen the promise it describes.

    Disconnecting is deliberately immediate rather than held for approval. It is already parent-only,
    and it is the escape hatch: nobody should have to agree to a proposal twice to stop LifePilot
    reading their email.
    """
    clean = _safe_arguments("manage_email_access", arguments, speaker)
    result, debug = call_tool(mcp, "manage_email_access", {"speaker": speaker, **clean})
    if not result:
        return Turn(speak=_blocked(debug, "change that"), debug=debug)

    return Turn(
        speak=result["say"],
        debug={**debug, **_debug("manage_email_access", clean, budget, started)},
    )


# "Anything waiting for me?" is a question about a decision, and a decision is never routable --
# the same reason `list_proposals` is kept out of `TOOL_SCHEMAS`. Matched here so it costs no model
# call. It used to reach `fix_week`, which minted a *second* proposal: the one person who could say
# yes could not ask what she was saying yes to.
ASKING_WHAT_IS_WAITING = (
    "waiting for me", "waiting on me", "anything waiting", "waiting for my",
    "to approve", "my approval", "need to approve", "anything pending",
)


def _asking_what_is_waiting(text: str) -> bool:
    said = " ".join(text.lower().replace("?", " ").split())
    return any(phrase in said for phrase in ASKING_WHAT_IS_WAITING)


def _whats_waiting(mcp, speaker, call_tool, state, budget, started):
    """Read back the proposal this speaker owes an answer on, and re-arm the yes.

    The server is asked whose call each pending proposal is, rather than the session guessing, so
    Mom can walk up to a fresh session, ask, and then say yes. No model call: the sentence and the
    card are both built from the server's own rows.
    """
    state["routed"] = "list_proposals"
    result, debug = call_tool(mcp, "list_proposals", {"speaker": speaker})
    if not result:
        return Turn(speak=_blocked(debug, "check what is waiting"), debug=debug)

    mine = [p for p in result.get("proposals", []) if p.get("yours_to_decide")]
    if not mine:
        return Turn(
            speak=_nothing_to_decide(state, speaker),
            debug={**debug, **_debug("list_proposals", {}, budget, started)},
        )

    proposal = _the_one_asked_of(mine, result)
    state.setdefault("pending_proposal", {})[speaker] = proposal["id"]
    card = {
        "proposal_id": proposal["id"],
        "change_count": proposal["change_count"],
        "changes": proposal["changes"],
    }
    return Turn(
        speak=_read_back(proposal),
        cards=[{"kind": "proposal", "title": "Waiting for your yes", "proposal": card}],
        debug={**debug, **_debug("list_proposals", {}, budget, started)},
    )


def _the_one_asked_of(mine: list[dict], result: dict) -> dict:
    """Of several pending, the one this question is about.

    A proposal addressed to this speaker by name wins over one any parent could decide: Mom asking
    while a week-fix of Dad's is still pending means the swap he asked *her* for. Failing that, the
    newest, because it is the one she just heard.
    """
    me = result.get("speaker", {}).get("name")
    addressed = [p for p in mine if p.get("needs_approval_from") == me]
    return max(addressed or mine, key=lambda p: p["id"])


def _read_back(proposal: dict) -> str:
    """The pending proposal said to the person who has to answer it.

    Built here rather than replayed: the sentence the server wrote was addressed to whoever asked
    for the change, and read back to the other parent it talks about her in the third person.
    """
    legs = ", and ".join(_change_said(change) for change in proposal["changes"])
    asker = proposal.get("created_by")
    opening = f"{asker} asked you to take" if proposal.get("kind") == "swap" else "Waiting on you:"
    return f"{opening} {legs}. Say yes and I will make the change."


def _change_said(change: dict) -> str:
    title = change.get("title") or "it"
    if change.get("was") and change.get("now"):
        return f"{title}, moving from {change['was']} to {change['now']}"
    return title


def _nothing_to_decide(state: dict, speaker: str) -> str:
    """Nothing is waiting for *this* speaker -- which is not the same as nothing waiting.

    Dad hearing "there is nothing waiting for a yes or no" about the swap he just asked for reads
    like a glitch. Naming whose call it is makes the guard look like the point it is.
    """
    others = [who for who in state.get("pending_proposal", {}) if who != speaker]
    if others:
        return f"That one is {others[0]}'s to answer."
    return "There is nothing waiting for a yes or no."


def _settle_proposal(mcp, speaker, text, call_tool, state, proposal_id, budget, started):
    """A yes approves the diff the parent just heard; a no leaves the week alone."""
    decision = _decision(text)
    if decision is None:
        return None

    state.get("pending_proposal", {}).pop(speaker, None)
    tool = "approve_proposal" if decision == "yes" else "reject_proposal"
    # This turn never reaches the router, so nothing else records what it did. Left unset, the debug
    # drawer and the eval both report whatever the previous turn chose.
    state["routed"] = tool
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
        speak = _why_them(best)
        if result.get("assigned_to") and result["assigned_to"] != best["name"]:
            speak = f"{speak} {result['assigned_to']} is down for it at the moment."

    return Turn(
        speak=speak,
        cards=[{"kind": "decision", "title": result["title"], "ranked": ranked,
                "ruled_out": result.get("ruled_out", []), "assigned_to": result.get("assigned_to")}],
        debug={**debug, **_debug(tool, clean, budget, started)},
    )


def _why_them(best: dict) -> str:
    """Who should go, in one sentence that says the name once.

    Every reason `allocation` records already opens with the name -- "Mom is only 10 minutes away"
    -- so wrapping it in "Mom, because ..." said it twice: "Mom, because Mom is the only one who
    can get there." The reason is a whole sentence already, and it is the answer to "who should go",
    so it is spoken as one. The stored reason is untouched: the card and "why not X" use it on its
    own, where the name has to be there.
    """
    reason = (best.get("reason") or "").strip().rstrip(".")
    if not reason:
        return f"{best['name']} should go."
    if reason.startswith(best["name"]):
        return f"{reason}."
    # A reason that does not open with the name needs one. "because" would need a pronoun, and a
    # name says nothing about which pronoun a person uses, so the name is simply put in front.
    return f"{best['name']}: {reason}."


def _try_it_out(mcp, speaker, text, arguments, call_tool, state, budget, started):
    """A what-if answers itself: the server already wrote the sentence, and it must not be softened."""
    clean = _pin_day(_safe_arguments("what_if", arguments, speaker), text)
    clean = _correct_title(clean, text, _known_things(mcp, speaker, call_tool, state))
    clean = _fill_until(clean, text)
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
    if decision is not None:
        # Same as settling a proposal: this turn skips the router, so it has to say what it did.
        state["routed"] = "add_rule" if decision == "yes" else None
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
    "get_schedule": {"start", "end", "about", "at", "title"},
    "detect_conflicts": {"start", "end"},
    "get_family": set(),
    "list_rules": set(),
    "remember_rule": {"rule_type", "params"},
    "what_if": {"kind", "title", "until", "at", "start", "end"},
    "add_event": {
        "title", "start", "end", "location", "members", "needs_transport", "category",
    },
    "cancel_event": {
        "title", "day", "at", "event_id", "override", "replace_with", "replace_members",
    },
    "fix_week": set(),
    "check_school_email": set(),
    "manage_email_access": {"senders", "disconnect"},
    "suggest_responsible": {"title"},
    "explain_choice": {"person", "title"},
}

#: Tools whose start and end are whole days. `what_if` is deliberately absent: a hypothetical
#: happens at a time of day, so trimming its timestamps would throw away the question.
WHOLE_DAY_ARGUMENTS = {
    "get_schedule": {"start", "end"},
    "detect_conflicts": {"start", "end"},
    "cancel_event": {"day"},
}

#: A hypothetical's fields that carry a date and a time of day together.
DATED_ARGUMENTS = ("at", "start", "until", "end")


def _pin_day(change: dict, text: str) -> dict:
    """Move a hypothetical onto the day the sentence names, keeping each time of day.

    Asked "what if my 4 PM runs till 5:30 on Thursday", Nova Micro answered `2026-10-21` -- a
    Wednesday -- and the what-if then asked about a day nobody mentioned. The day is in the
    sentence, so it is read from there. Same rule as `days_named_in_order` for a swap, and
    `named_day` for a reading: resolve days in code, never in the model.
    """
    day = named_day(text)
    if day is None:
        return change
    for field in DATED_ARGUMENTS:
        value = change.get(field)
        if isinstance(value, str) and "T" in value:
            change[field] = f"{day.isoformat()}T{value.split('T', 1)[1]}"
    return change

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


#: Words that mean somebody deliberately asked about a day gone by. Only then is the past in scope.
#: "this week" is deliberately absent: asked on a Thursday, a parent means the part still to come.
PAST_WORDS = ("yesterday", "last ", "earlier", "so far", "already", "did i", "was on")


def _from_today(arguments: dict, text: str) -> dict:
    """Pull a window back to today unless the past was actually asked for.

    A tester asking for their schedule was told "you worked yesterday from 9 to 4". The model copies
    the week out of the prompt, so the fix belongs here rather than in more prompt wording: days gone
    by are not part of an answer about a plan.
    """
    if any(word in text.lower() for word in PAST_WORDS):
        return arguments

    start = arguments.get("start")
    if not isinstance(start, str):
        return arguments
    try:
        asked = date.fromisoformat(start)
    except ValueError:
        return arguments

    today = clock_today()
    if asked >= today:
        return arguments

    end = arguments.get("end")
    # A single past day named outright ("what was on Monday") is left alone; a window that merely
    # starts too early is trimmed.
    if end == start:
        return arguments
    return {**arguments, "start": today.isoformat()}


def _day_in_window(index: int) -> date | None:
    """The date in the loaded window whose weekday is `index`, Monday being 0.

    Matched on the day's own weekday rather than its position in `DAY_NAMES`: that position is only
    an offset from `WEEK_START` while the window opens on a Monday, and it now opens on the Saturday
    running into the week.
    """
    span = (WEEK_END - WEEK_START).days
    for day in (WEEK_START + timedelta(days=offset) for offset in range(span + 1)):
        if day.weekday() == index:
            return day
    return None


def named_day(text: str) -> date | None:
    """The weekday somebody named, resolved inside the loaded window, or None if they named none."""
    asked = text.lower()
    for index, name in enumerate(DAY_NAMES):
        if name.lower() in asked:
            return _day_in_window(index)
    return None


def days_named_in_order(text: str) -> list[date]:
    """Every weekday named, in the order they were said, resolved inside the loaded window.

    A swap names two days -- "ask Mom to take Thursday, I will take Tuesday" -- and which is which
    is carried by their order, not by any word around them. Asked to resolve both itself, Nova Micro
    returned 2026-10-02 for "Tuesday", a Friday, and the swap was correctly refused for a lift that
    does not exist. The days are in the sentence, so they are read from it.
    """
    asked = text.lower()
    found = []
    for index, name in enumerate(DAY_NAMES):
        position = asked.find(name.lower())
        if position >= 0:
            day = _day_in_window(index)
            if day is not None:
                found.append((position, day))
    return [day for _, day in sorted(found)]


def _the_one_named_day(text: str) -> date | None:
    """The single weekday somebody named, or None if they named none or several.

    Several means a span: "what have I got Monday to Friday" names two days and wants the week, so
    collapsing it to Monday would answer a narrower question than the one asked.
    """
    asked = text.lower()
    named = [name for name in DAY_NAMES if name.lower() in asked]
    return named_day(text) if len(named) == 1 else None


#: Told to put something in the diary, not asked what is already in it. Checked at the start of the
#: sentence, so "what is my schedule" stays a question while "schedule my meeting" is an instruction.
BOOKING_VERBS = ("schedule", "book", "add", "create", "arrange", "set up", "put in", "put a")

#: Stripped before looking for the verb, so "can you schedule..." and "I want to book..." are read as
#: the instructions they are.
POLITE_OPENERS = (
    "can you", "could you", "would you", "please", "i want to", "i need to", "i'd like to",
    "i would like to", "lifepilot", "hey", "ok", "okay", "go ahead and", "let's", "lets",
)


#: An intention wrapped around a question. "I want to schedule a meeting at 4, do I have any work at
#: that time?" is asking whether four is free, and booking it would answer a question nobody asked
#: by changing the diary.
CHECKING_PHRASES = (
    "do i have", "do i already", "am i free", "am i busy", "is that ok", "is that okay",
    "does that work", "would that work", "is it free", "at that time", "can i say yes",
    "will that work", "is there anything", "have i got anything",
)


#: Words that may stand in front of the verb without turning the instruction into a question.
#: People put the time first as often as last -- "at 3 PM schedule a meeting", "for tomorrow
#: schedule the meeting" -- and requiring the verb at the head read both as questions about the
#: diary and booked nothing. Deliberately only when, never who or what: "my", "the" and "a" are
#: absent, which is what keeps "what is **my schedule**" a question. Reported from testing.
LEADING_WORDS = {
    "at", "on", "for", "in", "by", "from", "around", "about", "and", "then", "also", "tomorrow",
    "today", "tonight", "morning", "afternoon", "evening", "night", "this", "next", "coming",
    "noon", "midday", "am", "pm", "a.m.", "p.m.", "o'clock", "monday", "tuesday", "wednesday",
    "thursday", "friday", "saturday", "sunday", "week", "weekend",
}


def _only_says_when(words: list[str]) -> bool:
    """Whether everything before the verb is just a time or a day. A clock reading counts."""
    return all(
        word in LEADING_WORDS or any(character.isdigit() for character in word) for word in words
    )


def _is_booking(text: str) -> bool:
    """True when this is an instruction to create something rather than a question about the week.

    The verb may sit anywhere a time phrase could have pushed it to, but nothing else may precede
    it. "schedule" is the verb in "schedule a meeting" and the noun in "what is my schedule", and
    that one word carries the whole difference between answering and changing the diary.
    """
    said = " ".join(text.lower().replace(",", " ").split())
    if any(phrase in said for phrase in CHECKING_PHRASES):
        return False

    changed = True
    while changed:
        changed = False
        for opener in POLITE_OPENERS:
            if said.startswith(opener + " "):
                said = said[len(opener) + 1 :].strip()
                changed = True

    words = said.split()
    for position in range(len(words)):
        # Joined rather than indexed, because "set up" and "put in" are two words.
        if " ".join(words[position:]).startswith(BOOKING_VERBS):
            return _only_says_when(words[:position])
    return False


def _booking_wins(tool: str, arguments: dict, text: str, speaker: str, budget: Budget):
    """"Schedule my meeting at 4 today" has to create, whatever tool was chosen.

    It was being answered "you have nothing on today at 4 PM", which is true, unasked for, and leaves
    the meeting unbooked. The decision is made here from the words; the model is then asked once, with
    only `add_event` in scope, to pull out the title and the time. That is a forced tool-use call, the
    same fixed-schema pattern used for school email, and it spends from the turn's existing ceiling.
    """
    # Only when the model tried to answer from the calendar. "Book me a flight to Goa" is declined
    # by the model as out of scope, and that judgement is the right one: overriding it put a
    # midnight-to-midnight "flight to Goa" in the family's week.
    if tool not in {"get_schedule", "what_if"} or not _is_booking(text):
        return tool, arguments

    only_add = [t for t in TOOL_SCHEMAS if t["toolSpec"]["name"] == "add_event"]
    try:
        response = converse(
            messages=[{"role": "user", "content": [{"text": text}]}],
            system=route_system(speaker),
            tool_config={"tools": only_add, "toolChoice": {"tool": {"name": "add_event"}}},
            turn=budget,
            max_tokens=256,
        )
    except Exception:
        logger.warning("could not read the booking; leaving the model's own choice alone")
        return tool, arguments

    chosen = _tool_use(response)
    return ("add_event", chosen[1]) if chosen else (tool, arguments)


#: Words that make an utterance a question about money. LifePilot holds no amounts at all -- there is
#: no cost, price or currency field anywhere in the data model -- so these can never be answered.
MONEY = ("spend", "spent", "cost", "costs", "how much did", "how much do", "fees", "fee for")

#: Whole words only. A substring match read "costume" as "cost" and declined a question about a
#: school task LifePilot had written down itself, with "LifePilot keeps no record of money".
MONEY_WORDS = re.compile(r"\b(?:" + "|".join(re.escape(word) for word in MONEY) + r")\b")


def _money_is_declined(tool: str, arguments: dict, text: str) -> tuple[str, dict]:
    """A question about money is declined, whatever tool was chosen.

    With 18 tools the model routes "how much did we spend on football this month" to `get_family` and
    recites the roster at a question about money -- confidently wrong, which is worse than declining.
    The judgement needs no model: LifePilot stores no amounts, so there is nothing to answer from.
    Narrow on purpose -- only when the model already tried to answer from the family's own data.
    """
    if tool in {"cannot_help", "add_event", "approve_proposal", "reject_proposal"}:
        return tool, arguments
    said = text.lower()
    if not MONEY_WORDS.search(said):
        return tool, arguments
    return "cannot_help", {"reason": "LifePilot keeps no record of money"}


#: Shopping and errands. LifePilot is not a grocery list, and a sixteenth tool schema pushed "order
#: milk" to `cancel_event`, which then recited the whole diary at somebody asking for milk. Matched
#: at the head of the sentence, so "what order do I do these in" is still a question about the week.
ERRANDS = ("order ", "buy ", "purchase ", "add milk", "shopping", "groceries")


def _errands_are_declined(tool: str, arguments: dict, text: str) -> tuple[str, dict]:
    """An errand is declined, whatever tool was chosen.

    The same shape as `_money_is_declined`, and for the same reason: LifePilot keeps no shopping
    list, so there is nothing to answer from, and a confident wrong answer is worse than a refusal.
    Narrow on purpose -- only the verb at the head of the sentence counts.
    """
    if tool == "cannot_help":
        return tool, arguments
    said = text.strip().lower()
    if not any(said.startswith(word) for word in ERRANDS):
        return tool, arguments
    return "cannot_help", {"reason": "LifePilot keeps no shopping list"}


#: Asking whether anything is broken. Unambiguous, and the one question differentiator #1 rests on.
TROUBLE = (
    "any problem", "problems", "anything wrong", "what's wrong", "what is wrong",
    "anything broken", "is anything broken", "any issues", "any conflicts", "does the week work",
    "will the week work", "does this week work",
)


def _trouble_wins(tool: str, arguments: dict, text: str) -> tuple[str, dict]:
    """A question about what is broken is a conflict check, whatever tool was chosen.

    Adding a fourteenth tool schema pushed "any problems this week" to `get_schedule`, which then
    recited Thursday at somebody asking whether Thursday works -- true, and not the question. This
    needs no model: the words name the question, and the offline router has always decided it in
    code the same way. Narrow on purpose, like `_money_is_declined`: only a tool that was trying to
    answer from the week's own data is overridden, so a decision, a write or a refusal still stands.
    """
    if tool not in {"get_schedule", "get_family", "scan_risks", None}:
        return tool, arguments
    said = text.lower()
    if not any(phrase in said for phrase in TROUBLE):
        return tool, arguments
    return "detect_conflicts", {
        "start": WEEK_START.isoformat(),
        "end": WEEK_END.isoformat(),
    }


def _hypothetical_wins(tool: str, arguments: dict, text: str) -> tuple[str, dict]:
    """"What if X is cancelled" is a hypothetical, whatever tool was chosen.

    Letting get_schedule answer it produces a true sentence about X that says nothing about what
    happens if X goes away. Only a kind that can be read out of the words is redirected; anything
    vaguer is left alone, because a confident refusal is worse than a partial answer.
    """
    if tool != "get_schedule" or "what if" not in text.lower():
        return tool, arguments

    asked = text.lower()
    if "cancel" in asked or "called off" in asked or "does not happen" in asked:
        kind = "cancelled"
    elif "late" in asked or "overrun" in asked or "runs until" in asked or "runs till" in asked:
        kind = "runs_late"
    else:
        return tool, arguments

    named = arguments.get("title") or arguments.get("about")
    return "what_if", {"kind": kind, "title": named} if named else {"kind": kind}


#: Asking who drives, rather than what is on. These are the questions whose answer is a name and an
#: hour, and the model answers them as "my day" instead unless the named thing is pulled out here.
#: Stems, not whole words: "picks up", "picking up" and "pickup" are the same question, and matching
#: the exact spellings missed two of the three.
LIFT_WORDS = ("collect", "pick", "drop", "driv", "take")

#: Words a question could be about: what this family's events and places are called. Read once per
#: session from the family's own data, so nothing is hardcoded and no model call is involved.
def _known_things(mcp, speaker: str, call_tool, state: dict) -> set[str]:
    if "known_things" in state:
        return state["known_things"]

    known: set[str] = set()
    people: set[str] = set()
    due: set[str] = set()
    try:
        data, _ = call_tool(
            mcp,
            "get_schedule",
            {"speaker": speaker, "start": WEEK_START.isoformat(), "end": WEEK_END.isoformat()},
        )
        for event in (data or {}).get("events", []):
            if event.get("redacted"):
                continue
            known |= _ways_of_saying(str(event["title"]))
            if event.get("location"):
                known |= _ways_of_saying(str(event["location"]))
        # Tasks as well as events. Without them "when is the farmer costume due" named nothing the
        # family owned, so the question fell through to the model's guess -- the speaker's whole
        # week -- and never mentioned the costume LifePilot had written down from a school email.
        for task in (data or {}).get("tasks", []):
            due |= _ways_of_saying(str(task["title"]))
        known |= due
        family, _ = call_tool(mcp, "get_family", {"speaker": speaker})
        for place in (family or {}).get("locations", []):
            known |= _ways_of_saying(str(place))
        members = (family or {}).get("members", [])
        people = {str(m["name"]).lower() for m in members}
        # Kept rather than thrown away: "book lunch with Mom instead" names a person, and reading
        # that from the family's own roster is the same rule as reading a day from the sentence.
        state["known_people"] = {str(m["name"]).lower(): str(m["name"]) for m in members}
    except Exception:
        logger.warning("could not read the family's vocabulary; falling back to the model's choice")

    # A member's name is not a thing to ask the schedule about: "collect Aarav from school" is about
    # school, and leaving names in would make the longest match "aarav".
    state["known_things"] = known - people
    # Which of those are deadlines rather than appointments. A deadline belongs to whoever owns it,
    # so a question naming one must not stay narrowed to the asker: see `_when_is_question`.
    state["known_due"] = due - people
    return state["known_things"]


#: Words that only ever qualify a thing, never name one. "Collect him from practice" is not a
#: question about anything; "from football" is.
JUST_QUALIFIERS = {"class", "practice", "ground", "office", "block", "session", "lesson", "the"}


def _ways_of_saying(name: str) -> set[str]:
    """A thing, and the shorter words people actually use for it.

    Nobody says "collect Aarav from football practice"; they say "from football". Indexing both means
    the family's own words still drive this, with no vocabulary written into the code.
    """
    full = name.strip().lower()
    words = {word for word in full.split() if len(word) > 3 and word not in JUST_QUALIFIERS}
    return {full, *words} if full else set()


def _the_thing_they_named(text: str, known: set[str]) -> str | None:
    """The longest known event or place named in the sentence, or None.

    `known` comes from the family's own data, so no vocabulary is hardcoded here: a different family
    with swimming and chess gets the same behaviour without a code change.
    """
    asked = text.lower()
    named = [word for word in known if word and word in asked]
    return max(named, key=len) if named else None


def _correct_title(change: dict, text: str, known: set[str]) -> dict:
    """Replace a title the model invented with the one the sentence actually names.

    Asked "what if my performance review runs till 5:30", Nova Micro answered `title: "my"` and the
    hypothetical went looking for an event called "my". The title is in the sentence and the family's
    own event names are already loaded, so it is read from there -- the same rule as the day.

    A title that matches nothing is left alone: "I cannot find 'badminton'. That week has: ..." is a
    more useful answer than asking which event they meant.
    """
    title = (change.get("title") or "").strip().lower()
    if not title or title in known:
        return change
    named = _the_thing_they_named(text, known)
    return {**change, "title": named} if named else change


def _lift_question(arguments: dict, text: str, known: set[str]) -> dict:
    """"At what time do I collect Aarav from school" is a question about school.

    It was answered with the asker's whole day, which never mentioned school at all, because the model
    hears "I" and narrows to the speaker. Only sentences about driving somebody are touched, so "do I
    have any work at 4" keeps answering about four o'clock rather than about work.
    """
    if arguments.get("title") or arguments.get("at"):
        return arguments
    if not any(word in text.lower() for word in LIFT_WORDS):
        return arguments

    named = _the_thing_they_named(text, known)
    if named is None:
        return arguments
    # The question is about the thing, not about whoever asked.
    return {**{k: v for k, v in arguments.items() if k != "about"}, "title": named}


#: Asking when one particular thing is. "What have I got today" asks for a day and wants the day;
#: "when do I have lunch with Mom" asks about one thing, and the whole week back is a recital.
WHEN_WORDS = ("when do", "when is", "when's", "when are", "when does",
              "what time is", "what time do", "what time does")


def _when_is_question(arguments: dict, text: str, known: set[str], due: set[str] | None = None) -> dict:
    """"When do I have lunch with Mom" is a question about lunch, not a request for the week.

    Asked that, the model filled `start`, `end` and `about` and left `title` empty, so eight work
    blocks were read out and the lunch -- which was not in the loaded week at all -- never came up.
    The thing is named in the sentence and the family's own event names are already loaded, so it
    is read from there, the same rule as the day and the same shape as `_lift_question`.

    `about` is kept, unlike in a lift question: "when does Mom finish work" is about Mom *and*
    about work, and dropping her would answer with everybody's working day.

    Except for a deadline, which belongs to whoever owns it. "When is the farmer costume due" was
    narrowed to the asker, and a costume owned by Aarav was filtered straight back out again -- the
    right title and still the wrong answer. A thing in `due` is the household's, so `about` goes.
    """
    if arguments.get("title") or arguments.get("at"):
        return arguments
    if not any(word in text.lower() for word in WHEN_WORDS):
        return arguments

    named = _the_thing_they_named(text, known)
    if named is None:
        return arguments
    if named in (due or set()):
        return {**{k: v for k, v in arguments.items() if k != "about"}, "title": named}
    return {**arguments, "title": named}


def _correct_the_day(arguments: dict, text: str) -> dict:
    """Put a new event on the day that was actually named.

    "Book a dentist at ten on Friday" came back as next Thursday. Writing something into a family's
    calendar on the wrong day is worse than refusing, and the day is in the words, so it is read from
    them rather than trusted to the model.
    """
    day = named_day(text)
    if day is None:
        return arguments

    fixed = dict(arguments)
    for key in ("start", "end"):
        value = fixed.get(key)
        if not isinstance(value, str) or "T" not in value:
            continue
        _, _, clock = value.partition("T")
        fixed[key] = f"{day.isoformat()}T{clock}"
    return fixed


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


#: Words that introduce the end of something running over: "runs till 5:30", "until half five".
UNTIL_WORDS = ("until", "till", "til", "up to")


def _until_time(text: str) -> str | None:
    """The time a sentence says something runs until, as HH:MM.

    Read after the "until", because an overrun names two times -- "my 4 PM runs till 5:30" -- and it
    is the second one that answers the question.
    """
    asked = text.lower()
    for word in UNTIL_WORDS:
        position = asked.find(word)
        if position < 0:
            continue
        rest = asked[position + len(word) :]
        found = named_time(rest)
        if found:
            return _afternoon(found, rest)
    return None


#: "Until 5:30" with no am or pm means half past five in the evening. The same reasoning `named_time`
#: already applies to a spoken hour, which it does not apply to digits.
MORNING = re.compile(r"\b(am|a\.m\.)\b")


def _afternoon(clock: str, said: str) -> str:
    """An unqualified early hour, read as the afternoon. "Until 7 am" is left alone."""
    hour = int(clock[:2])
    if hour < 8 and not MORNING.search(said):
        return f"{hour + 12:02d}{clock[2:]}"
    return clock


def _fill_until(change: dict, text: str) -> dict:
    """Give an overrun the end time the sentence already stated.

    The model filled `kind` and the title and left `until` empty, so the what-if asked for a time
    the speaker had just given. Only an overrun has an end time, and only a missing one is filled:
    the model's own answer is never second-guessed.
    """
    if change.get("kind") != "runs_late" or change.get("until"):
        return change
    found = _until_time(text)
    return {**change, "until": found} if found else change


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

    # A question about one named thing gets an answer about that thing.
    if data.get("title"):
        return _named_facts(data, speaker)

    events = data["events"]
    mine = [e for e in events if not e.get("redacted")]
    hidden = len(events) - len(mine)
    tasks = data.get("tasks") or []

    one_day = data["from"] == data["to"]
    window = say_window(data["from"], data["to"])
    subject = data.get("about")
    mine_only = bool(subject) and subject == speaker

    # Asked about one person, a blocked-out hour IS the answer: a child sees a parent's work as
    # "Busy". Dropping those left "Dad has nothing on" beside a card showing two busy blocks --
    # the voice contradicting its own card, which is the worse half of the two.
    answerable = events if subject else mine

    if not events:
        if mine_only:
            nothing = "You have nothing on"
        elif subject:
            nothing = f"{subject} has nothing on"
        else:
            nothing = "There is nothing at all"
        # A day with no events can still have something due on it. Saying "nothing on" while a
        # costume is due that morning is how a deadline gets missed.
        if tasks:
            return [f"{nothing} {window}, but there are things due."] + _task_facts(tasks)
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
    facts = [f"{owner} {plural(len(answerable), 'thing')} {window}."]

    # Deadlines before the day's shape. They were last, so a week with seven events pushed them
    # past the token limit and a costume due on Friday was never spoken. A deadline is the part
    # that gets missed if it is not said, and school and work are the part already known.
    facts.extend(_task_facts(tasks))

    # Reading out nineteen events is a recital, not an answer, and it ran past the token limit
    # mid-sentence. Your own day is listed in full, because you asked for it. The family's week gets
    # its shape plus the parts that need somebody to drive.
    listed = (
        answerable
        if (one_day or subject)
        else [e for e in answerable if e.get("needs_transport")]
    )
    # In the order the day happens to the person hearing it. A school collection sorted by the start
    # of school is read out before their 9 o'clock, when the part that concerns them is at 3.
    listed = sorted(listed, key=_when_it_matters)
    for event in listed[:8]:
        # Whose it is has already been said once; repeating it on every line is how a robot talks.
        # Except when it is not theirs: asked when Mom finishes work, the children's school is in
        # her day because she drives them, and leaving the names off turned that into "Mom has
        # school from 8 AM to 3 PM". A line about somebody else has to say who.
        attending = not subject or subject in (event.get("members") or [])
        facts.append(
            _event_fact(event, with_day=not one_day, mine_only=bool(subject) and attending)
        )

    rest = len(answerable) - len(listed[:8])
    if rest > 0:
        facts.append(
            f"The other {rest} are the usual work and school."
            if not (one_day or subject)
            else f"{rest} more are not listed here."
        )

    # Last, and only when nothing was asked for in particular. Aarav asking about football heard
    # "12 other blocks of time belong to other people" before his answer, which sounds like a refusal
    # to a question nobody asked.
    if hidden and not subject:
        facts.append(f"{plural(hidden, 'other block')} of time belong to other people.")
    return facts


def _task_facts(tasks: list[dict]) -> list[str]:
    """What is due, said as a deadline rather than as an appointment."""
    return [_task_fact(task) for task in tasks[:4]]


def _task_fact(task: dict) -> str:
    """"Aarav needs a farmer costume by Friday." A task has a date, not a time of day.

    `say_day`, not `say_when`: a task is stored at midnight on its due date, and `say_when` reads
    that as "Tuesday at 12 AM" -- a time nobody said and nobody meant.
    """
    whose = f"{task['owner']} needs " if task.get("owner") else ""
    when = say_day(date.fromisoformat(task["due"][:10]), clock_today())
    opening = f"{whose}{task['title']}" if whose else task["title"]
    return f"{opening} {'by' if whose else 'is due'} {when}."


def _named_facts(data: dict, speaker: str) -> list[str]:
    """Asked about one named thing, say when it is, whose it is, and who drives. Nothing else.

    "What is the piano class timing and day" was answered with "Mom can see 19 things Monday to
    Friday", and the timing was somewhere in the recital that followed. The question names one event;
    so does the answer. Who is asking changes only whether the driver is "you".
    """
    named = data["title"]
    found = data["events"]
    due = data.get("tasks") or []

    # A named thing may be a deadline rather than an appointment. "The fancy dress competition is on
    # which date" named a task that was in the database, and the answer was "there is no fancy dress
    # competition in the week" -- said about something LifePilot had written down itself.
    if not found:
        if due:
            return _task_facts(due)
        # The window that was actually searched, not the one the session loaded: the card beside
        # this says Monday to Friday, and a sentence saying "last Saturday to Friday" beside it
        # reads as two different answers to one question.
        searched = say_window(data["from"], data["to"])
        return [f"There is no {named} between {searched}."]

    facts = []
    for event in found[:4]:
        whose = say_list(event.get("members") or [])
        owner = f"{whose}'s " if whose else ""
        when = say_span(event["start"], event.get("end"))
        where = f" at {event['location']}" if event.get("location") else ""
        facts.append(f"{owner}{event['title']} is {when}{where}.")
        if event.get("needs_transport"):
            facts.append(_who_collects(event, speaker))
    if len(found) > 4:
        facts.append(f"There are {len(found) - 4} more in the week.")
    facts.extend(_task_facts(due))
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
        # Name the child. "Somebody has to collect them" leaves the one useful fact out of a sentence
        # whose whole purpose is to say who needs collecting.
        lift = (
            f", so {say_lift(event.get('members') or [], collecting=True)}"
            if event.get("needs_transport")
            else ""
        )
        facts.append(f"{event['title']} finishes exactly then{lift}.")

    named = {id(e) for e in busy + then["finishing"]}
    others = [e for e in data["events"] if id(e) not in named]
    if others:
        facts.append(f"There {'is' if len(others) == 1 else 'are'} "
                     f"{plural(len(others), 'other thing')} that day, at other times.")
    return facts


def _who_collects(event: dict, speaker: str) -> str:
    """Who is down to drive, and when they have to be there.

    "Someone has to collect Aarav and Anaya" answers neither half of "at what time do I collect Aarav
    from school". When somebody else is down for it, saying so is the answer: it is not your errand.
    """
    whose = say_list(event.get("members") or []) or "them"
    collecting = event.get("lift") != "drop"
    moment = event.get("end") if collecting else event["start"]
    verb = "collect" if collecting else "drop off"

    driver = event.get("lift_by")
    if driver is None:
        return f"Nobody is down to {verb} {whose} yet."
    who = "You" if driver == speaker else driver
    # say_when already supplies the preposition: "today at 3 PM", not "at today at 3 PM".
    return f"{who} {verb}{'' if who == 'You' else 's'} {whose} {say_when(moment)}."


def _when_it_matters(event: dict) -> str:
    """The moment this event asks something of the listener: the gate time, or the start."""
    if event.get("driving") and event.get("lift") != "drop":
        return event.get("end") or event["start"]
    return event["start"]


def _lift_fact(event: dict, members: list[str], with_day: bool) -> str:
    """Your part in somebody else's event: the time you have to be there, and nothing else.

    A drop is at the start, a pickup is at the end. Where the assignment does not say which, the end
    is assumed, because that is the one somebody is waiting at.
    """
    collecting = event.get("lift") != "drop"
    moment = event.get("end") if collecting else event["start"]
    verb = "collect" if collecting else "drop off"
    whose = say_list(members) or "somebody"
    where = f" from {event['location']}" if collecting and event.get("location") else ""
    if not collecting and event.get("location"):
        where = f" at {event['location']}"
    return f"You {verb} {whose}{where} at {say_when(moment, with_day=with_day)} ({event['title']})."


def _event_fact(event: dict, with_day: bool, mine_only: bool = False) -> str:
    # The span, not just the start: "school at 8 AM" does not tell a parent when to collect anyone,
    # and "what are the school timings" is exactly that question.
    when = say_span(event["start"], event.get("end"), with_day=with_day)
    where = f" at {event['location']}" if event.get("location") else ""
    members = event.get("members") or []

    # In your day because you are driving, not attending. "School 8 AM to 3 PM" told the parent doing
    # the pickup that they were at school all day; the fact they need is the time at the gate.
    if event.get("driving"):
        return _lift_fact(event, members, with_day)

    lift = f", and {say_lift(members)}" if event.get("needs_transport") else ""
    if mine_only:
        # Already established as yours; naming yourself on every line is how a robot talks.
        return f"{event['title']} {when}{where}{lift}."
    whose = say_list(members) or "the family"
    return f"{whose}: {event['title']} {when}{where}{lift}."


def _on(when: str) -> str:
    """The same rule `say_on` applies, capitalised because this one opens a sentence."""
    said = say_on(when)
    return said[:1].upper() + said[1:]


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
        when = _on(say_when(conflict["when"]))
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
        # Counted apart from calls on purpose: a cache hit must be visible without ever looking like
        # spare budget. The ceiling is spent by calls alone.
        "cached_tokens": budget.cache_hits,
        "input_tokens": budget.input_tokens,
        "output_tokens": budget.output_tokens,
        "estimated_cost_usd": round(budget.cost_usd, 8),
        "turn_ms": round((time.perf_counter() - started) * 1000),
    }
    if note:
        debug["note"] = note
    return debug
