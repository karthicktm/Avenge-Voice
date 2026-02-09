"""Web search tools for voice agents using DuckDuckGo."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import urlparse

import structlog
from duckduckgo_search import DDGS

logger = structlog.get_logger()

# Thread pool for running sync DuckDuckGo search
_executor = ThreadPoolExecutor(max_workers=4)


class WebSearchTools:
    """Free web search for voice agents using DuckDuckGo.

    No API key required - uses DuckDuckGo's free search API.
    Supports domain restriction to search only within a specific website.
    """

    def __init__(self, search_domain: str | None = None) -> None:
        """Initialize web search tools.

        Args:
            search_domain: Optional domain to restrict searches to (e.g., "example.com").
                          If provided, all searches will be limited to this domain.
                          Can be a full URL or just a domain name.
        """
        self.search_domain = self._normalize_domain(search_domain)
        self.logger = logger.bind(
            component="web_search_tools",
            search_domain=self.search_domain,
        )

    @staticmethod
    def _normalize_domain(domain: str | None) -> str | None:
        """Normalize domain input to a clean domain name.

        Args:
            domain: Domain string (can be URL like "https://example.com/path" or just "example.com")

        Returns:
            Clean domain name or None
        """
        if not domain:
            return None

        domain = domain.strip()
        if not domain:
            return None

        # If it looks like a URL, parse it
        if "://" in domain:
            parsed = urlparse(domain)
            domain = parsed.netloc or parsed.path
        else:
            # Remove any path components
            domain = domain.split("/")[0]

        # Remove www. prefix for cleaner searches
        if domain.startswith("www."):
            domain = domain[4:]

        return domain.lower() if domain else None

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Get OpenAI function calling tool definitions.

        Returns:
            List of tool definitions for GPT Realtime API
        """
        # Customize description based on whether domain restriction is configured
        if self.search_domain:
            description = f"Search {self.search_domain} for information. Use this to find content, FAQs, product details, or any information from this website."
        else:
            description = "Search the web for real-time information. Use this to find current news, facts, product info, or any information not in your training data."

        return [
            {
                "type": "function",
                "name": "web_search",
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query to look up",
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

    def _build_search_query(self, query: str) -> str:
        """Build search query with optional domain restriction.

        Args:
            query: User's search query

        Returns:
            Query with site: operator if domain is configured
        """
        if self.search_domain:
            # Use DuckDuckGo's site: operator to restrict to domain
            return f"site:{self.search_domain} {query}"
        return query

    async def web_search(
        self,
        query: str,
        max_results: int = 3,
    ) -> dict[str, Any]:
        """Search the web using DuckDuckGo.

        If a search_domain is configured, searches are restricted to that domain only.

        Args:
            query: Search query
            max_results: Maximum results to return (default 3, max 5)

        Returns:
            Search results with title, URL, and snippet
        """
        try:
            # Limit max_results to prevent excessive API usage
            max_results = min(max_results, 5)

            # Build query with domain restriction if configured
            search_query = self._build_search_query(query)

            self.logger.info(
                "web_search_started",
                query=query,
                search_query=search_query,
                search_domain=self.search_domain,
                max_results=max_results,
            )

            # Run sync search in thread pool
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                _executor,
                self._sync_search,
                search_query,
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
