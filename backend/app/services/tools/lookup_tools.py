"""Lookup tools for voice agents — structured data query over JSONB collections."""

import uuid
from typing import Any

import structlog
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lookup import LookupCollection, LookupRecord

logger = structlog.get_logger()

_TRGM_THRESHOLD = 0.35  # pg_trgm similarity threshold for ASR error tolerance


class LookupTools:
    """Query structured data collections (properties, FAQs, products, staff, etc.).

    Uses Postgres FTS (search_vector) with ILIKE fallback — no embeddings, sub-10 ms,
    zero API cost.
    """

    def __init__(
        self,
        db: AsyncSession,
        user_id: int,
        workspace_id: uuid.UUID | None = None,
    ) -> None:
        """Initialise LookupTools.

        Args:
            db: Async database session.
            user_id: Owner user ID (integer matching users.id).
            workspace_id: Workspace UUID for multi-tenant scoping.
        """
        self.db = db
        self.user_id = user_id
        self.workspace_id = workspace_id
        self.log = logger.bind(
            component="lookup_tools",
            user_id=user_id,
            workspace_id=str(workspace_id),
        )

    # ------------------------------------------------------------------
    # Tool definitions (OpenAI Realtime function calling format)
    # ------------------------------------------------------------------

    @staticmethod
    def get_tool_definitions() -> list[dict[str, Any]]:
        """Return OpenAI function-calling tool definitions for the Realtime API."""
        return [
            {
                "type": "function",
                "name": "lookup_search",
                "description": (
                    "Search structured data collections (properties, FAQs, products, staff, etc.) "
                    "by keyword. Returns matching records with their full data payload."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Natural language or keyword query to search for.",
                        },
                        "domain": {
                            "type": "string",
                            "description": (
                                "Optional domain filter: property | faq | product | staff | custom:*"
                            ),
                        },
                        "collection_id": {
                            "type": "string",
                            "description": "Optional UUID — restrict search to one collection.",
                        },
                        "field": {
                            "type": "string",
                            "description": (
                                "Optional — return only this key from matched records' data "
                                "(e.g. 'price' or 'address')."
                            ),
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum results to return (default 3, max 10).",
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "type": "function",
                "name": "lookup_list_collections",
                "description": (
                    "List all active data collections available to search in this workspace."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        ]

    # ------------------------------------------------------------------
    # Tool execution router
    # ------------------------------------------------------------------

    async def execute_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Route a tool call to the appropriate handler.

        Args:
            tool_name: One of lookup_search | lookup_list_collections.
            arguments: Tool arguments dict.

        Returns:
            Result dict with success flag and data/error.
        """
        if tool_name == "lookup_search":
            return await self._lookup_search(arguments)
        if tool_name == "lookup_list_collections":
            return await self._lookup_list_collections()
        return {"success": False, "error": f"Unknown lookup tool: {tool_name}"}

    # ------------------------------------------------------------------
    # Private handlers
    # ------------------------------------------------------------------

    async def _lookup_search(self, arguments: dict[str, Any]) -> dict[str, Any]:  # noqa: PLR0912, PLR0915
        """Full-text search over LookupRecords with optional filters."""
        query_str: str = arguments.get("query", "").strip()
        domain: str | None = arguments.get("domain")
        collection_id_str: str | None = arguments.get("collection_id")
        field: str | None = arguments.get("field")
        limit: int = min(int(arguments.get("limit", 3)), 10)

        if not query_str:
            return {"success": False, "error": "query is required"}

        self.log.info("lookup_search", query=query_str, domain=domain, limit=limit)

        try:
            # Parse collection_id UUID
            collection_id: uuid.UUID | None = None
            if collection_id_str:
                try:
                    collection_id = uuid.UUID(collection_id_str)
                except ValueError:
                    return {"success": False, "error": "Invalid collection_id UUID"}

            # Base query: join records → collections
            stmt = (
                select(
                    LookupRecord.id,
                    LookupRecord.title,
                    LookupRecord.data,
                    LookupCollection.name.label("collection_name"),
                    LookupCollection.domain,
                )
                .join(LookupCollection, LookupRecord.collection_id == LookupCollection.id)
                .where(LookupCollection.is_active.is_(True))
            )

            # Workspace / user scoping
            # Always scope by user_id; if workspace_id is set, also include workspace collections
            if self.workspace_id:
                stmt = stmt.where(
                    or_(
                        LookupCollection.workspace_id == self.workspace_id,
                        LookupCollection.user_id == self.user_id,
                    )
                )
            else:
                stmt = stmt.where(LookupCollection.user_id == self.user_id)

            # Domain filter
            if domain:
                stmt = stmt.where(LookupCollection.domain == domain)

            # Collection filter
            if collection_id:
                stmt = stmt.where(LookupRecord.collection_id == collection_id)

            # FTS search — AND logic (all words must match)
            # Use 'simple' dictionary (lowercase only, no stemming) so non-English
            # content like Swedish is not mangled by English stemming rules.
            tsquery_expr = func.plainto_tsquery("simple", query_str)
            fts_stmt = (
                stmt.where(LookupRecord.search_vector.op("@@")(tsquery_expr))
                .order_by(func.ts_rank(LookupRecord.search_vector, tsquery_expr).desc())
                .limit(limit)
            )
            result = await self.db.execute(fts_stmt)
            rows = result.fetchall()

            # Fallback 1: FTS OR logic — any word in the query can match
            if not rows:
                words = [w.strip(".,!?") for w in query_str.split() if len(w.strip(".,!?")) > 2]  # noqa: PLR2004
                for word in words:
                    word_tsq = func.plainto_tsquery("simple", word)
                    word_fts_stmt = (
                        stmt.where(LookupRecord.search_vector.op("@@")(word_tsq))
                        .order_by(func.ts_rank(LookupRecord.search_vector, word_tsq).desc())
                        .limit(limit)
                    )
                    result = await self.db.execute(word_fts_stmt)
                    rows = result.fetchall()
                    if rows:
                        break

            # Fallback 2: ILIKE on title — try full query then individual words
            if not rows:
                fallback_stmt = stmt.where(LookupRecord.title.ilike(f"%{query_str}%")).limit(limit)
                result = await self.db.execute(fallback_stmt)
                rows = result.fetchall()

            if not rows:
                words = [w.strip(".,!?") for w in query_str.split() if len(w.strip(".,!?")) > 2]  # noqa: PLR2004
                for word in words:
                    fallback_stmt = stmt.where(LookupRecord.title.ilike(f"%{word}%")).limit(limit)
                    result = await self.db.execute(fallback_stmt)
                    rows = result.fetchall()
                    if rows:
                        break

            # Fallback 3: Trigram similarity on title — handles ASR 1-2 char
            # transcription errors (e.g. "Hindebanan" → "Hinderbanan", similarity ≈ 0.77).
            # Requires pg_trgm extension (migration 038). Threshold 0.35 tolerates
            # short strings with up to ~2 char differences without false positives;
            # workspace/user scoping already narrows the candidate set significantly.
            if not rows:
                trgm_stmt = (
                    stmt.where(func.similarity(LookupRecord.title, query_str) >= _TRGM_THRESHOLD)
                    .order_by(func.similarity(LookupRecord.title, query_str).desc())
                    .limit(limit)
                )
                result = await self.db.execute(trgm_stmt)
                rows = result.fetchall()

            if not rows:
                return {
                    "success": True,
                    "results": [],
                    "message": f"No records found for '{query_str}'",
                }

            records = []
            for row in rows:
                data = row.data or {}
                if field:
                    data = {field: data.get(field)}
                records.append(
                    {
                        "title": row.title,
                        "data": data,
                        "collection_name": row.collection_name,
                        "domain": row.domain,
                    }
                )

            return {"success": True, "results": records, "count": len(records)}

        except Exception:
            self.log.exception("lookup_search_error", query=query_str)
            return {"success": False, "error": "Lookup search failed due to an internal error"}

    async def _lookup_list_collections(self) -> dict[str, Any]:
        """Return all active collections for the current workspace."""
        self.log.info("lookup_list_collections")

        try:
            stmt = (
                select(
                    LookupCollection.id,
                    LookupCollection.name,
                    LookupCollection.domain,
                    LookupCollection.use_case_tag,
                    func.count(LookupRecord.id).label("record_count"),
                )
                .outerjoin(LookupRecord, LookupRecord.collection_id == LookupCollection.id)
                .where(LookupCollection.is_active.is_(True))
                .group_by(
                    LookupCollection.id,
                    LookupCollection.name,
                    LookupCollection.domain,
                    LookupCollection.use_case_tag,
                )
            )

            if self.workspace_id:
                stmt = stmt.where(LookupCollection.workspace_id == self.workspace_id)
            else:
                stmt = stmt.where(LookupCollection.user_id == self.user_id)

            result = await self.db.execute(stmt)
            rows = result.fetchall()

            collections = [
                {
                    "id": str(row.id),
                    "name": row.name,
                    "domain": row.domain,
                    "use_case_tag": row.use_case_tag,
                    "record_count": row.record_count,
                }
                for row in rows
            ]

            return {"success": True, "collections": collections, "count": len(collections)}

        except Exception:
            self.log.exception("lookup_list_collections_error")
            return {"success": False, "error": "Failed to list collections"}
