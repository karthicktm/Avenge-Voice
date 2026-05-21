"""New multi-layer category matcher for the workflow engine.

Layers (fastest first):
  0   — keyword overlap (~0.1 ms, no LLM)
  0.5 — multilingual embeddings (~100 ms, no LLM)
  0.75— LLM disambiguation (~400 ms, 1 LLM call)
  1   — hierarchical LLM (~4-6 s, N LLM calls) — deep trees only

Existing category_matcher.py is left completely untouched.
"""

from __future__ import annotations

import math
from typing import Any

import structlog

from app.services.workflow_engine.llm_client import LLMConfig, call_llm, embed_text

logger = structlog.get_logger()

# ── constants ────────────────────────────────────────────────────────────────

_KEYWORD_THRESHOLD = 0.5
_EMBED_THRESHOLD = 0.88
_EMBED_GAP = 0.10
_TOP_K_DISAMBIGUATE = 3

# Deep tree auto-detection thresholds
_DEEP_TREE_MIN_NODES = 25
_DEEP_TREE_MIN_DEPTH = 2


# ── public interface ──────────────────────────────────────────────────────────


def select_strategy(nodes: list[dict[str, Any]]) -> str:
    """Return 'flat' or 'hierarchical' based on tree shape."""
    if not nodes:
        return "flat"
    max_depth = max(n.get("depth", 0) for n in nodes)
    if max_depth >= _DEEP_TREE_MIN_DEPTH and len(nodes) >= _DEEP_TREE_MIN_NODES:
        return "hierarchical"
    return "flat"


async def match(
    text: str,
    nodes: list[dict[str, Any]],
    llm_config: LLMConfig,
    *,
    strategy: str | None = None,
    log: Any = None,
) -> tuple[dict[str, Any] | None, float, str]:
    """Match caller text against preloaded node list.

    Returns:
        (matched_node | None, confidence, resolution_layer)
        resolution_layer: "keyword" | "embedding" | "llm_disambiguate" | "llm_hierarchical" | "none"
    """
    if log is None:
        log = logger
    if not nodes:
        return None, 0.0, "none"

    if strategy is None:
        strategy = select_strategy(nodes)

    # Layer 0: keyword
    kw_matches = _keyword_match(text, nodes)
    if len(kw_matches) == 1:
        node, score = kw_matches[0]
        log.info("wf_match_keyword", label=node.get("label"), score=round(score, 3))
        return node, score, "keyword"

    # Layer 0.5 + 0.75: embedding → disambiguation
    embed_candidates = _nodes_with_embeddings(nodes) if not kw_matches else nodes
    result = await _match_embedding_or_disambiguate(text, embed_candidates, llm_config, log)
    if result is not None:
        return result

    # Layer 1: hierarchical LLM (deep trees only)
    if strategy == "hierarchical":
        result = await _match_hierarchical(text, nodes, llm_config, log)
        if result is not None:
            return result

    log.info("wf_match_none")
    return None, 0.0, "none"


async def _match_embedding_or_disambiguate(
    text: str,
    embed_candidates: list[dict[str, Any]],
    llm_config: LLMConfig,
    log: Any,
) -> tuple[dict[str, Any] | None, float, str] | None:
    """Layer 0.5 + 0.75: try embedding, fall through to LLM disambiguation."""
    if not embed_candidates:
        return None
    try:
        query_vec = await embed_text(llm_config, text)
        scored = _cosine_rank(query_vec, embed_candidates)
        if not scored:
            return None
        top_score, top_node = scored[0]
        second_score = scored[1][0] if len(scored) > 1 else 0.0
        if top_score >= _EMBED_THRESHOLD and (top_score - second_score) >= _EMBED_GAP:
            log.info("wf_match_embedding", label=top_node.get("label"), score=round(top_score, 3))
            return top_node, top_score, "embedding"
        top3 = [n for _, n in scored[:_TOP_K_DISAMBIGUATE]]
        picked = await _llm_disambiguate(text, top3, llm_config, log)
        if picked is not None:
            return picked, top_score, "llm_disambiguate"
    except Exception:
        log.exception("wf_embed_error")
    return None


