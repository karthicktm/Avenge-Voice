"""Document and DocumentChunk models for RAG knowledge base."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, LargeBinary, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.agent import Agent
    from app.models.workspace import Workspace


class Document(Base):
    """Document model for RAG knowledge base.

    Stores uploaded documents (PDF, DOCX, TXT, MD, XLSX) with metadata.
    Each document belongs to a specific agent and workspace for isolation.
    Documents are processed into chunks with embeddings for semantic search.
    """

    __tablename__ = "documents"

    # Primary key and foreign keys
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Agent this document belongs to",
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=True,  # Nullable for migration, will be required after workspace rollout
        index=True,
        comment="Workspace this document belongs to",
    )

    # File metadata
    filename: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="Original filename"
    )
    file_type: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        comment="File extension: pdf, docx, txt, md, xlsx, etc.",
    )
    file_size: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="File size in bytes"
    )

    # File storage
    content: Mapped[bytes | None] = mapped_column(
        LargeBinary,
        nullable=True,
        comment="File content (BYTEA for PostgreSQL storage, nullable for future S3/cloud storage)",
    )
    storage_provider: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="postgres",
        comment="Storage backend: postgres, s3, supabase, etc.",
    )
    storage_url: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        comment="External storage URL (for S3/cloud providers)",
    )

    # Processing status
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="uploading",
        index=True,
        comment="Processing status: uploading, processing, ready, error",
    )
    error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Error message if processing failed"
    )
    chunk_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="Number of chunks created from this document"
    )

    # Embedding metadata
    embedding_model: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="text-embedding-3-small",
        comment="Embedding model used (e.g., text-embedding-3-small)",
    )
    embedding_dimensions: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1536,
        comment="Embedding vector dimensions (1536 for text-embedding-3-small)",
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        index=True,
        comment="When document was uploaded",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
        comment="When document was last updated",
    )

    # Relationships
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        "DocumentChunk",
        back_populates="document",
        cascade="all, delete-orphan",
        lazy="selectin",  # Eager load chunks when querying document
    )
    agent: Mapped["Agent"] = relationship("Agent", back_populates="documents")
    workspace: Mapped["Workspace | None"] = relationship("Workspace")

    def __repr__(self) -> str:
        return (
            f"<Document(id={self.id}, filename={self.filename}, "
            f"agent_id={self.agent_id}, status={self.status}, chunks={self.chunk_count})>"
        )


class DocumentChunk(Base):
    """Document chunk with embedding for RAG retrieval.

    Each chunk represents a segment of a document with its vector embedding.
    Chunks are searched using semantic similarity (cosine distance) during RAG queries.
    """

    __tablename__ = "document_chunks"

    # Primary key and foreign key
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Document this chunk belongs to",
    )

    # Chunk data
    chunk_index: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="0-based index of chunk within document"
    )
    content_text: Mapped[str] = mapped_column(
        Text, nullable=False, comment="The actual text content of this chunk"
    )

    # Vector embedding (pgvector type)
    embedding: Mapped[Any] = mapped_column(
        Vector(1536),  # 1536 dimensions for text-embedding-3-small
        nullable=False,
        comment="Vector embedding for semantic search",
    )

    # Metadata (renamed to chunk_metadata to avoid SQLAlchemy reserved name conflict)
    chunk_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",  # Column name in database
        JSON,
        nullable=False,
        default=dict,
        comment="Additional metadata (page number, section, etc.)",
    )

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        comment="When chunk was created",
    )

    # Relationship
    document: Mapped["Document"] = relationship("Document", back_populates="chunks")

    def __repr__(self) -> str:
        return (
            f"<DocumentChunk(id={self.id}, document_id={self.document_id}, "
            f"chunk_index={self.chunk_index}, text_length={len(self.content_text)})>"
        )
