"""The synthetic demo family. Handcrafted and deterministic: the same call builds identical rows.

The week is Mon 2026-10-05 to Fri 2026-10-09. Thursday carries the signature scenario:

    Aarav's football pickup is at 17:00 at the ground.
    Dad is currently assigned. His performance review ends 16:45 at the office, 40 minutes away,
    so he arrives 17:25 -- too late.
    Mom finishes Anaya's piano at 16:45, 10 minutes away, so she arrives 16:55 -- in time.
    Grandpa is free, but the eligibility rule keeps him out while a parent is free.

No two events overlap. An overlap-only conflict check sees nothing wrong; that gap is the headline
number for differentiator #1.

Thursday also carries a rule clash: Aarav's project block runs 20:00-21:30, past the 21:00 study
deadline. Repairing both is the two-change diff of the demo.

Tuesday carries Mom's 6 PM cricket collection, which exists so a Dad/Mom swap can succeed: it is the
only lift of hers Dad can reach from the office.

The weekend running into the week is seeded too, so the day the demo is given on is never empty.
It is deliberately easy: no work, no school, and its one lift is reachable from home.
"""

import argparse
from datetime import date, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session

from lifepilot.db.models import (
    Assignment,
    Base,
    Event,
    Family,
    Location,
    Member,
    Rule,
    Task,
    TravelTime,
)
from lifepilot.db.session import make_engine, make_session_factory
from lifepilot_shared.week import demo_week

# The demo week follows the real calendar, so "tomorrow" is a day with something in it. Tests and
# the recorded demo pin it with LIFEPILOT_WEEK=fixed; see lifepilot_shared.week.
MONDAY, FRIDAY = demo_week()
TUESDAY = MONDAY + timedelta(days=1)
THURSDAY = MONDAY + timedelta(days=3)
# The weekend running into the week. demo_week rolls forward over a weekend, so asked on a Saturday
# the working week starts two days later and today holds nothing at all. See `demo_span`.
SATURDAY = MONDAY - timedelta(days=2)
SUNDAY = MONDAY - timedelta(days=1)

LOCATIONS = (
    "home",
    "dad office",
    "mom office",
    "school",
    "football ground",
    "piano school",
    "grandpa home",
    "cricket nets",
)

# One entry per unordered pair; the table is filled symmetrically. Minutes, door to door.
TRAVEL_MINUTES = {
    ("home", "dad office"): 35,
    ("home", "mom office"): 20,
    ("home", "school"): 12,
    ("home", "football ground"): 15,
    ("home", "piano school"): 10,
    ("home", "grandpa home"): 8,
    ("dad office", "mom office"): 25,
    ("dad office", "school"): 38,
    ("dad office", "football ground"): 40,
    ("dad office", "piano school"): 35,
    ("dad office", "grandpa home"): 40,
    ("mom office", "school"): 22,
    ("mom office", "football ground"): 25,
    ("mom office", "piano school"): 15,
    ("mom office", "grandpa home"): 25,
    ("school", "football ground"): 10,
    ("school", "piano school"): 14,
    ("school", "grandpa home"): 15,
    ("football ground", "piano school"): 10,
    ("football ground", "grandpa home"): 18,
    ("piano school", "grandpa home"): 12,
    ("home", "cricket nets"): 10,
    ("dad office", "cricket nets"): 30,
    ("mom office", "cricket nets"): 18,
    ("school", "cricket nets"): 12,
    ("football ground", "cricket nets"): 14,
    ("piano school", "cricket nets"): 12,
    ("grandpa home", "cricket nets"): 14,
}


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute)


def _weekdays() -> list[date]:
    return [MONDAY + timedelta(days=i) for i in range(5)]


def _add_locations(session: Session, family: Family) -> dict[str, int]:
    rows = [Location(family_id=family.id, name=name) for name in LOCATIONS]
    session.add_all(rows)
    session.flush()
    ids = {row.name: row.id for row in rows}

    for (a, b), minutes in TRAVEL_MINUTES.items():
        session.add(TravelTime(from_location_id=ids[a], to_location_id=ids[b], minutes=minutes))
        session.add(TravelTime(from_location_id=ids[b], to_location_id=ids[a], minutes=minutes))
    for loc_id in ids.values():
        session.add(TravelTime(from_location_id=loc_id, to_location_id=loc_id, minutes=0))
    session.flush()
    return ids


def _add_members(session: Session, family: Family, loc: dict[str, int]) -> dict[str, Member]:
    people = [
        Member(family_id=family.id, name="Dad", role="parent", can_drive=True, home_location_id=loc["home"]),
        Member(family_id=family.id, name="Mom", role="parent", can_drive=True, home_location_id=loc["home"]),
        Member(family_id=family.id, name="Aarav", role="child", home_location_id=loc["home"]),
        Member(family_id=family.id, name="Anaya", role="child", home_location_id=loc["home"]),
        Member(
            family_id=family.id,
            name="Grandpa",
            role="caregiver",
            can_drive=True,
            home_location_id=loc["grandpa home"],
        ),
    ]
    session.add_all(people)
    session.flush()
    return {person.name: person for person in people}


