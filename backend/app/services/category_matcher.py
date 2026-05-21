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

    Matching strategy — hierarchical LLM traversal:
      Load full tree, drill down level by level (roots → children of best root →
      grandchildren). At each step the LLM sees only sibling nodes and the path
      chosen so far, so it can't be distracted by unrelated branches.

    Returns:
        (matched_node | None, confidence | None, resolution_layer)
        resolution_layer: "llm" | "none"
    """
    log = logger.bind(
        component="category_matcher",
        workspace_id=str(workspace_id),
        tree_name=tree_name,
    )

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
    log.info("llm_hierarchical_start", total_nodes=total)

    try:
        # Allow ~7 s per level for up to 3 levels of depth
        matched = await asyncio.wait_for(
            _llm_hierarchical_select(text, children_map, log, openai_api_key),
            timeout=25.0,
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
    """Pick the best category by drilling down one level at a time.

    At each level, the LLM sees only the sibling candidates (children of the previously
    chosen node) plus the path already chosen, so context narrows progressively.

    Example: "crack in kitchen window"
      Level 1 — sees all roots → picks "Damage / surface / windows / interior"
      Level 2 — sees its children → picks "Windows / balcony door" (not "Walls / floors")
      Level 3 — sees its children → picks "Damaged window"
    """
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=openai_api_key)

    if not any(True for _ in children_map.values()):
        return None

    system_prompt = (
        "You are a category classifier for a property management system. "
        "You are shown a problem description and a numbered list of options at the current level of a category tree. "
        "The path chosen so far (if any) tells you which branch you are already in. "
        "Pick the number of the option that best matches the problem at this level. "
        "Prefer the option that names the specific damaged component or object "
        "(e.g. 'window', 'door', 'pipe') over one that only describes the symptom "
        "(e.g. 'crack', 'leak', 'noise'). A cracked window belongs under 'window', not 'cracks/holes'. "
        "Prefer a location-specific option (e.g. 'parking', 'stairwell') when the issue is location-specific. "
        "Categories may be in a different language than the description — match by meaning. "
        "Return 0 if none of the options fit. "
        "Respond with ONLY the number."
    )

    current_parent_id: uuid.UUID | None = None  # start at roots
    best_node: _NodeProxy | None = None
    chosen_path: list[str] = []

    while True:
        candidates = children_map.get(current_parent_id, [])
        if not candidates:
            # No children — best_node is the deepest match (a leaf)
            break

        candidates = sorted(candidates, key=lambda n: n.label)

        candidate_lines: list[str] = []
        for i, node in enumerate(candidates):
            line = f"{i + 1}. {node.label}"
            if node.example_query:
                line += f"  [{node.example_query}]"
            candidate_lines.append(line)

        path_context = (
            f"Path chosen so far: {' → '.join(chosen_path)}\n" if chosen_path else ""
        )
        user_message = (
            f"Problem: {text!r}\n"
            f"{path_context}"
            f"Options:\n{'\n'.join(candidate_lines)}\n\nBest match number (0 if none):"
        )

        log.info(
            "llm_hierarchical_level",
            depth=len(chosen_path),
            num_candidates=len(candidates),
            path_so_far=chosen_path,
        )

        raw = ""
        idx = 0
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
                break
            except (ValueError, IndexError):
                log.warning("llm_hierarchical_bad_response", raw=raw, attempt=attempt)
                if attempt == 1:
                    return best_node
                continue
            except Exception:
                log.exception("llm_hierarchical_error")
                return best_node

        if idx == 0:
            log.info("llm_hierarchical_no_match_at_level", depth=len(chosen_path))
            break  # no better match at this level — stop with best so far

        if not (1 <= idx <= len(candidates)):
            log.warning("llm_hierarchical_out_of_range", idx=idx, num=len(candidates))
            break

        best_node = candidates[idx - 1]
        chosen_path.append(best_node.label)
        current_parent_id = best_node.id
        log.info("llm_hierarchical_pick", label=best_node.label, depth=best_node.depth)

    return best_node
