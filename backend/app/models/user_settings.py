"""User settings model for storing API keys and configuration."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserSettings(Base):
    """User settings including API keys for voice/AI services.

    Settings can be either user-level (workspace_id=NULL) or workspace-level.
    Workspace-level settings allow different API keys per workspace/client.
    """

    __tablename__ = "user_settings"
    __table_args__ = (
        UniqueConstraint("user_id", "workspace_id", name="uq_user_settings_user_workspace"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="Workspace this setting belongs to (null = user-level default)",
    )

    # Voice & AI API Keys (encrypted at rest in production)
    openai_api_key: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="OpenAI API key for GPT Realtime"
    )
    deepgram_api_key: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Deepgram API key for STT"
    )
    elevenlabs_api_key: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="ElevenLabs API key for TTS"
    )
    google_api_key: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Google API key for Gemini Live"
    )

    # Telephony API Keys
    telnyx_api_key: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Telnyx API key"
    )
    telnyx_public_key: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Telnyx public key"
    )
    twilio_account_sid: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="Twilio Account SID"
    )
    twilio_auth_token: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Twilio Auth Token"
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

    def __repr__(self) -> str:
        return f"<UserSettings(user_id={self.user_id})>"
