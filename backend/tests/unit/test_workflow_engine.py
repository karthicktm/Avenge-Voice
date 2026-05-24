"""Unit tests for the workflow engine — matcher + executor (no DB, no LLM calls)."""

from __future__ import annotations

import math
import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.services.workflow_engine.executor import WorkflowExecutor
from app.services.workflow_engine.llm_client import LLMConfig
from app.services.workflow_engine.matcher import (
    _cosine,
    _cosine_rank,
    _keyword_match,
    _nodes_with_embeddings,
    match,
    select_strategy,
)

# ── helpers ────────────────────────────────────────────────────────────────────


def _make_node(
    node_id: str = "n1",
    label: str = "Test label",
    code: str | None = None,
    depth: int = 0,
    parent_id: str | None = None,
    embedding: list[float] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": node_id,
        "label": label,
        "code": code,
        "depth": depth,
        "parent_id": parent_id,
        "embedding": embedding,
        "metadata": metadata or {},
    }


def _unit_vec(dims: int, hot: int) -> list[float]:
    """Return a unit vector with a single 1.0 at position `hot`."""
    v = [0.0] * dims
    v[hot] = 1.0
    return v


def _cfg() -> LLMConfig:
    return LLMConfig(provider="openai", model="gpt-4o-mini", api_key="test-key")


# ── matcher — keyword layer ────────────────────────────────────────────────────


class TestKeywordMatch:
    def test_high_overlap_matches(self) -> None:
        # "water pipe" against "water pipe" → score 2/2 = 1.0 > 0.5
        nodes = [_make_node(label="water pipe")]
        result = _keyword_match("water pipe", nodes)
        assert len(result) == 1
        assert result[0][0] is nodes[0]

    def test_below_threshold_excluded(self) -> None:
        # "water" against "water leak bathroom heating" → 1/4 = 0.25 < 0.5
        nodes = [_make_node(label="water leak bathroom heating")]
        result = _keyword_match("water", nodes)
        assert result == []

    def test_code_in_haystack(self) -> None:
        # "abc" against "abc" (code only, 1/1 = 1.0)
        nodes = [_make_node(label="ABC", code="abc")]
        result = _keyword_match("abc", nodes)
        assert len(result) == 1

    def test_detection_signals_en_in_haystack(self) -> None:
        # haystack: "software" + "crash freeze" → 3 unique words
        # query "software crash" → overlap 2 → 2/3 = 0.67 > 0.5
        nodes = [
            _make_node(
                label="software",
                metadata={"detection_signals_en": "crash freeze"},
            )
        ]
        result = _keyword_match("software crash", nodes)
        assert len(result) == 1

    def test_german_detection_signals(self) -> None:
        # haystack: "fehler" + "startet nicht" → 3 unique words
        # query "startet nicht" → overlap 2 → 2/3 = 0.67 > 0.5
        nodes = [
            _make_node(
                label="fehler",
                metadata={"detection_signals_de": "startet nicht"},
            )
        ]
        result = _keyword_match("startet nicht", nodes)
        assert len(result) == 1

    def test_multiple_matches_sorted_descending(self) -> None:
        # n1: "pipe water" → query "water pipe": 2/2 = 1.0
        # n2: "water damage broken here" → overlap 1 → 1/4 = 0.25, below threshold
        # Use n2 with a label that crosses threshold but has lower score
        high_node = _make_node("n1", label="pipe water")  # 2/2 = 1.0
        low_node = _make_node("n2", label="water pool")   # 1/2 = 0.5, at threshold exactly
        result = _keyword_match("water pipe", [low_node, high_node])
        assert len(result) == 2
        assert result[0][0]["id"] == "n1"  # higher score first

    def test_empty_nodes_returns_empty(self) -> None:
        assert _keyword_match("anything", []) == []

    def test_example_query_in_haystack(self) -> None:
        # haystack: "nothing works" (from example_query, 2 words) + label "x" → 3 unique
        # query "nothing works" → overlap 2 → 2/3 = 0.67
        nodes = [_make_node(label="x", metadata={"example_query": "nothing works"})]
        result = _keyword_match("nothing works", nodes)
        assert len(result) == 1


