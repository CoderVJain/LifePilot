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
    assert len(week.commitments) == 20
    # Piano, football, Tuesday cricket, and the school run every weekday: the errands a family
    # actually negotiates.
    assert {n.title for n in week.needs} == {
        "piano class pickup", "football practice pickup", "cricket practice pickup", "school pickup",
    }
    assert len(week.needs) == 8, "five school collections plus piano, football and cricket"
    assert week.travel[(2, 4)] == 40 or len(week.travel) == 64


def test_dad_is_told_the_thursday_pickup_cannot_be_made(session):
    result = detect_conflicts(session, "Dad", MONDAY, FRIDAY)
    unreachable = [c for c in result["conflicts"] if c["kind"] == "unreachable"]

    assert len(unreachable) == 1
    conflict = unreachable[0]
    assert conflict["title"] == "football practice pickup"
    assert conflict["when"] == "2026-10-08T17:00"
    assert conflict["assigned_to"] == "Dad"
    assert "arrives 5:25 PM, needs 5 PM" in conflict["detail"]
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
    assert any("past your rule of 9 PM" in c["detail"] for c in clashes)


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
    assert result["checked"] == {"events": 20, "lifts_needed": 8, "rules": 5}


# --------------------------------------------------------------------------- "my" schedule


def test_my_schedule_is_mine_not_the_whole_familys(session):
    """Asking "what's my schedule tomorrow" and being told all nineteen family events is not an
    answer to the question that was asked."""
    from lifepilot.tools.context import get_schedule

    everything = get_schedule(session, "Dad", MONDAY, FRIDAY)
    just_dad = get_schedule(session, "Dad", MONDAY, FRIDAY, about="Dad")

    assert len(everything["events"]) == 20
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
    # Dad drives Aarav to football and collects both children from school on Tuesdays, so both are in
    # Dad's day -- and Aarav may see his own practice and his own school.
    assert titles <= {"Busy", "football practice", "school"}


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


# --------------------------------------------------------------------------- one named thing


def test_asking_about_a_named_event_answers_about_that_event(session):
    """Reported: "what is the piano class timing and day" was answered with "Mom can see 19 things
    Monday to Friday" and the timing was buried in the recital that followed."""
    from lifepilot.tools.context import get_schedule

    piano = get_schedule(session, "Mom", MONDAY, FRIDAY, title="piano")

    assert piano["title"] == "piano"
    assert {e["title"] for e in piano["events"]} == {"piano class"}
    assert piano["events"][0]["members"] == ["Anaya"]


def test_a_named_event_reads_the_same_whoever_asks(session):
    """Aarav asking about football got a different shape from Dad asking. Same question, same answer."""
    from lifepilot.tools.context import get_schedule

    as_aarav = get_schedule(session, "Aarav", MONDAY, FRIDAY, title="football")
    as_dad = get_schedule(session, "Dad", MONDAY, FRIDAY, title="football")

    assert [e["title"] for e in as_aarav["events"]] == [e["title"] for e in as_dad["events"]]
    assert [e["start"] for e in as_aarav["events"]] == [e["start"] for e in as_dad["events"]]


def test_narrowing_by_name_never_widens_what_you_may_see(session):
    """A child must not reach a parent's meeting by naming it. Redacted events read as "Busy", so
    matching on the real title would leak which meeting it was."""
    from lifepilot.tools.context import get_schedule

    assert get_schedule(session, "Aarav", MONDAY, FRIDAY, title="performance review")["events"] == []
    assert get_schedule(session, "Aarav", MONDAY, FRIDAY, title="Busy")["events"] == []
    assert get_schedule(session, "Dad", MONDAY, FRIDAY, title="performance review")["events"] != []


def test_an_unknown_name_is_not_silently_the_whole_week(session):
    from lifepilot.tools.context import get_schedule

    none = get_schedule(session, "Dad", MONDAY, FRIDAY, title="chess club")
    assert none["events"] == []
    assert none["title"] == "chess club"


# --------------------------------------------------------------------------- your part in it


def test_an_event_you_only_drive_is_marked_as_driving(session):
    """Dad is down for the football pickup. He is not at football for an hour; he is at the gate at
    five, and the view has to say which so the sentence can."""
    from lifepilot.tools.context import get_schedule

    dad = get_schedule(session, "Dad", MONDAY, FRIDAY, about="Dad")
    football = next(e for e in dad["events"] if e["title"] == "football practice")

    assert football["driving"] is True
    assert football["lift"] == "pickup"


def test_your_own_events_are_not_marked_as_driving(session):
    from lifepilot.tools.context import get_schedule

    dad = get_schedule(session, "Dad", MONDAY, FRIDAY, about="Dad")
    work = next(e for e in dad["events"] if e["title"] == "work")

    assert work["driving"] is False
    assert work["lift"] is None


def test_somebody_elses_lift_is_not_marked_as_yours(session):
    """Mom collects Anaya from piano. Dad sees the event, but it is not his errand."""
    from lifepilot.tools.context import get_schedule

    dad = get_schedule(session, "Dad", MONDAY, FRIDAY)
    piano = next(e for e in dad["events"] if e["title"] == "piano class")

    assert piano["driving"] is False


# --------------------------------------------------------------------------- the school run


def test_the_children_are_actually_collected_from_school(session):
    """Without this the demo family had two school-age children getting themselves home, and the week
    held two lifts in total. The school run is the errand working parents negotiate."""
    from lifepilot.tools.detect_conflicts import load_week

    week = load_week(session, 1, MONDAY, FRIDAY)
    school = [n for n in week.needs if n.title == "school pickup"]

    assert len(school) == 5, "every weekday"
    assert all(n.moment.hour == 15 for n in school), "school finishes at three"


def test_every_school_collection_is_reachable(session):
    """A collecting parent's day ends early enough to cross town: 22 minutes from Mom's office, 38
    from Dad's. Five impossible pickups would bury the one that is meant to be interesting."""
    result = detect_conflicts(session, "Dad", MONDAY, FRIDAY)
    broken = [c for c in result["conflicts"] if "school" in c["title"]]

    assert broken == []


def test_the_thursday_pickup_is_still_the_only_impossible_one(session):
    """The headline survives the richer week: one unreachable lift, and no overlap anywhere, so a
    calendar check still reports nothing."""
    result = detect_conflicts(session, "Dad", MONDAY, FRIDAY)

    unreachable = [c for c in result["conflicts"] if c["kind"] == "unreachable"]
    assert len(unreachable) == 1
    assert unreachable[0]["title"] == "football practice pickup"
    assert [c for c in result["conflicts"] if c["kind"] == "overlap"] == []


def test_the_school_run_is_split_between_both_parents(session):
    """Uneven on purpose, so the soft load_balance rule has something real to object to."""
    import sqlalchemy as sa

    from lifepilot.db.models import Assignment, Event, Member

    names = {m.id: m.name for m in session.scalars(sa.select(Member))}
    school_ids = {e.id for e in session.scalars(sa.select(Event).where(Event.title == "school"))}
    collectors = [
        names[a.member_id]
        for a in session.scalars(sa.select(Assignment))
        if a.event_id in school_ids
    ]

    assert len(collectors) == 5
    assert set(collectors) == {"Mom", "Dad"}, "both parents, not one"
