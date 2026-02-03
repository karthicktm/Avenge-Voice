"""Fix user_integrations unique constraint to include workspace_id.

The original unique index was on (user_id, integration_id) only, which prevents
a user from connecting the same integration in multiple workspaces. This migration
replaces it with a unique index on (user_id, integration_id, workspace_id).

Revision ID: 018_fix_integrations_unique
Revises: 017_fix_documents_column_types
Create Date: 2026-02-03
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "018_fix_integrations_unique"
down_revision: str | None = "17635397a860"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Replace unique index to include workspace_id."""
    # Drop the old unique index on (user_id, integration_id)
    op.drop_index("ix_user_integrations_user_integration", table_name="user_integrations")

    # Create new unique index on (user_id, integration_id, workspace_id)
    # PostgreSQL treats NULLs as distinct in unique indexes, so user-level
    # integrations (workspace_id=NULL) won't conflict with workspace-level ones.
    # The application layer handles preventing duplicate NULL workspace entries.
    op.create_index(
        "ix_user_integrations_user_integration",
        "user_integrations",
        ["user_id", "integration_id", "workspace_id"],
        unique=True,
    )


def downgrade() -> None:
    """Restore original unique index on (user_id, integration_id)."""
    op.drop_index("ix_user_integrations_user_integration", table_name="user_integrations")
    op.create_index(
        "ix_user_integrations_user_integration",
        "user_integrations",
        ["user_id", "integration_id"],
        unique=True,
    )
