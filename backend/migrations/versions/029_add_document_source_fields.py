"""Add source_type and source_url to documents for web crawl tracking.

Revision ID: 029_add_document_source_fields
Revises: 028_add_cross_lingual_support
Create Date: 2026-02-10
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "029_add_document_source_fields"
down_revision = "028_add_cross_lingual_support"
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
    """Add source tracking columns to documents."""
    if not column_exists("documents", "source_type"):
        op.add_column(
            "documents",
            sa.Column(
                "source_type",
                sa.String(50),
                nullable=False,
                server_default="upload",
                comment="Source type: upload or web_crawl",
            ),
        )
    if not column_exists("documents", "source_url"):
        op.add_column(
            "documents",
            sa.Column(
                "source_url",
                sa.String(2000),
                nullable=True,
                comment="URL the content was crawled from (for web_crawl)",
            ),
        )


def downgrade() -> None:
    """Remove source tracking columns."""
    if column_exists("documents", "source_url"):
        op.drop_column("documents", "source_url")
    if column_exists("documents", "source_type"):
        op.drop_column("documents", "source_type")
