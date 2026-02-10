"""Site search tools for voice agents — LLM-powered website crawling and analysis."""

import asyncio
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
import structlog
from bs4 import BeautifulSoup

logger = structlog.get_logger()

# Limits for voice latency
_FETCH_TIMEOUT = 8.0
_LLM_TIMEOUT = 30.0
_MAX_CONTENT_PER_PAGE = 4000
_MAX_TOTAL_CONTENT = 50000
_MAX_LINKS = 50
_MAX_SELECTED_PAGES = 8
_MAX_DEPTH = 2  # How many hops deep to crawl from entry page

_USER_AGENT = "Mozilla/5.0 (compatible; AvengeVoiceAgent/1.0; +https://avenge.ai)"


def _extract_clean_text(html: str) -> str:
    """Extract readable text from HTML, stripping nav/footer/scripts."""
    soup = BeautifulSoup(html, "lxml")

    # Remove non-content elements
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "iframe"]):
        tag.decompose()

    # Prefer main content area
    main = soup.find("main") or soup.find("article") or soup.find(role="main")
    source = main if main else soup.body if soup.body else soup

    text = source.get_text(separator="\n", strip=True)
    # Collapse multiple blank lines
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


def _extract_internal_links(html: str, base_url: str) -> list[dict[str, str]]:
    """Extract same-domain links with anchor text."""
    soup = BeautifulSoup(html, "lxml")
    parsed_base = urlparse(base_url)
    base_domain = parsed_base.netloc.lower().removeprefix("www.")

    seen: set[str] = set()
    links: list[dict[str, str]] = []

    for a_tag in soup.find_all("a", href=True):
        raw_href = a_tag.get("href", "")
        href = str(raw_href) if not isinstance(raw_href, str) else raw_href
        if href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue

        full_url = urljoin(base_url, href)
        parsed = urlparse(full_url)

        # Same domain only
        link_domain = parsed.netloc.lower().removeprefix("www.")
        if link_domain != base_domain:
            continue

        # Normalize — strip fragment
        clean_url = parsed._replace(fragment="").geturl()
        if clean_url in seen:
            continue
        seen.add(clean_url)

        # Skip non-page resources
        path_lower = parsed.path.lower()
        if any(
            path_lower.endswith(ext)
            for ext in (".jpg", ".jpeg", ".png", ".gif", ".svg", ".pdf", ".css", ".js", ".zip")
        ):
            continue

        anchor_text = a_tag.get_text(strip=True) or clean_url
        links.append({"url": clean_url, "text": anchor_text[:120]})

        if len(links) >= _MAX_LINKS:
            break

    return links


def _extract_form_filters(html: str, base_url: str) -> str:
    """Extract GET form filters from HTML so the LLM can construct filtered URLs."""
    soup = BeautifulSoup(html, "lxml")
    forms_info: list[str] = []

    for form in soup.find_all("form", method=lambda m: m and m.upper() == "GET"):
        action = form.get("action", base_url)
        if isinstance(action, list):
            action = action[0]
        form_url = urljoin(base_url, str(action))

        selects = form.find_all("select")
        if not selects:
            continue

        parts = [f"Filter form at: {form_url}"]
        for sel in selects:
            name = sel.get("name", "unknown")
            options = []
            for opt in sel.find_all("option"):
                val = opt.get("value", "")
                label = opt.get_text(strip=True)
                if val:
                    options.append(f"{label} (value={val})")
            if options:
                parts.append(f"  Filter '{name}': {', '.join(options[:20])}")

        if len(parts) > 1:
            forms_info.append("\n".join(parts))

    return "\n\n".join(forms_info)