async def _match_hierarchical(
    text: str,
    nodes: list[dict[str, Any]],
    llm_config: LLMConfig,
    log: Any,
) -> tuple[dict[str, Any] | None, float, str] | None:
    """Layer 1: delegate to existing hierarchical LLM traversal."""
    import os
    import uuid as _uuid

    from app.services.category_matcher import _llm_hierarchical_select, _NodeProxy

    children_map: dict[_uuid.UUID | None, list[_NodeProxy]] = {}
    for nd in nodes:
        proxy = _NodeProxy(
            id=_uuid.UUID(nd["id"]),
            label=nd["label"],
            code=nd.get("code"),
            depth=nd["depth"],
            parent_id=_uuid.UUID(nd["parent_id"]) if nd.get("parent_id") else None,
            example_query=(nd.get("metadata") or {}).get("example_query"),
        )
        children_map.setdefault(proxy.parent_id, []).append(proxy)

    openai_key = (
        llm_config.api_key
        if llm_config.provider == "openai"
        else os.environ.get("OPENAI_API_KEY", "")
    )
    matched_proxy = await _llm_hierarchical_select(text, children_map, log, openai_key)
    if not matched_proxy:
        return None
    match_id = str(matched_proxy.id)
    for nd in nodes:
        if nd["id"] == match_id:
            log.info("wf_match_hierarchical", label=nd.get("label"))
            return nd, 0.85, "llm_hierarchical"
    return None


# ── Layer 0 ───────────────────────────────────────────────────────────────────


def _keyword_match(text: str, nodes: list[dict[str, Any]]) -> list[tuple[dict[str, Any], float]]:
    """Return ALL nodes above keyword threshold, sorted descending by score."""
    words = set(text.lower().split())
    results: list[tuple[dict[str, Any], float]] = []
    for node in nodes:
        meta = node.get("metadata") or {}
        haystack = " ".join(
            filter(
                None,
                [
                    node.get("label", ""),
                    node.get("code", ""),
                    meta.get("example_query", ""),
                    meta.get("detection_signals_en", ""),
                    meta.get("detection_signals_de", ""),
                ],
            )
        ).lower()
        haystack_words = set(haystack.split())
        if not haystack_words:
            continue
        overlap = len(words & haystack_words)
        score = overlap / len(haystack_words)
        if score >= _KEYWORD_THRESHOLD:
            results.append((node, score))
    results.sort(key=lambda x: x[1], reverse=True)
    return results


# ── Layer 0.5 ─────────────────────────────────────────────────────────────────


def _nodes_with_embeddings(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [n for n in nodes if n.get("embedding")]


def _cosine_rank(
    query: list[float],
    nodes: list[dict[str, Any]],
) -> list[tuple[float, dict[str, Any]]]:
    """Return nodes sorted by cosine similarity to query vector."""
    scored: list[tuple[float, dict[str, Any]]] = []
    for node in nodes:
        vec = node.get("embedding")
        if not vec:
            continue
        sim = _cosine(query, vec)
        scored.append((sim, node))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ── Layer 0.75 ────────────────────────────────────────────────────────────────


async def _llm_disambiguate(
    text: str,
    candidates: list[dict[str, Any]],
    config: LLMConfig,
    log: Any,
) -> dict[str, Any] | None:
    """Single LLM call to pick the best among 2-3 close candidates."""
    if not candidates:
        return None

    domain = "a voice service system"
    if candidates:
        meta = candidates[0].get("metadata") or {}
        domain = meta.get("domain_context") or domain

    system = (
        f"You are a category classifier for {domain}. "
        "Pick the number that best matches the caller's request. "
        "Reply with ONLY the number."
    )
    lines = []
    for i, node in enumerate(candidates, 1):
        meta = node.get("metadata") or {}
        label = node.get("label", "")
        ex = meta.get("example_query", "")
        line = f"{i}. {label}"
        if ex:
            line += f"  [{ex}]"
        lines.append(line)

    user_msg = f"Caller: {text!r}\n\n" + "\n".join(lines) + "\n\nBest match number:"

    raw = ""
    for attempt in range(2):
        try:
            raw = await call_llm(config, system, user_msg, max_tokens=5)
            idx = int(raw)
            if 1 <= idx <= len(candidates):
                picked = candidates[idx - 1]
                log.info("wf_disambiguate_pick", label=picked.get("label"), raw=raw)
                return picked
            break
        except (ValueError, TypeError):
            log.warning("wf_disambiguate_bad_response", raw=raw, attempt=attempt)
            if attempt == 1:
                return candidates[0] if candidates else None
        except Exception:
            log.exception("wf_disambiguate_error")
            return candidates[0] if candidates else None
    return None
