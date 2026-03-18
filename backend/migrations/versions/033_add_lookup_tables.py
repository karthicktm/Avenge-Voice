"""Add lookup_collections and lookup_records tables.

Revision ID: 033_add_lookup_tables
Revises: 032_add_agent_deployments
Create Date: 2026-03-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "033_add_lookup_tables"
down_revision: str = "032_add_agent_deployments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # -----------------------------------------------------------------------
    # lookup_collections
    # -----------------------------------------------------------------------
    op.create_table(
        "lookup_collections",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("domain", sa.String(100), nullable=False, server_default="custom"),
        sa.Column("use_case_tag", sa.String(255), nullable=True),
        sa.Column("source_type", sa.String(50), nullable=False, server_default="manual"),
        sa.Column("field_schema", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
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
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_lookup_collections_workspace_id", "lookup_collections", ["workspace_id"])
    op.create_index("ix_lookup_collections_user_id", "lookup_collections", ["user_id"])
    op.create_index("ix_lookup_collections_domain", "lookup_collections", ["domain"])
    op.create_index("ix_lookup_collections_is_active", "lookup_collections", ["is_active"])

    # -----------------------------------------------------------------------
    # lookup_records
    # -----------------------------------------------------------------------
    op.create_table(
        "lookup_records",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "collection_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("lookup_collections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("workspace_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column(
            "data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("search_vector", postgresql.TSVECTOR(), nullable=True),
        sa.Column("tags", postgresql.ARRAY(sa.Text()), nullable=True),
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
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_lookup_records_collection_id", "lookup_records", ["collection_id"])
    op.create_index("ix_lookup_records_workspace_id", "lookup_records", ["workspace_id"])
    op.create_index("ix_lookup_records_user_id", "lookup_records", ["user_id"])
    op.create_index("ix_lookup_records_title", "lookup_records", ["title"])
    op.create_index(
        "ix_lookup_records_data_gin",
        "lookup_records",
        ["data"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_lookup_records_search_vector_gin",
        "lookup_records",
        ["search_vector"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_lookup_records_tags_gin",
        "lookup_records",
        ["tags"],
        postgresql_using="gin",
    )

    # -----------------------------------------------------------------------
    # Trigger: auto-rebuild search_vector on INSERT / UPDATE
    # -----------------------------------------------------------------------
    op.execute("""
        CREATE OR REPLACE FUNCTION update_lookup_search_vector()
        RETURNS trigger AS $$
        BEGIN
            NEW.search_vector :=
                to_tsvector('english',
                    coalesce(NEW.title, '') || ' ' || coalesce(NEW.data::text, '')
                );
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE TRIGGER trg_lookup_records_search_vector
        BEFORE INSERT OR UPDATE ON lookup_records
        FOR EACH ROW EXECUTE FUNCTION update_lookup_search_vector();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_lookup_records_search_vector ON lookup_records")
    op.execute("DROP FUNCTION IF EXISTS update_lookup_search_vector()")

    op.drop_index("ix_lookup_records_tags_gin", table_name="lookup_records")
    op.drop_index("ix_lookup_records_search_vector_gin", table_name="lookup_records")
    op.drop_index("ix_lookup_records_data_gin", table_name="lookup_records")
    op.drop_index("ix_lookup_records_title", table_name="lookup_records")
    op.drop_index("ix_lookup_records_user_id", table_name="lookup_records")
    op.drop_index("ix_lookup_records_workspace_id", table_name="lookup_records")
    op.drop_index("ix_lookup_records_collection_id", table_name="lookup_records")
    op.drop_table("lookup_records")

    op.drop_index("ix_lookup_collections_is_active", table_name="lookup_collections")
    op.drop_index("ix_lookup_collections_domain", table_name="lookup_collections")
    op.drop_index("ix_lookup_collections_user_id", table_name="lookup_collections")
    op.drop_index("ix_lookup_collections_workspace_id", table_name="lookup_collections")
    op.drop_table("lookup_collections")
