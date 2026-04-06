"""Category tree enrichment — generate full metadata for every node.

After a structured upload or AI discovery, this worker fetches every node in a
category tree, builds its full label path, then asks gpt-4o to produce:

  - example_query      : search terms a caller might use (for FTS / LLM matching)
  - urgency_level      : issue priority (e.g. "Prio 1" / "Prio 2" / "Prio 3")
  - self_resolution    : whether the tenant can resolve without a technician (bool)
  - requires_property_info : whether property-specific details are needed (bool)
  - can_report_fault   : whether a formal fault report can be filed (bool)
  - requires_manual_support : whether a human agent must handle this (bool)
  - info_to_collect    : what questions to ask the caller (string)

Fields that already have a value are preserved; only blank fields are filled in
(unless overwrite=True, which regenerates everything).

The generated values are merged into node_metadata (JSONB).  The Postgres
trigger on category_trees automatically rebuilds search_vector to include the
updated example_query, so FTS matching benefits immediately.
"""

import json
import uuid
from typing import Any

import structlog

logger = structlog.get_logger()

_MODEL = "gpt-4o"

# Fields that enrich() will generate. Order matters for the prompt.
_ENRICH_FIELDS = [
    "example_query",
    "urgency_level",
    "self_resolution",
    "requires_property_info",
    "can_report_fault",
    "requires_manual_support",
    "info_to_collect",
]


async def enrich_example_queries(  # noqa: PLR0915
    workspace_id: uuid.UUID,
    tree_name: str,
    user_id: int,
    openai_api_key: str,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Generate and persist full metadata for every node that is missing fields.

    Args:
        workspace_id: Workspace owning the tree.
        tree_name: Logical tree identifier.
        user_id: Integer user id — used to scope DB writes.
        openai_api_key: Key for gpt-4o calls.
        overwrite: If True, regenerate all fields even for nodes that already have them.

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

        # Identify leaf nodes — nodes that have no children
        parent_ids = {n.parent_id for n in nodes if n.parent_id is not None}
        leaf_ids = {n.id for n in nodes if n.id not in parent_ids}

        for node in nodes:
            meta = node.node_metadata or {}
            is_leaf = node.id in leaf_ids

            # Non-leaf nodes only get example_query; all metadata fields go on leaves only
            eligible_fields = _ENRICH_FIELDS if is_leaf else ["example_query"]

            # Determine which fields are missing (need generation)
            if overwrite:
                missing_fields = list(eligible_fields)
            else:
                missing_fields = [f for f in eligible_fields if not meta.get(f)]

            if not missing_fields:
                skipped += 1
                continue

            path_str = " > ".join(paths[node.id])
            try:
                generated = await _generate_metadata(path_str, missing_fields, client, log)
                if generated:
                    node.node_metadata = {**meta, **generated}
                    db.add(node)
                    enriched += 1
                    log.info("node_enriched", path=path_str, fields=list(generated.keys()))
                else:
                    failed += 1
            except Exception:
                log.exception("node_enrich_error", path=path_str)
                failed += 1

        if enriched:
            await db.commit()
            try:
                from app.db.redis import get_redis

                redis = await get_redis()
                await redis.delete(f"category_nodes:{workspace_id}")
            except Exception:
                log.warning("cache_invalidation_failed", workspace_id=str(workspace_id))

    log.info("enrich_complete", enriched=enriched, skipped=skipped, failed=failed)
    return {"enriched": enriched, "skipped": skipped, "failed": failed}


async def _generate_metadata(
    path: str, fields: list[str], client: Any, log: Any
) -> dict[str, Any] | None:
    """Ask gpt-4o to generate the requested metadata fields for a category path.

    Returns a dict of field → value, or None on failure.
    """
    field_descriptions = {
        "example_query": (
            "10 short search terms (single words or 2-word phrases) a tenant might say "
            "or type when reporting this issue. Include both the category language AND "
            "English equivalents. Return as a single space-separated string."
        ),
        "urgency_level": (
            "Issue urgency/priority. Use 'Prio 1' for urgent (health/safety risk, major damage), "
            "'Prio 2' for important (significant inconvenience, risk of getting worse), "
            "'Prio 3' for routine (minor inconvenience, cosmetic). Return one of: Prio 1, Prio 2, Prio 3."
        ),
        "self_resolution": (
            "Can the tenant resolve this themselves without a technician visiting? "
            "Return true or false."
        ),
        "requires_property_info": (
            "Does handling this issue require property-specific information "
            "(e.g. floor plan, supplier contact, boiler model)? Return true or false."
        ),
        "can_report_fault": (
            "Can a formal fault/maintenance report be filed for this issue? Return true or false."
        ),
        "requires_manual_support": (
            "Does this issue require a human agent to handle it "
            "(i.e. the AI voice agent alone cannot resolve it)? Return true or false."
        ),
        "info_to_collect": (
            "What 1-2 clarifying questions should the agent ask the caller to handle this issue? "
            "Return a single concise sentence."
        ),
    }

    fields_prompt = "\n".join(
        f'  "{f}": {field_descriptions[f]}' for f in fields if f in field_descriptions
    )

    system_prompt = (
        "You are an expert in property management issue triage. "
        "Given a category path from a property issue classification tree, "
        "return a JSON object with ONLY the fields listed below. "
        "Be concise and accurate. Return valid JSON only — no explanation, no markdown.\n\n"
        f"Fields to generate:\n{fields_prompt}"
    )

    try:
        response = await client.chat.completions.create(
            model=_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Category path: {path}"},
            ],
            response_format={"type": "json_object"},
            max_tokens=300,
            temperature=0,
        )
        raw = (response.choices[0].message.content or "").strip()
        parsed: dict[str, Any] = json.loads(raw)

        # Normalise boolean fields — LLM may return strings like "true"/"false"
        bool_fields = {
            "self_resolution",
            "requires_property_info",
            "can_report_fault",
            "requires_manual_support",
        }
        result: dict[str, Any] = {}
        for field in fields:
            val = parsed.get(field)
            if val is None:
                continue
            if field in bool_fields:
                if isinstance(val, bool):
                    result[field] = val
                else:
                    result[field] = str(val).lower() in {"true", "ja", "yes", "1"}
            elif field == "example_query":
                result[field] = " ".join(str(val).lower().split())
            else:
                result[field] = str(val).strip()

        log.debug("metadata_generated", path=path, fields=list(result.keys()))
        return result or None
    except Exception:
        log.exception("generate_metadata_error", path=path)
        return None
