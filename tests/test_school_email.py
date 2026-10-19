"""School email to plan (#7), and the four promises CLAUDE.md makes about it:

    an injection email executes nothing
    a sender who is not the school is never read
    disconnecting leaves no stored rows
    no email body reaches the database or a log
"""

import json
import logging
from datetime import date, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from cryptography.fernet import Fernet

from eval.generate import build_demo_family
from lifepilot.db.models import EmailLink, Member, Proposal, SchoolMessage, Task
from lifepilot.db.session import make_engine, make_session_factory
from lifepilot.mail import vault
from lifepilot.mail.gmail import FakeGmail
from lifepilot.tools import school_email as tool
from lifepilot.tools.approve import approve_proposal

TODAY = date(2026, 10, 8)
SCHOOL = "office@demo-school.invalid"

#: The labelled fake emails, read from the eval set so tests and evals cannot drift apart.
EMAIL_DIR = Path("eval/emails")
EMAILS = {
    "costume": json.loads((EMAIL_DIR / "costume_friday.json").read_text()),
    "injection": json.loads((EMAIL_DIR / "injection_cancel_pickups.json").read_text()),
    "newsletter": json.loads((EMAIL_DIR / "newsletter_no_task.json").read_text()),
    "closure": json.loads((EMAIL_DIR / "closure_tomorrow.json").read_text()),
}


@pytest.fixture(autouse=True)
def encryption_key(monkeypatch):
    monkeypatch.setenv(vault.KEY_ENV, Fernet.generate_key().decode())


@pytest.fixture
def session():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    factory = make_session_factory(engine, create=True)
    with factory() as s:
        build_demo_family(s)
        yield s


def link(session, senders=(SCHOOL,), token=True):
    dad = session.scalars(sa.select(Member).where(Member.name == "Dad")).one()
    row = EmailLink(
        family_id=dad.family_id,
        parent_id=dad.id,
        encrypted_token=vault.seal({"refresh_token": "demo"}) if token else b"",
        allowed_senders=list(senders),
    )
    session.add(row)
    session.commit()
    return row


def inbox(*names, sender=SCHOOL):
    return FakeGmail(
        [
            {
                "id": name,
                "sender": sender,
                "subject": EMAILS[name]["subject"],
                "body": EMAILS[name]["body"],
                "received_at": datetime(2026, 10, 7, 9, 0),
            }
            for name in names
        ]
    )


@pytest.fixture
def extraction(monkeypatch):
    """The model, replaced by the labelled expectation that lives beside each email."""
    seen = []

    def fake_extract(subject, body, today, turn=None, children=None):
        seen.append((subject, body, children))
        if turn is not None:
            turn.spend()
        expected = next(e["expected"] for e in EMAILS.values() if e["subject"] == subject)
        return [dict(task) for task in expected]

    monkeypatch.setattr(tool, "extract", fake_extract)
    return seen


# --------------------------------------------------------------------------- the happy path


def test_an_email_becomes_a_pending_task_nobody_has_approved(session, extraction):
    link(session)
    result = tool.check_school_email(session, "Dad", client=inbox("costume"), today=TODAY)

    assert result["new_tasks"] == 1
    assert result["tasks"][0]["title"] == "farmer costume"
    assert result["status"] == "pending"
    assert session.scalar(sa.select(sa.func.count()).select_from(Task).where(Task.source == "email")) == 0


def test_approving_writes_the_task(session, extraction):
    link(session)
    result = tool.check_school_email(session, "Dad", client=inbox("costume"), today=TODAY)
    approve_proposal(session, "Dad", result["proposal_id"])

    task = session.scalars(sa.select(Task).where(Task.source == "email")).one()
    assert task.title == "farmer costume"
    assert task.due == datetime(2026, 10, 9)
    assert task.owner_id == session.scalars(sa.select(Member).where(Member.name == "Aarav")).one().id


def test_the_answer_carries_the_task_the_conflict_and_the_fix(session, extraction):
    """One tool call, one result. Three round trips would not fit the 3-call ceiling."""
    link(session)
    result = tool.check_school_email(session, "Dad", client=inbox("costume"), today=TODAY)

    assert result["breaks"], "the demo week has an unreachable pickup in it"
    assert result["fix"]["changes"]
    assert "farmer costume" in result["say"]


