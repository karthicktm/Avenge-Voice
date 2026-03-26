"""Category tree enrichment — auto-generate example_query for nodes that lack one.

After a structured upload or on demand, this worker fetches every node in a
category tree, builds its full label path, then asks gpt-4o to produce a
compact set of search terms a caller might use to reach that node.

The generated terms are stored in node_metadata->>'example_query'.  The Postgres
trigger on category_trees automatically rebuilds search_vector to include them,
so FTS matching benefits immediately without any extra work.
"""

import uuid
from typing import Any

import structlog

logger = structlog.get_logger()

_MODEL = "gpt-4o"  # full model — runs once at upload, quality matters
_TERMS_PER_NODE = 10


async def enrich_example_queries(
    workspace_id: uuid.UUID,
    tree_name: str,
    user_id: int,
    openai_api_key: str,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Generate and persist example_query for every node that is missing one.

    Args:
        workspace_id: Workspace owning the tree.
        tree_name: Logical tree identifier.
        user_id: Integer user id — used to scope DB writes.
        openai_api_key: Key for gpt-4o calls.
        overwrite: If True, regenerate even for nodes that already have one.

    Returns:
        Summary dict with enriched / skipped / failed counts.
    """
    from openai import AsyncOpenAI
    from sqlalchemy import select

    from app.db.session import AsyncSessionLocal
    from app.models.category_tree import CategoryTree

    log = logger.bind(
        component="category_enrichment",
        workspace_id=str(workspace_id),
        tree_name=tree_name,
    )

    client = AsyncOpenAI(api_key=openai_api_key)
    enriched = skipped = failed = 0

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(CategoryTree).where(
                CategoryTree.workspace_id == workspace_id,
                CategoryTree.tree_name == tree_name,
                CategoryTree.status == "active",
            )
        )
        nodes = list(result.scalars().all())

        if not nodes:
            log.warning("enrich_no_nodes")
            return {"enriched": 0, "skipped": 0, "failed": 0}

        # Build id → node map and id → full label path
        node_map: dict[uuid.UUID, CategoryTree] = {n.id: n for n in nodes}
        paths: dict[uuid.UUID, list[str]] = {}
        for node in nodes:
            path: list[str] = []
            cur: CategoryTree | None = node
            while cur is not None:
                path.insert(0, cur.label)
                cur = node_map.get(cur.parent_id) if cur.parent_id else None
            paths[node.id] = path

        for node in nodes:
            meta = node.node_metadata or {}

            if not overwrite and meta.get("example_query"):
                skipped += 1
                continue

            path_str = " > ".join(paths[node.id])
            try:
                terms = await _generate_terms(path_str, client, log)
                if terms:
                    node.node_metadata = {**meta, "example_query": terms}
                    db.add(node)
                    enriched += 1
                    log.info("node_enriched", path=path_str, terms=terms)
                else:
                    failed += 1
            except Exception:
                log.exception("node_enrich_error", path=path_str)
                failed += 1

        if enriched:
            await db.commit()

    log.info("enrich_complete", enriched=enriched, skipped=skipped, failed=failed)
    return {"enriched": enriched, "skipped": skipped, "failed": failed}


async def _generate_terms(path: str, client: Any, log: Any) -> str | None:
    """Ask gpt-4o for representative caller search terms for a category path.

    Returns a space-separated string of terms, or None on failure.
    """
    try:
        response = await client.chat.completions.create(
            model=_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You generate search index terms for a property management issue category. "
                        f"Given a category path, return exactly {_TERMS_PER_NODE} short terms "
                        "(single words or 2-word phrases) that a tenant might say or type when "
                        "reporting an issue in this category. "
                        "Include both the local language of the category labels AND common English "
                        "equivalents so cross-language callers are covered. "
                        "Return ONLY the terms separated by spaces — no punctuation, no explanation."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Category path: {path}",
                },
            ],
            max_tokens=80,
            temperature=0,
        )
        raw = (response.choices[0].message.content or "").strip()
        terms = " ".join(raw.lower().split())
        log.debug("terms_generated", path=path, terms=terms)
        return terms or None
    except Exception:
        log.exception("generate_terms_error", path=path)
        return None
