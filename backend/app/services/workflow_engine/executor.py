"""WorkflowExecutor — drives a workflow graph during a live voice session.

Responsibilities:
- Track current node
- Run the categorize matching pipeline and store results in context_bag
- Resolve {{variable}} template tokens from context_bag
- Route to next node based on edge conditions
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import structlog

from app.services.workflow_engine.matcher import match, select_strategy

if TYPE_CHECKING:
    import uuid

    from app.services.workflow_engine.llm_client import LLMConfig

logger = structlog.get_logger()


class WorkflowExecutor:
    """Stateful executor for one call session."""

    def __init__(
        self,
        workflow_id: uuid.UUID,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        llm_config: LLMConfig,
    ) -> None:
        self.workflow_id = workflow_id
        self.nodes_by_id: dict[str, dict[str, Any]] = {n["id"]: n for n in nodes}
        self.edges = edges
        self.llm_config = llm_config
        self.context_bag: dict[str, Any] = {}
        self.current_node_id: str = self._find_entry_node_id()
        self._log = logger.bind(workflow_id=str(workflow_id))

    # ── node access ───────────────────────────────────────────────────────────

    @property
    def current_node(self) -> dict[str, Any] | None:
        return self.nodes_by_id.get(self.current_node_id)

    def _find_entry_node_id(self) -> str:
        for node in self.nodes_by_id.values():
            if node.get("type") == "entry":
                return str(node["id"])
        # Fall back to first node
        first = next(iter(self.nodes_by_id), "")
        return str(first)

    # ── categorize step ───────────────────────────────────────────────────────

    async def run_categorize(
        self,
        caller_text: str,
        preloaded_nodes: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Run matching pipeline and store results in context_bag.

        Returns only the fields referenced by the *next* node's template so
        the caller can pass a minimal context to the sub-agent.
        """
        node = self.current_node
        if node is None or node.get("type") != "categorize":
            raise ValueError(f"Current node {self.current_node_id!r} is not a categorize node")

        cfg = node.get("config") or {}
        strategy = cfg.get("strategy") or select_strategy(preloaded_nodes)

        matched_node, confidence, layer = await match(
            caller_text,
            preloaded_nodes,
            self.llm_config,
            strategy=strategy,
            log=self._log,
        )

        if matched_node:
            meta = matched_node.get("metadata") or {}
            self.context_bag.update(
                {
                    "code": matched_node.get("code"),
                    "label": matched_node.get("label"),
                    "path_string": matched_node.get("path", ""),
                    "action_type": meta.get("action_type"),
                    "priority_order": meta.get("priority_order"),
                    "transfer_target": meta.get("transfer_target"),
                    "email_target": meta.get("email_target"),
                    "required_information": meta.get("required_information"),
                    "approved_script": meta.get("approved_script"),
                    "urgency_level": meta.get("urgency_level"),
                    "info_to_collect": meta.get("info_to_collect"),
                    "self_resolution": meta.get("self_resolution"),
                    "safety_boundary": meta.get("safety_boundary"),
                    "confidence": confidence,
                    "resolution_layer": layer,
                }
            )
            self._log.info(
                "wf_categorize_done",
                label=matched_node.get("label"),
                action_type=meta.get("action_type"),
                layer=layer,
            )
        else:
            self.context_bag["action_type"] = "no_match"
            self.context_bag["resolution_layer"] = layer

        # Advance to next node based on action_type edge condition
        next_id = self.route()
        if next_id:
            self.current_node_id = next_id

        # Return only what the next node's template asks for
        next_node = self.current_node
        if next_node:
            return self._resolve_node_context(next_node)
        return dict(self.context_bag)

    # ── template resolution ───────────────────────────────────────────────────

    def resolve_template(self, template: str) -> str:
        """Replace {{variable}} tokens with values from context_bag."""

        def replacer(m: re.Match[str]) -> str:
            key = m.group(1).strip()
            val = self.context_bag.get(key)
            if val is None:
                return m.group(0)  # leave unreplaced if missing
            if isinstance(val, list):
                return ", ".join(str(v) for v in val)
            return str(val)

        return re.sub(r"\{\{([^}]+)\}\}", replacer, template)

    def _resolve_node_context(self, node: dict[str, Any]) -> dict[str, Any]:
        """Return only context_bag entries referenced by the node's template."""
        cfg = node.get("config") or {}
        template = cfg.get("template", "")
        referenced = re.findall(r"\{\{([^}]+)\}\}", template)
        return {k.strip(): self.context_bag.get(k.strip()) for k in referenced}

    # ── edge routing ──────────────────────────────────────────────────────────

    def route(self, source_handle: str | None = None) -> str | None:
        """Find the next node to advance to from the current node.

        For condition nodes the caller should pass source_handle ("yes" / "no")
        to select the correct outgoing branch.  For all other nodes the handle
        is None and the normal conditional/unconditional resolution applies.
        """
        outgoing = [e for e in self.edges if e.get("from") == self.current_node_id]
        if not outgoing:
            return None

        # Condition node — route by sourceHandle
        if source_handle is not None:
            for edge in outgoing:
                if edge.get("sourceHandle") == source_handle:
                    return edge.get("to")
            # Fall back: first outgoing if handle not matched
            return outgoing[0].get("to")

        # First try conditional edges
        for edge in outgoing:
            cond = edge.get("condition", "")
            if cond and self._eval_condition(cond):
                return edge.get("to")

        # Fall through to unconditional edge
        for edge in outgoing:
            if not edge.get("condition"):
                return edge.get("to")

        return None

    def route_condition(self) -> str | None:
        """Evaluate the current condition node and route to yes/no branch."""
        node = self.current_node
        if node is None or node.get("type") != "condition":
            return self.route()
        cfg = node.get("config") or {}
        condition_expr = cfg.get("condition", "")
        result = self._eval_condition(condition_expr) if condition_expr else False
        handle = "yes" if result else "no"
        next_id = self.route(source_handle=handle)
        if next_id:
            self.current_node_id = next_id
        return next_id

    def _eval_condition(self, condition: str) -> bool:
        """Evaluate simple 'key == value' or 'key != value' conditions."""
        # e.g. "action_type == transfer" or "action_type != no_match"
        for op in ("==", "!="):
            if op in condition:
                parts = condition.split(op, 1)
                key = parts[0].strip()
                value = parts[1].strip()
                bag_val = str(self.context_bag.get(key, ""))
                if op == "==":
                    return bag_val == value
                return bag_val != value
        return False

    # ── node instruction builder ──────────────────────────────────────────────

    def build_node_instruction(self) -> str:
        """Return the resolved instruction string for the current node."""
        node = self.current_node
        if not node:
            return ""
        cfg = node.get("config") or {}
        template = cfg.get("template", "")
        return self.resolve_template(template) if template else ""