def test_a_newsletter_proposes_nothing_and_says_it_was_read(session, extraction):
    """A tester sent a closure notice, got "Nothing new from school", and concluded LifePilot had
    not read it. It had, and had correctly decided an announcement asks nobody to do anything."""
    link(session)
    result = tool.check_school_email(session, "Dad", client=inbox("newsletter"), today=TODAY)

    assert result["new_tasks"] == 0
    assert "proposal_id" not in result
    assert result["say"] == "I read one email from school, and there is nothing you need to do."


def test_an_empty_inbox_is_a_different_answer_from_an_empty_newsletter(session, extraction):
    link(session)
    result = tool.check_school_email(session, "Dad", client=inbox(), today=TODAY)

    assert result["read"] == 0
    assert result["say"] == "Nothing new from school."


def test_the_same_email_is_never_extracted_twice(session, extraction):
    """One model call per email, ever. The stored row is the cache."""
    link(session)
    reader = inbox("costume")
    tool.check_school_email(session, "Dad", client=reader, today=TODAY)
    again = tool.check_school_email(session, "Dad", client=reader, today=TODAY)

    assert len(extraction) == 1
    assert again["new_tasks"] == 0
    assert again["new_messages"] == 0, "already read, so nothing was extracted again"
    assert again["say"] == "Nothing new from school."


def test_reading_costs_at_most_one_call_per_email(session, extraction):
    link(session)
    result = tool.check_school_email(session, "Dad", client=inbox("costume"), today=TODAY)
    assert result["model_calls"] == 1


# --------------------------------------------------------------------------- the four promises


def test_an_injection_email_executes_nothing(session, extraction):
    """The email says to cancel every pickup. Nothing in the result can act, and nothing has."""
    link(session)
    before = session.scalar(sa.select(sa.func.count()).select_from(sa.text("assignment")))

    result = tool.check_school_email(session, "Dad", client=inbox("injection"), today=TODAY)

    assert result["status"] == "pending"
    assert "CANCELLED" not in json.dumps(result).upper()
    assert session.scalar(sa.select(sa.func.count()).select_from(sa.text("assignment"))) == before
    assert session.scalar(sa.select(sa.func.count()).select_from(Task).where(Task.source == "email")) == 0


def test_a_sender_who_is_not_the_school_is_never_read(session, extraction):
    link(session)
    stranger = inbox("costume", sender="someone@elsewhere.invalid")

    result = tool.check_school_email(session, "Dad", client=stranger, today=TODAY)

    assert result["read"] == 0
    assert extraction == []
    assert session.scalar(sa.select(sa.func.count()).select_from(SchoolMessage)) == 0


def test_every_query_names_the_allowed_senders(session, extraction):
    link(session)
    reader = inbox("costume")
    tool.check_school_email(session, "Dad", client=reader, today=TODAY)

    assert reader.queries == [f"from:({SCHOOL}) after:2026/09/24"]


def test_disconnecting_revokes_and_leaves_no_rows(session, extraction):
    link(session)
    reader = inbox("costume")
    tool.check_school_email(session, "Dad", client=reader, today=TODAY)
    assert session.scalar(sa.select(sa.func.count()).select_from(SchoolMessage)) == 1

    result = tool.manage_email_access(session, "Dad", disconnect=True, client=reader)

    assert result["revoked"] and reader.revoked
    assert session.scalar(sa.select(sa.func.count()).select_from(SchoolMessage)) == 0
    assert session.scalar(sa.select(sa.func.count()).select_from(EmailLink)) == 0


def test_no_email_body_reaches_the_database_or_the_log(session, extraction, caplog):
    link(session)
    with caplog.at_level(logging.DEBUG):
        tool.check_school_email(session, "Dad", client=inbox("costume"), today=TODAY)

    stored = session.scalars(sa.select(SchoolMessage)).one()
    phrase = "Plain brown or green clothes"
    assert phrase not in json.dumps(
        {c.name: str(getattr(stored, c.name)) for c in SchoolMessage.__table__.columns}
    )
    assert phrase not in caplog.text
    assert stored.sender == SCHOOL


# --------------------------------------------------------------------------- access and refusals


def test_a_child_cannot_read_the_school_email(session, extraction):
    link(session)
    with pytest.raises(tool.NotAllowed):
        tool.check_school_email(session, "Aarav", client=inbox("costume"), today=TODAY)


def test_without_a_linked_account_it_says_so(session, extraction):
    with pytest.raises(tool.NotLinked):
        tool.check_school_email(session, "Dad", client=inbox("costume"), today=TODAY)


