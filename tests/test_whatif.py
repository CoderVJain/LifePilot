"""Trying a change without making it. Pure, offline, free."""

from datetime import date, datetime

import pytest

from eval.generate import MONDAY, build_demo_family
from lifepilot.db.session import make_engine, make_session_factory
from lifepilot.engine.conflicts import detect
from lifepilot.engine.whatif import UnknownHypothetical, apply_hypothetical, ripple
from lifepilot.tools.detect_conflicts import load_week

FRIDAY = date(2026, 10, 9)


@pytest.fixture
def week():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    factory = make_session_factory(engine, create=True)
    with factory() as session:
        build_demo_family(session)
        return load_week(session, 1, MONDAY, FRIDAY)


def snapshot(week):
    return (
        [(c.id, c.start, c.end, c.title) for c in week.commitments],
        [(n.event_id, n.moment) for n in week.needs],
        dict(week.assigned),
    )


def test_the_original_week_is_untouched(week):
    """The whole promise of a what-if. Everything else here is detail."""
    before = snapshot(week)
    apply_hypothetical(week, {"kind": "runs_late", "title": "performance review", "until": "17:30"})
    apply_hypothetical(week, {"kind": "cancelled", "title": "piano class"})
    apply_hypothetical(
        week,
        {"kind": "new_event", "title": "late meeting", "start": "2026-10-09T18:00",
         "end": "2026-10-09T19:00", "member_ids": [1]},
    )
    assert snapshot(week) == before


def test_a_meeting_running_late_moves_only_its_own_end(week):
    after = apply_hypothetical(
        week, {"kind": "runs_late", "title": "performance review", "until": "17:30"}
    )
    review = next(c for c in after.commitments if c.title == "performance review")
    assert review.end == datetime(2026, 10, 8, 17, 30)
    assert review.start == datetime(2026, 10, 8, 15, 45)
    others = {c.id: (c.start, c.end) for c in after.commitments if c.title != "performance review"}
    assert others == {c.id: (c.start, c.end) for c in week.commitments if c.title != "performance review"}


def test_an_event_running_late_drags_its_own_pickup_with_it(week):
    """If football overruns, the collection is later too. Leaving it put would be a fiction."""
    after = apply_hypothetical(
        week, {"kind": "runs_late", "title": "football practice", "until": "17:45"}
    )
    football = next(n for n in after.needs if "football" in n.title)
    assert football.moment == datetime(2026, 10, 8, 17, 45)


def test_saying_yes_to_a_friday_evening_meeting(week):
    after = apply_hypothetical(
        week,
        {"kind": "new_event", "title": "6pm meeting", "start": "2026-10-09T18:00",
         "end": "2026-10-09T19:00", "member_ids": [1], "location_id": 2},
    )
    assert len(after.commitments) == len(week.commitments) + 1
    added = next(c for c in after.commitments if c.title == "6pm meeting")
    assert added.movable is False, "something being offered to you is not yours to move"


def test_cancelling_something_removes_its_lift_too(week):
    after = apply_hypothetical(week, {"kind": "cancelled", "title": "football practice"})
    assert not [c for c in after.commitments if c.title == "football practice"]
    assert not [n for n in after.needs if "football" in n.title]
    assert all("football" not in str(k) for k in after.assigned)


def test_cancelling_the_thursday_football_removes_the_conflict(week):
    before = detect(week)
    after = detect(apply_hypothetical(week, {"kind": "cancelled", "title": "football practice"}))
    change = ripple(before, after)
    assert change.breaks == ()
    assert any(c.kind == "unreachable" for c in change.resolves)


def test_a_ripple_names_only_what_is_new(week):
    before = detect(week)
    after = detect(
        apply_hypothetical(
            week,
            {"kind": "new_event", "title": "late client call", "start": "2026-10-08T16:30",
             "end": "2026-10-08T17:30", "member_ids": [2], "location_id": 3},
        )
    )
    change = ripple(before, after)
    assert change.is_safe is False
    assert change.breaks, "Mom is now busy through the pickup she was going to cover"
    # The rule clash was already there and must not be reported as newly caused.
    assert any(c.kind == "rule_clash" for c in change.unchanged)


def test_a_harmless_change_is_reported_as_safe(week):
    before = detect(week)
    after = detect(
        apply_hypothetical(
            week,
            {"kind": "new_event", "title": "quiet coffee", "start": "2026-10-06T11:00",
             "end": "2026-10-06T11:30", "member_ids": [], "location_id": 1},
        )
    )
    assert ripple(before, after).is_safe is True


@pytest.mark.parametrize(
    "change",
    [
        {"kind": "teleport", "title": "piano class"},
        {"kind": "runs_late", "title": "nothing called this", "until": "18:00"},
        {"kind": "runs_late", "title": "piano class", "until": "half five"},
        {"kind": "runs_late", "title": "piano class", "until": "15:00"},
        {"kind": "runs_late", "until": "18:00"},
        {"kind": "new_event", "title": "x", "start": "2026-10-09T19:00", "end": "2026-10-09T18:00"},
    ],
)
def test_a_question_it_cannot_answer_is_refused_not_guessed(week, change):
    with pytest.raises(UnknownHypothetical):
        apply_hypothetical(week, change)


def test_an_unfindable_event_lists_what_that_week_actually_has(week):
    with pytest.raises(UnknownHypothetical) as raised:
        apply_hypothetical(week, {"kind": "cancelled", "title": "swimming"})
    assert "football practice" in str(raised.value)


