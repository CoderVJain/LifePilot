"""detect_conflicts against the real seeded family. Offline, free, on in-memory SQLite.

This is differentiator #1 proven on the actual demo data rather than a hand-built fixture.
"""

from datetime import date

import pytest

from eval.generate import MONDAY, build_demo_family
from lifepilot.db.session import make_engine, make_session_factory
from lifepilot.tools.detect_conflicts import detect_conflicts, load_week

FRIDAY = date(2026, 10, 9)


@pytest.fixture
def session():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    factory = make_session_factory(engine, create=True)
    with factory() as s:
        build_demo_family(s)
        yield s


def test_the_week_loads_into_plain_values(session):
    week = load_week(session, 1, MONDAY, FRIDAY)
    assert len(week.people) == 5
    assert len(week.commitments) == 19
    # Piano and football both need someone to collect a child.
    assert {n.title for n in week.needs} == {"piano class pickup", "football practice pickup"}
    assert week.travel[(2, 4)] == 40 or len(week.travel) == 49


def test_dad_is_told_the_thursday_pickup_cannot_be_made(session):
    result = detect_conflicts(session, "Dad", MONDAY, FRIDAY)
    unreachable = [c for c in result["conflicts"] if c["kind"] == "unreachable"]

    assert len(unreachable) == 1
    conflict = unreachable[0]
    assert conflict["title"] == "football practice pickup"
    assert conflict["when"] == "2026-10-08T17:00"
    assert conflict["assigned_to"] == "Dad"
    assert "arrives 17:25, needs 17:00" in conflict["detail"]
    assert conflict["could_cover"] == ["Mom"]


def test_no_two_events_overlap_so_a_calendar_check_would_find_nothing(session):
    """The headline: the overlap baseline reports zero, LifePilot reports a real problem."""
    result = detect_conflicts(session, "Dad", MONDAY, FRIDAY)
    assert [c for c in result["conflicts"] if c["kind"] == "overlap"] == []
    assert [c for c in result["conflicts"] if c["kind"] != "overlap"] != []


def test_why_not_grandpa_is_answerable_from_the_stored_reasons(session):
    result = detect_conflicts(session, "Dad", MONDAY, FRIDAY)
    conflict = next(c for c in result["conflicts"] if c["kind"] == "unreachable")
    reasons = {c["name"]: c["reason"] for c in conflict["candidates"]}
    assert reasons["Grandpa"] == "rule: only when no parent is free"
    assert reasons["Aarav"] == "cannot drive"


def test_the_late_project_block_breaks_the_homework_rule(session):
    result = detect_conflicts(session, "Dad", MONDAY, FRIDAY)
    clashes = [c for c in result["conflicts"] if c["kind"] == "rule_clash"]
    assert any("past your rule of 21:00" in c["detail"] for c in clashes)


def test_a_child_only_sees_problems_that_involve_them(session):
    as_dad = detect_conflicts(session, "Dad", MONDAY, FRIDAY)
    as_anaya = detect_conflicts(session, "Anaya", MONDAY, FRIDAY)

    dad_titles = {c["title"] for c in as_dad["conflicts"]}
    anaya_titles = {c["title"] for c in as_anaya["conflicts"]}

    assert "football practice pickup" in dad_titles
    assert "football practice pickup" not in anaya_titles
    assert anaya_titles <= dad_titles


def test_the_result_says_what_was_checked(session):
    result = detect_conflicts(session, "Dad", MONDAY, FRIDAY)
    assert result["checked"] == {"events": 19, "lifts_needed": 2, "rules": 5}


# --------------------------------------------------------------------------- "my" schedule


def test_my_schedule_is_mine_not_the_whole_familys(session):
    """Asking "what's my schedule tomorrow" and being told all nineteen family events is not an
    answer to the question that was asked."""
    from lifepilot.tools.context import get_schedule

    everything = get_schedule(session, "Dad", MONDAY, FRIDAY)
    just_dad = get_schedule(session, "Dad", MONDAY, FRIDAY, about="Dad")

    assert len(everything["events"]) == 19
    assert len(just_dad["events"]) < len(everything["events"])
    assert just_dad["about"] == "Dad"

    titles = {e["title"] for e in just_dad["events"]}
    assert "performance review" in titles, "Dad's own review"
    assert "piano class" not in titles, "Anaya's piano is not Dad's day"
    assert "Busy" not in titles, "nothing redacted survives a question about yourself"


