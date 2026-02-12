"""Campaign model for outbound calling campaigns."""

import uuid
from datetime import UTC, datetime, time
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, Time, Uuid
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.agent import Agent
    from app.models.contact import Contact
    from app.models.workspace import Workspace


class CampaignStatus(str, Enum):
    """Campaign status."""

    DRAFT = "draft"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELED = "canceled"


class CampaignContactStatus(str, Enum):
    """Status of a contact within a campaign."""

    PENDING = "pending"
    CALLING = "calling"
    COMPLETED = "completed"
    FAILED = "failed"
    NO_ANSWER = "no_answer"
    BUSY = "busy"
    VOICEMAIL = "voicemail"
    SKIPPED = "skipped"
    DO_NOT_CALL = "do_not_call"


class CallDisposition(str, Enum):
    """Call outcome/disposition codes."""

    # Positive outcomes
    INTERESTED = "interested"
    APPOINTMENT_BOOKED = "appointment_booked"
    SALE_MADE = "sale_made"
    CALLBACK_REQUESTED = "callback_requested"
    INFO_SENT = "info_sent"

    # Neutral outcomes
    VOICEMAIL_LEFT = "voicemail_left"
    WRONG_NUMBER = "wrong_number"
    NOT_AVAILABLE = "not_available"
    TRANSFERRED = "transferred"

    # Negative outcomes
    NOT_INTERESTED = "not_interested"
    DO_NOT_CALL = "do_not_call"
    HUNG_UP = "hung_up"
    INVALID_NUMBER = "invalid_number"

    # Technical outcomes
    NO_ANSWER = "no_answer"
    BUSY = "busy"
    FAILED = "failed"
    MACHINE_DETECTED = "machine_detected"


class Campaign(Base):
    """Outbound calling campaign.

    Manages bulk outbound calls to a list of contacts using a specific agent.
    """

    __tablename__ = "campaigns"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, index=True, comment="Owner user ID"
    )

    # Workspace isolation
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Workspace this campaign belongs to",
    )

    # Agent to use for calls
    agent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Agent that handles campaign calls",
    )

    # Campaign details
    name: Mapped[str] = mapped_column(String(255), nullable=False, comment="Campaign name")
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Campaign description"
    )
    script: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Campaign objective / talking points for the AI agent"
    )
    campaign_greeting: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Outbound greeting (overrides agent default greeting)"
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=CampaignStatus.DRAFT.value,
        index=True,
        comment="Campaign status",
    )

    # Phone number to call from
    from_phone_number: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="Phone number to call from (E.164 format)"
    )

    # Scheduling
    scheduled_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="When to start the campaign"
    )
    scheduled_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="When to end the campaign"
    )

    # Calling hours (time windows when calls are allowed)
    calling_hours_start: Mapped[time | None] = mapped_column(
        Time, nullable=True, comment="Start of daily calling window (e.g., 09:00)"
    )
    calling_hours_end: Mapped[time | None] = mapped_column(
        Time, nullable=True, comment="End of daily calling window (e.g., 17:00)"
    )
    calling_days: Mapped[list[int] | None] = mapped_column(
        ARRAY(Integer),
        nullable=True,
        comment="Days of week to call (0=Mon, 6=Sun). Null means all days.",
    )
    timezone: Mapped[str | None] = mapped_column(
        String(50), nullable=True, default="UTC", comment="Timezone for calling hours"
    )

    # Call settings
    calls_per_minute: Mapped[int] = mapped_column(
        Integer, nullable=False, default=2, comment="Max calls to initiate per minute"
    )
    max_concurrent_calls: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, comment="Max simultaneous active calls"
    )
    max_attempts_per_contact: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, comment="Max call attempts per contact"
    )
    retry_delay_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=60, comment="Minutes to wait before retry"
    )

    # Statistics (denormalized for performance)
    total_contacts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="Total contacts in campaign"
    )
    contacts_called: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="Contacts that have been called"
    )
    contacts_completed: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="Contacts with completed calls"
    )
    contacts_failed: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="Contacts with failed calls"
    )
    total_call_duration_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="Total duration of all calls"
    )

    # Error tracking
    last_error: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Most recent error message"
    )
    error_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="Total number of errors encountered"
    )
    last_error_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="When the last error occurred"
    )

    # Timestamps
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="When the campaign started running"
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="When the campaign completed"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace", lazy="selectin")
    agent: Mapped["Agent"] = relationship("Agent", lazy="selectin")
    campaign_contacts: Mapped[list["CampaignContact"]] = relationship(
        "CampaignContact", back_populates="campaign", cascade="all, delete-orphan", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Campaign(id={self.id}, name={self.name}, status={self.status})>"


class CampaignContact(Base):
    """Junction table linking contacts to campaigns with call tracking."""

    __tablename__ = "campaign_contacts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    contact_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Call tracking
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=CampaignContactStatus.PENDING.value,
        index=True,
        comment="Contact status in this campaign",
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="Number of call attempts"
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="When the last call was attempted"
    )
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True, comment="When to try next"
    )

    # Last call result
    last_call_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("call_records.id", ondelete="SET NULL"),
        nullable=True,
        comment="Most recent call record",
    )
    last_call_duration_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="Duration of last call"
    )
    last_call_outcome: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="Outcome of last call"
    )

    # Disposition (business outcome)
    disposition: Mapped[str | None] = mapped_column(
        String(50), nullable=True, index=True, comment="Call disposition/outcome code"
    )
    disposition_notes: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Notes about the call outcome"
    )
    callback_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="When callback was requested"
    )

    # Priority ordering
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="Call priority (higher = sooner)"
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    # Relationships
    campaign: Mapped["Campaign"] = relationship("Campaign", back_populates="campaign_contacts")
    contact: Mapped["Contact"] = relationship("Contact", lazy="selectin")

    def __repr__(self) -> str:
        return f"<CampaignContact(campaign_id={self.campaign_id}, contact_id={self.contact_id}, status={self.status})>"
