"""Add RAG support with documents and chunks tables

Revision ID: 0d6a5b92ea4d
Revises: ee167a9a2635
Create Date: 2025-01-31 16:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0d6a5b92ea4d"
down_revision: str | Sequence[str] | None = "ee167a9a2635"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add RAG support: pgvector extension, documents table, and document_chunks table."""
    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Create documents table
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(500), nullable=False, comment="Original filename"),
        sa.Column(
            "file_type", sa.String(50), nullable=False, comment="File type (pdf, docx, txt, md)"
        ),
        sa.Column("file_size", sa.Integer(), nullable=False, comment="File size in bytes"),
        sa.Column(
            "content", sa.Text(), nullable=True, comment="Extracted text content from the file"
        ),
        sa.Column(
            "status",
            sa.String(50),
            nullable=False,
            server_default="pending",
            comment="Processing status: pending, processing, ready, failed",
        ),
        sa.Column(
            "error_message", sa.Text(), nullable=True, comment="Error message if processing failed"
        ),
        sa.Column(
            "chunk_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="Number of chunks created",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When processing completed",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_documents_agent_id", "documents", ["agent_id"])
    op.create_index("ix_documents_status", "documents", ["status"])

    # Create document_chunks table with vector embedding
    op.execute(
        """
        CREATE TABLE document_chunks (
            id UUID PRIMARY KEY,
            document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            chunk_index INTEGER NOT NULL,
            content_text TEXT NOT NULL,
            embedding vector(1536) NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
        )
        """
    )
    op.create_index("ix_document_chunks_document_id", "document_chunks", ["document_id"])

    # Create IVFFlat index for vector similarity search
    # Note: IVFFlat index requires at least some data to be present to work efficiently
    # Using 100 lists which is good for up to ~1M vectors
    op.execute(
        """
        CREATE INDEX ix_document_chunks_embedding_ivfflat
        ON document_chunks
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100)
        """
    )


def downgrade() -> None:
    """Remove RAG support tables."""
    op.drop_index("ix_document_chunks_embedding_ivfflat", "document_chunks")
    op.drop_index("ix_document_chunks_document_id", "document_chunks")
    op.drop_table("document_chunks")

    op.drop_index("ix_documents_status", "documents")
    op.drop_index("ix_documents_agent_id", "documents")
    op.drop_table("documents")

    # Note: We don't drop the pgvector extension as it might be used elsewhere
