"""Document models for RAG/Knowledge Base functionality."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.agent import Agent


class Document(Base):
    """Document uploaded to an agent's knowledge base.

    Stores file metadata and processing status.
    The actual file content is extracted and stored in DocumentChunks.
    """

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # File metadata
    filename: Mapped[str] = mapped_column(String(500), nullable=False, comment="Original filename")
    file_type: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="File type (pdf, docx, txt, md)"
    )
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, comment="File size in bytes")

    # Extracted content (raw text before chunking)
    content: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Extracted text content from the file"
    )

    # Processing status
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="pending",
        index=True,
        comment="Processing status: pending, processing, ready, failed",
    )
    error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Error message if processing failed"
    )
    chunk_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="Number of chunks created"
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
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="When processing completed"
    )

    # Relationships
    agent: Mapped["Agent"] = relationship("Agent", back_populates="documents")
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        "DocumentChunk", back_populates="document", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Document(id={self.id}, filename={self.filename}, status={self.status})>"


class DocumentChunk(Base):
    """Chunk of document content with embedding for semantic search.

    Documents are split into chunks of ~500 characters with overlap
    for better retrieval quality.
    """

    __tablename__ = "document_chunks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Chunk content
    chunk_index: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="Position of this chunk in the document"
    )
    content_text: Mapped[str] = mapped_column(Text, nullable=False, comment="Chunk text content")

    # Embedding vector (1536 dimensions for text-embedding-3-small)
    embedding: Mapped[list[float]] = mapped_column(
        Vector(1536), nullable=False, comment="Embedding vector from OpenAI"
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    # Relationships
    document: Mapped["Document"] = relationship("Document", back_populates="chunks")

    # Indexes for vector similarity search
    __table_args__ = (
        Index(
            "ix_document_chunks_embedding_ivfflat",
            embedding,
            postgresql_using="ivfflat",
            postgresql_with={"lists": 100},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    def __repr__(self) -> str:
        return f"<DocumentChunk(id={self.id}, document_id={self.document_id}, index={self.chunk_index})>"
