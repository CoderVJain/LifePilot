"""suggest_responsible and explain_choice against the seeded family. Offline and free.

The demo moment: Dad cannot make Thursday's football pickup, Mom can, and "why not Grandpa?" has an
exact answer that came from the decision itself.
"""

from datetime import date

import pytest

from eval.generate import build_demo_family
from lifepilot.db.session import make_engine, make_session_factory
from lifepilot.tools.decide import explain_choice, suggest_responsible
from lifepilot.tools.rules import list_rules, remove_rule

MONDAY, FRIDAY = date(2026, 10, 5), date(2026, 10, 9)


@pytest.fixture
def session():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    factory = make_session_factory(engine, create=True)
    with factory() as s:
        build_demo_family(s)
        yield s


def suggest(session, **kwargs):
    return suggest_responsible(session, "Dad", MONDAY, FRIDAY, **kwargs)


def test_mom_is_suggested_for_the_football_pickup(session):
    result = suggest(session, title="football")
    assert result["found"] is True
    assert result["assigned_to"] == "Dad"
    assert result["ranked"][0]["name"] == "Mom"


def test_the_suggestion_carries_a_reason_a_person_would_accept(session):
    top = suggest(session, title="football")["ranked"][0]
    assert top["reason"]
    assert top["deciding_factor"] in {"load", "travel", "slack", "only_one", "tie"}


def test_everyone_ruled_out_comes_back_with_why(session):
    result = suggest(session, title="football")
    ruled_out = {r["name"]: r["reason"] for r in result["ruled_out"]}
    assert ruled_out["Dad"] == "arrives 17:25, needs 17:00"
    assert ruled_out["Grandpa"] == "rule: only when no parent is free"
    assert ruled_out["Aarav"] == "cannot drive"


def test_why_not_grandpa_names_the_rule(session):
    """CLAUDE.md's example answer, produced from the stored reason rather than generated."""
    answer = explain_choice(session, "Dad", MONDAY, FRIDAY, "Grandpa", title="football")
    assert answer["can_do_it"] is False
    assert answer["reason"] == "rule: only when no parent is free"
    assert answer["say"] == "Not Grandpa: rule: only when no parent is free."


def test_why_not_dad_names_the_travel_time(session):
    answer = explain_choice(session, "Dad", MONDAY, FRIDAY, "Dad", title="football")
    assert answer["can_do_it"] is False
    assert "arrives 17:25, needs 17:00" in answer["say"]


def test_why_mom_says_what_makes_her_able(session):
    answer = explain_choice(session, "Dad", MONDAY, FRIDAY, "Mom", title="football")
    assert answer["can_do_it"] is True
    assert "10 minutes away" in answer["reason"]


def test_asking_about_someone_outside_the_family(session):
    answer = explain_choice(session, "Dad", MONDAY, FRIDAY, "Priya", title="football")
    assert answer["found"] is False
    assert "do not know anyone called Priya" in answer["say"]


def test_the_explanation_matches_the_suggestion_for_every_person(session):
    """The two tools must never disagree: both read the same recorded reasons."""
    result = suggest(session, title="football")
    ruled_out = {r["name"]: r["reason"] for r in result["ruled_out"]}
    for name, reason in ruled_out.items():
        answer = explain_choice(session, "Dad", MONDAY, FRIDAY, name, title="football")
        assert answer["can_do_it"] is False
        assert answer["reason"] == reason


def test_dropping_the_grandparent_rule_changes_the_answer_to_why_not_grandpa(session):
    before = explain_choice(session, "Dad", MONDAY, FRIDAY, "Grandpa", title="football")
    assert before["can_do_it"] is False

    eligibility = next(r for r in list_rules(session, "Dad")["rules"] if r["type"] == "eligibility")
    remove_rule(session, "Dad", eligibility["id"], confirmed=True)

    after = explain_choice(session, "Dad", MONDAY, FRIDAY, "Grandpa", title="football")
    assert after["can_do_it"] is True


def test_an_unknown_lift_lists_the_ones_that_exist(session):
    result = suggest(session, title="swimming")
    assert result["found"] is False
    assert {lift["title"] for lift in result["lifts"]} == {
        "piano class pickup",
        "football practice pickup",
    }


def test_a_lift_can_be_asked_for_by_event_id(session):
    by_title = suggest(session, title="football")
    by_id = suggest(session, event_id=by_title["event_id"])
    assert by_id["ranked"] == by_title["ranked"]
