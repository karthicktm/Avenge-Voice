"""Web search tools for voice agents using DuckDuckGo."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import structlog
from duckduckgo_search import DDGS

logger = structlog.get_logger()

# Thread pool for running sync DuckDuckGo search
_executor = ThreadPoolExecutor(max_workers=4)


class WebSearchTools:
    """Free web search for voice agents using DuckDuckGo.

    No API key required - uses DuckDuckGo's free search API.
    """

    def __init__(self) -> None:
        """Initialize web search tools.

        No API key needed for DuckDuckGo.
        """
        self.logger = logger.bind(component="web_search_tools")

    @staticmethod
    def get_tool_definitions() -> list[dict[str, Any]]:
        """Get OpenAI function calling tool definitions.

        Returns:
            List of tool definitions for GPT Realtime API
        """
        return [
            {
                "type": "function",
                "name": "web_search",
                "description": "Search the web for real-time information. Use this to find current news, facts, product info, or any information not in your training data.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query to look up on the web",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of results to return (default 3, max 5)",
                        },
                    },
                    "required": ["query"],
                },
            },
        ]

    def _sync_search(self, query: str, max_results: int) -> list[dict[str, Any]]:
        """Synchronous search using DDGS (runs in thread pool)."""
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        return results

    async def web_search(
        self,
        query: str,
        max_results: int = 3,
    ) -> dict[str, Any]:
        """Search the web using DuckDuckGo.

        Args:
            query: Search query
            max_results: Maximum results to return (default 3, max 5)

        Returns:
            Search results with title, URL, and snippet
        """
        try:
            # Limit max_results to prevent excessive API usage
            max_results = min(max_results, 5)

            self.logger.info("web_search_started", query=query, max_results=max_results)

            # Run sync search in thread pool
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                _executor,
                self._sync_search,
                query,
                max_results,
            )

            if not results:
                return {
                    "success": True,
                    "found": False,
                    "message": f"No results found for '{query}'",
                    "results": [],
                }

            # Format results for voice agent consumption
            formatted_results = [
                {
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", ""),
                }
                for r in results
            ]

            self.logger.info(
                "web_search_completed",
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
            self.logger.exception("web_search_failed", query=query, error=str(e))
            return {
                "success": False,
                "error": f"Web search failed: {e!s}",
            }

    async def execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a web search tool by name.

        Args:
            tool_name: Tool name
            arguments: Tool arguments

        Returns:
            Tool result
        """
        if tool_name == "web_search":
            return await self.web_search(**arguments)
        return {"success": False, "error": f"Unknown tool: {tool_name}"}
