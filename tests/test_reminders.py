"""Speaking first, computed as pure functions: no clock, no socket, no model.

The cost rules forbid aiming a scheduled job at Bedrock, so the last test here is the important one.
"""

from datetime import datetime, timedelta

from simulator import reminders
from simulator.reminders import due_now

NOW = datetime(2026, 10, 8, 16, 15)


def schedule(*events) -> dict:
    return {"events": list(events)}


def event(title, start, minutes=60, members=("Aarav",), transport=False, redacted=False) -> dict:
    begins = datetime.fromisoformat(start)
    return {
        "title": title,
        "start": begins.isoformat(),
        "end": (begins + timedelta(minutes=minutes)).isoformat(),
        "members": list(members),
        "needs_transport": transport,
        "redacted": redacted,
    }


def unreachable(when, title="football practice pickup", cover=("Mom",)) -> dict:
    return {
        "conflicts": [{
            "kind": "unreachable",
            "title": title,
            "when": when,
            "detail": f"{title}: Dad is down for it but arrives at 5:25, needs to be there at 5:00",
            "could_cover": list(cover),
        }]
    }


# --------------------------------------------------------------------------- something starting


def test_something_starting_shortly_is_mentioned():
    said = due_now(schedule(event("football practice", "2026-10-08T16:25")), {}, NOW, set())

    assert len(said) == 1
    assert said[0].kind == "nudge"
    assert "starts in 10 minutes" in said[0].speak
    assert "4:25 PM" in said[0].speak


def test_something_far_off_is_left_alone():
    assert due_now(schedule(event("football", "2026-10-08T19:00")), {}, NOW, set()) == []


def test_something_already_started_is_not_announced():
    """A reminder that arrives after the thing began is noise."""
    assert due_now(schedule(event("football", "2026-10-08T16:00")), {}, NOW, set()) == []


def test_a_lift_is_named_in_the_nudge():
    said = due_now(
        schedule(event("football", "2026-10-08T16:20", transport=True)), {}, NOW, set()
    )
    assert "someone has to drive Aarav" in said[0].speak


def test_a_hidden_event_is_never_announced():
    """Role privacy holds on the proactive path too, where nobody asked a question to be filtered."""
    said = due_now(
        schedule(event("Busy", "2026-10-08T16:20", members=(), redacted=True)), {}, NOW, set()
    )
    assert said == []


# --------------------------------------------------------------------------- something breaking


def test_a_lift_nobody_can_make_is_raised_with_time_to_spare():
    said = due_now({}, unreachable("2026-10-08T17:00"), NOW, set())

    assert len(said) == 1
    assert said[0].kind == "warning"
    assert "arrives at 5:25" in said[0].speak
    assert "Mom could go instead" in said[0].speak


def test_a_warning_too_far_ahead_waits():
    assert due_now({}, unreachable("2026-10-08T22:00"), NOW, set()) == []


def test_a_warning_in_the_past_is_dropped():
    assert due_now({}, unreachable("2026-10-08T15:00"), NOW, set()) == []


def test_a_warning_with_nobody_free_still_warns():
    said = due_now({}, unreachable("2026-10-08T17:00", cover=()), NOW, set())
    assert said and "could go instead" not in said[0].speak


def test_the_warning_comes_before_the_reminder():
    """A plan about to break matters more than something about to start."""
    said = due_now(
        schedule(event("football practice", "2026-10-08T16:25")),
        unreachable("2026-10-08T17:00"),
        NOW,
        set(),
    )
    assert [s.kind for s in said] == ["warning", "nudge"]


# --------------------------------------------------------------------------- saying it once


def test_nothing_is_said_twice():
    once = due_now(schedule(event("football", "2026-10-08T16:25")), {}, NOW, set())
    again = due_now(
        schedule(event("football", "2026-10-08T16:25")), {}, NOW, {s.key for s in once}
    )
    assert once and again == []


def test_two_different_events_are_two_different_keys():
    said = due_now(
        schedule(
            event("football", "2026-10-08T16:25"),
            event("piano", "2026-10-08T16:20", members=("Anaya",)),
        ),
        {},
        NOW,
        set(),
    )
    assert len({s.key for s in said}) == 2


# --------------------------------------------------------------------------- what it must not do


def test_nothing_here_calls_a_model():
    """CLAUDE.md: never point a loop or a scheduled job at the model. A tick that phrased its output
    through Nova would spend money for as long as the demo is open.

    Checked against the parsed module rather than its text, so the docstring may discuss Bedrock
    without the test mistaking prose for a call.
    """
    import ast
    import pathlib

    tree = ast.parse(pathlib.Path(reminders.__file__).read_text(encoding="utf-8"))

    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported.update(alias.name for alias in node.names)

    assert not {name for name in imported if "llm" in name or "boto" in name or "bedrock" in name}
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "converse" not in called
    assert "phrase" not in called


def test_an_unreadable_time_is_ignored_rather_than_raising():
    """This runs on a timer with nobody watching, so bad data must not take the loop down."""
    assert due_now({"events": [{"title": "x", "start": "soon"}]}, {}, NOW, set()) == []
    assert due_now({}, {"conflicts": [{"kind": "unreachable", "when": "later"}]}, NOW, set()) == []