def test_a_link_with_no_senders_reads_nothing(session, extraction):
    link(session, senders=())
    with pytest.raises(tool.NotLinked):
        tool.check_school_email(session, "Dad", client=inbox("costume"), today=TODAY)


def test_setting_the_senders_is_a_parents_decision(session):
    with pytest.raises(tool.NotAllowed):
        tool.manage_email_access(session, "Aarav", senders=[SCHOOL])


def test_senders_can_be_set_before_gmail_is_linked(session):
    result = tool.manage_email_access(session, "Dad", senders=[f"Demo School <{SCHOOL}>"])

    assert result["allowed_senders"] == [SCHOOL]
    assert result["linked"] is False
    assert "Link Gmail" in result["say"]


# --------------------------------------------------------------------------- closures


def school_events(session, when=date(2026, 10, 9)):
    import sqlalchemy as sa2

    from lifepilot.db.models import Event

    return session.scalars(
        sa2.select(Event).where(Event.category == "school", Event.start >= datetime.combine(
            when, datetime.min.time()), Event.start <= datetime.combine(when, datetime.max.time()))
    ).all()


def test_a_closure_proposes_clearing_school_that_day(session, extraction):
    """A closure asks nobody to do anything, and still changes the week more than most tasks."""
    link(session)
    result = tool.check_school_email(session, "Dad", client=inbox("closure"), today=TODAY)

    assert result["new_tasks"] == 0
    assert result["closures"] == [
        {"kind": "closure", "title": "heavy rains", "date": "2026-10-09"}
    ]
    assert [c["kind"] for c in result["changes"]] == ["remove"]
    assert result["changes"][0]["title"] == "school"
    assert "closed" in result["say"] and "Shall I clear it?" in result["say"]


def test_a_closure_says_who_it_frees_from_the_run(session, extraction):
    """The useful half of the answer: no school means somebody stops having to drive."""
    link(session)
    result = tool.check_school_email(session, "Dad", client=inbox("closure"), today=TODAY)

    assert result["changes"][0]["frees"], "the school run is assigned to a parent every weekday"
    assert "frees" in result["say"]


def test_nothing_is_cleared_until_a_parent_approves(session, extraction):
    link(session)
    before = len(school_events(session))
    tool.check_school_email(session, "Dad", client=inbox("closure"), today=TODAY)

    assert len(school_events(session)) == before


def test_approving_a_closure_clears_school_and_its_lifts(session, extraction):
    import sqlalchemy as sa2

    from lifepilot.db.models import Assignment

    link(session)
    result = tool.check_school_email(session, "Dad", client=inbox("closure"), today=TODAY)
    event_ids = [c["event_id"] for c in result["changes"]]

    approve_proposal(session, "Dad", result["proposal_id"])

    assert school_events(session) == []
    left = session.scalars(
        sa2.select(Assignment).where(Assignment.event_id.in_(event_ids))
    ).all()
    assert left == [], "a cleared event must not leave a lift assigned to nobody's event"


def test_a_closure_can_only_clear_school(session, extraction):
    """A school is an authority on school and on nothing else. An email is the one input we must
    assume is hostile, so "we are closed" cannot propose clearing a parent's work."""
    link(session)
    result = tool.check_school_email(session, "Dad", client=inbox("closure"), today=TODAY)

    assert tool.CLEARABLE == ("school",)
    assert all(c["title"] == "school" for c in result["changes"])


def test_a_closure_for_a_past_day_clears_nothing(session, extraction, monkeypatch):
    """A forwarded notice about last week must not delete history."""
    link(session)
    result = tool.check_school_email(
        session, "Dad", client=inbox("closure"), today=date(2026, 10, 20)
    )

    assert result["new_tasks"] == 0
    assert "proposal_id" not in result
    assert "Nothing in your week changes" in result["say"]


def test_the_children_are_named_to_the_extraction(session, extraction):
    """Without them the model answered the word "child", and the sentence came out as "child needs
    Fancy Dress Competition"."""
    link(session)
    tool.check_school_email(session, "Dad", client=inbox("costume"), today=TODAY)

    assert extraction[0][2] == ["Aarav", "Anaya"]


