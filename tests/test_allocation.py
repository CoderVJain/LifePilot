"""Who should do it, and why. Pure, offline, free."""

from datetime import datetime

from lifepilot.engine.allocation import rank
from lifepilot.engine.reachability import Candidate


def who(person_id, name, *, slack=None, travel=None, reachable=True):
    return Candidate(
        person_id, name, reachable, "", arrival=datetime(2026, 10, 8, 17), slack_minutes=slack,
        travel_minutes=travel,
    )


def test_nobody_reachable_means_no_choice():
    assert rank([who(1, "Dad", reachable=False)]) == []


def test_the_only_candidate_is_named_as_such():
    choice = rank([who(1, "Mom", slack=5, travel=10)])[0]
    assert choice.name == "Mom"
    assert choice.deciding_factor == "only_one"
    assert choice.reason == "Mom is the only one who can get there"


def test_proximity_wins_when_load_is_equal():
    choices = rank([who(1, "Dad", slack=30, travel=40), who(2, "Mom", slack=5, travel=10)])
    assert [c.name for c in choices] == ["Mom", "Dad"]
    assert choices[0].deciding_factor == "travel"
    assert choices[0].reason == "Mom is only 10 minutes away"


def test_a_lighter_load_beats_being_nearer_when_the_family_asked_for_balance():
    """The soft rule is what makes load lead. Without it, proximity would win."""
    candidates = [who(1, "Dad", slack=5, travel=10), who(2, "Mom", slack=5, travel=15)]
    loads = {1: 4, 2: 1}

    balanced = rank(candidates, loads, balance_load=True)
    assert balanced[0].name == "Mom"
    assert balanced[0].deciding_factor == "load"
    assert balanced[0].reason == "Mom has done fewer pickups this week"

    unbalanced = rank(candidates, loads, balance_load=False)
    assert unbalanced[0].name == "Dad"
    assert unbalanced[0].deciding_factor == "travel"


def test_slack_separates_people_who_are_equally_near_and_equally_loaded():
    choices = rank([who(1, "Dad", slack=5, travel=10), who(2, "Mom", slack=25, travel=10)])
    assert choices[0].name == "Mom"
    assert choices[0].deciding_factor == "slack"
    assert choices[0].reason == "Mom has the most room either side"


def test_nothing_on_beforehand_counts_as_the_most_room_not_the_least():
    """slack of None means unconstrained. Treating it as zero would rank the freest person last."""
    choices = rank([who(1, "Dad", slack=45, travel=10), who(2, "Grandpa", slack=None, travel=10)])
    assert choices[0].name == "Grandpa"


def test_an_exact_tie_is_admitted_rather_than_dressed_up():
    choices = rank([who(1, "Dad", slack=10, travel=10), who(2, "Mom", slack=10, travel=10)])
    assert choices[0].deciding_factor == "tie"
    assert "and so could the others" in choices[0].reason


def test_the_order_is_stable_for_identical_candidates():
    candidates = [who(2, "Mom", slack=10, travel=10), who(1, "Dad", slack=10, travel=10)]
    assert [c.name for c in rank(candidates)] == ["Dad", "Mom"]
    assert [c.name for c in rank(list(reversed(candidates)))] == ["Dad", "Mom"]


def test_unreachable_candidates_are_never_ranked():
    choices = rank([who(1, "Dad", reachable=False), who(2, "Mom", slack=5, travel=10)])
    assert [c.name for c in choices] == ["Mom"]


def test_the_reason_always_matches_the_factor_that_actually_decided():
    """The whole point: the explanation is derived from the sort, so it cannot drift from it."""
    choices = rank(
        [who(1, "Dad", slack=5, travel=40), who(2, "Mom", slack=5, travel=10),
         who(5, "Grandpa", slack=60, travel=10)],
        loads={1: 0, 2: 0, 5: 0},
    )
    for choice in choices[:-1]:
        assert choice.deciding_factor in {"load", "travel", "slack", "tie"}
        if choice.deciding_factor == "travel":
            assert str(choice.travel_minutes) in choice.reason
