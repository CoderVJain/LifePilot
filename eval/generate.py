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
"""

import argparse
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from lifepilot.db.models import Assignment, Event, Family, Location, Member, Rule, Task, TravelTime
from lifepilot.db.session import make_engine, make_session_factory

MONDAY = date(2026, 10, 5)
THURSDAY = MONDAY + timedelta(days=3)

LOCATIONS = (
    "home",
    "dad office",
    "mom office",
    "school",
    "football ground",
    "piano school",
    "grandpa home",
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


def _add_work_and_school(session: Session, family: Family, loc: dict[str, int], who: dict[str, Member]):
    """Weekday routine. Thursday is shorter for both parents so the afternoon scenario has no overlap."""
    for day in _weekdays():
        dad_end = at(day, 15, 45) if day == THURSDAY else at(day, 16, 30)
        mom_end = at(day, 15, 45) if day == THURSDAY else at(day, 16, 0)
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
        session.add(Event(
            family_id=family.id, member_ids=[who["Aarav"].id, who["Anaya"].id], title="school",
            category="school", start=at(day, 8, 0), end=at(day, 15, 0), location_id=loc["school"],
            movable=False,
        ))


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
    _add_rules(session, family, who)
    session.commit()
    return family


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the LifePilot demo family.")
    parser.add_argument("--seed-db", action="store_true", help="write to DATABASE_URL (or in-memory SQLite)")
    args = parser.parse_args()
    if not args.seed_db:
        parser.error("nothing to do: pass --seed-db")

    engine = make_engine()
    factory = make_session_factory(engine, create=True)
    with factory() as session:
        family = build_demo_family(session)
        # render_as_string masks the password; str(url) would print it in cleartext.
        target = engine.url.render_as_string(hide_password=True)
        print(f"seeded family {family.id} ({family.name}) into {target}")


if __name__ == "__main__":
    main()
