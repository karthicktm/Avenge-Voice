"""Category tree models for generic classifier tool."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import ARRAY, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.agent import Agent
    from app.models.workspace import Workspace


class CategoryTree(Base, TimestampMixin):
    """One node in a named, hierarchical category tree.

    A tree is identified by (workspace_id, tree_name). All rows sharing that
    pair form one hierarchy; parent_id=None marks root nodes.

    Only nodes with status='active' are returned by the categorize() tool.
    Draft trees are invisible to agents until explicitly approved.

    The search_vector column is rebuilt automatically by a Postgres trigger
    whenever the label or code is written, enabling sub-10 ms FTS lookups.
    """

    __tablename__ = "category_trees"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        comment="Workspace owner — mandatory, no cross-workspace visibility",
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        comment="Optional pin to a specific agent; null = any agent in workspace can use it",
    )
    user_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Owner user ID (integer FK to users.id)",
    )

    tree_name: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        comment="Logical tree identifier shared by all nodes (e.g. 'property_issues')",
    )
    source_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="structured_upload",
        comment="structured_upload | ai_generated",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="draft",
        comment="draft | active | archived",
    )

    code: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
        comment="Optional external code from the source file",
    )
    label: Mapped[str] = mapped_column(
        String(300),
        nullable=False,
        comment="Human-readable node label — indexed for full-text search",
    )

    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("category_trees.id", ondelete="CASCADE"),
        nullable=True,
        comment="Parent node UUID; null for root (L1) nodes",
    )
    depth: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Pre-computed depth: 0=L1, 1=L2, 2=L3, ...",
    )
    position: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Sort order among siblings",
    )

    # Rebuilt by Postgres trigger on every INSERT / UPDATE
    search_vector: Mapped[Any] = mapped_column(TSVECTOR, nullable=True)

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace", foreign_keys=[workspace_id])
    agent: Mapped["Agent | None"] = relationship("Agent", foreign_keys=[agent_id])
    parent: Mapped["CategoryTree | None"] = relationship(
        "CategoryTree",
        foreign_keys=[parent_id],
        back_populates="children",
        remote_side="CategoryTree.id",
    )
    children: Mapped[list["CategoryTree"]] = relationship(
        "CategoryTree",
        foreign_keys=[parent_id],
        back_populates="parent",
        cascade="all, delete-orphan",
        order_by="CategoryTree.position",
    )

    __table_args__ = (
        Index("ix_category_trees_workspace_id", "workspace_id"),
        Index("ix_category_trees_agent_id", "agent_id"),
        Index("ix_category_trees_parent_id", "parent_id"),
        Index("ix_category_trees_workspace_tree_name", "workspace_id", "tree_name"),
        Index("ix_category_trees_workspace_agent", "workspace_id", "agent_id"),
        Index("ix_category_trees_tree_name_status", "tree_name", "status"),
        Index(
            "ix_category_trees_search_vector_gin",
            "search_vector",
            postgresql_using="gin",
        ),
    )

    def __repr__(self) -> str:
        return f"<CategoryTree {self.tree_name!r} label={self.label!r} depth={self.depth}>"


class CategoryResult(Base):
    """Audit record for each categorize() call during a live conversation.

    Written once and never updated. Snapshots the matched code and path so
    historical records remain interpretable even after the tree is edited.
    """

    __tablename__ = "category_results"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)

    call_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
        comment="External call session UUID passed by the caller (optional)",
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
        comment="Workspace at time of call (denormalized for fast analytics)",
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
        comment="Agent that triggered the categorization",
    )
    tree_name: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        comment="Tree name at time of call (denormalized snapshot)",
    )

    matched_node_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("category_trees.id", ondelete="SET NULL"),
        nullable=True,
        comment="FK to matched node; SET NULL if node is later deleted",
    )
    matched_code: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
        comment="Snapshot of node.code at match time",
    )
    matched_path: Mapped[list[str] | None] = mapped_column(
        ARRAY(String),
        nullable=True,
        comment="Full label path snapshot e.g. ['Water/leakage', 'Bathroom', 'Tap']",
    )

    input_text: Mapped[str] = mapped_column(Text, nullable=False, comment="Raw caller input text")
    confidence: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="FTS ts_rank score (normalised 0-1) or LLM confidence",
    )
    resolution_layer: Mapped[str | None] = mapped_column(
        String(10),
        nullable=True,
        comment="Which layer matched: fts | llm | none",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_category_results_workspace_id", "workspace_id"),
        Index("ix_category_results_agent_id", "agent_id"),
        Index("ix_category_results_call_id", "call_id"),
        Index("ix_category_results_tree_name", "tree_name"),
    )

    def __repr__(self) -> str:
        return f"<CategoryResult tree={self.tree_name!r} matched={self.matched_code!r}>"