async def _fetch_page(url: str, request_timeout: float = _FETCH_TIMEOUT) -> str | None:
    """Fetch a single page. Returns HTML or None on failure."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                url,
                timeout=request_timeout,
                follow_redirects=True,
                headers={
                    "User-Agent": _USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9,sv;q=0.8",
                },
            )
            resp.raise_for_status()
            return resp.text
    except Exception as exc:
        logger.warning("site_search_fetch_failed", url=url, error=str(exc))
        return None


async def _llm_select_links(
    query: str,
    links: list[dict[str, str]],
    openai_api_key: str,
    page_context: str = "",
    filters_info: str = "",
) -> list[str]:
    """Ask GPT-4o-mini to pick the most relevant links for the query."""
    links_text = "\n".join(f"- {link['text']}  →  {link['url']}" for link in links)

    context_section = ""
    if page_context:
        context_section = f"\nCurrent page content summary:\n{page_context}\n"

    filters_section = ""
    if filters_info:
        filters_section = (
            f"\nThis page has filter forms. You can construct filtered URLs by appending "
            f"query parameters. For example: baseurl/?param=value&param2=value2\n\n"
            f"Available filters:\n{filters_info}\n"
        )

    prompt = (
        "You are a web navigation assistant. Given a user query and a list of links from a website, "
        "select up to 8 URLs most likely to contain information relevant to the query.\n"
        "The link text may be in any language — understand it regardless.\n\n"
        "IMPORTANT RULES:\n"
        "- If this is a listing or catalog page, you MUST include ALL numbered page links "
        "(e.g., '2', '3', 'Next', '»') because the answer could be on any page.\n"
        "- Include category, filter, and sub-section links that could narrow down to the answer.\n"
        "- Include links whose text or URL contains keywords related to the query.\n"
        "- When in doubt, include more links rather than fewer.\n"
        "- If filter forms are available and the query mentions a specific location, category, or "
        "type, you MAY construct a filtered URL using the available filter parameters. "
        "Add this constructed URL to your selection alongside regular links.\n\n"
        "Return ONLY a JSON array of the selected URLs, nothing else.\n\n"
        f"Query: {query}\n{context_section}{filters_section}\nLinks:\n{links_text}"
    )

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {openai_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0,
                    "max_tokens": 500,
                },
                timeout=_LLM_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            content: str = data["choices"][0]["message"]["content"]

            # Parse JSON array from response
            import json

            # Strip markdown code fences if present
            content = content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1] if "\n" in content else content[3:]
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()

            urls: list[str] = json.loads(content)
            return [u for u in urls if isinstance(u, str)][:_MAX_SELECTED_PAGES]
    except Exception as exc:
        logger.warning("site_search_llm_select_failed", error=f"{type(exc).__name__}: {exc}")
        # Fallback: return first 3 links
        return [link["url"] for link in links[:3]]


async def _llm_analyze_content(
    query: str,
    pages: list[dict[str, str]],
    openai_api_key: str,
    language: str,
    site_description: str | None,
) -> str:
    """Ask GPT-4o-mini to analyze fetched page content and answer the query."""
    # Build content block — distribute budget evenly so deeper pages aren't dropped
    per_page_budget = max(500, _MAX_TOTAL_CONTENT // max(len(pages), 1))
    content_parts: list[str] = []
    total_chars = 0
    for page in pages:
        remaining = _MAX_TOTAL_CONTENT - total_chars
        if remaining <= 0:
            break
        budget = min(per_page_budget, remaining)
        truncated = page["content"][:budget]
        content_parts.append(f"--- Page: {page['url']} ---\n{truncated}")
        total_chars += len(truncated)

    all_content = "\n\n".join(content_parts)

    site_ctx = f"\nSite description: {site_description}" if site_description else ""

    prompt = (
        f"You are helping a voice agent answer a caller's question about a website.{site_ctx}\n\n"
        f"The caller's query: {query}\n\n"
        f"Below is content fetched from the website. Analyze it and provide a concise, "
        f"structured answer with the most relevant information.\n\n"
        f"IMPORTANT: Respond in the language matching this locale: {language}\n"
        f"If the content is in a different language than the response language, translate the key information.\n"
        f"Be specific — include names, numbers, addresses, prices, dates when available.\n"
        f"If the information is not found, say so clearly.\n\n"
        f"Website content:\n{all_content}"
    )

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {openai_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 1000,
                },
                timeout=_LLM_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]  # type: ignore[no-any-return]
    except Exception as exc:
        logger.warning("site_search_llm_analyze_failed", error=f"{type(exc).__name__}: {exc}")
        # Fallback: return raw truncated content
        return all_content[:1500]


class SiteSearchTools:
    """LLM-powered site search for voice agents.

    Crawls a configured website, uses GPT-4o-mini to select relevant pages,
    then analyzes the content to answer the caller's query.
    """

    def __init__(
        self,
        site_url: str,
        site_description: str | None = None,
        openai_api_key: str | None = None,
        language: str = "en-US",
    ) -> None:
        self.site_url = site_url.rstrip("/")
        self.site_description = site_description
        self.openai_api_key = openai_api_key
        self.language = language
        self.logger = logger.bind(
            component="site_search_tools",
            site_url=self.site_url,
        )

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Get OpenAI function calling tool definitions."""
        parsed = urlparse(self.site_url)
        domain = parsed.netloc or parsed.path

        desc_parts = [
            f"IMPORTANT: You MUST use this tool to search {domain} whenever the user asks about "
            f"products, services, availability, pricing, locations, or ANY information that would be on this website. "
            f"Do NOT try to answer from memory — always search first to get accurate, up-to-date information.",
        ]
        if self.site_description:
            desc_parts.append(f"This website contains: {self.site_description}")

        return [
            {
                "type": "function",
                "name": "search_site",
                "description": " ".join(desc_parts),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "What to search for on the website — be specific",
                        },
                    },
                    "required": ["query"],
                },
            },
        ]

    async def search_site(self, query: str) -> dict[str, Any]:
        """Search the configured website using multi-hop LLM-powered crawling.

        Pipeline (repeated up to _MAX_DEPTH hops):
        1. Fetch entry page
        2. Extract internal links
        3. LLM selects most relevant links
        4. Fetch selected pages in parallel
        5. Extract links from newly fetched pages → repeat from step 3
        6. LLM analyzes all collected content and returns answer
        """
        self.logger.info("site_search_started", query=query)

        if not self.openai_api_key:
            return {
                "success": False,
                "error": "Site search requires an OpenAI API key for intelligent content analysis.",
            }

        # 1. Fetch entry page
        entry_html = await _fetch_page(self.site_url)
        if not entry_html:
            return {
                "success": False,
                "error": f"Could not fetch {self.site_url}",
            }

        # Track all fetched URLs and collected pages
        fetched_urls: set[str] = {self.site_url}
        entry_content = _extract_clean_text(entry_html)[:_MAX_CONTENT_PER_PAGE]
        pages: list[dict[str, str]] = [{"url": self.site_url, "content": entry_content}]

        # Collect links and form filters from entry page
        all_new_links = _extract_internal_links(entry_html, self.site_url)
        last_filters_info = _extract_form_filters(entry_html, self.site_url)
        self.logger.info("site_search_links_found", depth=0, count=len(all_new_links))

        # Multi-hop crawl: fetch pages, then discover deeper links
        last_page_content = entry_content

        for depth in range(_MAX_DEPTH):
            if not all_new_links:
                break

            # Filter out already-fetched URLs
            candidate_links = [link for link in all_new_links if link["url"] not in fetched_urls]
            if not candidate_links:
                break

            # Give LLM page content + filter forms so it can make smart choices
            page_summary = last_page_content[:500]

            # LLM selects relevant links with page context and filter info
            selected_urls = await _llm_select_links(
                query,
                candidate_links,
                self.openai_api_key,
                page_context=page_summary,
                filters_info=last_filters_info,
            )
            # Remove already-fetched (safety check)
            selected_urls = [u for u in selected_urls if u not in fetched_urls]
            if not selected_urls:
                break

            self.logger.info(
                "site_search_links_selected",
                depth=depth + 1,
                urls=selected_urls,
            )

            # Parallel page fetch
            fetch_tasks = [_fetch_page(url) for url in selected_urls]
            results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

            # Collect content and discover new links from fetched pages
            all_new_links = []
            last_page_content = ""
            last_filters_info = ""
            for url, result in zip(selected_urls, results, strict=True):
                fetched_urls.add(url)
                if not isinstance(result, str) or not result:
                    continue

                content = _extract_clean_text(result)[:_MAX_CONTENT_PER_PAGE]
                if content:
                    pages.append({"url": url, "content": content})
                    last_page_content = content

                # Extract links and filters from this page for the next hop
                page_links = _extract_internal_links(result, url)
                all_new_links.extend(page_links)
                page_filters = _extract_form_filters(result, url)
                if page_filters:
                    last_filters_info = page_filters

        self.logger.info("site_search_pages_fetched", count=len(pages))

        # Final step: LLM content analysis
        answer = await _llm_analyze_content(
            query=query,
            pages=pages,
            openai_api_key=self.openai_api_key,
            language=self.language,
            site_description=self.site_description,
        )

        self.logger.info(
            "site_search_completed",
            query=query,
            pages_analyzed=len(pages),
            answer_length=len(answer),
        )

        return {
            "success": True,
            "query": query,
            "pages_analyzed": len(pages),
            "answer": answer,
        }

    async def execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a site search tool by name."""
        if tool_name == "search_site":
            return await self.search_site(**arguments)
        return {"success": False, "error": f"Unknown tool: {tool_name}"}