def test_a_meeting_with_no_stated_end_is_taken_as_an_hour(week):
    """Nobody says "a six o'clock, finishing at seven". Refusing over it would be pedantry."""
    after = apply_hypothetical(
        week, {"kind": "new_event", "title": "6pm meeting", "start": "2026-10-09T18:00"}
    )
    added = next(c for c in after.commitments if c.title == "6pm meeting")
    assert added.end == datetime(2026, 10, 9, 19, 0)


def test_an_event_can_be_identified_by_when_it_starts(week):
    """"My four o'clock" names a time, not a title."""
    after = apply_hypothetical(
        week, {"kind": "runs_late", "at": "2026-10-08T15:45", "until": "17:30"}
    )
    review = next(c for c in after.commitments if c.title == "performance review")
    assert review.end == datetime(2026, 10, 8, 17, 30)


def test_whoever_is_asking_gets_their_own_event_when_a_time_is_ambiguous(week):
    """Mom and Dad both start work in the morning; "my nine o'clock" must mean the asker's."""
    dad = apply_hypothetical(
        week, {"kind": "runs_late", "at": "2026-10-05T09:30", "until": "18:00", "for_member": [1]}
    )
    changed = [c for c in dad.commitments if c.end == datetime(2026, 10, 5, 18, 0)]
    assert changed and 1 in changed[0].member_ids


def test_a_rounded_time_finds_the_askers_own_commitment(week):
    """The demo's own #5 line, and it failed two ways at once. Thursday 16:00 holds Aarav's football
    and Anaya's piano; Dad's review starts 15:45. Matching the start to the minute could never find
    the review, and falling back to whoever else had a 16:00 answered about a child's diary -- which
    is what the browser run caught. "My 4 PM" is how a 15:45 review is spoken."""
    after = apply_hypothetical(
        week,
        {"kind": "runs_late", "at": "2026-10-08T16:00", "until": "17:30", "for_member": [1]},
    )
    review = next(c for c in after.commitments if c.title == "performance review")
    assert review.end == datetime(2026, 10, 8, 17, 30)
    football = next(c for c in after.commitments if c.title == "football practice")
    piano = next(c for c in after.commitments if c.title == "piano class")
    assert football.end == datetime(2026, 10, 8, 17, 0), "a child's event is not the asker's"
    assert piano.end == datetime(2026, 10, 8, 16, 45)


def test_a_bare_time_never_reaches_somebody_elses_event(week):
    """Tuesday 17:00 is Aarav's cricket and Dad has nothing near it. Answering about the cricket
    would be a confident answer to a question nobody asked; saying so is the honest reply."""
    with pytest.raises(UnknownHypothetical) as refused:
        apply_hypothetical(
            week,
            {"kind": "runs_late", "at": "2026-10-06T17:00", "until": "18:30", "for_member": [1]},
        )
    assert "nothing" in str(refused.value).lower()


def test_a_named_title_still_reaches_another_persons_event(week):
    """The restriction is on a bare time. "What if football is cancelled" is about Aarav's football,
    asked by a parent, and must keep working."""
    after = apply_hypothetical(
        week, {"kind": "cancelled", "title": "football practice", "for_member": [1]}
    )
    assert not [c for c in after.commitments if c.title == "football practice"]


def test_a_title_decides_when_the_asker_has_nothing_at_that_time(week):
    """Both were given: the time finds nothing of theirs, so the title decides rather than refusing."""
    after = apply_hypothetical(
        week,
        {"kind": "runs_late", "at": "2026-10-06T17:00", "title": "performance review",
         "until": "17:30", "for_member": [1]},
    )
    review = next(c for c in after.commitments if c.title == "performance review")
    assert review.end == datetime(2026, 10, 8, 17, 30)


def test_a_problem_that_gets_worse_is_not_reported_as_unchanged(week):
    """Found by re-testing #5 in the browser. Dad's football pickup was already unreachable -- he
    arrived 17:25 for a 17:00 collection. Letting his review run to 17:30 means he cannot go at all,
    yet the conflict keyed the same before and after, so it landed in `unchanged` and the spoken
    answer was "That works. Nothing new breaks." A problem the change made worse is not unchanged."""
    before = detect(week)
    after = detect(
        apply_hypothetical(
            week,
            {"kind": "runs_late", "at": "2026-10-08T16:00", "until": "17:30", "for_member": [1]},
        )
    )
    effect = ripple(before, after)
    assert effect.worsens, "the pickup got worse and must be said out loud"
    assert "performance review" in effect.worsens[0].detail
    assert not effect.unchanged or all(
        c.title != effect.worsens[0].title for c in effect.unchanged
    ), "it cannot be in both buckets"


def test_a_worsened_problem_is_not_called_safe(week):
    """`is_safe` drives the spoken sentence, so it has to mean "nothing got worse", not "no new
    key appeared"."""
    before = detect(week)
    after = detect(
        apply_hypothetical(
            week,
            {"kind": "runs_late", "at": "2026-10-08T16:00", "until": "17:30", "for_member": [1]},
        )
    )
    assert not ripple(before, after).is_safe


def test_an_untouched_problem_still_counts_as_unchanged(week):
    """The other side of it: a hypothetical somewhere else must not relabel every standing problem
    as worse, or the word stops meaning anything."""
    before = detect(week)
    after = detect(
        apply_hypothetical(week, {"kind": "runs_late", "at": "2026-10-05T09:30", "until": "16:45",
                                  "for_member": [1]})
    )
    effect = ripple(before, after)
    assert effect.unchanged, "Thursday's problems are untouched by a Monday change"
    assert not effect.worsens
