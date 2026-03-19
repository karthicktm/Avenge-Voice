"""Categorize tool for voice agents — classify caller input against a named category tree."""

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


class CategorizeTools:
    """Classify caller input against a workspace category tree.

    Registered under key "categorization" in the ToolRegistry.
    The agent's system prompt specifies which tree_name to use — not hardcoded here.

    Matching layers:
      1. Postgres FTS (plainto_tsquery 'simple') — fast, zero API cost.
      2. LLM-assisted selection from top-5 FTS candidates — only when FTS score is low.
    """

    def __init__(
        self,
        db: AsyncSession,
        user_id: int,
        workspace_id: uuid.UUID | None = None,
        agent_id: uuid.UUID | None = None,
        openai_api_key: str | None = None,
    ) -> None:
        self.db = db
        self.user_id = user_id
        self.workspace_id = workspace_id
        self.agent_id = agent_id
        self.openai_api_key = openai_api_key
        self.log = logger.bind(
            component="categorize_tools",
            user_id=user_id,
            workspace_id=str(workspace_id),
        )

    # ------------------------------------------------------------------
    # Tool definitions (OpenAI Realtime function-calling format)
    # ------------------------------------------------------------------

    @staticmethod
    def get_tool_definitions() -> list[dict[str, Any]]:
        """Return OpenAI Realtime API tool definition for the categorize tool."""
        return [
            {
                "type": "function",
                "name": "categorize",
                "description": (
                    "Classify the caller's description or issue against the configured category tree. "
                    "Call this tool when the caller describes a problem, request, or topic that needs "
                    "to be categorized. The agent system prompt specifies which tree_name to use."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "The caller's raw input text to categorize.",
                        },
                        "tree_name": {
                            "type": "string",
                            "description": "The category tree to classify against (set in your system prompt).",
                        },
                        "call_id": {
                            "type": "string",
                            "description": "Optional current call session ID for audit logging.",
                        },
                    },
                    "required": ["text", "tree_name"],
                },
            }
        ]

    # ------------------------------------------------------------------
    # Tool execution router
    # ------------------------------------------------------------------

    async def execute_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Route tool call to the appropriate handler."""
        if tool_name == "categorize":
            return await self._categorize(arguments)
        return {"success": False, "error": f"Unknown categorize tool: {tool_name}"}

    # ------------------------------------------------------------------
    # Private handler
    # ------------------------------------------------------------------

    async def _categorize(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Classify caller input and return matched category info."""
        text: str = str(arguments.get("text", "")).strip()
        tree_name: str = str(arguments.get("tree_name", "")).strip()
        call_id_str: str | None = arguments.get("call_id")

        if not text:
            return {"success": False, "error": "text is required"}
        if not tree_name:
            return {"success": False, "error": "tree_name is required"}
        if not self.workspace_id:
            return {"success": False, "error": "Workspace not configured"}

        call_id: uuid.UUID | None = None
        if call_id_str:
            import contextlib

            with contextlib.suppress(ValueError):
                call_id = uuid.UUID(call_id_str)

        self.log.info("categorize_start", tree_name=tree_name, text_len=len(text))

        try:
            from sqlalchemy import select

            from app.models.category_tree import CategoryResult, CategoryTree
            from app.services.category_matcher import match_category

            matched_node, confidence, layer = await match_category(
                db=self.db,
                workspace_id=self.workspace_id,
                tree_name=tree_name,
                text=text,
                user_id=self.user_id,
                top_k=1,
                openai_api_key=self.openai_api_key,
            )

            # Build path
            path: list[str] = []
            code = None
            label = None
            depth = 0

            if matched_node:
                code = matched_node.code
                label = matched_node.label
                depth = matched_node.depth

                # Load all nodes to reconstruct path
                all_result = await self.db.execute(
                    select(CategoryTree).where(
                        CategoryTree.workspace_id == self.workspace_id,
                        CategoryTree.tree_name == tree_name,
                        CategoryTree.status == "active",
                    )
                )
                all_nodes: dict[uuid.UUID, CategoryTree] = {
                    n.id: n for n in all_result.scalars().all()
                }
                current: CategoryTree | None = matched_node
                while current is not None:
                    path.insert(0, current.label)
                    if current.parent_id is None:
                        break
                    current = all_nodes.get(current.parent_id)

            # Write audit row
            result_row = CategoryResult(
                id=uuid.uuid4(),
                call_id=call_id,
                workspace_id=self.workspace_id,
                agent_id=self.agent_id,
                tree_name=tree_name,
                matched_node_id=matched_node.id if matched_node else None,
                matched_code=code,
                matched_path=path if path else None,
                input_text=text,
                confidence=confidence,
                resolution_layer=layer,
                created_at=datetime.now(UTC),
            )
            self.db.add(result_row)
            await self.db.commit()

            self.log.info(
                "categorize_done",
                matched=matched_node is not None,
                layer=layer,
                label=label,
            )

            return {
                "success": True,
                "matched": matched_node is not None,
                "code": code,
                "label": label,
                "path": path,
                "depth": depth,
                "confidence": confidence,
                "resolution_layer": layer,
                "result_id": str(result_row.id),
            }

        except Exception:
            self.log.exception("categorize_error", tree_name=tree_name)
            return {"success": False, "error": "Categorization failed due to an internal error"}
