"""Add tsvector column and GIN index for full-text keyword search.

Adds hybrid search support alongside existing vector similarity search.
Uses 'simple' dictionary (language-agnostic) for multilingual compatibility.

Revision ID: 030_add_fulltext_search
Revises: 029_add_document_source_fields
Create Date: 2026-02-12
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "030_add_fulltext_search"
down_revision = "029_add_document_source_fields"
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
    """Add tsvector column, GIN index, backfill, and trigger."""
    if not column_exists("document_chunks", "content_tsv"):
        # Add tsvector column
        op.add_column(
            "document_chunks",
            sa.Column(
                "content_tsv",
                sa.dialects.postgresql.TSVECTOR,
                nullable=True,
                comment="Full-text search vector (simple dictionary)",
            ),
        )

        # Create GIN index for fast full-text search
        op.create_index(
            "ix_document_chunks_content_tsv",
            "document_chunks",
            ["content_tsv"],
            postgresql_using="gin",
        )

        # Backfill existing rows
        op.execute("UPDATE document_chunks SET content_tsv = to_tsvector('simple', content_text)")

        # Create trigger function to auto-populate content_tsv on INSERT/UPDATE
        op.execute(
            """
            CREATE OR REPLACE FUNCTION document_chunks_tsv_trigger()
            RETURNS trigger AS $$
            BEGIN
                NEW.content_tsv := to_tsvector('simple', NEW.content_text);
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """
        )

        # Attach trigger to table
        op.execute(
            """
            CREATE TRIGGER trg_document_chunks_tsv
            BEFORE INSERT OR UPDATE OF content_text ON document_chunks
            FOR EACH ROW
            EXECUTE FUNCTION document_chunks_tsv_trigger();
            """
        )


def downgrade() -> None:
    """Remove tsvector column, index, and trigger."""
    # Drop trigger and function
    op.execute("DROP TRIGGER IF EXISTS trg_document_chunks_tsv ON document_chunks")
    op.execute("DROP FUNCTION IF EXISTS document_chunks_tsv_trigger()")

    # Drop index and column
    op.drop_index("ix_document_chunks_content_tsv", table_name="document_chunks")
    if column_exists("document_chunks", "content_tsv"):
        op.drop_column("document_chunks", "content_tsv")