#: Who collects the children from school, by weekday. The school run is the errand working parents
#: actually negotiate, and without it the week has only two lifts in it and the solver has nothing to
#: reason about. Uneven on purpose: it gives the soft load_balance rule something real to object to.
SCHOOL_COLLECTOR = {0: "Mom", 1: "Dad", 2: "Mom", 3: "Mom", 4: "Mom"}

#: School finishes at 3. A parent collecting has to be there, so their working day ends early enough
#: to cross town: 22 minutes from Mom's office, 38 from Dad's.
COLLECTION_DAY_END = {"Mom": (14, 30), "Dad": (14, 15)}


def _add_work_and_school(session: Session, family: Family, loc: dict[str, int], who: dict[str, Member]):
    """Weekday routine, including the school run.

    Thursday is shorter for both parents so the afternoon scenario has no overlap: a calendar check
    must find nothing while the football pickup is still impossible.
    """
    for day in _weekdays():
        collector = SCHOOL_COLLECTOR[day.weekday()]
        dad_end = _working_until(day, "Dad", collector)
        mom_end = _working_until(day, "Mom", collector)

        session.add(Event(
            family_id=family.id, member_ids=[who["Dad"].id], title="work", category="work",
            start=at(day, 9, 30), end=dad_end, location_id=loc["dad office"],
            movable=False, visibility="parents",
        ))
        session.add(Event(
            family_id=family.id, member_ids=[who["Mom"].id], title="work", category="work",
            start=at(day, 9, 0), end=mom_end, location_id=loc["mom office"],
            movable=False, visibility="parents",
        ))
        school = Event(
            family_id=family.id, member_ids=[who["Aarav"].id, who["Anaya"].id], title="school",
            category="school", start=at(day, 8, 0), end=at(day, 15, 0), location_id=loc["school"],
            needs_transport=True, movable=False,
        )
        session.add(school)
        session.flush()
        session.add(Assignment(event_id=school.id, member_id=who[collector].id, kind="pickup"))


def _working_until(day: date, parent: str, collector: str):
    """When this parent's day ends. Early when they are collecting, so the 3 o'clock is reachable."""
    if parent == collector:
        hour, minute = COLLECTION_DAY_END[parent]
        return at(day, hour, minute)
    if day == THURSDAY:
        return at(day, 15, 45)
    return at(day, 16, 30) if parent == "Dad" else at(day, 16, 0)


def _add_thursday_scenario(session: Session, family: Family, loc: dict[str, int], who: dict[str, Member]):
    review = Event(
        family_id=family.id, member_ids=[who["Dad"].id], title="performance review", category="work",
        start=at(THURSDAY, 15, 45), end=at(THURSDAY, 16, 45), location_id=loc["dad office"],
        movable=False, visibility="parents",
    )
    piano = Event(
        family_id=family.id, member_ids=[who["Anaya"].id], title="piano class", category="activity",
        start=at(THURSDAY, 16, 0), end=at(THURSDAY, 16, 45), location_id=loc["piano school"],
        needs_transport=True, movable=False,
    )
    football = Event(
        family_id=family.id, member_ids=[who["Aarav"].id], title="football practice", category="activity",
        start=at(THURSDAY, 16, 0), end=at(THURSDAY, 17, 0), location_id=loc["football ground"],
        needs_transport=True, movable=True,
    )
    project = Event(
        family_id=family.id, member_ids=[who["Aarav"].id], title="science project block",
        category="study", start=at(THURSDAY, 20, 0), end=at(THURSDAY, 21, 30),
        location_id=loc["home"], movable=True,
    )
    session.add_all([review, piano, football, project])
    session.flush()

    # Mom already covers piano. Dad is assigned football, and cannot reach it: that is the conflict.
    session.add(Assignment(event_id=piano.id, member_id=who["Mom"].id, kind="pickup"))
    session.add(Assignment(event_id=football.id, member_id=who["Dad"].id, kind="pickup"))

    session.add(Task(
        family_id=family.id, owner_id=who["Aarav"].id, title="science project model",
        category="study", due=at(MONDAY + timedelta(days=4), 8, 0), est_minutes=180, prep_days=3,
    ))


def _add_tuesday_cricket(session: Session, family: Family, loc: dict[str, int], who: dict[str, Member]):
    """Mom's one late-afternoon lift, and the only one Dad can take off her.

    Without it the week admits no feasible Dad/Mom swap at all: every other lift Mom holds is the
    3 o'clock school run or 4:45 piano, and Dad is at the office until 4:30 on the days he is not
    collecting, so he can never reach the leg he takes back. Tuesday is the one weekday Mom does not
    collect from school, which keeps this her only lift that day -- a day holding two of her lifts
    would make the swap ambiguous and `request_swap` would rightly ask which one.
    """
    cricket = Event(
        family_id=family.id, member_ids=[who["Aarav"].id], title="cricket practice", category="activity",
        start=at(TUESDAY, 17, 0), end=at(TUESDAY, 18, 0), location_id=loc["cricket nets"],
        needs_transport=True, movable=True,
    )
    session.add(cricket)
    session.flush()
    session.add(Assignment(event_id=cricket.id, member_id=who["Mom"].id, kind="pickup"))


