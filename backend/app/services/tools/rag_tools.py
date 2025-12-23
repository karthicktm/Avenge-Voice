"""RAG (Retrieval Augmented Generation) tools for voice agents."""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.rag_service import RAGService


class RAGTools:
    """RAG tools for searching knowledge base during voice calls.

    These tools enable voice agents to search uploaded documents and provide
    accurate answers based on their custom knowledge base. Queries are automatically
    extracted from spoken conversation context.
    """

    def __init__(self, db: AsyncSession, agent_id: uuid.UUID):
        """Initialize RAG tools.

        Args:
            db: Async database session
            agent_id: UUID of the agent (for knowledge base isolation)
        """
        self.db = db
        self.agent_id = agent_id
        self.rag_service = RAGService(db)

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Get OpenAI function definitions for RAG tools.

        Returns:
            List of tool definitions in OpenAI format
        """
        return [
            {
                "type": "function",
                "name": "search_knowledge_base",
                "description": (
                    "Search the agent's knowledge base for relevant information. "
                    "Use this when the customer asks about products, services, policies, "
                    "documentation, or any information that might be in uploaded documents. "
                    "Automatically formulate a search query based on what the customer said. "
                    "Examples: refund policy, product features, shipping times, pricing, "
                    "technical specifications, company policies, etc."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": (
                                "Natural language search query. Extract key terms and concepts "
                                "from the customer's question to find relevant information. "
                                "Example: if customer asks 'How long does shipping take?', "
                                "use query like 'shipping delivery time duration estimate'"
                            ),
                        },
                        "top_k": {
                            "type": "integer",
                            "description": (
                                "Number of relevant results to return (1-10). "
                                "Use 3 for most questions, increase to 5-10 for complex topics "
                                "that might need more context."
                            ),
                            "minimum": 1,
                            "maximum": 10,
                            "default": 3,
                        },
                    },
                    "required": ["query"],
                },
            }
        ]

    async def search_knowledge_base(self, query: str, top_k: int = 3) -> dict[str, Any]:
        """Search agent's knowledge base using semantic similarity.

        This is the main RAG tool that gets called during voice conversations.
        The GPT model automatically extracts the search query from what the
        customer said and calls this function.

        Args:
            query: Natural language search query (automatically formulated by GPT)
            top_k: Number of results to return (default 3)

        Returns:
            Dictionary with search results formatted for voice response

        Example:
            Customer says: "What's your refund policy?"
            GPT calls: search_knowledge_base(query="refund policy return process")
            Returns: Relevant chunks from uploaded policy documents
            GPT speaks: "According to our policy, you can return items within 30 days..."
        """
        try:
            # Validate top_k
            top_k = max(1, min(10, top_k))

            # Search knowledge base
            results = await self.rag_service.search_knowledge_base(
                agent_id=self.agent_id,
                query=query,
                top_k=top_k,
            )

            if not results:
                return {
                    "success": True,
                    "results": [],
                    "message": (
                        "No relevant information found in the knowledge base. "
                        "You may need to provide a general answer or ask the customer "
                        "to contact support for more details."
                    ),
                    "query": query,
                }

            # Format results for voice response
            formatted_results = []
            sources = []

            for i, result in enumerate(results, 1):
                source = result["source"]
                text = result["text"]
                score = result["score"]

                # Add source to list (deduplicated)
                if source not in sources:
                    sources.append(source)

                # Format result with source attribution
                formatted_results.append(
                    f"[Result {i} from {source}] (relevance: {score:.2f})\n{text}"
                )

            # Combine results into natural text for voice
            results_text = "\n\n".join(formatted_results)

            return {
                "success": True,
                "results": results_text,
                "sources": sources,
                "total_results": len(results),
                "query": query,
                "message": (
                    f"Found {len(results)} relevant results from {len(sources)} document(s). "
                    "Use this information to answer the customer's question naturally. "
                    "Cite the source documents when appropriate."
                ),
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "message": (
                    "Failed to search knowledge base. Provide a general answer "
                    "or ask the customer to contact support."
                ),
                "query": query,
            }

    async def execute_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a RAG tool by name.

        Args:
            tool_name: Name of the tool to execute
            arguments: Tool arguments from GPT

        Returns:
            Tool execution result

        Raises:
            ValueError: If tool name is not recognized
        """
        if tool_name == "search_knowledge_base":
            query = arguments.get("query", "")
            top_k = arguments.get("top_k", 3)
            return await self.search_knowledge_base(query=query, top_k=top_k)
        else:
            raise ValueError(f"Unknown RAG tool: {tool_name}")
