"""Workflow model — generic conversation flow graph attached to an agent."""

import uuid
from typing import Any

from sqlalchemy import JSON, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Workflow(Base, TimestampMixin):
    """Conversation workflow: a graph of nodes and edges that drives an agent session.

    nodes — list of node config dicts (id, type, label, config, position)
    edges — list of edge config dicts (id, from, to, condition, label)
    """

    __tablename__ = "workflows"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    nodes: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    edges: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)

    def __repr__(self) -> str:
        return f"<Workflow(id={self.id}, name={self.name!r}, workspace_id={self.workspace_id})>"
