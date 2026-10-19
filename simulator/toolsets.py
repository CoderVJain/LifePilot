"""The coarse routing set, for experiment 4's granularity comparison.

`TOOLSET=full` (the default) offers the model one schema per tool. `TOOLSET=coarse` offers nine
merged schemas instead, and each coarse call is translated back to the same fine-grained tool the
full set would have reached. Same capabilities, same server, different granularity -- which is what
experiment 4 is comparing.

The comparison is about **routing**, so this is a view over the schemas the model chooses among, not
a second registration on the MCP server. The server stays at 18 spec-pure tools. Four of those are
never routed to at all -- a yes or no is settled in code before the model is asked -- so the real
comparison is 14 schemas against 9.

A coarse tool is told apart by its arguments rather than by a mode word: the model fills them
anyway, and an extra enum is one more thing for it to get wrong.
"""

import os

#: Set TOOLSET=coarse to offer the merged set. Anything else, including unset, means the full set.
TOOLSET_ENV = "TOOLSET"

COARSE_SCHEMAS = [
    {
        "toolSpec": {
            "name": "get_context",
            "description": (
                "Look something up: who is in the family, or what is already on. "
                "Give start and end for a schedule; omit them to hear who the family is."
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
                                "they ask about a particular class, practice or meeting rather "
                                "than a whole day."
                            ),
                        },
                        "about": {
                            "type": "string",
                            "description": (
                                "Whose day. Resolve 'my' and 'I' to the speaker's own name; "
                                "otherwise whoever they named. Omit for everyone."
                            ),
                        },
                    },
                    "required": [],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "update_rules",
            "description": (
                "The family's standing rules. Give rule_type and params to state a new one "
                "('no homework after nine', 'never move piano'); omit both to hear the rules "
                "that already exist."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "rule_type": {
                            "type": "string",
                            "description": (
                                "One of immovable_event, latest_end, buffer_after, eligibility, "
                                "load_balance."
                            ),
                        },
                        "params": {
                            "type": "object",
                            "description": "The rule's details, as the full set's remember_rule takes them.",
                        },
                    },
                    "required": [],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "find_problems",
            "description": (
                "What is broken: a lift nobody can make, a clash, a rule broken. Set "
                "forgetting for deadlines with no time set aside -- 'what am I forgetting'."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "start": {"type": "string", "description": "First day, YYYY-MM-DD."},
                        "end": {"type": "string", "description": "Last day, YYYY-MM-DD."},
                        "forgetting": {
                            "type": "boolean",
                            "description": (
                                "True when they ask what they are forgetting or what might slip, "
                                "which is about tasks and deadlines rather than the diary."
                            ),
                        },
                    },
                    "required": [],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "decide_and_explain",
            "description": (
                "Who should cover a lift, and why a particular person was or was not chosen. "
                "Name a person to ask about them specifically ('why not Grandpa'); omit the "
                "person to be told who should go."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "person": {
                            "type": "string",
                            "description": (
                                "The person being asked about. Set it only when they named "
                                "somebody, as in 'why not Grandpa'."
                            ),
                        },
                        "title": {
                            "type": "string",
                            "description": "The lift, such as 'football', when they named one.",
                        },
                    },
                    "required": [],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "plan_changes",
            "description": (
                "Work out changes to the week. Give a kind to try something out without changing "
                "anything ('what if my four o'clock runs late'); omit it to repair what is "
                "actually broken, for a parent to approve."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "kind": {
                            "type": "string",
                            "description": (
                                "The hypothetical: runs_late, cancelled, or new_event. Set it only "
                                "for a what-if, never to repair the week."
                            ),
                        },
                        "title": {"type": "string", "description": "The thing being changed."},
                        "until": {"type": "string", "description": "New end time, HH:MM."},
                        "at": {"type": "string", "description": "A named time, HH:MM."},
                        "start": {"type": "string", "description": "First day, YYYY-MM-DD."},
                        "end": {"type": "string", "description": "Last day, YYYY-MM-DD."},
                    },
                    "required": [],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "update_schedule",
            "description": (
                "Change what is in the week, when they have decided to: 'book a dentist at ten "
                "on Friday', or 'cancel football practice' with cancel set to true."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "What it is called."},
                        "start": {
                            "type": "string",
                            "description": "When it starts, YYYY-MM-DDTHH:MM.",
                        },
                        "end": {"type": "string", "description": "When it ends, YYYY-MM-DDTHH:MM."},
                        "members": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Whose it is. Omit for the speaker.",
                        },
                        "location": {"type": "string", "description": "Where, if they said."},
                        "needs_transport": {
                            "type": "boolean",
                            "description": "True when a child has to be driven there.",
                        },
                        "cancel": {
                            "type": "boolean",
                            "description": "True to take it out of the week instead of adding it.",
                        },
                        "day": {
                            "type": "string",
                            "description": "Which day, YYYY-MM-DD, when cancelling.",
                        },
                    },
                    "required": ["title"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "school_email",
            "description": (
                "The school's email. Omit everything to hear what is new; give senders or "
                "disconnect to change what LifePilot may read."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "senders": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "The email addresses allowed. Omit to hear what is new.",
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
                                "The day whose lift the speaker is handing over, YYYY-MM-DD."
                            ),
                        },
                        "take_day": {
                            "type": "string",
                            "description": (
                                "The day whose lift the speaker is taking on, YYYY-MM-DD."
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

#: Which fine-grained tools each coarse schema stands in for. Read by the test that keeps the two
#: sets in sync, so a tool added to one and forgotten in the other fails rather than drifts.
COVERS = {
    "get_context": ("get_family", "get_schedule"),
    "update_rules": ("remember_rule", "list_rules"),
    "find_problems": ("detect_conflicts", "scan_risks"),
    "decide_and_explain": ("suggest_responsible", "explain_choice"),
    "plan_changes": ("fix_week", "what_if"),
    "update_schedule": ("add_event", "cancel_event"),
    "school_email": ("check_school_email", "manage_email_access"),
    "request_swap": ("request_swap",),
    "cannot_help": ("cannot_help",),
}


def coarse() -> bool:
    return (os.environ.get(TOOLSET_ENV) or "").strip().lower() == "coarse"


def translate(tool: str, arguments: dict) -> tuple[str, dict]:
    """A coarse call as the fine-grained call it stands for. Anything else passes through.

    Each branch reads the arguments the model already filled rather than a mode word, so there is
    no extra enum for it to get wrong. Unchanged for a tool that is not in the coarse set, which is
    what lets this run in front of the full set harmlessly.
    """
    if tool == "get_context":
        if arguments.get("start") or arguments.get("end"):
            # `get_schedule` requires both days; `get_context` cannot, because the same schema also
            # has to be callable with none for the family. Asked "what have I got today" the model
            # filled `start` and left `end` out, and the missing field surfaced to the speaker as a
            # pydantic validation error. The loaded window is the default the offline router has
            # always used for a day nobody bounded.
            from simulator.conversation import WEEK_START

            filled = dict(arguments)
            filled.setdefault("start", filled.get("end") or WEEK_START.isoformat())
            filled.setdefault("end", filled["start"])
            return "get_schedule", filled
        return "get_family", {}

    if tool == "update_rules":
        if arguments.get("rule_type"):
            return "remember_rule", arguments
        return "list_rules", {}

    if tool == "find_problems":
        if arguments.get("forgetting"):
            return "scan_risks", {}
        # `detect_conflicts` requires both days and the coarse schema cannot, because the same
        # schema also answers "what am I forgetting", which takes none.
        from simulator.conversation import WEEK_END, WEEK_START

        filled = {k: v for k, v in arguments.items() if k in ("start", "end")}
        filled.setdefault("start", filled.get("end") or WEEK_START.isoformat())
        filled.setdefault("end", WEEK_END.isoformat())
        return "detect_conflicts", filled

    if tool == "decide_and_explain":
        if arguments.get("person"):
            return "explain_choice", arguments
        return "suggest_responsible", {k: v for k, v in arguments.items() if k == "title"}

    if tool == "plan_changes":
        if arguments.get("kind"):
            return "what_if", arguments
        return "fix_week", {}

    if tool == "update_schedule":
        # The one branch that reads a flag rather than the shape of the arguments. Every other
        # branch can tell the two apart by what the model filled in; here it cannot, because a
        # cancellation usually names no time at all ("cancel football practice"). Treating a
        # missing `start` as a cancellation would turn one forgetful add into a deletion, and
        # deleting the wrong thing is far worse than routing to the wrong read-only tool.
        if arguments.get("cancel"):
            wanted = ("title", "day", "at")
            return "cancel_event", {k: v for k, v in arguments.items() if k in wanted}
        return "add_event", {k: v for k, v in arguments.items() if k not in ("cancel", "day")}

    if tool == "school_email":
        if arguments.get("senders") or arguments.get("disconnect"):
            return "manage_email_access", arguments
        return "check_school_email", {}

    return tool, arguments