def _add_weekend(session: Session, family: Family, loc: dict[str, int], who: dict[str, Member]):
    """Saturday and Sunday, so the day the demo is given on is never an empty day.

    Deliberately easy: nobody works and nobody is at school, so the one lift is reachable from home
    by either parent and the week's only unreachable lift stays Thursday's. A weekend that broke
    would move the headline off the scenario the demo is built on.
    """
    match = Event(
        family_id=family.id, member_ids=[who["Aarav"].id], title="football match", category="activity",
        start=at(SATURDAY, 10, 0), end=at(SATURDAY, 12, 0), location_id=loc["football ground"],
        needs_transport=True, movable=False,
    )
    lunch = Event(
        family_id=family.id,
        member_ids=[who[name].id for name in ("Dad", "Mom", "Aarav", "Anaya", "Grandpa")],
        title="lunch at grandpa's", category="other", start=at(SUNDAY, 13, 0), end=at(SUNDAY, 15, 0),
        location_id=loc["grandpa home"], movable=False,
    )
    # Feeds the science project task due Friday morning, so "what am I forgetting" has a weekend
    # answer as well as a weekday one.
    study = Event(
        family_id=family.id, member_ids=[who["Aarav"].id], title="science project work",
        category="study", start=at(SUNDAY, 16, 0), end=at(SUNDAY, 18, 0), location_id=loc["home"],
        movable=True,
    )
    session.add_all([match, lunch, study])
    session.flush()
    session.add(Assignment(event_id=match.id, member_id=who["Dad"].id, kind="pickup"))


def _add_rules(session: Session, family: Family, who: dict[str, Member]):
    parent = who["Mom"].id
    rules = [
        Rule(family_id=family.id, type="immovable_event", params={"title": "piano class"},
             spoken_text="Anaya's piano class cannot be moved.", confirmed_by=parent),
        Rule(family_id=family.id, type="latest_end", params={"category": "study", "latest_end": "21:00"},
             spoken_text="No homework after 9 PM.", confirmed_by=parent),
        Rule(family_id=family.id, type="buffer_after",
             params={"member": "Aarav", "after": "school", "minutes": 30},
             spoken_text="Aarav needs 30 minutes rest after school.", confirmed_by=parent),
        Rule(family_id=family.id, type="eligibility",
             params={"role": "caregiver", "only_if": "no_parent_free"},
             spoken_text="Grandparents only when both of us are busy.", confirmed_by=parent),
        Rule(family_id=family.id, type="load_balance", hard=False, params={"between": ["Dad", "Mom"]},
             spoken_text="Try to keep pickups even between us.", confirmed_by=parent),
    ]
    session.add_all(rules)


def build_demo_family(session: Session) -> Family:
    """Create the whole demo family in one session. Returns the Family row."""
    family = Family(name="Sharma", timezone="Asia/Kolkata")
    session.add(family)
    session.flush()

    loc = _add_locations(session, family)
    who = _add_members(session, family, loc)
    _add_work_and_school(session, family, loc, who)
    _add_thursday_scenario(session, family, loc, who)
    _add_tuesday_cricket(session, family, loc, who)
    _add_weekend(session, family, loc, who)
    _add_rules(session, family, who)
    session.commit()
    return family


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the LifePilot demo family.")
    parser.add_argument("--seed-db", action="store_true", help="write to DATABASE_URL (or in-memory SQLite)")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="drop everything first. Needed to move the demo week on; forgets any linked Gmail.",
    )
    args = parser.parse_args()
    if not args.seed_db:
        parser.error("nothing to do: pass --seed-db")

    engine = make_engine()
    factory = make_session_factory(engine, create=True)
    # render_as_string masks the password; str(url) would print it in cleartext.
    target = engine.url.render_as_string(hide_password=True)

    if args.reset:
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        print(f"dropped and recreated every table in {target}")

    with factory() as session:
        # Seeding twice used to append a second family, each with its own "Dad". `resolve_viewer`
        # takes the first member of that name, so the newer family became unreachable and the demo
        # silently kept answering from the older, staler week. Refusing is the whole fix.
        existing = session.scalars(sa.select(Family)).first()
        if existing is not None:
            raise SystemExit(
                f"{target} already holds family {existing.id} ({existing.name}). Seeding again "
                "would add a second family with the same names, and the first one would keep "
                "answering. Pass --reset to replace it; that also forgets any linked Gmail."
            )

        family = build_demo_family(session)
        print(f"seeded family {family.id} ({family.name}) into {target}")


if __name__ == "__main__":
    main()
