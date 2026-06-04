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

    # ── action_type inference ─────────────────────────────────────────────────

    _EMERGENCY_KEYWORDS: frozenset[str] = frozenset(
        ["brand", "nödsituation", "gasutsläpp", "gasläcka", "explosion", "evakuering"]
    )
    _FAULT_KEYWORDS: frozenset[str] = frozenset(
        [
            "felanmälan",
            "hiss",
            "hissfråga",
            "ventilation",
            "värme",
            "vatten",
            "avlopp",
            "läcka",
            "läckage",
            "el ",
            "elfel",
            "belysning",
            "dörr",
            "fönster",
            "lås",
            "kök",
            "badrum",
            "toalett",
            "balkong",
            "trasig",
            "reparation",
            "underhåll",
            "skada",
            "buller",
            "störning",
            "fukt",
            "mögel",
            "brand",
            "tvättmaskin",
            "diskmaskin",
            "spis",
            "kyl",
            "frys",
        ]
    )
    _SUPPORT_KEYWORDS: frozenset[str] = frozenset(
        [
            "betalning",
            "betala hyra",
            "hyresavi",
            "faktura",
            "avi",
            "deposition",
            "skuld",
            "inkasso",
            "hyresrabatt",
            "autogiro",
            "bankgiro",
        ]
    )

    def _infer_action_type(self, label: str, path_string: str) -> str:
        """Infer action_type from category label/path when not set in tree metadata.

        Used as a fallback when the category tree was built without action_type
        metadata. Keyword rules cover the most common real-estate support scenarios.
        """
        text = (label + " " + path_string).lower()
        if any(kw in text for kw in self._EMERGENCY_KEYWORDS):
            return "emergency"
        if any(kw in text for kw in self._FAULT_KEYWORDS):
            return "fault"
        if any(kw in text for kw in self._SUPPORT_KEYWORDS):
            return "support"
        return "information"

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
            action_type = meta.get("action_type")
            label = matched_node.get("label") or ""
            path_string = matched_node.get("path", "") or ""

            # Fall back to extracting action_type from metadata alternatives:
            # 1. "example_query" field using "action_type=<value>" convention
            # 2. Keyword inference from label/path as last resort
            if not action_type:
                eq = meta.get("example_query", "")
                if eq and "action_type=" in eq:
                    action_type = eq.split("action_type=", 1)[1].split(",")[0].strip()
                    self._log.info(
                        "wf_action_type_from_example_query",
                        label=label,
                        action_type=action_type,
                    )
            if not action_type:
                action_type = self._infer_action_type(label, path_string)
                self._log.warning(
                    "wf_action_type_inferred",
                    label=label,
                    path=path_string,
                    inferred=action_type,
                )

            self.context_bag.update(
                {
                    "code": matched_node.get("code"),
                    "label": label,
                    "path_string": path_string,
                    "action_type": action_type,
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
                label=label,
                action_type=action_type,
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
        # Support both string format ("action_type == value") and the object format
        # {"key": "action_type", "operator": "==", "value": "..."} saved by the UI.
        condition_expr: str = cfg.get("condition") or ""
        if not condition_expr and cfg.get("key"):
            condition_expr = f"{cfg['key']} {cfg.get('operator', '==')} {cfg.get('value', '')}"
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

    def has_condition_at_entry(self) -> bool:
        """Return True when the node immediately after entry is a condition node."""
        next_id = self.route()
        if not next_id:
            return False
        node = self.nodes_by_id.get(next_id)
        return bool(node and node.get("type") == "condition")

    def build_entry_routing_note(self) -> str:
        """Return a routing instruction to inject at session start.

        Tells the model which tool to call once the caller has stated their
        issue.  Looks one hop through a condition node to find a categorize
        node.  Returns empty string if no categorize node is reachable.
        """
        next_id = self.route()
        if not next_id:
            return ""
        next_node = self.nodes_by_id.get(next_id)
        if not next_node:
            return ""

        # Resolve the categorize node — directly after entry, or through a condition.
        categorize_node = None
        if next_node.get("type") == "categorize":
            categorize_node = next_node
        elif next_node.get("type") == "condition":
            for edge in self.edges:
                if edge.get("from") == next_id:
                    branch_id = edge.get("to")
                    if branch_id:
                        branch_node = self.nodes_by_id.get(branch_id)
                        if branch_node and branch_node.get("type") == "categorize":
                            categorize_node = branch_node
                            break

        if not categorize_node:
            return ""
        cfg = categorize_node.get("config") or {}
        tree_name = cfg.get("tree_name", "")
        if not tree_name:
            return ""
        return (
            f"\n\n[WORKFLOW — MANDATORY, OVERRIDES ALL OTHER INSTRUCTIONS]\n"
            f"PRIORITY: ask them to describe their reason for calling. "
            f"Do NOT answer any question. Do NOT offer help. Do NOT ask for a property name "
            f"or address. Keep asking until you have a clear answer.\n"
            f"Once the caller answers, IMMEDIATELY call the `categorize` tool with "
            f'tree_name="{tree_name}" and the caller\'s EXACT words as the `text` argument. '
            f"Quote verbatim — do not paraphrase. The result tells you what to do next."
        )

    def to_state(self) -> dict[str, Any]:
        """Serialise mutable state for Redis storage."""
        return {
            "workflow_id": str(self.workflow_id),
            "nodes": list(self.nodes_by_id.values()),
            "edges": self.edges,
            "current_node_id": self.current_node_id,
            "context_bag": self.context_bag,
        }

    @classmethod
    def from_state(cls, state: dict[str, Any], llm_config: LLMConfig) -> WorkflowExecutor:
        """Restore an executor from a serialised state dict."""
        import uuid as _uuid

        ex = cls(
            workflow_id=_uuid.UUID(state["workflow_id"]),
            nodes=state["nodes"],
            edges=state["edges"],
            llm_config=llm_config,
        )
        ex.current_node_id = state["current_node_id"]
        ex.context_bag = state["context_bag"]
        return ex
