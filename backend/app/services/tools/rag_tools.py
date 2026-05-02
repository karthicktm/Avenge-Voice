"""RAG tools for voice agents - knowledge base search."""

import uuid
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.rag_service import RAGService

logger = structlog.get_logger()


class RAGTools:
    """Knowledge Base tools for voice agents.

    Provides semantic search over uploaded documents
    to retrieve relevant information during calls.
    """

    def __init__(
        self,
        db: AsyncSession,
        agent_id: uuid.UUID,
        embedding_config: dict[str, Any] | None = None,
    ) -> None:
        """Initialize RAG tools.

        Args:
            db: Database session
            agent_id: Agent UUID for scoping searches
            embedding_config: Configuration for embedding provider with keys:
                - api_key: API key for embedding provider
                - embedding_model: Model name (e.g., text-embedding-3-small)
                - embedding_provider: Provider name (openai or voyage)
        """
        self.db = db
        self.agent_id = agent_id
        self.embedding_config = embedding_config
        self.rag_service = RAGService(db, embedding_config=embedding_config)
        self.logger = logger.bind(component="rag_tools", agent_id=str(agent_id))

    @staticmethod
    def get_tool_definitions() -> list[dict[str, Any]]:
        """Get OpenAI function calling tool definitions.

        Returns:
            List of tool definitions for GPT Realtime API
        """
        return [
            {
                "type": "function",
                "name": "search_knowledge_base",
                "description": "Search the knowledge base for information from uploaded documents. MUST be called before answering any factual question about company policies, rules, procedures, regulations, dates, deadlines, holidays, or any topic that may be covered in the uploaded materials. Also call for follow-up and clarifying questions — never answer from training data when the knowledge base may have the answer.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query to find relevant information. Be specific and use keywords.",
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "Number of relevant results to return (default 3, max 5)",
                        },
                    },
                    "required": ["query"],
                },
            },
        ]

    async def search_knowledge_base(
        self,
        query: str,
        top_k: int = 3,
    ) -> dict[str, Any]:
        """Search the knowledge base for relevant content.

        Args:
            query: Search query
            top_k: Number of results to return (default 3, max 5)

        Returns:
            Search results with relevant document excerpts
        """
        try:
            # Limit top_k
            top_k = min(top_k, 5)

            self.logger.warning(
                "knowledge_base_search_started",
                query=query,
                top_k=top_k,
            )

            results = await self.rag_service.search(
                agent_id=self.agent_id,
                query=query,
                top_k=top_k,
            )

            if not results:
                self.logger.warning(
                    "knowledge_base_search_empty",
                    query=query,
                    agent_id=str(self.agent_id),
                )
                return {
                    "success": True,
                    "found": False,
                    "message": f"No relevant information found for '{query}'",
                    "results": [],
                }

            # Format results for voice agent consumption
            formatted_results = [
                {
                    "content": r["content"],
                    "source": r["filename"],
                    "relevance": round(r["similarity"] * 100, 1),
                }
                for r in results
            ]

            self.logger.warning(
                "knowledge_base_search_completed",
                query=query,
                result_count=len(formatted_results),
            )

            return {
                "success": True,
                "found": True,
                "query": query,
                "result_count": len(formatted_results),
                "results": formatted_results,
            }

        except Exception as e:
            self.logger.exception("knowledge_base_search_failed", query=query, error=str(e))
            return {
                "success": False,
                "error": f"Knowledge base search failed: {e!s}",
            }

    async def execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a RAG tool by name.

        Args:
            tool_name: Tool name
            arguments: Tool arguments

        Returns:
            Tool result
        """
        if tool_name == "search_knowledge_base":
            return await self.search_knowledge_base(**arguments)
        return {"success": False, "error": f"Unknown tool: {tool_name}"}
