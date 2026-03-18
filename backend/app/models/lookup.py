"""Lookup models for structured data query collections."""

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.workspace import Workspace


class LookupCollection(Base, TimestampMixin):
    """A named collection of structured records (e.g. property listings, FAQs, products)."""

    __tablename__ = "lookup_collections"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)

    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(nullable=False, index=True)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    domain: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="custom",
        index=True,
    )  # property | faq | product | staff | custom:*
    use_case_tag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="manual",
    )  # excel | csv | json | manual

    # Schema definition: {key: {label, description, searchable}}
    field_schema: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)

    # Relationships
    workspace: Mapped["Workspace | None"] = relationship("Workspace", foreign_keys=[workspace_id])
    records: Mapped[list["LookupRecord"]] = relationship(
        "LookupRecord",
        back_populates="collection",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        """String representation."""
        return f"<LookupCollection {self.name!r} domain={self.domain!r}>"


class LookupRecord(Base, TimestampMixin):
    """A single record within a LookupCollection."""

    __tablename__ = "lookup_records"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)

    collection_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("lookup_collections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(nullable=False, index=True)

    title: Mapped[str] = mapped_column(String(500), nullable=False, index=True)

    # Full row payload — schema-free
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    # Full-text search vector (rebuilt by Postgres trigger on insert/update)
    search_vector: Mapped[Any] = mapped_column(TSVECTOR, nullable=True)

    tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)

    # Relationships
    collection: Mapped["LookupCollection"] = relationship(
        "LookupCollection",
        back_populates="records",
    )

    __table_args__ = (
        Index("ix_lookup_records_data_gin", "data", postgresql_using="gin"),
        Index("ix_lookup_records_search_vector_gin", "search_vector", postgresql_using="gin"),
        Index("ix_lookup_records_tags_gin", "tags", postgresql_using="gin"),
    )

    def __repr__(self) -> str:
        """String representation."""
        return f"<LookupRecord {self.title!r} collection={self.collection_id}>"
