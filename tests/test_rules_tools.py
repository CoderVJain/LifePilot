"""add_rule / list_rules / remove_rule against the seeded family. Offline and free."""

import pytest
import sqlalchemy as sa

from eval.generate import build_demo_family
from lifepilot.db.models import Rule
from lifepilot.db.session import make_engine, make_session_factory
from lifepilot.tools.rules import NotAllowed, add_rule, list_rules, remove_rule


@pytest.fixture
def session():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    factory = make_session_factory(engine, create=True)
    with factory() as s:
        build_demo_family(s)
        yield s


NEW_RULE = ("latest_end", {"category": "activity", "latest_end": "19:30"})


def test_a_rule_is_read_back_and_not_stored_until_confirmed(session):
    before = session.scalar(sa.select(sa.func.count()).select_from(Rule))

    first = add_rule(session, "Dad", *NEW_RULE, "no clubs after half seven")
    assert first["stored"] is False
    assert first["needs_confirmation"] is True
    assert first["readback"] == "No activity after 19:30."
    assert "Shall I remember that?" in first["say"]
    assert session.scalar(sa.select(sa.func.count()).select_from(Rule)) == before


def test_confirming_stores_it_with_the_parents_own_words(session):
    add_rule(session, "Dad", *NEW_RULE, "no clubs after half seven")
    stored = add_rule(session, "Dad", *NEW_RULE, "no clubs after half seven", confirmed=True)

    assert stored["stored"] is True
    rule = session.get(Rule, stored["rule_id"])
    assert rule.type == "latest_end"
    assert rule.params == {"category": "activity", "latest_end": "19:30"}
    assert rule.spoken_text == "no clubs after half seven"
    assert rule.hard is True
    assert rule.confirmed_by is not None


def test_a_rule_type_we_cannot_enforce_is_refused_with_an_explanation(session):
    result = add_rule(session, "Dad", "no_screens", {"after": "19:00"}, "no screens after seven")
    assert result["stored"] is False
    assert result["needs_confirmation"] is False
    assert "not a rule LifePilot can enforce" in result["problem"]


def test_a_supported_type_with_nonsense_details_is_refused_not_guessed(session):
    result = add_rule(
        session, "Dad", "latest_end", {"category": "study", "latest_end": "half nine"}, "..."
    )
    assert result["stored"] is False
    assert "24-hour time" in result["problem"]


def test_only_a_parent_may_change_the_rules(session):
    with pytest.raises(NotAllowed):
        add_rule(session, "Aarav", *NEW_RULE, "no clubs after half seven", confirmed=True)
    with pytest.raises(NotAllowed):
        remove_rule(session, "Grandpa", 1, confirmed=True)


def test_the_same_rule_twice_is_not_stored_twice(session):
    add_rule(session, "Dad", *NEW_RULE, "said once", confirmed=True)
    again = add_rule(session, "Mom", *NEW_RULE, "said again", confirmed=True)
    assert again["stored"] is False
    assert "already told me" in again["say"]


def test_the_seeded_rules_all_read_back(session):
    listed = list_rules(session, "Dad")
    assert len(listed["rules"]) == 5
    assert {r["type"] for r in listed["rules"]} == {
        "immovable_event",
        "latest_end",
        "buffer_after",
        "eligibility",
        "load_balance",
    }
    for rule in listed["rules"]:
        assert rule["readback"].endswith(".")
        assert rule["spoken_text"]


def test_load_balancing_is_stored_as_a_preference(session):
    listed = list_rules(session, "Dad")
    soft = [r for r in listed["rules"] if not r["hard"]]
    assert [r["type"] for r in soft] == ["load_balance"]


def test_removing_a_rule_reads_it_back_first(session):
    rule_id = list_rules(session, "Dad")["rules"][0]["id"]
    asked = remove_rule(session, "Dad", rule_id)
    assert asked["removed"] is False
    assert asked["needs_confirmation"] is True
    assert "Shall I forget it?" in asked["say"]
    assert len(list_rules(session, "Dad")["rules"]) == 5


def test_a_removed_rule_stops_applying_but_the_row_survives(session):
    rule_id = list_rules(session, "Dad")["rules"][0]["id"]
    remove_rule(session, "Dad", rule_id, confirmed=True)

    assert len(list_rules(session, "Dad")["rules"]) == 4
    # The history of a past week should still be explainable.
    assert session.get(Rule, rule_id).active is False


