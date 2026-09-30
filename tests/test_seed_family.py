"""The seeded demo family has the properties the demo claims. Offline and free.

These assertions are the evidence behind differentiator #1: the Thursday pickup is unreachable for
the adult currently assigned to it, while no two events overlap at all.
"""

from datetime import datetime, timedelta

import sqlalchemy as sa

from eval.generate import THURSDAY, at, build_demo_family
from lifepilot.db.models import Assignment, Event, Member, Rule, TravelTime
from lifepilot.db.session import make_engine, make_session_factory


def fresh_session():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    return make_session_factory(engine, create=True)()


def _dump(session) -> list[tuple]:
    """Every row of every table, ordered, as comparable tuples."""
    rows = []
    for table in sorted(Event.metadata.tables):
        stmt = sa.select(Event.metadata.tables[table]).order_by(*Event.metadata.tables[table].c)
        rows.append((table, [tuple(str(v) for v in row) for row in session.execute(stmt)]))
    return rows


def test_same_build_twice_gives_identical_rows():
    with fresh_session() as first, fresh_session() as second:
        build_demo_family(first)
        build_demo_family(second)
        assert _dump(first) == _dump(second)


def test_no_two_events_sharing_a_person_overlap():
    """An overlap-only conflict check must find nothing wrong with this week. That is the point."""
    with fresh_session() as session:
        build_demo_family(session)
        events = list(session.scalars(sa.select(Event)))

        for i, a in enumerate(events):
            for b in events[i + 1:]:
                if set(a.member_ids) & set(b.member_ids):
                    assert a.end <= b.start or b.end <= a.start, f"{a.title} overlaps {b.title}"


def _last_commitment_before(session, member: Member, moment: datetime, excluding: int) -> Event:
    """The member's latest Thursday commitment ending at or before `moment`, attended or driven.

    `excluding` is the event being travelled to: an adult already assigned to it must not count as
    being there already.
    """
    driven = set(
        session.scalars(sa.select(Assignment.event_id).where(Assignment.member_id == member.id))
    )
    candidates = session.scalars(
        sa.select(Event)
        .where(Event.start >= at(THURSDAY, 0, 0), Event.end <= moment, Event.id != excluding)
        .order_by(Event.end.desc())
    )
    return next(e for e in candidates if member.id in e.member_ids or e.id in driven)


def test_thursday_pickup_is_unreachable_for_dad_but_reachable_for_mom():
    with fresh_session() as session:
        build_demo_family(session)
        by_name = {m.name: m for m in session.scalars(sa.select(Member))}
        football = session.scalars(sa.select(Event).where(Event.title == "football practice")).one()
        pickup_at = football.end
        assert pickup_at == at(THURSDAY, 17, 0)

        def arrival(member: Member) -> datetime:
            last = _last_commitment_before(session, member, pickup_at, excluding=football.id)
            minutes = session.get(TravelTime, (last.location_id, football.location_id)).minutes
            return last.end + timedelta(minutes=minutes)

        # Dad leaves the review at 16:45, 40 minutes from the ground.
        assert arrival(by_name["Dad"]) == at(THURSDAY, 17, 25)
        assert arrival(by_name["Dad"]) > pickup_at
        # Mom leaves piano at 16:45, 10 minutes from the ground.
        assert arrival(by_name["Mom"]) == at(THURSDAY, 16, 55)
        assert arrival(by_name["Mom"]) <= pickup_at


def test_dad_holds_the_broken_assignment():
    with fresh_session() as session:
        build_demo_family(session)
        football = session.scalars(sa.select(Event).where(Event.title == "football practice")).one()
        assignee = session.scalars(
            sa.select(Member).join(Assignment, Assignment.member_id == Member.id)
            .where(Assignment.event_id == football.id)
        ).one()
        assert assignee.name == "Dad"


def test_all_five_rule_types_are_seeded():
    with fresh_session() as session:
        build_demo_family(session)
        types = {r.type for r in session.scalars(sa.select(Rule))}
        assert types == {
            "immovable_event",
            "latest_end",
            "buffer_after",
            "eligibility",
            "load_balance",
        }


def test_piano_is_immovable_and_the_project_block_breaks_the_study_deadline():
    with fresh_session() as session:
        build_demo_family(session)
        piano = session.scalars(sa.select(Event).where(Event.title == "piano class")).one()
        project = session.scalars(sa.select(Event).where(Event.title == "science project block")).one()
        assert piano.movable is False
        assert project.movable is True
        assert project.end > at(THURSDAY, 21, 0)


def test_travel_table_is_symmetric_and_complete():
    with fresh_session() as session:
        build_demo_family(session)
        rows = {
            (r.from_location_id, r.to_location_id): r.minutes
            for r in session.scalars(sa.select(TravelTime))
        }
        for (a, b), minutes in rows.items():
            assert rows[(b, a)] == minutes
        assert len(rows) == 7 * 7
