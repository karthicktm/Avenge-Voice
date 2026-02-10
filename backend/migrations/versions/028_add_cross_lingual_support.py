"""Add cross-lingual knowledge base support.

Adds translation columns to documents and chunks, plus embedding_large
for text-embedding-3-large (3072 dimensions).

Revision ID: 028_add_cross_lingual_support
Revises: 027_set_admin_superadmin_role
Create Date: 2025-02-10
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision = "028_add_cross_lingual_support"
down_revision = "027_set_admin_superadmin_role"
branch_labels = None
depends_on = None


def column_exists(table: str, column: str) -> bool:
    """Check if a column exists in a table."""
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            """
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = :table AND column_name = :column
            )
            """
        ),
        {"table": table, "column": column},
    )
    return result.scalar() or False


def upgrade() -> None:
    """Add cross-lingual support columns."""
    # Add columns to documents table
    if not column_exists("documents", "source_language"):
        op.add_column(
            "documents",
            sa.Column(
                "source_language",
                sa.String(10),
                nullable=True,
                comment="Detected source language code (e.g., sv, de, en)",
            ),
        )
    if not column_exists("documents", "translation_enabled"):
        op.add_column(
            "documents",
            sa.Column(
                "translation_enabled",
                sa.Boolean,
                nullable=False,
                server_default="false",
                comment="Whether translation was applied during processing",
            ),
        )
    if not column_exists("documents", "embedding_dimensions"):
        op.add_column(
            "documents",
            sa.Column(
                "embedding_dimensions",
                sa.Integer,
                nullable=False,
                server_default="1536",
                comment="Embedding vector dimensions (1536 or 3072)",
            ),
        )

    # Add columns to document_chunks table
    if not column_exists("document_chunks", "translated_text"):
        op.add_column(
            "document_chunks",
            sa.Column(
                "translated_text",
                sa.Text,
                nullable=True,
                comment="English translation of chunk content",
            ),
        )
    if not column_exists("document_chunks", "source_language"):
        op.add_column(
            "document_chunks",
            sa.Column(
                "source_language",
                sa.String(10),
                nullable=True,
                comment="Source language code for this chunk",
            ),
        )
    if not column_exists("document_chunks", "translation_status"):
        op.add_column(
            "document_chunks",
            sa.Column(
                "translation_status",
                sa.String(20),
                nullable=False,
                server_default="not_needed",
                comment="Translation status: not_needed, completed, failed, skipped",
            ),
        )
    if not column_exists("document_chunks", "embedding_large"):
        op.add_column(
            "document_chunks",
            sa.Column(
                "embedding_large",
                Vector(3072),
                nullable=True,
                comment="Embedding vector for text-embedding-3-large (3072 dims)",
            ),
        )

    # Make embedding column nullable to support either embedding or embedding_large
    op.alter_column(
        "document_chunks",
        "embedding",
        nullable=True,
    )

    # Add use_best_practices to agents table
    if not column_exists("agents", "use_best_practices"):
        op.add_column(
            "agents",
            sa.Column(
                "use_best_practices",
                sa.Boolean,
                nullable=False,
                server_default="true",
                comment="Include language-specific best practices in system prompt",
            ),
        )

    # Note: Index creation for embedding_large (3072 dims) is skipped because
    # pgvector < 0.7.0 has a 2000 dimension limit for indexes.
    # The column will work without an index, just with slower search performance.
    # Upgrade pgvector to 0.7.0+ and add the index manually if needed:
    # CREATE INDEX ix_document_chunks_embedding_large_hnsw
    # ON document_chunks USING hnsw (embedding_large vector_cosine_ops)
    # WITH (m = 16, ef_construction = 64);


def downgrade() -> None:
    """Remove cross-lingual support columns."""
    # Drop index if it exists (only if pgvector was upgraded and index was added)
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_embedding_large_hnsw")

    # Remove columns from agents
    if column_exists("agents", "use_best_practices"):
        op.drop_column("agents", "use_best_practices")

    # Remove columns from document_chunks
    if column_exists("document_chunks", "embedding_large"):
        op.drop_column("document_chunks", "embedding_large")
    if column_exists("document_chunks", "translation_status"):
        op.drop_column("document_chunks", "translation_status")
    if column_exists("document_chunks", "source_language"):
        op.drop_column("document_chunks", "source_language")
    if column_exists("document_chunks", "translated_text"):
        op.drop_column("document_chunks", "translated_text")

    # Remove columns from documents
    if column_exists("documents", "embedding_dimensions"):
        op.drop_column("documents", "embedding_dimensions")
    if column_exists("documents", "translation_enabled"):
        op.drop_column("documents", "translation_enabled")
    if column_exists("documents", "source_language"):
        op.drop_column("documents", "source_language")
