"""Site indexer service — BFS-crawls a website and indexes pages into the knowledge base."""

import uuid
from collections import deque
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
import structlog
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.services.rag_service import RAGService

logger = structlog.get_logger()

_USER_AGENT = "Mozilla/5.0 (compatible; AvengeVoiceAgent/1.0; +https://avenge.ai)"
_FETCH_TIMEOUT = 10.0


def _extract_clean_text(html: str) -> str:
    """Extract readable text from HTML."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "iframe"]):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.find(role="main")
    source = main if main else soup.body if soup.body else soup
    text = source.get_text(separator="\n", strip=True)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


def _extract_title(html: str) -> str:
    """Extract page title from HTML."""
    soup = BeautifulSoup(html, "lxml")
    title_tag = soup.find("title")
    if title_tag:
        return title_tag.get_text(strip=True)[:200]
    return "Untitled"


def _extract_internal_links(html: str, base_url: str) -> list[str]:
    """Extract same-domain links from HTML."""
    soup = BeautifulSoup(html, "lxml")
    parsed_base = urlparse(base_url)
    base_domain = parsed_base.netloc.lower().removeprefix("www.")

    links: list[str] = []
    seen: set[str] = set()

    for a_tag in soup.find_all("a", href=True):
        raw_href = a_tag.get("href", "")
        href = str(raw_href) if not isinstance(raw_href, str) else raw_href
        if href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue

        full_url = urljoin(base_url, href)
        parsed = urlparse(full_url)
        link_domain = parsed.netloc.lower().removeprefix("www.")
        if link_domain != base_domain:
            continue

        clean_url = parsed._replace(fragment="").geturl()
        if clean_url in seen:
            continue
        seen.add(clean_url)

        path_lower = parsed.path.lower()
        if any(
            path_lower.endswith(ext)
            for ext in (".jpg", ".jpeg", ".png", ".gif", ".svg", ".pdf", ".css", ".js", ".zip")
        ):
            continue

        links.append(clean_url)

    return links


async def _fetch_page(url: str) -> tuple[str, str] | None:
    """Fetch a page. Returns (html, final_url) or None."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                url,
                timeout=_FETCH_TIMEOUT,
                follow_redirects=True,
                headers={
                    "User-Agent": _USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
            )
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            if "text/html" not in content_type and "application/xhtml" not in content_type:
                return None
            return resp.text, str(resp.url)
    except Exception as exc:
        logger.warning("site_indexer_fetch_failed", url=url, error=str(exc))
        return None


class SiteIndexer:
    """BFS-crawls a website and indexes pages into the knowledge base.

    Pages are stored as Document records with source_type='web_crawl',
    then processed through the existing RAG pipeline (chunking, translation,
    embedding).
    """

    def __init__(
        self,
        db: AsyncSession,
        agent_id: uuid.UUID,
        embedding_config: dict[str, Any] | None = None,
    ) -> None:
        self.db = db
        self.agent_id = agent_id
        self.embedding_config = embedding_config
        self.logger = logger.bind(
            component="site_indexer",
            agent_id=str(agent_id),
        )

    async def update_last_crawl_at(self) -> None:
        """Update agent's tool_configs with current timestamp after crawl."""
        from app.models.agent import Agent

        result = await self.db.execute(select(Agent).where(Agent.id == self.agent_id))
        agent = result.scalar_one()
        configs = dict(agent.tool_configs or {})
        site_config = dict(configs.get("site_search", {}))
        site_config["last_crawl_at"] = datetime.now(UTC).isoformat()
        configs["site_search"] = site_config
        agent.tool_configs = configs
        await self.db.commit()

    async def crawl_and_index(
        self,
        site_url: str,
        max_pages: int = 50,
    ) -> dict[str, Any]:
        """BFS-crawl a website and index pages into the knowledge base.

        Args:
            site_url: Starting URL to crawl
            max_pages: Maximum pages to crawl (default 50)

        Returns:
            Summary with pages_crawled, pages_indexed, errors
        """
        self.logger.info("site_indexer_started", site_url=site_url, max_pages=max_pages)

        # Delete previous web_crawl documents for this agent and domain
        parsed = urlparse(site_url)
        domain = parsed.netloc.lower().removeprefix("www.")
        await self._delete_previous_crawl(domain)

        # BFS crawl
        visited: set[str] = set()
        queue: deque[str] = deque([site_url])
        pages: list[dict[str, str]] = []
        errors: list[str] = []

        while queue and len(pages) < max_pages:
            url = queue.popleft()
            if url in visited:
                continue
            visited.add(url)

            result = await _fetch_page(url)
            if result is None:
                errors.append(url)
                continue

            html, final_url = result
            title = _extract_title(html)
            content = _extract_clean_text(html)

            min_content_length = 50
            if len(content) < min_content_length:
                continue

            pages.append(
                {
                    "url": final_url,
                    "title": title,
                    "content": content,
                }
            )

            # Discover new links
            new_links = _extract_internal_links(html, final_url)
            for link in new_links:
                if link not in visited:
                    queue.append(link)

        self.logger.info(
            "site_indexer_crawl_complete",
            pages_found=len(pages),
            urls_visited=len(visited),
        )

        # Index pages into knowledge base
        indexed = 0
        rag_service = RAGService(self.db, embedding_config=self.embedding_config)

        for page in pages:
            try:
                await self._index_page(rag_service, page)
                indexed += 1
            except Exception as exc:
                self.logger.warning(
                    "site_indexer_page_index_failed",
                    url=page["url"],
                    error=str(exc),
                )
                errors.append(page["url"])

        summary = {
            "pages_crawled": len(pages),
            "pages_indexed": indexed,
            "errors": len(errors),
            "domain": domain,
        }
        self.logger.info("site_indexer_completed", **summary)
        return summary

    async def _delete_previous_crawl(self, domain: str) -> None:
        """Delete previous web_crawl documents for this agent matching the domain."""
        result = await self.db.execute(
            select(Document).where(
                Document.agent_id == self.agent_id,
                Document.source_type == "web_crawl",
                Document.source_url.ilike(f"%{domain}%"),
            )
        )
        old_docs = list(result.scalars().all())
        if old_docs:
            rag_service = RAGService(self.db, embedding_config=self.embedding_config)
            for doc in old_docs:
                await rag_service.delete_document(doc.id)
            self.logger.info("site_indexer_deleted_previous", count=len(old_docs))

    async def _index_page(
        self,
        rag_service: RAGService,
        page: dict[str, str],
    ) -> None:
        """Create a Document record for a crawled page and process it."""
        content_bytes = page["content"].encode("utf-8")
        title = page["title"][:200]
        url = page["url"]

        # Create document record
        document = Document(
            agent_id=self.agent_id,
            filename=f"{title}.txt",
            file_type="txt",
            file_size=len(content_bytes),
            source_type="web_crawl",
            source_url=url,
            status="pending",
        )
        self.db.add(document)
        await self.db.commit()
        await self.db.refresh(document)

        # Process through RAG pipeline
        try:
            document.status = "processing"
            await self.db.commit()

            await rag_service.process_document(document.id, content_bytes)
        except Exception:
            # process_document handles its own error status updates
            self.logger.exception(
                "site_indexer_process_failed",
                document_id=str(document.id),
                url=url,
            )
            raise