def test_a_child_the_family_does_not_have_is_no_child(session, monkeypatch):
    """An unmatched name is dropped rather than spoken back. Nobody is called "child", and with two
    children in the family LifePilot asks which one instead of guessing."""
    monkeypatch.setattr(
        tool,
        "extract",
        lambda *a, **k: [
            {"kind": "task", "title": "Fancy Dress Competition", "child": "child",
             "due": "2026-10-09", "category": "event", "prep_days": 0}
        ],
    )
    link(session)
    result = tool.check_school_email(session, "Dad", client=inbox("costume"), today=TODAY)

    assert result["changes"][0]["child"] is None
    assert result["changes"][0]["owner_id"] is None
    assert "child needs" not in result["say"]
    assert result["needs_child"] == ["Aarav", "Anaya"]
    assert "Is it Aarav or Anaya?" in result["say"]


# --------------------------------------------------------------------------- which child?


@pytest.fixture
def unnamed_task(monkeypatch):
    """An email whose task names no child we can match."""
    monkeypatch.setattr(
        tool,
        "extract",
        lambda *a, **k: [
            {"kind": "task", "title": "Fancy Dress Competition", "child": "",
             "due": "2026-10-09", "category": "event", "prep_days": 0}
        ],
    )


def test_a_named_child_amends_the_proposal_without_approving_it(session, unnamed_task):
    link(session)
    found = tool.check_school_email(session, "Dad", client=inbox("costume"), today=TODAY)

    named = tool.name_task_child(session, "Dad", found["proposal_id"], "Anaya")

    anaya = session.scalars(sa.select(Member).where(Member.name == "Anaya")).one()
    proposal = session.get(Proposal, found["proposal_id"])
    assert named["named"] is True
    assert proposal.changes[0]["owner_id"] == anaya.id
    assert proposal.changes[0]["child"] == "Anaya"
    assert proposal.status == "pending", "naming the child is not approving the task"
    assert "Shall I" in named["say"]


def test_the_task_is_written_to_the_named_child(session, unnamed_task):
    link(session)
    found = tool.check_school_email(session, "Dad", client=inbox("costume"), today=TODAY)
    tool.name_task_child(session, "Dad", found["proposal_id"], "Aarav")
    approve_proposal(session, "Dad", found["proposal_id"])

    aarav = session.scalars(sa.select(Member).where(Member.name == "Aarav")).one()
    task = session.scalars(sa.select(Task).where(Task.source == "email")).one()
    assert task.owner_id == aarav.id


def test_someone_who_is_not_a_child_is_refused(session, unnamed_task):
    """"Mom" is a real family member and not an answer to "which child"."""
    link(session)
    found = tool.check_school_email(session, "Dad", client=inbox("costume"), today=TODAY)

    for wrong in ("Mom", "Rahul"):
        answer = tool.name_task_child(session, "Dad", found["proposal_id"], wrong)
        assert answer["named"] is False
        assert "Aarav and Anaya" in answer["say"]


def test_a_child_cannot_name_the_child(session, unnamed_task):
    link(session)
    found = tool.check_school_email(session, "Dad", client=inbox("costume"), today=TODAY)

    with pytest.raises(tool.NotAllowed):
        tool.name_task_child(session, "Aarav", found["proposal_id"], "Aarav")


def test_an_already_decided_proposal_takes_no_name(session, unnamed_task):
    link(session)
    found = tool.check_school_email(session, "Dad", client=inbox("costume"), today=TODAY)
    approve_proposal(session, "Dad", found["proposal_id"])

    answer = tool.name_task_child(session, "Dad", found["proposal_id"], "Aarav")
    assert answer["named"] is False


def test_an_email_that_names_a_child_is_not_queried(session, extraction):
    """The costume email says Aarav, so there is nothing to ask."""
    link(session)
    result = tool.check_school_email(session, "Dad", client=inbox("costume"), today=TODAY)

    assert result["needs_child"] == []
    assert "which child" not in result["say"]


def test_an_only_child_is_assumed_rather_than_asked(session, unnamed_task):
    """With one child there is no ambiguity, so asking would be a question for its own sake."""
    anaya = session.scalars(sa.select(Member).where(Member.name == "Anaya")).one()
    session.delete(anaya)
    session.commit()
    link(session)

    result = tool.check_school_email(session, "Dad", client=inbox("costume"), today=TODAY)

    aarav = session.scalars(sa.select(Member).where(Member.name == "Aarav")).one()
    assert result["needs_child"] == []
    assert result["changes"][0]["owner_id"] == aarav.id
