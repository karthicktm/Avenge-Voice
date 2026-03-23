"""Category matching logic — Postgres FTS (Layer 1) + LLM fallback (Layer 2)."""

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


async def match_category(  # noqa: PLR0911, PLR0912
    db: AsyncSession,
    workspace_id: uuid.UUID,
    tree_name: str,
    text: str,
    user_id: int,
    top_k: int = 1,
    openai_api_key: str | None = None,
) -> tuple[CategoryTree | None, float | None, str]:
    """Match input text against an active category tree.

    Args:
        db: Async DB session.
        workspace_id: Workspace owning the tree.
        tree_name: Logical tree identifier.
        text: Raw caller input to classify.
        user_id: Owner user ID for scoping.
        top_k: Max candidates to consider.
        openai_api_key: Optional key for LLM fallback.

    Returns:
        (matched_node | None, confidence | None, resolution_layer)
        resolution_layer is one of: "fts" | "llm" | "none"
    """
    log = logger.bind(
        component="category_matcher",
        workspace_id=str(workspace_id),
        tree_name=tree_name,
    )

    # ------------------------------------------------------------------
    # Layer 1 — Postgres FTS
    # ------------------------------------------------------------------
    tsquery = func.plainto_tsquery("simple", text)
    ts_rank_expr = func.ts_rank(CategoryTree.search_vector, tsquery)

    stmt = (
        select(CategoryTree, ts_rank_expr.label("score"))
        .where(
            CategoryTree.workspace_id == workspace_id,
            CategoryTree.tree_name == tree_name,
            CategoryTree.status == "active",
            CategoryTree.search_vector.op("@@")(tsquery),
        )
        .order_by(ts_rank_expr.desc())
        .limit(10)  # fetch more candidates for depth-aware selection
    )

    result = await db.execute(stmt)
    rows = result.fetchall()

    if rows:
        best_node, best_score = rows[0]
        log.info("fts_result", score=best_score, label=best_node.label, candidates=len(rows))

        if best_score >= FTS_THRESHOLD:
            # Filter to all results with a reasonable score
            good_rows = [r for r in rows if r[1] >= FTS_THRESHOLD]
            # If only one good match, return it directly
            if len(good_rows) == 1:
                return good_rows[0][0], float(good_rows[0][1]), "fts"
            # Multiple good matches — check if there are deeper (more specific) nodes
            max_depth = max(r[0].depth for r in good_rows)
            if max_depth == 0 or max_depth == good_rows[0][0].depth:
                # All at same depth or only root nodes — let LLM pick most specific
                pass  # fall through to LLM with good_rows as candidates
            else:
                # Prefer deeper nodes — filter to deepest level and return best score
                deepest = [r for r in good_rows if r[0].depth == max_depth]
                if len(deepest) == 1:
                    return deepest[0][0], float(deepest[0][1]), "fts"
                # Multiple deep matches — let LLM decide
            candidates = [r[0] for r in good_rows]
            log.info("fts_multiple_candidates_using_llm", count=len(candidates))
        else:
            log.info("fts_below_threshold", score=best_score, threshold=FTS_THRESHOLD)
            candidates = [r[0] for r in rows[:5]]
    else:
        log.info("fts_no_results")
        candidates = []

    # ------------------------------------------------------------------
    # Layer 2 — LLM selects most specific match from candidates
    # ------------------------------------------------------------------
    # (candidates already set above)

    if not candidates:
        # FTS found nothing — likely a language mismatch (e.g. English input vs Swedish tree).
        # Fall back to LLM with a sample of tree nodes fetched directly from DB.
        if not openai_api_key:
            log.info("no_candidates_for_llm")
            return None, None, "none"

        fallback_stmt = (
            select(CategoryTree)
            .where(
                CategoryTree.workspace_id == workspace_id,
                CategoryTree.tree_name == tree_name,
                CategoryTree.status == "active",
            )
            .order_by(CategoryTree.depth.asc(), CategoryTree.label.asc())
            .limit(30)
        )
        fallback_result = await db.execute(fallback_stmt)
        candidates = list(fallback_result.scalars().all())
        if not candidates:
            log.info("no_candidates_for_llm")
            return None, None, "none"
        log.info("fts_fallback_to_tree_sample", sample_size=len(candidates))

    try:
        llm_node = await asyncio.wait_for(
            _llm_select(
                text=text,
                candidates=candidates,
                openai_api_key=openai_api_key,
                log=log,
            ),
            timeout=3.0,
        )
    except TimeoutError:
        log.warning("llm_select_timeout")
        return None, None, "none"

    if llm_node is not None:
        return llm_node, 0.8, "llm"

    return None, None, "none"


async def _llm_select(  # noqa: PLR0911
    text: str,
    candidates: list[CategoryTree],
    openai_api_key: str | None,
    log: Any,
) -> CategoryTree | None:
    """Ask an LLM to pick the best candidate from a short list.

    Returns the best candidate node, or None if no candidate is a good match.
    Retries once on JSON parse failure.
    """
    if not openai_api_key:
        log.warning("llm_select_skipped_no_api_key")
        return None

    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=openai_api_key)
    except ImportError:
        log.warning("llm_select_skipped_openai_not_installed")
        return None

    candidate_list = "\n".join(
        f"{i + 1}. [{c.code or '-'}] {c.label}" for i, c in enumerate(candidates)
    )

    system_prompt = (
        "You are a category classifier. Given caller input and a list of candidate categories, "
        "select the single MOST SPECIFIC match by returning its number (1-based). "
        "Always prefer leaf/specific categories over parent/root categories when both match. "
        "Categories may be in a different language than the caller input — match by meaning. "
        "If none is a good match, return 0. Respond with ONLY the number — no explanation."
    )
    user_message = (
        f"Caller input: {text!r}\n\n"
        f"Candidates:\n{candidate_list}\n\n"
        "Which number is the MOST SPECIFIC match? Prefer detailed sub-categories over broad root categories. (0 if none)"
    )

    for attempt in range(2):
        try:
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                max_tokens=10,
                temperature=0,
            )
            raw = (response.choices[0].message.content or "").strip()
            idx = int(raw)
            if idx == 0:
                log.info("llm_select_no_match")
                return None
            if 1 <= idx <= len(candidates):
                chosen = candidates[idx - 1]
                log.info("llm_select_matched", label=chosen.label, attempt=attempt)
                return chosen
        except (ValueError, IndexError) as exc:
            log.warning("llm_select_parse_error", raw=raw if "raw" in dir() else "", error=str(exc))
            if attempt == 1:
                return None
        except Exception:
            log.exception("llm_select_error")
            return None

    return None
