"""SQLAlchemy models for LifePilot.

Datetimes are naive local time in the family's timezone: one family lives in one timezone, and
reachability is minute arithmetic, so UTC conversion would add a failure mode and buy nothing.

Only portable `sa.JSON` is used, so the same schema runs on in-memory SQLite (tests, evals) and on
Neon Postgres (seed, demo).
"""

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

ROLES = ("parent", "child", "caregiver")
RULE_TYPES = ("immovable_event", "latest_end", "buffer_after", "eligibility", "load_balance")
PROPOSAL_KINDS = ("fix", "assign", "swap", "rule", "event", "task")
PROPOSAL_STATUSES = ("pending", "approved", "rejected", "expired")
ASSIGNMENT_KINDS = ("drop", "pickup")
TASK_SOURCES = ("voice", "email")
VISIBILITIES = ("all", "parents", "owner")


class Base(DeclarativeBase):
    pass


class Family(Base):
    __tablename__ = "family"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    timezone: Mapped[str] = mapped_column(default="Asia/Kolkata")

    members: Mapped[list["Member"]] = relationship(back_populates="family")
    locations: Mapped[list["Location"]] = relationship(back_populates="family")


class Location(Base):
    __tablename__ = "location"

    id: Mapped[int] = mapped_column(primary_key=True)
    family_id: Mapped[int] = mapped_column(sa.ForeignKey("family.id"))
    name: Mapped[str]

    family: Mapped[Family] = relationship(back_populates="locations")


class Member(Base):
    __tablename__ = "member"

    id: Mapped[int] = mapped_column(primary_key=True)
    family_id: Mapped[int] = mapped_column(sa.ForeignKey("family.id"))
    name: Mapped[str]
    role: Mapped[str]
    can_drive: Mapped[bool] = mapped_column(default=False)
    home_location_id: Mapped[int | None] = mapped_column(sa.ForeignKey("location.id"))

    family: Mapped[Family] = relationship(back_populates="members")


class TravelTime(Base):
    """Fixed table, seeded. No Maps API: out of scope by design."""

    __tablename__ = "travel_time"

    from_location_id: Mapped[int] = mapped_column(sa.ForeignKey("location.id"), primary_key=True)
    to_location_id: Mapped[int] = mapped_column(sa.ForeignKey("location.id"), primary_key=True)
    minutes: Mapped[int]


class Event(Base):
    __tablename__ = "event"

    id: Mapped[int] = mapped_column(primary_key=True)
    family_id: Mapped[int] = mapped_column(sa.ForeignKey("family.id"))
    member_ids: Mapped[list[int]] = mapped_column(sa.JSON, default=list)
    title: Mapped[str]
    category: Mapped[str]
    start: Mapped[datetime]
    end: Mapped[datetime]
    location_id: Mapped[int | None] = mapped_column(sa.ForeignKey("location.id"))
    needs_transport: Mapped[bool] = mapped_column(default=False)
    movable: Mapped[bool] = mapped_column(default=True)
    visibility: Mapped[str] = mapped_column(default="all")

    assignments: Mapped[list["Assignment"]] = relationship(back_populates="event")


class Task(Base):
    __tablename__ = "task"

    id: Mapped[int] = mapped_column(primary_key=True)
    family_id: Mapped[int] = mapped_column(sa.ForeignKey("family.id"))
    owner_id: Mapped[int | None] = mapped_column(sa.ForeignKey("member.id"))
    title: Mapped[str]
    category: Mapped[str]
    due: Mapped[datetime]
    est_minutes: Mapped[int] = mapped_column(default=30)
    prep_days: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(default="open")
    source: Mapped[str] = mapped_column(default="voice")


class Rule(Base):
    """A rule stated once by voice, read back, then enforced by the solver on every plan."""

    __tablename__ = "rule"

    id: Mapped[int] = mapped_column(primary_key=True)
    family_id: Mapped[int] = mapped_column(sa.ForeignKey("family.id"))
    type: Mapped[str]
    hard: Mapped[bool] = mapped_column(default=True)
    params: Mapped[dict] = mapped_column(sa.JSON, default=dict)
    spoken_text: Mapped[str]
    confirmed_by: Mapped[int | None] = mapped_column(sa.ForeignKey("member.id"))
    active: Mapped[bool] = mapped_column(default=True)


class Assignment(Base):
    __tablename__ = "assignment"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(sa.ForeignKey("event.id"))
    member_id: Mapped[int] = mapped_column(sa.ForeignKey("member.id"))
    kind: Mapped[str]

    event: Mapped[Event] = relationship(back_populates="assignments")


class Proposal(Base):
    """Every write goes through one of these. Only approve_proposal executes it."""

    __tablename__ = "proposal"

    id: Mapped[int] = mapped_column(primary_key=True)
    family_id: Mapped[int] = mapped_column(sa.ForeignKey("family.id"))
    kind: Mapped[str]
    created_by: Mapped[int] = mapped_column(sa.ForeignKey("member.id"))
    changes: Mapped[list] = mapped_column(sa.JSON, default=list)
    violations: Mapped[list] = mapped_column(sa.JSON, default=list)
    solve_ms: Mapped[int | None]
    status: Mapped[str] = mapped_column(default="pending")
    needs_approval_from: Mapped[int | None] = mapped_column(sa.ForeignKey("member.id"))
    decided_by: Mapped[int | None] = mapped_column(sa.ForeignKey("member.id"))
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)


class EmailLink(Base):
    __tablename__ = "email_link"

    id: Mapped[int] = mapped_column(primary_key=True)
    family_id: Mapped[int] = mapped_column(sa.ForeignKey("family.id"))
    parent_id: Mapped[int] = mapped_column(sa.ForeignKey("member.id"))
    encrypted_token: Mapped[bytes]
    allowed_senders: Mapped[list[str]] = mapped_column(sa.JSON, default=list)
    linked_at: Mapped[datetime] = mapped_column(default=datetime.now)
    last_checked_at: Mapped[datetime | None]


class SchoolMessage(Base):
    """Deliberately has no subject and no body column: the email text is discarded after extraction,
    and the strongest way to keep that promise is to leave nowhere to put it."""

    __tablename__ = "school_message"

    id: Mapped[int] = mapped_column(primary_key=True)
    family_id: Mapped[int] = mapped_column(sa.ForeignKey("family.id"))
    gmail_message_id: Mapped[str] = mapped_column(unique=True)
    sender: Mapped[str]
    received_at: Mapped[datetime]
    extracted_tasks: Mapped[list] = mapped_column(sa.JSON, default=list)
    status: Mapped[str] = mapped_column(default="new")
