"""Tool registry for managing available tools for voice agents."""

import asyncio
import contextlib
import hashlib
import json
import time
import uuid
from typing import TYPE_CHECKING, Any, cast

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.tools.calendly_tools import CalendlyTools
from app.services.tools.call_control_tools import CallControlTools
from app.services.tools.campaign_tools import CampaignTools
from app.services.tools.categorize_tools import CategorizeTools
from app.services.tools.crm_tools import CRMTools
from app.services.tools.email_tools import ResendEmailTools
from app.services.tools.gohighlevel_tools import GoHighLevelTools
from app.services.tools.lookup_tools import LookupTools
from app.services.tools.rag_tools import RAGTools
from app.services.tools.shopify_tools import ShopifyTools
from app.services.tools.site_search_tools import SiteSearchTools
from app.services.tools.sms_tools import TelnyxSMSTools, TwilioSMSTools

if TYPE_CHECKING:
    from redis.asyncio import Redis


def _short_hash(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:16]


# Minimum word-overlap score to trust an in-memory match without hitting the DB.
_IN_MEMORY_THRESHOLD = 0.5


_IN_MEMORY_MIN_WORD_LEN = 4  # consistent with FTS layer's significant-word threshold


def _match_in_memory(text: str, nodes: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Score nodes by word overlap and return the best match above threshold.

    Used as a fast Layer-0 check before touching the DB. Operates entirely on
    the prewarmed node list so it completes in microseconds.

    Scoring uses max(|text_words|, |node_words|) as the denominator so that
    short category labels cannot reach the threshold via a single common word.
    Short words (< _IN_MEMORY_MIN_WORD_LEN chars) are excluded to avoid
    stop-word false positives (e.g. Swedish "i", "en", "av", "med").
    """
    text_words = {w for w in text.lower().split() if len(w) >= _IN_MEMORY_MIN_WORD_LEN}
    if not text_words:
        return None

    best_score = 0.0
    best_node: dict[str, Any] | None = None

    for node in nodes:
        meta = node.get("metadata") or {}
        example = meta.get("example_query") or ""
        search_text = f"{node['label']} {node.get('code') or ''} {example}".lower()
        node_words = {w for w in search_text.split() if len(w) >= _IN_MEMORY_MIN_WORD_LEN}
        if not node_words:
            continue
        intersection = len(text_words & node_words)
        score = intersection / max(len(text_words), len(node_words))
        if score > best_score:
            best_score = score
            best_node = node

    if best_node and best_score >= _IN_MEMORY_THRESHOLD:
        meta = best_node.get("metadata") or {}
        return {
            "success": True,
            "matched": True,
            "code": best_node.get("code"),
            "label": best_node["label"],
            "path": best_node["path"],
            "depth": best_node["depth"],
            "confidence": round(best_score, 3),
            "resolution_layer": "in_memory",
            # Well-known metadata fields (flat for easy agent access)
            "urgency_level": meta.get("urgency_level"),
            "self_resolution": meta.get("self_resolution"),
            "can_report_fault": meta.get("can_report_fault"),
            "requires_manual_support": meta.get("requires_manual_support"),
            "requires_property_info": meta.get("requires_property_info"),
            "info_to_collect": meta.get("info_to_collect"),
            "metadata": meta or None,
        }
    return None


def _canonical_lookup_args(args: dict[str, Any]) -> str:
    return "|".join(
        [
            str(args.get("query", "")).lower().strip(),
            str(args.get("domain") or ""),
            str(args.get("collection_id") or ""),
            str(args.get("field") or ""),
            str(min(int(args.get("limit", 3)), 10)),
        ]
    )


class ToolRegistry:
    """Registry of all available tools for voice agents.

    Manages:
    - Internal tools (CRM, bookings)
    - External integrations (GoHighLevel, Calendly, Shopify, SMS, etc.)
    - Tool execution routing
    """

    def __init__(
        self,
        db: AsyncSession,
        user_id: int,
        integrations: dict[str, dict[str, Any]] | None = None,
        workspace_id: Any | None = None,
        agent_id: uuid.UUID | None = None,
        openai_api_key: str | None = None,
        tool_configs: dict[str, dict[str, Any]] | None = None,
        campaign_context: dict[str, Any] | None = None,
        redis: "Redis | None" = None,
    ) -> None:
        """Initialize tool registry.

        Args:
            db: Database session
            user_id: User ID (integer matching users.id)
            integrations: Dict of integration credentials keyed by integration_id
                         e.g., {"gohighlevel": {"access_token": "...", "location_id": "..."}}
            workspace_id: Workspace UUID for scoping CRM operations
            agent_id: Agent UUID for RAG/Knowledge Base operations
            openai_api_key: OpenAI API key (fallback for RAG embeddings if not in integrations)
            tool_configs: Per-tool configuration from agent settings
                         e.g., {"site_search": {"site_url": "https://example.com"}}
            campaign_context: Campaign context dict (auto-registers disposition tool when present)
        """
        self.db = db
        self.user_id = user_id
        self.integrations = integrations or {}
        self.workspace_id = workspace_id
        self.agent_id = agent_id
        self.openai_api_key = openai_api_key
        self.tool_configs = tool_configs or {}
        self.campaign_context = campaign_context
        self._redis = redis
        self._tool_cache: dict[str, Any] = {}
        self._background_tasks: set[asyncio.Task[Any]] = set()
        self._log = structlog.get_logger().bind(
            component="tool_registry",
            agent_id=str(agent_id) if agent_id else None,
            workspace_id=str(workspace_id) if workspace_id else None,
        )
        # tree_name → flat list of node dicts (loaded at session start)
        self._prewarmed_trees: dict[str, list[dict[str, Any]]] = {}
        self.crm_tools = CRMTools(db, user_id, workspace_id=workspace_id)
        self.lookup_tools = LookupTools(
            db, user_id, workspace_id=workspace_id, openai_api_key=openai_api_key
        )
        self.categorize_tools = CategorizeTools(
            db,
            user_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
            openai_api_key=openai_api_key,
        )
        self._ghl_tools: GoHighLevelTools | None = None
        self._calendly_tools: CalendlyTools | None = None
        self._shopify_tools: ShopifyTools | None = None
        self._twilio_sms_tools: TwilioSMSTools | None = None
        self._telnyx_sms_tools: TelnyxSMSTools | None = None
        self._resend_email_tools: ResendEmailTools | None = None
        self._site_search_tools: SiteSearchTools | None = None
        self._rag_tools: RAGTools | None = None

    def _get_ghl_tools(self) -> GoHighLevelTools | None:
        """Get GoHighLevel tools if credentials are available."""
        if self._ghl_tools:
            return self._ghl_tools

        ghl_creds = self.integrations.get("gohighlevel")
        if ghl_creds and ghl_creds.get("access_token") and ghl_creds.get("location_id"):
            self._ghl_tools = GoHighLevelTools(
                access_token=ghl_creds["access_token"],
                location_id=ghl_creds["location_id"],
            )
            return self._ghl_tools

        return None

    def _get_calendly_tools(self) -> CalendlyTools | None:
        """Get Calendly tools if credentials are available."""
        if self._calendly_tools:
            return self._calendly_tools

        creds = self.integrations.get("calendly")
        if creds and creds.get("access_token"):
            self._calendly_tools = CalendlyTools(
                access_token=creds["access_token"],
            )
            return self._calendly_tools

        return None

    def _get_shopify_tools(self) -> ShopifyTools | None:
        """Get Shopify tools if credentials are available."""
        if self._shopify_tools:
            return self._shopify_tools

        creds = self.integrations.get("shopify")
        if creds and creds.get("access_token") and creds.get("shop_domain"):
            self._shopify_tools = ShopifyTools(
                access_token=creds["access_token"],
                shop_domain=creds["shop_domain"],
            )
            return self._shopify_tools

        return None

    def _get_twilio_sms_tools(self) -> TwilioSMSTools | None:
        """Get Twilio SMS tools if credentials are available."""
        if self._twilio_sms_tools:
            return self._twilio_sms_tools

        creds = self.integrations.get("twilio-sms")
        if (
            creds
            and creds.get("account_sid")
            and creds.get("auth_token")
            and creds.get("from_number")
        ):
            self._twilio_sms_tools = TwilioSMSTools(
                account_sid=creds["account_sid"],
                auth_token=creds["auth_token"],
                from_number=creds["from_number"],
            )
            return self._twilio_sms_tools

        return None

    def _get_telnyx_sms_tools(self) -> TelnyxSMSTools | None:
        """Get Telnyx SMS tools if credentials are available."""
        if self._telnyx_sms_tools:
            return self._telnyx_sms_tools

        creds = self.integrations.get("telnyx-sms")
        if creds and creds.get("api_key") and creds.get("from_number"):
            self._telnyx_sms_tools = TelnyxSMSTools(
                api_key=creds["api_key"],
                from_number=creds["from_number"],
                messaging_profile_id=creds.get("messaging_profile_id"),
            )
            return self._telnyx_sms_tools

        return None

    def _get_resend_email_tools(self) -> ResendEmailTools | None:
        """Get Resend email tools if credentials are available."""
        if self._resend_email_tools:
            return self._resend_email_tools

        creds = self.integrations.get("resend")
        if creds and creds.get("api_key") and creds.get("from_email"):
            self._resend_email_tools = ResendEmailTools(
                api_key=creds["api_key"],
                from_email=creds["from_email"],
            )
            return self._resend_email_tools

        return None

    def _get_site_search_tools(self) -> SiteSearchTools | None:
        """Get Site Search tools for LLM-powered website crawling.

        Requires site_url to be configured via tool_configs:
            {"site_search": {"site_url": "https://example.com", "site_description": "..."}}
        """
        if self._site_search_tools:
            return self._site_search_tools

        site_config = self.tool_configs.get("site_search", {})
        site_url = site_config.get("site_url")

        if not site_url:
            return None

        self._site_search_tools = SiteSearchTools(
            site_url=site_url,
            site_description=site_config.get("site_description"),
            openai_api_key=self.openai_api_key,
            language=site_config.get("language", "en-US"),
        )
        return self._site_search_tools

    def _get_rag_tools(self) -> RAGTools | None:
        """Get RAG tools if agent_id and embedding credentials are available.

        Credentials come from workspace integrations (shared across agents).
        Translation settings come from agent's tool_configs (agent-specific).
        Falls back to OpenAI API key if no explicit knowledge_base config.
        """
        if self._rag_tools:
            return self._rag_tools

        if not self.agent_id:
            self._log.warning("rag_tools_skipped_no_agent_id")
            return None

        # Get knowledge_base credentials from workspace integrations
        kb_creds = self.integrations.get("knowledge_base", {})
        api_key = kb_creds.get("api_key")

        self._log.info(
            "rag_tools_credential_check",
            has_kb_creds=bool(kb_creds),
            has_kb_api_key=bool(api_key),
            has_openai_fallback=bool(self.openai_api_key),
        )

        # Fall back to OpenAI API key if no explicit knowledge_base config
        if not api_key and self.openai_api_key:
            api_key = self.openai_api_key
            self._log.info("rag_tools_using_openai_fallback")

        if not api_key:
            self._log.warning("rag_tools_skipped_no_api_key")
            return None

        # Get agent-specific translation settings from tool_configs
        agent_kb_config = self.tool_configs.get("knowledge_base", {})

        embedding_config = {
            # Credentials from workspace integrations
            "api_key": api_key,
            "embedding_model": kb_creds.get("embedding_model", "text-embedding-3-small"),
            "embedding_provider": kb_creds.get("embedding_provider", "openai"),
            # Translation settings from agent's tool_configs
            "enable_translation": agent_kb_config.get("enable_translation", "false"),
            "translation_model": agent_kb_config.get("translation_model", "gpt-4o-mini"),
        }

        self._log.info(
            "rag_tools_initialized",
            agent_id=str(self.agent_id),
            embedding_model=embedding_config["embedding_model"],
            embedding_provider=embedding_config["embedding_provider"],
            enable_translation=embedding_config["enable_translation"],
        )

        self._rag_tools = RAGTools(self.db, self.agent_id, embedding_config=embedding_config)
        return self._rag_tools

    async def _redis_get(self, key: str) -> dict[str, Any] | None:
        if not self._redis:
            return None
        try:
            raw = await self._redis.get(key)
            return json.loads(raw) if raw else None
        except Exception:
            return None

    async def _redis_set(self, key: str, value: dict[str, Any], ttl: int) -> None:
        if not self._redis:
            return
        with contextlib.suppress(Exception):
            await self._redis.setex(key, ttl, json.dumps(value))

    async def prewarm_collections(self) -> None:
        """Pre-fetch lookup collections list into session + Redis cache."""
        if not self.workspace_id:
            return
        await self.execute_tool("lookup_list_collections", {})

    async def prewarm_category_trees(self) -> None:
        """Pre-load all active category tree nodes for this workspace into memory.

        Loads once per session from Redis (if warm) or the DB (cold start).
        Subsequent categorize() calls use _match_in_memory() as Layer 0 and only
        fall through to Postgres FTS / LLM when the in-memory score is too low.
        Nodes are cached in Redis for 1 hour so restarts stay fast.
        """
        if not self.workspace_id:
            return

        from sqlalchemy import select

        from app.models.category_tree import CategoryTree

        log = structlog.get_logger().bind(
            component="prewarm_category_trees", workspace_id=str(self.workspace_id)
        )

        redis_key = f"category_nodes:{self.workspace_id}"
        cached = await self._redis_get(redis_key)
        if cached and isinstance(cached.get("trees"), dict):
            self._prewarmed_trees = cached["trees"]
            log.info("category_trees_prewarmed_from_redis", tree_count=len(self._prewarmed_trees))
            return

        # Load all active nodes for the workspace in one query
        result = await self.db.execute(
            select(CategoryTree).where(
                CategoryTree.workspace_id == self.workspace_id,
                CategoryTree.status == "active",
            )
        )
        all_nodes = list(result.scalars().all())

        # Build per-tree maps
        node_map: dict[uuid.UUID, CategoryTree] = {n.id: n for n in all_nodes}
        trees: dict[str, list[dict[str, Any]]] = {}

        for node in all_nodes:
            # Reconstruct label path from root to this node
            path: list[str] = []
            current: CategoryTree | None = node
            while current is not None:
                path.insert(0, current.label)
                if current.parent_id is None:
                    break
                current = node_map.get(current.parent_id)

            trees.setdefault(node.tree_name, []).append(
                {
                    "id": str(node.id),
                    "label": node.label,
                    "code": node.code,
                    "depth": node.depth,
                    "path": path,
                    "parent_id": str(node.parent_id) if node.parent_id else None,
                    "metadata": node.node_metadata,
                }
            )

        self._prewarmed_trees = trees
        await self._redis_set(redis_key, {"trees": trees}, ttl=3600)
        log.info(
            "category_trees_prewarmed_from_db",
            tree_count=len(trees),
            total_nodes=len(all_nodes),
        )

    def get_all_tool_definitions(  # noqa: PLR0912, PLR0915
        self,
        enabled_tools: list[str],
        enabled_tool_ids: dict[str, list[str]] | None = None,
    ) -> list[dict[str, Any]]:
        """Get tool definitions for enabled tools.

        Args:
            enabled_tools: List of enabled integration IDs (legacy)
            enabled_tool_ids: Granular tool selection {integration_id: [tool_id1, tool_id2]}

        Returns:
            List of OpenAI function calling tool definitions
        """
        tools: list[dict[str, Any]] = []

        # Helper to filter tools by enabled_tool_ids
        def filter_tools(
            integration_id: str, all_tools: list[dict[str, Any]]
        ) -> list[dict[str, Any]]:
            """Filter tools based on enabled_tool_ids if provided."""
            if not enabled_tool_ids or integration_id not in enabled_tool_ids:
                # No granular filtering - return all tools (backward compatible)
                return all_tools

            allowed_tool_ids = set(enabled_tool_ids[integration_id])
            return [
                tool
                for tool in all_tools
                if tool.get("name") in allowed_tool_ids
                or tool.get("function", {}).get("name") in allowed_tool_ids
            ]

        # Call Control tools - always available if "call_control" is enabled
        if "call_control" in enabled_tools:
            call_control_tools = CallControlTools.get_tool_definitions()
            tools.extend(filter_tools("call_control", call_control_tools))

        # Internal CRM tools - always available if "crm" is enabled
        if "crm" in enabled_tools:
            crm_tools = CRMTools.get_tool_definitions()
            tools.extend(filter_tools("crm", crm_tools))

        # Internal Bookings tools - also from CRM but filtered separately
        if "bookings" in enabled_tools:
            booking_tools = CRMTools.get_tool_definitions()
            tools.extend(filter_tools("bookings", booking_tools))

        # GoHighLevel tools - available if "gohighlevel" is enabled and credentials exist
        if "gohighlevel" in enabled_tools and self._get_ghl_tools():
            ghl_tools = GoHighLevelTools.get_tool_definitions()
            tools.extend(filter_tools("gohighlevel", ghl_tools))

        # Calendly tools
        if "calendly" in enabled_tools and self._get_calendly_tools():
            calendly_tools = CalendlyTools.get_tool_definitions()
            tools.extend(filter_tools("calendly", calendly_tools))

        # Shopify tools
        if "shopify" in enabled_tools and self._get_shopify_tools():
            shopify_tools = ShopifyTools.get_tool_definitions()
            tools.extend(filter_tools("shopify", shopify_tools))

        # Twilio SMS tools
        if "twilio-sms" in enabled_tools and self._get_twilio_sms_tools():
            twilio_tools = TwilioSMSTools.get_tool_definitions()
            tools.extend(filter_tools("twilio-sms", twilio_tools))

        # Telnyx SMS tools
        if "telnyx-sms" in enabled_tools and self._get_telnyx_sms_tools():
            telnyx_tools = TelnyxSMSTools.get_tool_definitions()
            tools.extend(filter_tools("telnyx-sms", telnyx_tools))

        # Knowledge Base / RAG tools (requires agent_id) — register BEFORE site search
        # so we know whether KB exists when building site search tool description
        kb_in_enabled = "knowledge_base" in enabled_tools
        has_knowledge_base = False
        self._log.info(
            "knowledge_base_tool_check",
            kb_in_enabled_tools=kb_in_enabled,
            enabled_tools=enabled_tools,
            agent_id=str(self.agent_id) if self.agent_id else None,
        )

        if kb_in_enabled:
            rag_tools_instance = self._get_rag_tools()
            if rag_tools_instance:
                rag_tools = RAGTools.get_tool_definitions()
                tools.extend(filter_tools("knowledge_base", rag_tools))
                has_knowledge_base = True
                self._log.info("knowledge_base_tool_registered", tool_count=len(rag_tools))
            else:
                self._log.warning("knowledge_base_tool_not_registered_no_instance")

        # Campaign tools - auto-registered when campaign_context is present
        if self.campaign_context:
            campaign_tools = CampaignTools.get_tool_definitions()
            tools.extend(campaign_tools)

        # Lookup tools (structured data collections — no external API needed)
        if "lookup" in enabled_tools:
            lookup_tool_defs = LookupTools.get_tool_definitions()
            tools.extend(filter_tools("lookup", lookup_tool_defs))

        # Categorization tools (FTS + LLM category tree matching)
        if "categorization" in enabled_tools or "category_tree" in enabled_tools:
            categorize_tool_defs = CategorizeTools.get_tool_definitions()
            integration_id = (
                "category_tree" if "category_tree" in enabled_tools else "categorization"
            )
            tools.extend(filter_tools(integration_id, categorize_tool_defs))

        # Resend email tools
        if "resend" in enabled_tools and self._get_resend_email_tools():
            resend_tools = ResendEmailTools.get_tool_definitions()
            tools.extend(filter_tools("resend", resend_tools))

        # Site Search tools (requires site_url configured)
        if "site_search" in enabled_tools:
            site_search_instance = self._get_site_search_tools()
            if site_search_instance:
                site_search_tools = site_search_instance.get_tool_definitions(
                    has_knowledge_base=has_knowledge_base,
                )
                tools.extend(filter_tools("site_search", site_search_tools))

        return tools

    async def execute_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a tool with structured logging of request and response."""
        log = self._log.bind(tool=tool_name)
        log.info("tool_call_start", arguments=arguments)
        t0 = time.monotonic()
        result = await self._execute_tool_impl(tool_name, arguments)
        elapsed_ms = round((time.monotonic() - t0) * 1000, 1)
        log.info(
            "tool_call_done",
            elapsed_ms=elapsed_ms,
            success=result.get("success"),
            result=result,
        )
        return result

    async def _execute_tool_impl(  # noqa: PLR0911, PLR0912, PLR0915
        self, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute a tool by routing to appropriate handler.

        Args:
            tool_name: Tool name
            arguments: Tool arguments

        Returns:
            Tool execution result
        """
        # Call Control tools
        call_control_tool_names = {
            "end_call",
            "transfer_call",
            "send_dtmf",
        }

        if tool_name in call_control_tool_names:
            return await CallControlTools.execute_tool(tool_name, arguments)

        # CRM tools
        crm_tool_names = {
            "search_customer",
            "create_contact",
            "check_availability",
            "book_appointment",
            "list_appointments",
            "cancel_appointment",
            "reschedule_appointment",
        }

        if tool_name in crm_tool_names:
            return await self.crm_tools.execute_tool(tool_name, arguments)

        # GoHighLevel tools
        ghl_tool_names = {
            "ghl_search_contact",
            "ghl_get_contact",
            "ghl_create_contact",
            "ghl_update_contact",
            "ghl_add_contact_tags",
            "ghl_get_calendars",
            "ghl_get_calendar_slots",
            "ghl_book_appointment",
            "ghl_get_appointments",
            "ghl_cancel_appointment",
            "ghl_get_pipelines",
            "ghl_create_opportunity",
        }

        if tool_name in ghl_tool_names:
            ghl_tools = self._get_ghl_tools()
            if not ghl_tools:
                return {
                    "success": False,
                    "error": "GoHighLevel integration not configured. Please add your API credentials.",
                }
            return await ghl_tools.execute_tool(tool_name, arguments)

        # Calendly tools
        calendly_tool_names = {
            "calendly_get_event_types",
            "calendly_get_availability",
            "calendly_create_scheduling_link",
            "calendly_list_events",
            "calendly_get_event",
            "calendly_cancel_event",
        }

        if tool_name in calendly_tool_names:
            calendly_tools = self._get_calendly_tools()
            if not calendly_tools:
                return {
                    "success": False,
                    "error": "Calendly integration not configured. Please add your API credentials.",
                }
            return await calendly_tools.execute_tool(tool_name, arguments)

        # Shopify tools
        shopify_tool_names = {
            "shopify_search_orders",
            "shopify_get_order",
            "shopify_get_order_tracking",
            "shopify_search_products",
            "shopify_check_inventory",
            "shopify_search_customers",
            "shopify_get_customer_orders",
        }

        if tool_name in shopify_tool_names:
            shopify_tools = self._get_shopify_tools()
            if not shopify_tools:
                return {
                    "success": False,
                    "error": "Shopify integration not configured. Please add your API credentials.",
                }
            return await shopify_tools.execute_tool(tool_name, arguments)

        # Twilio SMS tools
        twilio_tool_names = {
            "twilio_send_sms",
            "twilio_get_message_status",
        }

        if tool_name in twilio_tool_names:
            twilio_tools = self._get_twilio_sms_tools()
            if not twilio_tools:
                return {
                    "success": False,
                    "error": "Twilio SMS integration not configured. Please add your API credentials.",
                }
            return await twilio_tools.execute_tool(tool_name, arguments)

        # Telnyx SMS tools
        telnyx_tool_names = {
            "telnyx_send_sms",
            "telnyx_get_message_status",
        }

        if tool_name in telnyx_tool_names:
            telnyx_tools = self._get_telnyx_sms_tools()
            if not telnyx_tools:
                return {
                    "success": False,
                    "error": "Telnyx SMS integration not configured. Please add your API credentials.",
                }
            return await telnyx_tools.execute_tool(tool_name, arguments)

        # Site Search tools
        site_search_tool_names = {
            "search_site",
        }

        if tool_name in site_search_tool_names:
            site_search_tools = self._get_site_search_tools()
            if not site_search_tools:
                return {
                    "success": False,
                    "error": "Site Search not configured. Please set a website URL.",
                }
            return await site_search_tools.execute_tool(tool_name, arguments)

        # RAG / Knowledge Base tools
        rag_tool_names = {
            "search_knowledge_base",
        }

        if tool_name in rag_tool_names:
            rag_tools = self._get_rag_tools()
            if not rag_tools:
                return {
                    "success": False,
                    "error": "Knowledge Base not available. Agent ID required.",
                }
            return await rag_tools.execute_tool(tool_name, arguments)

        # Lookup tools
        lookup_tool_names = {
            "lookup_search",
            "lookup_list_collections",
        }

        if tool_name in lookup_tool_names:
            if tool_name == "lookup_search":
                # Apply configured collection_id from tool_configs if Gemini didn't provide a valid one
                configured_collection_id = self.tool_configs.get("lookup_search", {}).get(
                    "collection_id", ""
                )
                provided_collection_id = str(arguments.get("collection_id") or "")
                is_valid_uuid = False
                if provided_collection_id:
                    try:
                        uuid.UUID(provided_collection_id)
                        is_valid_uuid = True
                    except ValueError:
                        pass
                if not is_valid_uuid and configured_collection_id:
                    arguments = {**arguments, "collection_id": configured_collection_id}

                canonical = _canonical_lookup_args(arguments)
                session_key = f"lookup_search:{canonical}"

                if session_key in self._tool_cache:
                    return cast("dict[str, Any]", self._tool_cache[session_key])

                redis_key = f"lookup:search:{self.workspace_id}:{_short_hash(canonical)}"
                cached = await self._redis_get(redis_key)
                if cached:
                    self._tool_cache[session_key] = cached
                    return cached

                result = await self.lookup_tools.execute_tool(tool_name, arguments)
                if result.get("success"):
                    self._tool_cache[session_key] = result
                    await self._redis_set(redis_key, result, ttl=900)
                return result

            if tool_name == "lookup_list_collections":
                session_key = "lookup_list_collections"

                if session_key in self._tool_cache:
                    return cast("dict[str, Any]", self._tool_cache[session_key])

                redis_key = f"lookup:collections:{self.workspace_id}"
                cached = await self._redis_get(redis_key)
                if cached:
                    self._tool_cache[session_key] = cached
                    return cached

                result = await self.lookup_tools.execute_tool(tool_name, arguments)
                if result.get("success"):
                    self._tool_cache[session_key] = result
                    await self._redis_set(redis_key, result, ttl=900)
                return result

            return await self.lookup_tools.execute_tool(tool_name, arguments)

        # Categorization tools
        if tool_name == "categorize":
            tree_name = str(arguments.get("tree_name", ""))
            text_norm = str(arguments.get("text", "")).lower().strip()
            session_key = f"categorize:{tree_name}:{text_norm}"

            # Layer 0: session-level exact cache (within this call)
            if session_key in self._tool_cache:
                return cast("dict[str, Any]", self._tool_cache[session_key])

            # Layer 1: Redis result cache (cross-session, 24 h for LLM results)
            redis_key = f"categorize:{self.workspace_id}:{tree_name}:{_short_hash(text_norm)}"
            cached = await self._redis_get(redis_key)
            if cached:
                self._tool_cache[session_key] = cached
                return cached

            # Layer 2: in-memory match against prewarmed tree nodes (sub-millisecond)
            prewarmed_nodes = self._prewarmed_trees.get(tree_name)
            if prewarmed_nodes:
                in_mem = _match_in_memory(text_norm, prewarmed_nodes)
                if in_mem:
                    self._tool_cache[session_key] = in_mem
                    return in_mem

            # Layer 3: Postgres FTS + optional LLM fallback (existing path)
            # Pass prewarmed nodes so match_category() and categorize_tools skip
            # redundant DB queries for LLM traversal and path reconstruction.
            if prewarmed_nodes:
                arguments = {**arguments, "_prewarmed_nodes": prewarmed_nodes}
            result = await self.categorize_tools.execute_tool(tool_name, arguments)
            self._tool_cache[session_key] = result
            if result.get("success") and result.get("resolution_layer") == "llm":
                await self._redis_set(redis_key, result, ttl=86400)
            return result

        # Resend email tools — fire-and-forget so the agent doesn't wait for HTTP
        if tool_name == "resend_send_email":
            resend_tools = self._get_resend_email_tools()
            if not resend_tools:
                return {
                    "success": False,
                    "error": "Resend integration not configured. Please add your API key and from email.",
                }
            task = asyncio.create_task(resend_tools.execute_tool(tool_name, arguments))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
            return {"success": True, "queued": True, "message": "Email is being sent"}

        # Campaign tools
        campaign_tool_names = {
            "set_call_disposition",
        }

        if tool_name in campaign_tool_names:
            return await CampaignTools.execute_tool(tool_name, arguments)

        # Unknown tool
        return {"success": False, "error": f"Unknown tool: {tool_name}"}

    async def close(self) -> None:
        """Clean up resources."""
        # Wait for any background tasks (e.g. fire-and-forget emails) to finish
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
        if self._ghl_tools:
            await self._ghl_tools.close()
        if self._calendly_tools:
            await self._calendly_tools.close()
        if self._shopify_tools:
            await self._shopify_tools.close()
        if self._twilio_sms_tools:
            await self._twilio_sms_tools.close()
        if self._telnyx_sms_tools:
            await self._telnyx_sms_tools.close()
        if self._resend_email_tools:
            await self._resend_email_tools.close()
