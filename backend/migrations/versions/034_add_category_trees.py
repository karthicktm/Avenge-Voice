"""Add category_trees and category_results tables.

Revision ID: 034_add_category_trees
Revises: 033_add_lookup_tables
Create Date: 2026-03-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "034_add_category_trees"
down_revision: str = "033_add_lookup_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # -----------------------------------------------------------------------
    # category_trees — self-referencing hierarchy
    # -----------------------------------------------------------------------
    op.create_table(
        "category_trees",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("tree_name", sa.String(120), nullable=False),
        sa.Column("source_type", sa.String(30), nullable=False, server_default="structured_upload"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("code", sa.String(80), nullable=True),
        sa.Column("label", sa.String(300), nullable=False),
        sa.Column(
            "parent_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("category_trees.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("depth", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("search_vector", postgresql.TSVECTOR(), nullable=True),
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

    op.create_index("ix_category_trees_workspace_id", "category_trees", ["workspace_id"])
    op.create_index("ix_category_trees_agent_id", "category_trees", ["agent_id"])
    op.create_index("ix_category_trees_parent_id", "category_trees", ["parent_id"])
    op.create_index(
        "ix_category_trees_workspace_tree_name",
        "category_trees",
        ["workspace_id", "tree_name"],
    )
    op.create_index(
        "ix_category_trees_workspace_agent",
        "category_trees",
        ["workspace_id", "agent_id"],
    )
    op.create_index(
        "ix_category_trees_tree_name_status",
        "category_trees",
        ["tree_name", "status"],
    )
    op.create_index(
        "ix_category_trees_search_vector_gin",
        "category_trees",
        ["search_vector"],
        postgresql_using="gin",
    )

    # Trigger: rebuild search_vector from label + code on every insert/update
    op.execute("""
        CREATE OR REPLACE FUNCTION update_category_tree_search_vector()
        RETURNS trigger AS $$
        BEGIN
            NEW.search_vector :=
                to_tsvector('simple',
                    coalesce(NEW.label, '') || ' ' || coalesce(NEW.code, '')
                );
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE TRIGGER trg_category_trees_search_vector
        BEFORE INSERT OR UPDATE ON category_trees
        FOR EACH ROW EXECUTE FUNCTION update_category_tree_search_vector();
    """)

    # -----------------------------------------------------------------------
    # category_results — immutable audit log
    # -----------------------------------------------------------------------
    op.create_table(
        "category_results",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("call_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("workspace_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("agent_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("tree_name", sa.String(120), nullable=False),
        sa.Column(
            "matched_node_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("category_trees.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("matched_code", sa.String(80), nullable=True),
        sa.Column("matched_path", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("input_text", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("resolution_layer", sa.String(10), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_index("ix_category_results_workspace_id", "category_results", ["workspace_id"])
    op.create_index("ix_category_results_agent_id", "category_results", ["agent_id"])
    op.create_index("ix_category_results_call_id", "category_results", ["call_id"])
    op.create_index("ix_category_results_tree_name", "category_results", ["tree_name"])


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_category_trees_search_vector ON category_trees")
    op.execute("DROP FUNCTION IF EXISTS update_category_tree_search_vector()")

    op.drop_index("ix_category_results_tree_name", table_name="category_results")
    op.drop_index("ix_category_results_call_id", table_name="category_results")
    op.drop_index("ix_category_results_agent_id", table_name="category_results")
    op.drop_index("ix_category_results_workspace_id", table_name="category_results")
    op.drop_table("category_results")

    op.drop_index("ix_category_trees_search_vector_gin", table_name="category_trees")
    op.drop_index("ix_category_trees_tree_name_status", table_name="category_trees")
    op.drop_index("ix_category_trees_workspace_agent", table_name="category_trees")
    op.drop_index("ix_category_trees_workspace_tree_name", table_name="category_trees")
    op.drop_index("ix_category_trees_parent_id", table_name="category_trees")
    op.drop_index("ix_category_trees_agent_id", table_name="category_trees")
    op.drop_index("ix_category_trees_workspace_id", table_name="category_trees")
    op.drop_table("category_trees")
