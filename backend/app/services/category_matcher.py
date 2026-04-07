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
        # Swedish — temporal/ordinal/frequency (no topical signal)
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
        # Swedish — operational/status words that appear in many category labels
        # (e.g. "X fungerar inte", "Y funkar inte") but give no topical signal.
        # Matching on these causes FTS to return the wrong leaf before LLM runs.
        "fungerar",
        "fungera",
        "funkar",
        "funka",
        "inte",
        "ej",
        "trasig",
        "trasigt",
        "trasiga",
        "fel",
        "felet",
        "problem",
        "avhjälpning",
        "felanmälan",
        "anmälan",
        "rapport",
        "åtgärd",
        "åtgärda",
        "hjälp",
        "hjälpa",
        # English — temporal/ordinal/frequency
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
        # English — operational/status words
        "works",
        "working",
        "broken",
        "not",
        "doesn't",
        "doesnt",
        "report",
        "issue",
        "fault",
        "error",
        "fix",
        "repair",
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