def test_driving_someone_counts_as_your_afternoon(session):
    """Dad is down for the football pickup. He is not a member of the event, but it is his."""
    from lifepilot.tools.context import get_schedule

    just_dad = get_schedule(session, "Dad", MONDAY, FRIDAY, about="Dad")
    assert "football practice" in {e["title"] for e in just_dad["events"]}


def test_a_childs_own_day_excludes_the_parents(session):
    from lifepilot.tools.context import get_schedule

    just_aarav = get_schedule(session, "Aarav", MONDAY, FRIDAY, about="Aarav")
    titles = {e["title"] for e in just_aarav["events"]}

    assert "school" in titles
    assert "football practice" in titles
    assert "work" not in titles
    assert "Busy" not in titles


def test_asking_about_someone_else_answers_about_them(session):
    """The report that prompted this: asked for Aarav's school timing, the answer was Dad's day."""
    from lifepilot.tools.context import get_schedule

    aarav = get_schedule(session, "Dad", MONDAY, FRIDAY, about="Aarav")
    titles = {e["title"] for e in aarav["events"]}

    assert aarav["about"] == "Aarav"
    assert "school" in titles
    assert "football practice" in titles
    assert "performance review" not in titles, "that is Dad's, and Dad is not who was asked about"
    assert "piano class" not in titles, "that is Anaya's"


def test_asking_about_someone_else_still_obeys_what_you_may_see(session):
    """Narrowing happens after the visibility rules, never instead of them."""
    from lifepilot.tools.context import get_schedule

    as_aarav = get_schedule(session, "Aarav", MONDAY, FRIDAY, about="Dad")
    titles = {e["title"] for e in as_aarav["events"]}

    assert "work" not in titles
    assert "performance review" not in titles
    assert "Busy" in titles, "Dad's work shows as Busy, with no detail"
    # Dad drives Aarav to football, so it is in Dad's day -- and Aarav may see his own practice.
    assert titles <= {"Busy", "football practice"}


def test_a_name_nobody_has_is_not_silently_treated_as_everyone(session):
    from lifepilot.tools.context import get_schedule

    unknown = get_schedule(session, "Dad", MONDAY, FRIDAY, about="Priya")
    assert unknown["about"] is None


def test_tasks_are_filtered_to_their_owner_too(session):
    from lifepilot.tools.context import get_schedule

    dad = get_schedule(session, "Dad", MONDAY, FRIDAY, about="Dad")
    aarav = get_schedule(session, "Aarav", MONDAY, FRIDAY, about="Aarav")

    assert dad["tasks"] == []
    assert {t["title"] for t in aarav["tasks"]} == {"science project model"}


# --------------------------------------------------------------------------- one moment


def at_time(session, moment: str):
    from datetime import date

    from lifepilot.tools.context import get_schedule

    thursday = date(2026, 10, 8)
    return get_schedule(session, "Dad", thursday, thursday, about="Dad", at=moment)


def test_asking_about_a_moment_answers_about_that_moment(session):
    """"Do I have anything at five" answered with the whole day leaves the asker to work it out."""
    result = at_time(session, "16:30")
    then = result["at_that_time"]

    assert result["at"] == "2026-10-08T16:30"
    assert then["free"] is False
    assert {e["title"] for e in then["running"]} == {"performance review", "football practice"}


def test_a_free_moment_is_reported_free(session):
    then = at_time(session, "19:00")["at_that_time"]
    assert then["free"] is True
    assert then["running"] == []


def test_something_finishing_exactly_then_does_not_make_you_busy_but_is_still_said(session):
    """Football ends at 5. Five o'clock is free, and the reason it is not really free is that
    somebody has to be at the ground to collect him."""
    then = at_time(session, "17:00")["at_that_time"]

    assert then["free"] is True
    assert then["running"] == []
    finishing = {e["title"] for e in then["finishing"]}
    assert "football practice" in finishing
    assert any(e["needs_transport"] for e in then["finishing"])


def test_something_starting_exactly_then_does_make_you_busy(session):
    then = at_time(session, "16:00")["at_that_time"]
    assert then["free"] is False
    assert "football practice" in {e["title"] for e in then["starting"]}


def test_a_whole_day_question_still_gets_the_whole_day(session):
    from datetime import date

    from lifepilot.tools.context import get_schedule

    thursday = date(2026, 10, 8)
    whole = get_schedule(session, "Dad", thursday, thursday, about="Dad")
    assert whole["at"] is None
    assert whole["at_that_time"] is None
    assert len(whole["events"]) == 3
