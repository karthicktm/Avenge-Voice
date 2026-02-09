"""Web search tools for voice agents using Tavily API with fallback."""

import asyncio
import os
import re
from typing import Any
from urllib.parse import urlparse

import httpx
import structlog

logger = structlog.get_logger()


class WebSearchTools:
    """Web search for voice agents using Tavily API.

    Tavily is designed specifically for AI applications and provides
    high-quality search results optimized for LLM consumption.

    Supports domain restriction to search only within a specific website.
    Falls back to direct URL fetching if Tavily API key is not available.
    """

    def __init__(
        self,
        search_domain: str | None = None,
        tavily_api_key: str | None = None,
        openai_api_key: str | None = None,
    ) -> None:
        """Initialize web search tools.

        Args:
            search_domain: Optional domain to restrict searches to (e.g., "example.com").
                          If provided, all searches will be limited to this domain.
                          Can be a full URL or just a domain name.
            tavily_api_key: Optional Tavily API key. If not provided, falls back to
                           TAVILY_API_KEY environment variable.
            openai_api_key: Optional OpenAI API key for using OpenAI's built-in web search.
                           If not provided, falls back to OPENAI_API_KEY environment variable.
        """
        self.search_domain = self._normalize_domain(search_domain)
        self.tavily_api_key = tavily_api_key or os.environ.get("TAVILY_API_KEY")
        self.openai_api_key = openai_api_key or os.environ.get("OPENAI_API_KEY")
        self.logger = logger.bind(
            component="web_search_tools",
            search_domain=self.search_domain,
            has_tavily_key=bool(self.tavily_api_key),
            has_openai_key=bool(self.openai_api_key),
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
            description = (
                f"IMPORTANT: You MUST use this tool to search {self.search_domain} whenever the user asks about "
                f"products, services, availability, pricing, locations, or ANY information that would be on this website. "
                f"Do NOT try to answer from memory - always search first to get accurate, up-to-date information from {self.search_domain}."
            )
        else:
            description = (
                "Search the web for real-time information. Use this tool whenever the user asks about "
                "current events, specific products, services, availability, prices, or any factual information "
                "that may have changed since your training. Always search to provide accurate, current information."
            )

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
                            "description": "The search query - be specific and include relevant keywords",
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

    async def _tavily_search(
        self, query: str, max_results: int, include_domains: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """Search using Tavily API.

        Args:
            query: Search query
            max_results: Maximum results
            include_domains: Optional list of domains to restrict search to

        Returns:
            List of search results
        """
        async with httpx.AsyncClient() as client:
            payload: dict[str, Any] = {
                "api_key": self.tavily_api_key,
                "query": query,
                "max_results": max_results,
                "search_depth": "advanced",
                "include_answer": True,
            }

            if include_domains:
                payload["include_domains"] = include_domains

            response = await client.post(
                "https://api.tavily.com/search",
                json=payload,
                timeout=15.0,
            )
            response.raise_for_status()
            data = response.json()

            results = []
            for r in data.get("results", []):
                results.append(
                    {
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "snippet": r.get("content", ""),
                    }
                )

            # Include Tavily's AI-generated answer if available
            if data.get("answer"):
                results.insert(
                    0,
                    {
                        "title": "Summary",
                        "url": "",
                        "snippet": data["answer"],
                    },
                )

            return results

    async def _openai_web_search(
        self, query: str, max_results: int, include_domains: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """Search using OpenAI's Responses API with built-in web_search.

        Args:
            query: Search query
            max_results: Maximum results (used for context, OpenAI controls actual count)
            include_domains: Optional list of domains to focus search on

        Returns:
            List of search results
        """
        # Modify query to include domain restriction if specified
        search_query = query
        if include_domains:
            domain_hint = f"Search only on {', '.join(include_domains)}: "
            search_query = domain_hint + query

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.openai.com/v1/responses",
                headers={
                    "Authorization": f"Bearer {self.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-4o-search-preview",
                    "tools": [{"type": "web_search"}],
                    "input": search_query,
                },
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()

            results = []

            # Extract search results from the response
            for item in data.get("output", []):
                if item.get("type") == "message":
                    content = item.get("content", [])
                    for c in content:
                        if c.get("type") == "text":
                            # The response text contains the search summary
                            results.append(
                                {
                                    "title": "Search Result",
                                    "url": "",
                                    "snippet": c.get("text", "")[:1000],
                                }
                            )
                            break

            # Also extract any annotations/citations
            for item in data.get("output", []):
                if item.get("type") == "message":
                    for c in item.get("content", []):
                        annotations = c.get("annotations", [])
                        for ann in annotations[:max_results]:
                            if ann.get("type") == "url_citation":
                                results.append(
                                    {
                                        "title": ann.get("title", "Source"),
                                        "url": ann.get("url", ""),
                                        "snippet": ann.get("text", ""),
                                    }
                                )

            return results[:max_results]

    async def _fetch_and_extract(self, url: str) -> dict[str, Any] | None:
        """Fetch a URL and extract text content.

        Args:
            url: URL to fetch

        Returns:
            Dict with title, url, and snippet or None if failed
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url,
                    timeout=10.0,
                    follow_redirects=True,
                    headers={
                        "User-Agent": "Mozilla/5.0 (compatible; VoiceAgent/1.0; +https://avenge.ai)"
                    },
                )
                response.raise_for_status()
                html = response.text

                # Simple title extraction
                title_match = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
                title = title_match.group(1).strip() if title_match else url

                # Extract text content (simple approach - remove tags)
                text = re.sub(
                    r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE
                )
                text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
                text = re.sub(r"<[^>]+>", " ", text)
                text = re.sub(r"\s+", " ", text).strip()

                # Take first part as snippet
                max_snippet_length = 500
                snippet = (
                    text[:max_snippet_length] + "..." if len(text) > max_snippet_length else text
                )

                return {"title": title, "url": str(response.url), "snippet": snippet}
        except Exception as e:
            self.logger.warning("fetch_failed", url=url, error=str(e))
            return None

    async def web_search(
        self,
        query: str,
        max_results: int = 3,
    ) -> dict[str, Any]:
        """Search the web using Tavily API.

        If a search_domain is configured, searches are restricted to that domain only.
        Falls back to direct URL fetching if Tavily is not available.

        Args:
            query: Search query
            max_results: Maximum results to return (default 3, max 5)

        Returns:
            Search results with title, URL, and snippet
        """
        try:
            # Limit max_results to prevent excessive API usage
            max_results = min(max_results, 5)

            self.logger.info(
                "web_search_started",
                query=query,
                search_domain=self.search_domain,
                max_results=max_results,
                using_openai=bool(self.openai_api_key),
                using_tavily=bool(self.tavily_api_key),
            )

            results: list[dict[str, Any]] = []
            include_domains = [self.search_domain] if self.search_domain else None

            if self.openai_api_key:
                # Use OpenAI's Responses API with built-in web search (preferred)
                self.logger.info("using_openai_web_search")
                try:
                    results = await self._openai_web_search(query, max_results, include_domains)
                except Exception as e:
                    self.logger.warning("openai_search_failed_falling_back", error=str(e))
                    # Fall through to Tavily or direct fetch

            if not results and self.tavily_api_key:
                # Use Tavily API as fallback
                self.logger.info("using_tavily_search")
                results = await self._tavily_search(query, max_results, include_domains)
            if not results and self.search_domain:
                # Fallback: Fetch relevant pages from the domain directly
                self.logger.info("using_direct_fetch_fallback")
                base_url = f"https://{self.search_domain}"

                # Try common URL patterns based on the query
                urls_to_try = [base_url]
                query_lower = query.lower()

                # Add query-based URL patterns
                query_slug = re.sub(r"[^a-z0-9]+", "-", query_lower).strip("-")
                urls_to_try.extend(
                    [
                        f"{base_url}/{query_slug}",
                        f"{base_url}/search?q={query}",
                        f"{base_url}/?s={query}",
                    ]
                )

                # Add common Swedish apartment-related URLs for housing sites
                if any(word in query_lower for word in ["apartment", "lägenhet", "bostad", "hyra"]):
                    urls_to_try.extend(
                        [
                            f"{base_url}/lediga-lagenheter",
                            f"{base_url}/bostader",
                            f"{base_url}/hyresbostader",
                        ]
                    )

                # Fetch pages in parallel
                tasks = [self._fetch_and_extract(url) for url in urls_to_try[:5]]
                fetched = await asyncio.gather(*tasks, return_exceptions=True)

                for result in fetched:
                    if isinstance(result, dict) and result:
                        results.append(result)
                    if len(results) >= max_results:
                        break
            if not results and not self.search_domain:
                # No search providers available and no domain to fetch
                return {
                    "success": False,
                    "error": "Web search requires OPENAI_API_KEY or TAVILY_API_KEY to be configured.",
                }

            if not results:
                return {
                    "success": True,
                    "found": False,
                    "message": f"No results found for '{query}'",
                    "results": [],
                }

            self.logger.info(
                "web_search_completed",
                query=query,
                result_count=len(results),
            )

            return {
                "success": True,
                "found": True,
                "query": query,
                "result_count": len(results),
                "results": results,
            }

        except httpx.HTTPStatusError as e:
            self.logger.exception(
                "web_search_http_error", query=query, status=e.response.status_code
            )
            return {
                "success": False,
                "error": f"Search API error: {e.response.status_code}",
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