def test_removing_something_that_is_not_there(session):
    assert remove_rule(session, "Dad", 999, confirmed=True)["removed"] is False


def test_a_child_may_still_hear_the_rules(session):
    """Rules are how the family explains itself. Reading them is not changing them."""
    listed = list_rules(session, "Aarav")
    assert listed["speaker"]["role"] == "child"
    assert len(listed["rules"]) == 5


# --------------------------------------------------------------------------- rules as constraints


def test_a_new_rule_immediately_changes_what_is_broken(session):
    """A rule is a constraint, not a note. Stating one has to change the answer."""
    from datetime import date

    from lifepilot.tools.detect_conflicts import detect_conflicts

    window = (date(2026, 10, 5), date(2026, 10, 9))
    before = detect_conflicts(session, "Dad", *window)["conflicts"]

    # Football runs 16:00-17:00, so a 16:30 cut-off on activities breaks it.
    add_rule(
        session,
        "Dad",
        "latest_end",
        {"category": "activity", "latest_end": "16:30"},
        "no clubs past half four",
        confirmed=True,
    )
    after = detect_conflicts(session, "Dad", *window)["conflicts"]

    assert len(after) > len(before)
    new = [c for c in after if c["kind"] == "rule_clash" and "16:30" in c["detail"]]
    assert new, "the rule the parent just stated did not reach the solver"


def test_dropping_the_grandparent_rule_changes_who_is_allowed_to_cover(session):
    """Grandpa is excluded by a rule, not by distance. Retire it and he becomes eligible."""
    from datetime import date

    from lifepilot.tools.detect_conflicts import detect_conflicts

    window = (date(2026, 10, 5), date(2026, 10, 9))
    conflict = next(
        c for c in detect_conflicts(session, "Dad", *window)["conflicts"] if c["kind"] == "unreachable"
    )
    reasons = {c["name"]: c["reason"] for c in conflict["candidates"]}
    assert reasons["Grandpa"] == "rule: only when no parent is free"

    eligibility = next(r for r in list_rules(session, "Dad")["rules"] if r["type"] == "eligibility")
    remove_rule(session, "Dad", eligibility["id"], confirmed=True)

    conflict = next(
        c for c in detect_conflicts(session, "Dad", *window)["conflicts"] if c["kind"] == "unreachable"
    )
    assert "Grandpa" in conflict["could_cover"]


# --------------------------------------------------------------------------- names must be real


def test_me_means_whoever_is_speaking(session):
    result = add_rule(
        session, "Dad", "load_balance", {"between": ["me", "Mom"]}, "keep it even between me and Mom"
    )
    assert result["params"]["between"] == ["Dad", "Mom"]
    assert result["readback"] == "I will try to keep pickups even between Dad and Mom."


def test_a_rule_about_someone_who_is_not_in_the_family_is_refused(session):
    """Storing it would look like it worked and then quietly never apply."""
    result = add_rule(
        session, "Dad", "load_balance", {"between": ["me", "Priya"]}, "even between me and Priya"
    )
    assert result["stored"] is False
    assert "I do not know anyone called 'Priya'" in result["problem"]
    assert "Dad, Mom, Aarav, Anaya, Grandpa" in result["problem"]


def test_a_buffer_for_an_unknown_child_is_refused(session):
    result = add_rule(
        session, "Dad", "buffer_after", {"member": "Rohan", "after": "school", "minutes": 20}, "..."
    )
    assert result["stored"] is False
    assert "Rohan" in result["problem"]


def test_a_name_is_matched_whatever_the_casing(session):
    result = add_rule(
        session, "Dad", "buffer_after", {"member": "aarav", "after": "school", "minutes": 20}, "..."
    )
    assert result["params"]["member"] == "Aarav"


def test_balancing_between_the_same_person_twice_is_refused(session):
    result = add_rule(session, "Dad", "load_balance", {"between": ["me", "Dad"]}, "...")
    assert result["stored"] is False
    assert "two different people" in result["problem"]


def test_the_everyday_word_for_a_role_is_understood(session):
    """People say grandparents, not caregiver. The stored role is still one of the three."""
    result = add_rule(
        session,
        "Dad",
        "eligibility",
        {"role": "grandparents", "only_if": "no_parent_free"},
        "grandparents only when we are both busy",
    )
    assert result["params"]["role"] == "caregiver"
    assert result["readback"] == "I will only ask a grandparent or carer to cover when no parent is free."
