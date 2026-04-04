"""Category matching logic — Postgres FTS (Layer 1) + hierarchical LLM fallback (Layer 2)."""

import asyncio
import uuid
from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category_tree import CategoryTree

logger = structlog.get_logger()

# ts_rank score below this threshold triggers LLM fallback
FTS_THRESHOLD = 0.05
TRGM_THRESHOLD = 0.35

# Common Swedish + English words that carry no category-matching signal.
# These are temporal/ordinal/frequency words that appear in conversational
# context ("det är första gången") but not in category labels as topic markers.
_WORD_MATCH_STOPWORDS = frozenset(
    {
        # Swedish
        "första",
        "andra",
        "tredje",
        "gången",
        "gånger",
        "sedan",
        "igår",
        "idag",
        "imorgon",
        "alltid",
        "aldrig",
        "ibland",
        "ofta",
        "bara",
        "igen",
        "redan",
        "fortfarande",
        "nyligen",
        "plötsligt",
        "senaste",
        "ungefär",
        "cirka",
        "kanske",
        "förra",
        "nästa",
        "just",
        "faktiskt",
        "egentligen",
        "verkligen",
        # English
        "first",
        "second",
        "third",
        "time",
        "times",
        "again",
        "already",
        "always",
        "never",
        "today",
        "yesterday",
        "tomorrow",
        "recently",
        "sudden",
        "suddenly",
        "maybe",
        "perhaps",
        "still",
        "actually",
        "really",
        "once",
        "twice",
    }
)


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


async def match_category(  # noqa: PLR0911, PLR0912
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
    # Layer 1b — Word-by-word FTS fallback
    # Full descriptions rarely match short category labels with AND logic.
    # Try each significant word individually and take the deepest match.
    # ------------------------------------------------------------------
    min_word_len = (
        2  # include 3+ char words so English short terms like "rat", "cold", "lock" are tried
    )
    significant_words = [
        w.strip(".,!?-")
        for w in text.split()
        if len(w.strip(".,!?-")) > min_word_len
        and w.strip(".,!?-").lower() not in _WORD_MATCH_STOPWORDS
    ]
    for word in significant_words:
        word_tsq = func.plainto_tsquery("simple", word)
        word_stmt = (
            select(CategoryTree, ts_rank_expr.label("score"))
            .where(
                CategoryTree.workspace_id == workspace_id,
                CategoryTree.tree_name == tree_name,
                CategoryTree.status == "active",
                CategoryTree.search_vector.op("@@")(word_tsq),
            )
            .order_by(
                CategoryTree.depth.desc(), func.ts_rank(CategoryTree.search_vector, word_tsq).desc()
            )
            .limit(5)
        )
        word_result = await db.execute(word_stmt)
        word_rows = word_result.fetchall()
        for node, score in word_rows:
            if score >= FTS_THRESHOLD:
                log.info(
                    "fts_word_matched", word=word, score=score, label=node.label, depth=node.depth
                )
                return node, float(score), "fts"

    # ------------------------------------------------------------------
    # Layer 1c — Trigram similarity on label (pg_trgm)
    # Catches spelling variants / ASR errors that share trigrams with
    # category labels (e.g. "ventilasjon" → "ventilation").
    # Does NOT resolve semantic gaps (rat vs mice share zero trigrams —
    # the LLM layer below handles those). Zero API cost.
    # Requires pg_trgm extension (migration 038).
    # ------------------------------------------------------------------
    if text.strip():
        trgm_stmt = (
            select(CategoryTree, func.similarity(CategoryTree.label, text).label("trgm_score"))
            .where(
                CategoryTree.workspace_id == workspace_id,
                CategoryTree.tree_name == tree_name,
                CategoryTree.status == "active",
                func.similarity(CategoryTree.label, text) >= TRGM_THRESHOLD,
            )
            .order_by(
                CategoryTree.depth.desc(),
                func.similarity(CategoryTree.label, text).desc(),
            )
            .limit(5)
        )
        trgm_result = await db.execute(trgm_stmt)
        for node, trgm_score in trgm_result.fetchall():
            log.info("trgm_matched", score=trgm_score, label=node.label, depth=node.depth)
            return node, float(trgm_score), "fts"

    # ------------------------------------------------------------------
    # Layer 2 — Hierarchical LLM traversal
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

    # Sort each level alphabetically for stable LLM output
    for siblings in children_map.values():
        siblings.sort(key=lambda n: n.label)

    total = sum(len(v) for v in children_map.values())
    log.info("llm_hierarchical_start", total_nodes=total)

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
    children_map: dict[uuid.UUID | None, list[_NodeProxy]],
    log: Any,
    openai_api_key: str,
) -> _NodeProxy | None:
    """Drill down the tree level by level using LLM at each step.

    At each level the LLM only sees sibling nodes (never parents), so it
    naturally picks the most specific matching category.
    """
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=openai_api_key)

    current_parent_id: uuid.UUID | None = None  # start from roots
    last_picked: _NodeProxy | None = None

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
    siblings: list[_NodeProxy],
    client: Any,
    log: Any,
) -> _NodeProxy | None:
    """Ask LLM to pick the best sibling node for the given text.

    Returns the chosen node or None if no match.
    """
    # Build candidate list — include example_query hints when present so the
    # LLM understands what each category covers without hardcoded examples.
    # e.g. "2. VVS  [värme uppvärmning kallt ventilation vatten avlopp]"
    candidate_lines = []
    for i, s in enumerate(siblings):
        line = f"{i + 1}. {s.label}"
        if s.example_query:
            line += f"  [{s.example_query}]"
        candidate_lines.append(line)
    candidate_list = "\n".join(candidate_lines)
    sibling_labels = [s.label for s in siblings]

    log.info(
        "llm_pick_input",
        text=text,
        candidates=sibling_labels,
        depth=siblings[0].depth if siblings else None,
    )

    system_prompt = (
        "You are a category classifier. "
        "Given a description and a numbered list of categories, "
        "pick the single best matching category number (1-based). "
        "Each category may include hint terms in brackets showing what it covers. "
        "Categories and hints may be in a different language than the description — match by meaning. "
        "Prefer the most specific available match. "
        "Return 0 only if no category is even remotely related — "
        "if in doubt between 0 and a plausible match, pick the match. "
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
                log.info(
                    "llm_pick_no_match",
                    text=text,
                    candidates=sibling_labels,
                    depth=siblings[0].depth if siblings else None,
                )
                return None
            if 1 <= idx <= len(siblings):
                chosen = siblings[idx - 1]
                log.info(
                    "llm_level_pick",
                    text=text,
                    picked=chosen.label,
                    picked_index=idx,
                    candidates=sibling_labels,
                    depth=chosen.depth,
                )
                return chosen
        except (ValueError, IndexError):
            log.warning(
                "llm_pick_bad_response", raw=raw if "raw" in dir() else None, attempt=attempt
            )
            if attempt == 1:
                return None
        except Exception:
            log.exception("llm_pick_error")
            return None

    return None
