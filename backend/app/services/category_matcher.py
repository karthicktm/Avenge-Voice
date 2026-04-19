"""Category matching logic — LLM-based categorization."""

import asyncio
import uuid
from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category_tree import CategoryTree

logger = structlog.get_logger()


@dataclass
class _NodeProxy:
    """Lightweight stand-in for CategoryTree when matching from preloaded cache."""

    id: uuid.UUID
    label: str
    code: str | None
    depth: int
    parent_id: uuid.UUID | None
    example_query: str | None = None


# Public type alias used by callers
MatchedNode = CategoryTree | _NodeProxy


async def match_category(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    tree_name: str,
    text: str,
    user_id: int,
    top_k: int = 1,
    openai_api_key: str | None = None,
    preloaded_nodes: list[dict[str, Any]] | None = None,
) -> tuple[MatchedNode | None, float | None, str]:
    """Match input text against an active category tree.

    Matching strategy:
      1. Postgres FTS — fast exact/stem match. If a deep node (depth >= 2) scores
         above threshold, return it directly.
      2. Hierarchical LLM traversal — load full tree, drill down level by level
         (roots → children of best root → grandchildren). Each step the LLM sees
         only sibling nodes so it can't pick a parent over a more specific child.

    Returns:
        (matched_node | None, confidence | None, resolution_layer)
        resolution_layer: "fts" | "llm" | "none"
    """
    log = logger.bind(
        component="category_matcher",
        workspace_id=str(workspace_id),
        tree_name=tree_name,
    )

    # ------------------------------------------------------------------
    # LLM traversal — always use LLM for accurate categorization
    # ------------------------------------------------------------------
    if not openai_api_key:
        log.info("llm_skipped_no_api_key")
        return None, None, "none"

    # Build children_map from preloaded cache when available — avoids DB query.
    # Fall back to DB only when caller did not supply preloaded_nodes.
    children_map: dict[uuid.UUID | None, list[_NodeProxy]] = {}

    if preloaded_nodes:
        log.info("llm_using_preloaded_nodes", total_nodes=len(preloaded_nodes))
        for nd in preloaded_nodes:
            meta = nd.get("metadata") or {}
            proxy = _NodeProxy(
                id=uuid.UUID(nd["id"]),
                label=nd["label"],
                code=nd.get("code"),
                depth=nd["depth"],
                parent_id=uuid.UUID(nd["parent_id"]) if nd.get("parent_id") else None,
                example_query=meta.get("example_query"),
            )
            children_map.setdefault(proxy.parent_id, []).append(proxy)
    else:
        all_result = await db.execute(
            select(CategoryTree).where(
                CategoryTree.workspace_id == workspace_id,
                CategoryTree.tree_name == tree_name,
                CategoryTree.status == "active",
            )
        )
        db_nodes = list(all_result.scalars().all())
        if not db_nodes:
            return None, None, "none"
        for node in db_nodes:
            proxy = _NodeProxy(
                id=node.id,
                label=node.label,
                code=node.code,
                depth=node.depth,
                parent_id=node.parent_id,
                example_query=(node.node_metadata or {}).get("example_query"),
            )
            children_map.setdefault(proxy.parent_id, []).append(proxy)

    if not children_map:
        return None, None, "none"

    total = sum(len(v) for v in children_map.values())
    log.info("llm_flat_start", total_nodes=total)

    try:
        matched = await asyncio.wait_for(
            _llm_flat_select(text, children_map, log, openai_api_key),
            timeout=10.0,
        )
    except TimeoutError:
        log.warning("llm_flat_timeout")
        return None, None, "none"

    if matched:
        log.info("llm_flat_matched", label=matched.label, depth=matched.depth)
        return matched, 0.85, "llm"

    return None, None, "none"


async def _llm_flat_select(
    text: str,
    children_map: dict[uuid.UUID | None, list[_NodeProxy]],
    log: Any,
    openai_api_key: str,
) -> _NodeProxy | None:
    """Pick the best category with a single LLM call showing all full category paths.

    Instead of drilling down level-by-level (which cascades wrong root picks into wrong
    leaf picks), show the LLM every leaf's complete path at once so it can make a
    holistic decision. The description "EV charger not working in parking" will see both
    "El → Elfel" and "Parkering → Fel på parkeringsplats" side-by-side and pick correctly.
    """
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=openai_api_key)

    # Build a flat id→node map for path reconstruction
    all_nodes: dict[uuid.UUID, _NodeProxy] = {
        n.id: n for siblings in children_map.values() for n in siblings
    }
    if not all_nodes:
        return None

    # Collect leaf nodes (nodes that have no children in the tree)
    leaf_nodes = [n for n in all_nodes.values() if n.id not in children_map]
    if not leaf_nodes:
        # Degenerate tree — all nodes are roots; treat them all as candidates
        leaf_nodes = list(all_nodes.values())

    # Build full ancestor path for each leaf: ["Root", "Child", "Leaf"]
    def _full_path(node: _NodeProxy) -> list[str]:
        path: list[str] = [node.label]
        current = node
        while current.parent_id is not None:
            parent = all_nodes.get(current.parent_id)
            if parent is None:
                break
            path.insert(0, parent.label)
            current = parent
        return path

    # Stable sort: depth ascending then label for reproducible numbering
    leaf_nodes.sort(key=lambda n: (n.depth, n.label))

    candidate_lines: list[str] = []
    for i, leaf in enumerate(leaf_nodes):
        path_str = " → ".join(_full_path(leaf))
        line = f"{i + 1}. {path_str}"
        if leaf.example_query:
            line += f"  [{leaf.example_query}]"
        candidate_lines.append(line)

    candidate_list = "\n".join(candidate_lines)
    log.info("llm_flat_input", text=text, num_candidates=len(leaf_nodes))

    system_prompt = (
        "You are a category classifier for a property management system. "
        "Given a problem description and a numbered list of categories shown as full hierarchical paths, "
        "pick the number of the best matching category. "
        "Each entry shows the complete path from the top-level group down to the specific issue type. "
        "Match by BOTH the type of problem AND its location — "
        "a category whose path mentions the right location (e.g. parking, garage, stairwell) "
        "beats a category that only matches the problem type (e.g. electrical fault). "
        "Categories may be in a different language than the description — match by meaning. "
        "Return 0 only if no category is a reasonable fit. "
        "Respond with ONLY the number."
    )
    user_message = (
        f"Description: {text!r}\n\nCategories:\n{candidate_list}\n\nBest match number (0 if none):"
    )

    for attempt in range(2):
        try:
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                max_tokens=5,
                temperature=0,
            )
            raw = (response.choices[0].message.content or "").strip()
            idx = int(raw)
            if idx == 0:
                log.info("llm_flat_no_match", text=text)
                return None
            if 1 <= idx <= len(leaf_nodes):
                chosen = leaf_nodes[idx - 1]
                log.info(
                    "llm_flat_pick",
                    text=text,
                    picked=" → ".join(_full_path(chosen)),
                    depth=chosen.depth,
                )
                return chosen
        except (ValueError, IndexError):
            log.warning(
                "llm_flat_bad_response",
                raw=raw if "raw" in dir() else None,
                attempt=attempt,
            )
            if attempt == 1:
                return None
        except Exception:
            log.exception("llm_flat_error")
            return None

    return None
