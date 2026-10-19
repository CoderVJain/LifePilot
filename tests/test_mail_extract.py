"""Extraction: one email in, zero or one dated task out, and nothing else reachable."""

from datetime import date

import pytest

from lifepilot.mail import extract as extract_module
from lifepilot.mail.extract import TOOL_NAME, extract, trim

TODAY = date(2026, 10, 8)


@pytest.fixture
def recorder(monkeypatch):
    """Stands in for Bedrock, and keeps what it was asked so the call shape can be asserted."""

    class Recorder:
        def __init__(self):
            self.kwargs = None
            self.filled = {}

        def __call__(self, **kwargs):
            self.kwargs = kwargs
            return {
                "output": {
                    "message": {"content": [{"toolUse": {"name": TOOL_NAME, "input": self.filled}}]}
                }
            }

    stub = Recorder()
    monkeypatch.setattr(extract_module, "converse", stub)
    return stub


def test_one_tool_in_scope_and_it_is_forced(recorder):
    recorder.filled = {
        "kind": "task",
        "title": "farmer costume",
        "child": "Aarav",
        "due": "2026-10-09",
        "category": "supplies",
        "prep_days": 1,
    }
    tasks = extract("Annual Day costumes", "Aarav performs on Friday.", TODAY)

    config = recorder.kwargs["tool_config"]
    assert [t["toolSpec"]["name"] for t in config["tools"]] == [TOOL_NAME]
    assert config["toolChoice"] == {"tool": {"name": TOOL_NAME}}
    assert tasks == [
        {
            "kind": "task",
            "title": "farmer costume",
            "child": "Aarav",
            "due": "2026-10-09",
            "category": "supplies",
            "prep_days": 1,
        }
    ]


def test_the_tool_has_no_side_effects_to_reach_for():
    """The whole injection defence: the one tool in scope only records fields.

    Checked on the schema's shape, not its prose. An earlier version searched the whole JSON for
    words like "send" and tripped over the description "such as sending a costume" -- which proved
    nothing either way, because what an email could reach for is the parameters, not the English.
    """
    spec = extract_module.EXTRACT_TOOL["toolSpec"]
    schema = spec["inputSchema"]["json"]

    assert set(schema["properties"]) == {
        "kind", "title", "child", "due", "category", "prep_days"
    }, "a new field here is a new thing an email can influence"
    assert schema["properties"]["kind"]["enum"] == ["task", "closure", "nothing"]
    assert schema["type"] == "object"

    # Nothing in the form names a thing in the family's week, so nothing in it can address one.
    for forbidden in ("event_id", "proposal_id", "member_id", "speaker", "tool"):
        assert forbidden not in schema["properties"]


def test_a_newsletter_produces_no_task(recorder):
    recorder.filled = {
        "kind": "nothing",
        "title": "",
        "child": "",
        "due": "",
        "category": "event",
        "prep_days": 0,
    }
    assert extract("October newsletter", "Our team won on Tuesday.", TODAY) == []


def test_a_task_without_a_readable_date_is_dropped(recorder):
    recorder.filled = {
        "kind": "task",
        "title": "costume",
        "child": "Aarav",
        "due": "soon",
        "category": "supplies",
        "prep_days": 0,
    }
    assert extract("Costumes", "Please send a costume soon.", TODAY) == []


def test_a_closure_is_a_dated_closure_not_a_task(recorder):
    """A closure asks nobody to do anything and still changes the week: no school, no school run."""
    recorder.filled = {
        "kind": "closure",
        "title": "heavy rains",
        "child": "",
        "due": "2026-10-09",
        "category": "event",
        "prep_days": 0,
    }
    assert extract("School closed tomorrow", "Closed tomorrow, heavy rains.", TODAY) == [
        {"kind": "closure", "title": "heavy rains", "date": "2026-10-09"}
    ]


def test_a_closure_with_no_date_is_dropped(recorder):
    """"We may close at some point" says which day to clear without saying which day."""
    recorder.filled = {"kind": "closure", "title": "rains", "child": "", "due": "", "prep_days": 0}
    assert extract("Possible closure", "We may close.", TODAY) == []


def test_only_subject_and_trimmed_body_reach_the_model(recorder):
    recorder.filled = {"kind": "nothing", "title": "", "child": "", "due": "", "prep_days": 0}
    extract("Fees", "Fees due on the 15th.\n> last week we said something else\nregards", TODAY)

    sent = recorder.kwargs["messages"][0]["content"][0]["text"]
    assert sent == "Subject: Fees\nFees due on the 15th."


def test_today_is_told_to_the_model_so_friday_has_a_date(recorder):
    recorder.filled = {"kind": "nothing", "title": "", "child": "", "due": "", "prep_days": 0}
    extract("Costumes", "Friday.", TODAY)
    assert "2026-10-08" in recorder.kwargs["system"][0]["text"]


def test_trim_keeps_the_email_and_drops_the_quoted_reply():
    body = "Costume by Friday.\n\n-----Original Message-----\nFrom: someone"
    assert trim(body) == "Costume by Friday."
