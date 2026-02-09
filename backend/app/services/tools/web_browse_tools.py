"""Web browsing tools for voice agents - fetch and extract content from URLs."""

import asyncio
import re
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
import structlog

logger = structlog.get_logger()


class WebBrowseTools:
    """Web browsing tools for voice agents.

    Allows agents to fetch URLs, extract content, and follow links
    to gather information from websites.
    """

    def __init__(self, allowed_domain: str | None = None) -> None:
        """Initialize web browse tools.

        Args:
            allowed_domain: Optional domain to restrict browsing to.
                           If provided, only URLs on this domain can be fetched.
        """
        self.allowed_domain = self._normalize_domain(allowed_domain)
        self.logger = logger.bind(
            component="web_browse_tools",
            allowed_domain=self.allowed_domain,
        )

    @staticmethod
    def _normalize_domain(domain: str | None) -> str | None:
        """Normalize domain input to a clean domain name."""
        if not domain:
            return None

        domain = domain.strip()
        if not domain:
            return None

        if "://" in domain:
            parsed = urlparse(domain)
            domain = parsed.netloc or parsed.path
        else:
            domain = domain.split("/")[0]

        if domain.startswith("www."):
            domain = domain[4:]

        return domain.lower() if domain else None

    @staticmethod
    def get_tool_definitions() -> list[dict[str, Any]]:
        """Get OpenAI function calling tool definitions."""
        return [
            {
                "type": "function",
                "name": "browse_website",
                "description": (
                    "REQUIRED: Fetch real information from websites. "
                    "When users ask about apartments, availability, products, services, prices, or ANY factual information, "
                    "you MUST call this tool FIRST to get the actual current data. "
                    "Use fetch_all_pages=true when looking for specific items that might be on different pages. "
                    "CRITICAL: After receiving the tool response, you MUST share the fetched information directly with the user. "
                    "NEVER tell users to 'check the website themselves' - YOU have the data, so YOU must share it."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "The full URL to browse (e.g., 'https://example.com/page')",
                        },
                        "fetch_all_pages": {
                            "type": "boolean",
                            "description": "Set to true to automatically fetch paginated content (multiple pages). Use this when searching for specific listings or items.",
                        },
                        "extract_links": {
                            "type": "boolean",
                            "description": "Whether to extract and return links found on the page (default: false)",
                        },
                    },
                    "required": ["url"],
                },
            },
            {
                "type": "function",
                "name": "extract_page_data",
                "description": (
                    "Extract structured data from a webpage like listings, products, or articles. "
                    "Use this to find specific items like apartment listings, product catalogs, etc. "
                    "CRITICAL: Share the extracted data with the user - never tell them to check the website."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "The URL to extract data from",
                        },
                        "data_type": {
                            "type": "string",
                            "enum": ["listings", "article", "contact", "general"],
                            "description": "Type of data to extract: 'listings' for property/product lists, 'article' for text content, 'contact' for contact info, 'general' for everything",
                        },
                    },
                    "required": ["url"],
                },
            },
        ]

    def _is_url_allowed(self, url: str) -> bool:
        """Check if URL is allowed based on domain restriction."""
        if not self.allowed_domain:
            return True

        parsed = urlparse(url)
        url_domain = parsed.netloc.lower()
        if url_domain.startswith("www."):
            url_domain = url_domain[4:]

        return url_domain == self.allowed_domain

    async def _fetch_page(self, url: str) -> tuple[str, str]:
        """Fetch a page and return (html, final_url)."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                timeout=15.0,
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9,sv;q=0.8",
                },
            )
            response.raise_for_status()
            return response.text, str(response.url)

    def _extract_text_content(self, html: str, main_only: bool = False) -> str:
        """Extract readable text from HTML.

        Args:
            html: The HTML content
            main_only: If True, try to extract only main content area (skip nav/footer)
        """
        text = html

        # Remove script and style elements
        text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<noscript[^>]*>.*?</noscript>", "", text, flags=re.DOTALL | re.IGNORECASE)

        # Remove navigation, header, footer elements when extracting main content only
        if main_only:
            text = re.sub(r"<header[^>]*>.*?</header>", "", text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r"<footer[^>]*>.*?</footer>", "", text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r"<nav[^>]*>.*?</nav>", "", text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(
                r'<[^>]*class="[^"]*(?:menu|nav|header|footer|sidebar)[^"]*"[^>]*>.*?</\w+>',
                "",
                text,
                flags=re.DOTALL | re.IGNORECASE,
            )

        # Remove HTML comments
        text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)

        # Replace common elements with newlines for better structure
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"</p>|</div>|</li>|</h[1-6]>", "\n", text, flags=re.IGNORECASE)

        # Remove remaining HTML tags
        text = re.sub(r"<[^>]+>", " ", text)

        # Decode common HTML entities
        text = text.replace("&nbsp;", " ")
        text = text.replace("&amp;", "&")
        text = text.replace("&lt;", "<")
        text = text.replace("&gt;", ">")
        text = text.replace("&quot;", '"')
        text = text.replace("&#39;", "'")

        # Clean up whitespace
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n\s*\n+", "\n\n", text)
        text = text.strip()

        return text

    def _extract_title(self, html: str) -> str:
        """Extract page title from HTML."""
        match = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return "Untitled"

    def _extract_links(self, html: str, base_url: str) -> list[dict[str, str]]:
        """Extract links from HTML."""
        links = []
        seen_urls = set()

        for match in re.finditer(
            r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>([^<]*)</a>', html, re.IGNORECASE
        ):
            href = match.group(1)
            text = match.group(2).strip()

            # Skip empty, anchor, or javascript links
            if not href or href.startswith(("#", "javascript:")):
                continue

            # Make absolute URL
            full_url = urljoin(base_url, href)

            # Skip if already seen
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)

            # Only include allowed domain links if restricted
            if self.allowed_domain and not self._is_url_allowed(full_url):
                continue

            links.append({"url": full_url, "text": text or href})

        return links[:20]  # Limit to 20 links

    def _extract_pagination_urls(self, html: str, base_url: str, max_pages: int = 5) -> list[str]:
        """Extract pagination URLs from HTML (generic for any website)."""
        pagination_urls: list[str] = []
        seen_urls: set[str] = {base_url}

        # Common pagination URL patterns (covers most sites)
        url_patterns = [
            # WordPress/CMS style: /page/2/, /page/3/
            r'href=["\']([^"\']*?/page/(\d+)/?[^"\']*)["\']',
            # Query param style: ?page=2, ?p=2, ?paged=2, ?pg=2
            r'href=["\']([^"\']*[?&](?:page|p|paged|pg)=(\d+)[^"\']*)["\']',
            # Offset/start style: ?offset=10, ?start=10, ?from=10
            r'href=["\']([^"\']*[?&](?:offset|start|from|skip)=(\d+)[^"\']*)["\']',
            # E-commerce style: ?pageNumber=2, ?pageNum=2
            r'href=["\']([^"\']*[?&](?:pageNumber|pageNum|pagenumber)=(\d+)[^"\']*)["\']',
            # Simple numbered URLs: /2, /3 at the end
            r'href=["\']([^"\']*?/(\d+)/?)["\']',
        ]

        # Look for pagination container patterns (class-based)
        container_patterns = [
            r'<[^>]*class="[^"]*(?:pagination|paging|page-numbers|paginator)[^"]*"[^>]*>(.*?)</(?:div|nav|ul)>',
        ]

        # First try to find pagination container
        pagination_html = html
        for pattern in container_patterns:
            match = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
            if match:
                pagination_html = match.group(1)
                break

        # Extract URLs from pagination area (or full HTML if no container found)
        for pattern in url_patterns:
            for match in re.finditer(pattern, pagination_html, re.IGNORECASE):
                href = match.group(1)
                # Skip if it looks like a non-page link (images, assets, etc.)
                if re.search(r"\.(jpg|jpeg|png|gif|css|js|ico)(\?|$)", href, re.IGNORECASE):
                    continue

                full_url = urljoin(base_url, href)

                # Only include same-domain URLs
                if self.allowed_domain and not self._is_url_allowed(full_url):
                    continue

                # Skip if URL is same as base (just different fragment)
                if full_url.split("#")[0] == base_url.split("#")[0]:
                    continue

                if full_url not in seen_urls:
                    seen_urls.add(full_url)
                    pagination_urls.append(full_url)

        # Also look for "next" links by text content
        next_patterns = [
            r'<a[^>]*href=["\']([^"\']+)["\'][^>]*>(?:[^<]*(?:next|nästa|siguiente|suivant|weiter|次)[^<]*)</a>',
            r'<a[^>]*href=["\']([^"\']+)["\'][^>]*class="[^"]*next[^"]*"[^>]*>',
        ]
        for pattern in next_patterns:
            for match in re.finditer(pattern, html, re.IGNORECASE):
                href = match.group(1)
                full_url = urljoin(base_url, href)
                if self.allowed_domain and not self._is_url_allowed(full_url):
                    continue
                if full_url not in seen_urls:
                    seen_urls.add(full_url)
                    pagination_urls.append(full_url)

        # Sort by page number if possible, limit to max_pages
        def extract_page_num(url: str) -> int:
            # Try various patterns to extract page number
            patterns = [
                r"/page/(\d+)",
                r"[?&](?:page|p|paged|pg|pageNumber)=(\d+)",
                r"/(\d+)/?$",
            ]
            for p in patterns:
                match = re.search(p, url, re.IGNORECASE)
                if match:
                    return int(match.group(1))
            return 999

        pagination_urls.sort(key=extract_page_num)
        return pagination_urls[: max_pages - 1]  # -1 because we already have page 1

    def _extract_listings(self, html: str, base_url: str) -> list[dict[str, Any]]:
        """Extract listing-like content (apartments, products, etc.)."""
        listings = []

        # Look for common listing patterns
        # Pattern 1: Cards with links (common in property sites)
        card_patterns = [
            r'<article[^>]*class="[^"]*card[^"]*"[^>]*>(.*?)</article>',
            r'<div[^>]*class="[^"]*listing[^"]*"[^>]*>(.*?)</div>',
            r'<div[^>]*class="[^"]*property[^"]*"[^>]*>(.*?)</div>',
            r'<li[^>]*class="[^"]*item[^"]*"[^>]*>(.*?)</li>',
        ]

        for pattern in card_patterns:
            matches = re.findall(pattern, html, re.DOTALL | re.IGNORECASE)
            for match in matches[:10]:  # Limit per pattern
                # Extract title
                title_match = re.search(r"<h[1-6][^>]*>([^<]+)</h[1-6]>", match, re.IGNORECASE)
                title = title_match.group(1).strip() if title_match else ""

                # Extract link
                link_match = re.search(r'href=["\']([^"\']+)["\']', match)
                url = urljoin(base_url, link_match.group(1)) if link_match else ""

                # Extract any price-like text
                price_match = re.search(r"(\d[\d\s]*(?:kr|SEK|:-|€|\$))", match, re.IGNORECASE)
                price = price_match.group(1).strip() if price_match else ""

                # Extract location hints
                location_match = re.search(
                    r"(stockholm|göteborg|malmö|barkarby|solna|sundbyberg|[A-ZÅÄÖ][a-zåäö]+stad)",
                    match,
                    re.IGNORECASE,
                )
                location = location_match.group(1) if location_match else ""

                # Get text content
                text = self._extract_text_content(match)[:300]

                if title or text:
                    listings.append(
                        {
                            "title": title,
                            "url": url,
                            "price": price,
                            "location": location,
                            "description": text,
                        }
                    )

        # Deduplicate by title
        seen_titles = set()
        unique_listings = []
        for listing in listings:
            if listing["title"] and listing["title"] not in seen_titles:
                seen_titles.add(listing["title"])
                unique_listings.append(listing)

        return unique_listings[:15]

    async def browse_website(
        self,
        url: str,
        fetch_all_pages: bool = False,
        extract_links: bool = False,
    ) -> dict[str, Any]:
        """Browse a website and extract its content.

        Args:
            url: URL to browse
            fetch_all_pages: Whether to automatically fetch paginated content
            extract_links: Whether to extract links from the page

        Returns:
            Page content with title, text, and optionally links
        """
        try:
            # Validate URL
            if not url.startswith(("http://", "https://")):
                url = "https://" + url

            if not self._is_url_allowed(url):
                return {
                    "success": False,
                    "error": f"URL not allowed. Can only browse {self.allowed_domain}",
                }

            self.logger.info("browsing_website", url=url, fetch_all_pages=fetch_all_pages)

            # Fetch first page
            html, final_url = await self._fetch_page(url)
            title = self._extract_title(html)
            all_links: list[dict[str, str]] = []
            pages_fetched = 1

            if extract_links:
                all_links.extend(self._extract_links(html, final_url))

            # Limit per-page content to fit more pages while keeping key info
            per_page_limit = 2000

            first_page_content = self._extract_text_content(html, main_only=True)
            if len(first_page_content) > per_page_limit:
                first_page_content = first_page_content[:per_page_limit] + "..."
            all_content = [first_page_content]

            # Fetch additional pages if requested
            if fetch_all_pages:
                pagination_urls = self._extract_pagination_urls(html, final_url, max_pages=5)
                if pagination_urls:
                    self.logger.info(
                        "fetching_additional_pages",
                        count=len(pagination_urls),
                        urls=pagination_urls[:3],
                    )

                    # Fetch pages in parallel - extract only main content to avoid duplicates
                    async def fetch_page_content(page_url: str) -> str | None:
                        try:
                            page_html, _ = await self._fetch_page(page_url)
                            # Use main_only=True to skip nav/header/footer duplicates
                            content = self._extract_text_content(page_html, main_only=True)
                            # Limit each page to fit more pages in total
                            if len(content) > per_page_limit:
                                content = content[:per_page_limit] + "..."
                            return content
                        except Exception as e:
                            self.logger.warning("page_fetch_failed", url=page_url, error=str(e))
                            return None

                    tasks = [fetch_page_content(page_url) for page_url in pagination_urls]
                    results = await asyncio.gather(*tasks)

                    for page_content in results:
                        if page_content:
                            all_content.append(page_content)
                            pages_fetched += 1

            # Combine all content - each page's content limited
            raw_content = "\n\n".join(all_content)

            # Put instruction AT THE START of content so AI reads it first
            instruction_prefix = (
                f"[SYSTEM: You successfully fetched {pages_fetched} page(s) from {title}. "
                "The website content is below. You MUST now tell the user what you found. "
                "DO NOT say 'check the website' - you have the data, share it directly. "
                "List the specific items, names, locations, and details from the content below.]\n\n"
                "--- WEBSITE CONTENT ---\n\n"
            )
            combined_content = instruction_prefix + raw_content

            result: dict[str, Any] = {
                "success": True,
                "url": final_url,
                "title": title,
                "pages_fetched": pages_fetched,
                "content": combined_content,
            }

            if extract_links:
                result["links"] = all_links[:20]

            self.logger.info(
                "browse_completed",
                url=final_url,
                pages_fetched=pages_fetched,
                content_length=len(combined_content),
            )
            return result

        except httpx.HTTPStatusError as e:
            self.logger.warning("browse_http_error", url=url, status=e.response.status_code)
            return {
                "success": False,
                "error": f"Page not found or unavailable (HTTP {e.response.status_code})",
            }
        except Exception as e:
            self.logger.exception("browse_failed", url=url, error=str(e))
            return {"success": False, "error": f"Failed to browse: {e!s}"}

    async def extract_page_data(
        self,
        url: str,
        data_type: str = "general",
    ) -> dict[str, Any]:
        """Extract structured data from a webpage.

        Args:
            url: URL to extract data from
            data_type: Type of data to extract ('listings', 'article', 'contact', 'general')

        Returns:
            Extracted data based on type
        """
        try:
            if not url.startswith(("http://", "https://")):
                url = "https://" + url

            if not self._is_url_allowed(url):
                return {
                    "success": False,
                    "error": f"URL not allowed. Can only browse {self.allowed_domain}",
                }

            self.logger.info("extracting_data", url=url, data_type=data_type)

            html, final_url = await self._fetch_page(url)
            title = self._extract_title(html)

            result: dict[str, Any] = {
                "success": True,
                "url": final_url,
                "title": title,
                "data_type": data_type,
            }

            if data_type == "listings":
                listings = self._extract_listings(html, final_url)
                result["listings"] = listings
                result["count"] = len(listings)
                result["summary"] = f"Found {len(listings)} listings on the page"
                result["instruction"] = (
                    f"Share these {len(listings)} listings with the user. "
                    "Describe what you found - names, locations, prices, sizes if available. "
                    "Do NOT tell the user to check the website - you have the data."
                )
            elif data_type == "contact":
                content = self._extract_text_content(html)
                # Extract contact info patterns
                emails = re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", content)
                phones = re.findall(r"(?:\+46|0)[\d\s-]{8,12}", content)
                result["emails"] = list(set(emails))[:5]
                result["phones"] = list(set(phones))[:5]
                result["instruction"] = (
                    "Share the contact information with the user: "
                    f"emails: {result['emails']}, phones: {result['phones']}. "
                    "Do NOT tell them to find it themselves."
                )
            else:
                content = self._extract_text_content(html)
                max_length = 4000
                result["content"] = content[:max_length] + (
                    "..." if len(content) > max_length else ""
                )
                result["instruction"] = (
                    "Summarize the key information from this page for the user. "
                    "Share specific details and facts. Do NOT tell them to check it themselves."
                )

            self.logger.info("extraction_completed", url=final_url, data_type=data_type)
            return result

        except Exception as e:
            self.logger.exception("extraction_failed", url=url, error=str(e))
            return {"success": False, "error": f"Failed to extract data: {e!s}"}

    async def execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a web browse tool by name."""
        if tool_name == "browse_website":
            return await self.browse_website(**arguments)
        if tool_name == "extract_page_data":
            return await self.extract_page_data(**arguments)
        return {"success": False, "error": f"Unknown tool: {tool_name}"}