# ── matcher — cosine math ─────────────────────────────────────────────────────


class TestCosine:
    def test_identical_vectors(self) -> None:
        v = [1.0, 2.0, 3.0]
        assert _cosine(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors(self) -> None:
        assert _cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_opposite_vectors(self) -> None:
        assert _cosine([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)

    def test_zero_vector_returns_zero(self) -> None:
        assert _cosine([0.0, 0.0], [1.0, 0.0]) == 0.0


class TestCosineRank:
    def test_sorted_by_similarity(self) -> None:
        query = _unit_vec(3, 0)
        nodes = [
            _make_node("a", embedding=_unit_vec(3, 1)),  # orthogonal → 0.0
            _make_node("b", embedding=_unit_vec(3, 0)),  # identical → 1.0
        ]
        ranked = _cosine_rank(query, nodes)
        assert ranked[0][1]["id"] == "b"
        assert ranked[0][0] == pytest.approx(1.0)

    def test_node_without_embedding_skipped(self) -> None:
        nodes = [_make_node("a"), _make_node("b", embedding=[1.0, 0.0])]
        ranked = _cosine_rank([1.0, 0.0], nodes)
        assert len(ranked) == 1
        assert ranked[0][1]["id"] == "b"


class TestNodesWithEmbeddings:
    def test_filters_none_embeddings(self) -> None:
        nodes = [_make_node("a"), _make_node("b", embedding=[0.5, 0.5])]
        result = _nodes_with_embeddings(nodes)
        assert len(result) == 1
        assert result[0]["id"] == "b"

    def test_empty_list_embedding_excluded(self) -> None:
        node = _make_node("a")
        node["embedding"] = []  # falsy
        assert _nodes_with_embeddings([node]) == []


# ── matcher — strategy selection ─────────────────────────────────────────────


class TestSelectStrategy:
    def test_empty_nodes_flat(self) -> None:
        assert select_strategy([]) == "flat"

    def test_small_shallow_tree_flat(self) -> None:
        nodes = [_make_node(depth=1) for _ in range(10)]
        assert select_strategy(nodes) == "flat"

    def test_large_deep_tree_hierarchical(self) -> None:
        nodes = [_make_node(depth=2) for _ in range(30)]
        assert select_strategy(nodes) == "hierarchical"

    def test_deep_but_few_nodes_flat(self) -> None:
        # depth ≥ 2 but too few nodes
        nodes = [_make_node(depth=2) for _ in range(5)]
        assert select_strategy(nodes) == "flat"

    def test_many_nodes_but_shallow_flat(self) -> None:
        nodes = [_make_node(depth=1) for _ in range(50)]
        assert select_strategy(nodes) == "flat"


# ── matcher — full pipeline (mocked LLM + embed) ──────────────────────────────


@pytest.mark.asyncio
class TestMatchPipeline:
    async def test_single_keyword_match_returns_immediately(self) -> None:
        nodes = [_make_node("n1", label="water leak pipe")]
        matched, score, layer = await match("water leak pipe", nodes, _cfg())
        assert matched is not None
        assert matched["id"] == "n1"
        assert layer == "keyword"

    async def test_no_nodes_returns_none(self) -> None:
        result = await match("anything", [], _cfg())
        assert result == (None, 0.0, "none")

    async def test_embedding_layer_high_score_returns(self) -> None:
        query_vec = _unit_vec(4, 0)
        node = _make_node("n1", embedding=_unit_vec(4, 0))  # cosine = 1.0

        with patch(
            "app.services.workflow_engine.matcher.embed_text",
            new_callable=AsyncMock,
            return_value=query_vec,
        ):
            matched, score, layer = await match("anything", [node], _cfg())

        assert matched is not None
        assert matched["id"] == "n1"
        assert layer == "embedding"
        assert score == pytest.approx(1.0)

    async def test_embedding_layer_low_gap_falls_to_disambiguate(self) -> None:
        # Two nodes with similar embedding scores — gap < 0.10
        query_vec = [1.0, 0.1]
        norm = math.sqrt(1.0**2 + 0.1**2)
        query_vec = [x / norm for x in query_vec]

        # Node A: slightly closer
        node_a = _make_node("a", embedding=[1.0, 0.0])
        # Node B: slightly farther
        node_b = _make_node("b", embedding=[0.95, 0.31])
        # Normalise node B
        nb = node_b["embedding"]
        nb_norm = math.sqrt(sum(x**2 for x in nb))
        node_b["embedding"] = [x / nb_norm for x in nb]

        with (
            patch(
                "app.services.workflow_engine.matcher.embed_text",
                new_callable=AsyncMock,
                return_value=query_vec,
            ),
            patch(
                "app.services.workflow_engine.matcher._llm_disambiguate",
                new_callable=AsyncMock,
                return_value=node_a,
            ) as mock_disambig,
        ):
            matched, _, layer = await match("some text", [node_a, node_b], _cfg())

        assert layer == "llm_disambiguate"
        assert matched is node_a
        mock_disambig.assert_called_once()

    async def test_embed_error_falls_through_to_none(self) -> None:
        node = _make_node("n1", embedding=[1.0, 0.0])
        with patch(
            "app.services.workflow_engine.matcher.embed_text",
            side_effect=RuntimeError("api error"),
        ):
            matched, score, layer = await match("text", [node], _cfg())
        assert matched is None
        assert layer == "none"

    async def test_strategy_override_skips_hierarchical(self) -> None:
        # Deep tree but strategy forced to flat — Layer 1 should never run
        nodes = [_make_node(depth=3) for _ in range(50)]
        with patch(
            "app.services.workflow_engine.matcher.embed_text",
            side_effect=RuntimeError("skip embed"),
        ):
            _, _, layer = await match("text", nodes, _cfg(), strategy="flat")
        assert layer == "none"


# ── executor — context bag + template resolution ──────────────────────────────


def _make_executor(
    nodes: list[dict[str, Any]] | None = None,
    edges: list[dict[str, Any]] | None = None,
) -> WorkflowExecutor:
    wf_id = uuid.uuid4()
    n = nodes or [{"id": "entry_1", "type": "entry"}]
    e = edges or []
    return WorkflowExecutor(wf_id, n, e, _cfg())


class TestWorkflowExecutor:
    def test_entry_node_selected_on_init(self) -> None:
        ex = _make_executor(
            nodes=[
                {"id": "n_other", "type": "categorize"},
                {"id": "n_entry", "type": "entry"},
            ]
        )
        assert ex.current_node_id == "n_entry"

    def test_fallback_to_first_node_when_no_entry(self) -> None:
        nodes = [{"id": "first", "type": "instruction"}]
        ex = _make_executor(nodes=nodes)
        assert ex.current_node_id == "first"

    def test_resolve_template_simple(self) -> None:
        ex = _make_executor()
        ex.context_bag["action_type"] = "transfer"
        ex.context_bag["transfer_target"] = "+49123456"
        result = ex.resolve_template("Action: {{action_type}} → {{transfer_target}}")
        assert result == "Action: transfer → +49123456"

    def test_resolve_template_missing_key_unchanged(self) -> None:
        ex = _make_executor()
        result = ex.resolve_template("Hello {{missing_key}}")
        assert result == "Hello {{missing_key}}"

    def test_resolve_template_list_value_joined(self) -> None:
        ex = _make_executor()
        ex.context_bag["required_information"] = ["name", "phone", "problem"]
        result = ex.resolve_template("Collect: {{required_information}}")
        assert result == "Collect: name, phone, problem"

    def test_build_node_instruction_uses_template(self) -> None:
        nodes = [
            {
                "id": "n1",
                "type": "instruction",
                "config": {"template": "Say: {{approved_script}}"},
            }
        ]
        ex = _make_executor(nodes=nodes)
        ex.context_bag["approved_script"] = "Thank you for calling."
        instruction = ex.build_node_instruction()
        assert instruction == "Say: Thank you for calling."

    def test_build_node_instruction_no_template_returns_empty(self) -> None:
        nodes = [{"id": "n1", "type": "instruction", "config": {}}]
        ex = _make_executor(nodes=nodes)
        assert ex.build_node_instruction() == ""


# ── executor — edge routing ───────────────────────────────────────────────────


class TestEdgeRouting:
    def _categorize_to_transfer_setup(self) -> WorkflowExecutor:
        nodes = [
            {"id": "n_cat", "type": "categorize"},
            {"id": "n_transfer", "type": "transfer"},
            {"id": "n_email", "type": "collect_email"},
            {"id": "n_end", "type": "end_call"},
        ]
        edges = [
            {"from": "n_cat", "to": "n_transfer", "condition": "action_type == transfer"},
            {"from": "n_cat", "to": "n_email", "condition": "action_type == collect_then_email"},
            {"from": "n_transfer", "to": "n_end"},
            {"from": "n_email", "to": "n_end"},
        ]
        ex = WorkflowExecutor(uuid.uuid4(), nodes, edges, _cfg())
        ex.current_node_id = "n_cat"
        return ex

    def test_conditional_route_transfer(self) -> None:
        ex = self._categorize_to_transfer_setup()
        ex.context_bag["action_type"] = "transfer"
        next_id = ex.route()
        assert next_id == "n_transfer"

    def test_conditional_route_collect_email(self) -> None:
        ex = self._categorize_to_transfer_setup()
        ex.context_bag["action_type"] = "collect_then_email"
        next_id = ex.route()
        assert next_id == "n_email"

    def test_unconditional_edge_after_transfer(self) -> None:
        ex = self._categorize_to_transfer_setup()
        ex.context_bag["action_type"] = "transfer"
        ex.current_node_id = "n_transfer"
        next_id = ex.route()
        assert next_id == "n_end"

    def test_no_outgoing_edges_returns_none(self) -> None:
        ex = self._categorize_to_transfer_setup()
        ex.current_node_id = "n_end"
        assert ex.route() is None

    def test_unmatched_condition_falls_to_unconditional(self) -> None:
        nodes = [
            {"id": "src", "type": "categorize"},
            {"id": "cond", "type": "instruction"},
            {"id": "fallback", "type": "instruction"},
        ]
        edges = [
            {"from": "src", "to": "cond", "condition": "action_type == transfer"},
            {"from": "src", "to": "fallback"},  # unconditional
        ]
        ex = WorkflowExecutor(uuid.uuid4(), nodes, edges, _cfg())
        ex.current_node_id = "src"
        ex.context_bag["action_type"] = "no_match"
        assert ex.route() == "fallback"


# ── executor — condition node routing ────────────────────────────────────────


class TestConditionNodeRouting:
    def _setup(self) -> WorkflowExecutor:
        nodes = [
            {"id": "cond", "type": "condition", "config": {"condition": "action_type == transfer"}},
            {"id": "yes_node", "type": "transfer"},
            {"id": "no_node", "type": "collect_email"},
        ]
        edges = [
            {"from": "cond", "to": "yes_node", "sourceHandle": "yes"},
            {"from": "cond", "to": "no_node", "sourceHandle": "no"},
        ]
        ex = WorkflowExecutor(uuid.uuid4(), nodes, edges, _cfg())
        ex.current_node_id = "cond"
        return ex

    def test_true_condition_routes_yes(self) -> None:
        ex = self._setup()
        ex.context_bag["action_type"] = "transfer"
        next_id = ex.route_condition()
        assert next_id == "yes_node"
        assert ex.current_node_id == "yes_node"

    def test_false_condition_routes_no(self) -> None:
        ex = self._setup()
        ex.context_bag["action_type"] = "collect_then_email"
        next_id = ex.route_condition()
        assert next_id == "no_node"

    def test_not_equal_condition(self) -> None:
        nodes = [
            {"id": "cond", "type": "condition", "config": {"condition": "action_type != no_match"}},
            {"id": "yes_node", "type": "transfer"},
            {"id": "no_node", "type": "end_call"},
        ]
        edges = [
            {"from": "cond", "to": "yes_node", "sourceHandle": "yes"},
            {"from": "cond", "to": "no_node", "sourceHandle": "no"},
        ]
        ex = WorkflowExecutor(uuid.uuid4(), nodes, edges, _cfg())
        ex.current_node_id = "cond"
        ex.context_bag["action_type"] = "transfer"
        next_id = ex.route_condition()
        assert next_id == "yes_node"


# ── executor — run_categorize (mocked matcher) ────────────────────────────────


@pytest.mark.asyncio
class TestRunCategorize:
    def _make_workflow(self) -> WorkflowExecutor:
        nodes = [
            {"id": "cat", "type": "categorize", "config": {}},
            {
                "id": "transfer",
                "type": "transfer",
                "config": {"template": "Transfer to {{transfer_target}}"},
            },
        ]
        edges = [{"from": "cat", "to": "transfer", "condition": "action_type == transfer"}]
        ex = WorkflowExecutor(uuid.uuid4(), nodes, edges, _cfg())
        ex.current_node_id = "cat"
        return ex

    async def test_successful_match_populates_context_bag(self) -> None:
        ex = self._make_workflow()
        matched_node = {
            "id": "node_x",
            "label": "Software Issue",
            "code": "2.0",
            "path": "Service > Software",
            "metadata": {
                "action_type": "transfer",
                "transfer_target": "+49123456789",
            },
        }

        with patch(
            "app.services.workflow_engine.executor.match",
            new_callable=AsyncMock,
            return_value=(matched_node, 0.95, "embedding"),
        ):
            ctx = await ex.run_categorize("Software startet nicht", [matched_node])

        assert ex.context_bag["action_type"] == "transfer"
        assert ex.context_bag["code"] == "2.0"
        assert ex.context_bag["confidence"] == pytest.approx(0.95)
        assert ex.context_bag["resolution_layer"] == "embedding"

    async def test_no_match_sets_action_type_no_match(self) -> None:
        ex = self._make_workflow()
        with patch(
            "app.services.workflow_engine.executor.match",
            new_callable=AsyncMock,
            return_value=(None, 0.0, "none"),
        ):
            await ex.run_categorize("completely unrecognised utterance", [])

        assert ex.context_bag["action_type"] == "no_match"

    async def test_routing_advances_current_node(self) -> None:
        ex = self._make_workflow()
        matched_node = {
            "id": "node_x",
            "label": "Transfer Node",
            "code": "T1",
            "path": "Root",
            "metadata": {"action_type": "transfer", "transfer_target": "+49123"},
        }

        with patch(
            "app.services.workflow_engine.executor.match",
            new_callable=AsyncMock,
            return_value=(matched_node, 0.9, "embedding"),
        ):
            await ex.run_categorize("transfer me", [matched_node])

        # Should have advanced from 'cat' to 'transfer'
        assert ex.current_node_id == "transfer"

    async def test_wrong_node_type_raises(self) -> None:
        nodes = [{"id": "n1", "type": "instruction"}]
        ex = WorkflowExecutor(uuid.uuid4(), nodes, [], _cfg())
        with pytest.raises(ValueError, match="not a categorize node"):
            await ex.run_categorize("anything", [])
