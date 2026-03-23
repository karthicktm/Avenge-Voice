"""Category matching logic — Postgres FTS (Layer 1) + hierarchical LLM fallback (Layer 2)."""

import asyncio
import uuid
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category_tree import CategoryTree

logger = structlog.get_logger()

# ts_rank score below this threshold triggers LLM fallback
FTS_THRESHOLD = 0.05


async def match_category(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    tree_name: str,
    text: str,
    user_id: int,
    top_k: int = 1,
    openai_api_key: str | None = None,
) -> tuple[CategoryTree | None, float | None, str]:
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
    # Layer 1 — Postgres FTS (prefer deepest match above threshold)
    # ------------------------------------------------------------------
    tsquery = func.plainto_tsquery("simple", text)
    ts_rank_expr = func.ts_rank(CategoryTree.search_vector, tsquery)

    fts_stmt = (
        select(CategoryTree, ts_rank_expr.label("score"))
        .where(
            CategoryTree.workspace_id == workspace_id,
            CategoryTree.tree_name == tree_name,
            CategoryTree.status == "active",
            CategoryTree.search_vector.op("@@")(tsquery),
        )
        .order_by(CategoryTree.depth.desc(), ts_rank_expr.desc())  # deepest first
        .limit(10)
    )

    fts_result = await db.execute(fts_stmt)
    fts_rows = fts_result.fetchall()

    if fts_rows:
        # Take the deepest node that's above threshold
        for node, score in fts_rows:
            if score >= FTS_THRESHOLD:
                log.info("fts_matched", score=score, label=node.label, depth=node.depth)
                return node, float(score), "fts"
        log.info("fts_below_threshold", best_score=fts_rows[0][1])
    else:
        log.info("fts_no_results")

    # ------------------------------------------------------------------
    # Layer 2 — Hierarchical LLM traversal
    # ------------------------------------------------------------------
    if not openai_api_key:
        log.info("llm_skipped_no_api_key")
        return None, None, "none"

    # Load all active nodes for this tree once
    all_result = await db.execute(
        select(CategoryTree).where(
            CategoryTree.workspace_id == workspace_id,
            CategoryTree.tree_name == tree_name,
            CategoryTree.status == "active",
        )
    )
    all_nodes = list(all_result.scalars().all())
    if not all_nodes:
        return None, None, "none"

    # Build parent→children map
    children_map: dict[uuid.UUID | None, list[CategoryTree]] = {}
    for node in all_nodes:
        children_map.setdefault(node.parent_id, []).append(node)

    # Sort each level alphabetically for stable LLM output
    for siblings in children_map.values():
        siblings.sort(key=lambda n: n.label)

    log.info("llm_hierarchical_start", total_nodes=len(all_nodes))

    try:
        matched = await asyncio.wait_for(
            _llm_hierarchical_select(text, children_map, log, openai_api_key),
            timeout=6.0,
        )
    except TimeoutError:
        log.warning("llm_hierarchical_timeout")
        return None, None, "none"

    if matched:
        log.info("llm_hierarchical_matched", label=matched.label, depth=matched.depth)
        return matched, 0.85, "llm"

    return None, None, "none"


async def _llm_hierarchical_select(
    text: str,
    children_map: dict[uuid.UUID | None, list[CategoryTree]],
    log: Any,
    openai_api_key: str,
) -> CategoryTree | None:
    """Drill down the tree level by level using LLM at each step.

    At each level the LLM only sees sibling nodes (never parents), so it
    naturally picks the most specific matching category.
    """
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=openai_api_key)

    current_parent_id: uuid.UUID | None = None  # start from roots
    last_picked: CategoryTree | None = None

    for _level in range(5):  # max depth guard
        siblings = children_map.get(current_parent_id, [])
        if not siblings:
            break

        picked = await _llm_pick_from_siblings(text, siblings, client, log)
        if picked is None:
            break  # LLM said none match — stop here

        last_picked = picked

        # If this node has no children, we're at a leaf — done
        if picked.id not in {k for k in children_map if k is not None}:
            break

        current_parent_id = picked.id

    return last_picked


async def _llm_pick_from_siblings(
    text: str,
    siblings: list[CategoryTree],
    client: Any,
    log: Any,
) -> CategoryTree | None:
    """Ask LLM to pick the best sibling node for the given text.

    Returns the chosen node or None if no match.
    """
    candidate_list = "\n".join(f"{i + 1}. {s.label}" for i, s in enumerate(siblings))

    system_prompt = (
        "You are a category classifier. "
        "Given a description and a list of categories at the same level, "
        "pick the single best matching category number (1-based). "
        "Categories may be in a different language — match by meaning. "
        "Return 0 if none match. Respond with ONLY the number."
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
                return None
            if 1 <= idx <= len(siblings):
                chosen = siblings[idx - 1]
                log.info("llm_level_pick", label=chosen.label, depth=chosen.depth)
                return chosen
        except (ValueError, IndexError):
            if attempt == 1:
                return None
        except Exception:
            log.exception("llm_pick_error")
            return None

    return None
