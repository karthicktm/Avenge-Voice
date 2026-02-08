"""User profile model for additional user information."""

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.user import User


class UserProfile(Base, TimestampMixin):
    """User profile model.

    Stores additional user information and signup metadata.
    """

    __tablename__ = "user_profiles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Additional profile information
    phone_number: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="User phone number"
    )
    avatar_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="User avatar URL"
    )
    job_title: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="User job title"
    )
    department: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="User department"
    )

    # Signup metadata (collected during registration)
    signup_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="Metadata collected during signup (purpose, number of users/agents, etc.)",
    )

    # Preferences
    preferences: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="User preferences (notifications, theme, language, etc.)",
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="profile")
    organization: Mapped["Organization"] = relationship("Organization")

    def __repr__(self) -> str:
        """String representation."""
        return f"<UserProfile user_id={self.user_id}>"
