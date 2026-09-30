"""Round-trip the models on in-memory SQLite. Offline and free."""

from datetime import datetime

import pytest
import sqlalchemy as sa

from lifepilot.db.models import (
    Assignment,
    Base,
    Event,
    Family,
    Location,
    Member,
    Proposal,
    Rule,
    SchoolMessage,
    TravelTime,
)
from lifepilot.db.session import make_engine, make_session_factory


@pytest.fixture
def session():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    factory = make_session_factory(engine, create=True)
    with factory() as s:
        yield s


def test_round_trip_a_family_with_an_assigned_pickup(session):
    family = Family(name="Sharma", timezone="Asia/Kolkata")
    session.add(family)
    session.flush()

    home = Location(family_id=family.id, name="home")
    ground = Location(family_id=family.id, name="football ground")
    session.add_all([home, ground])
    session.flush()

    session.add(TravelTime(from_location_id=home.id, to_location_id=ground.id, minutes=15))
    dad = Member(family_id=family.id, name="Dad", role="parent", can_drive=True, home_location_id=home.id)
    aarav = Member(family_id=family.id, name="Aarav", role="child")
    session.add_all([dad, aarav])
    session.flush()

    football = Event(
        family_id=family.id,
        member_ids=[aarav.id],
        title="football",
        category="activity",
        start=datetime(2026, 10, 1, 17, 0),
        end=datetime(2026, 10, 1, 18, 0),
        location_id=ground.id,
        needs_transport=True,
    )
    session.add(football)
    session.flush()
    session.add(Assignment(event_id=football.id, member_id=dad.id, kind="pickup"))
    session.commit()

    stored = session.get(Event, football.id)
    assert stored.member_ids == [aarav.id]
    assert stored.movable is True
    assert stored.assignments[0].kind == "pickup"


def test_json_columns_survive_the_round_trip(session):
    family = Family(name="Sharma")
    session.add(family)
    session.flush()
    session.add(Rule(
        family_id=family.id,
        type="eligibility",
        params={"role": "caregiver", "only_if": "no_parent_free"},
        spoken_text="Grandparents only when both of you are busy.",
    ))
    session.add(Proposal(
        family_id=family.id,
        kind="fix",
        created_by=1,
        changes=[{"what": "Thursday pickup", "to": "Mom", "reason": "10 minutes away after piano"}],
    ))
    session.commit()

    rule = session.scalars(sa.select(Rule)).one()
    assert rule.params["only_if"] == "no_parent_free"
    proposal = session.scalars(sa.select(Proposal)).one()
    assert proposal.changes[0]["reason"].startswith("10 minutes")
    assert proposal.status == "pending"


def test_school_message_has_nowhere_to_store_an_email_body():
    """CLAUDE.md discards the body after extraction. The schema must leave no column for it."""
    columns = set(SchoolMessage.__table__.columns.keys())
    assert columns == {
        "id",
        "family_id",
        "gmail_message_id",
        "sender",
        "received_at",
        "extracted_tasks",
        "status",
    }


def test_every_declared_table_creates_cleanly(session):
    assert len(Base.metadata.tables) == 11
