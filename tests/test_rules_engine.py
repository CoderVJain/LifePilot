"""The five rule types, and the refusal to invent a sixth. Pure, offline, free."""

import pytest

from lifepilot.engine.rules import (
    RULE_TYPES,
    InvalidRule,
    UnsupportedRule,
    is_hard,
    readback,
    validate,
)


def test_an_unknown_type_is_refused_and_says_what_is_supported():
    """A rule bent into the nearest shape is worse than one never stored."""
    with pytest.raises(UnsupportedRule) as raised:
        validate("no_screens_at_dinner", {"limit": "19:00"})
    message = str(raised.value)
    assert "not a rule LifePilot can enforce" in message
    for name in RULE_TYPES:
        assert name in message


@pytest.mark.parametrize(
    ("rule_type", "params", "expected"),
    [
        ("immovable_event", {"title": " piano class "}, {"title": "piano class"}),
        (
            "latest_end",
            {"category": "study", "latest_end": "21:00"},
            {"category": "study", "latest_end": "21:00"},
        ),
        (
            "buffer_after",
            {"member": "Aarav", "after": "school", "minutes": 30},
            {"member": "Aarav", "after": "school", "minutes": 30},
        ),
        (
            "eligibility",
            {"role": "caregiver", "only_if": "no_parent_free"},
            {"role": "caregiver", "only_if": "no_parent_free"},
        ),
        ("load_balance", {"between": ["Dad", "Mom"]}, {"between": ["Dad", "Mom"]}),
    ],
)
def test_each_supported_type_validates_and_normalises(rule_type, params, expected):
    assert validate(rule_type, params) == expected


def test_only_load_balancing_is_a_preference():
    assert is_hard("load_balance") is False
    for rule_type in RULE_TYPES:
        if rule_type != "load_balance":
            assert is_hard(rule_type) is True


@pytest.mark.parametrize("clock", ["9pm", "25:00", "21:60", "", "21", "half nine"])
def test_a_time_that_is_not_a_time_is_rejected(clock):
    with pytest.raises(InvalidRule):
        validate("latest_end", {"category": "study", "latest_end": clock})


@pytest.mark.parametrize("minutes", [0, -10, "thirty", None, True, 900])
def test_a_buffer_needs_a_sensible_number_of_minutes(minutes):
    with pytest.raises(InvalidRule):
        validate("buffer_after", {"member": "Aarav", "after": "school", "minutes": minutes})


def test_a_role_that_is_not_a_family_role_is_rejected():
    with pytest.raises(InvalidRule) as raised:
        validate("eligibility", {"role": "neighbour", "only_if": "no_parent_free"})
    assert "not a role in this family" in str(raised.value)


def test_an_eligibility_condition_we_cannot_enforce_is_refused_not_approximated():
    with pytest.raises(UnsupportedRule):
        validate("eligibility", {"role": "caregiver", "only_if": "only_on_weekends"})


def test_balancing_needs_at_least_two_people():
    with pytest.raises(InvalidRule):
        validate("load_balance", {"between": ["Dad"]})
    with pytest.raises(InvalidRule):
        validate("load_balance", {"between": ["Dad", "  "]})


def test_a_missing_detail_says_what_is_missing():
    with pytest.raises(InvalidRule) as raised:
        validate("buffer_after", {"after": "school", "minutes": 30})
    assert "who the rest is for" in str(raised.value)


@pytest.mark.parametrize(
    ("rule_type", "params", "sentence"),
    [
        ("immovable_event", {"title": "piano class"}, "I will never move piano class."),
        ("latest_end", {"category": "study", "latest_end": "21:00"}, "No study after 21:00."),
        (
            "buffer_after",
            {"member": "Aarav", "after": "school", "minutes": 30},
            "Aarav gets 30 minutes after school before anything else.",
        ),
        (
            "eligibility",
            {"role": "caregiver", "only_if": "no_parent_free"},
            "I will only ask a grandparent or carer to cover when no parent is free.",
        ),
        (
            "load_balance",
            {"between": ["Dad", "Mom"]},
            "I will try to keep pickups even between Dad and Mom.",
        ),
    ],
)
def test_every_rule_reads_back_as_a_sentence_a_parent_can_confirm(rule_type, params, sentence):
    assert readback(rule_type, params) == sentence


def test_latest_end_without_a_category_still_reads_naturally():
    assert readback("latest_end", {"latest_end": "21:00"}) == "Nothing after 21:00."


def test_an_everyday_word_for_a_category_maps_to_the_one_events_use():
    """"No homework after nine" must become the category events actually carry, or it matches none."""
    assert validate("latest_end", {"category": "homework", "latest_end": "21:00"}) == {
        "category": "study",
        "latest_end": "21:00",
    }
    assert validate("latest_end", {"category": "clubs", "latest_end": "19:30"})["category"] == "activity"


def test_a_category_we_do_not_track_is_refused_rather_than_stored_and_ignored():
    with pytest.raises(InvalidRule) as raised:
        validate("latest_end", {"category": "screen time", "latest_end": "19:00"})
    assert "do not track anything called 'screen time'" in str(raised.value)
