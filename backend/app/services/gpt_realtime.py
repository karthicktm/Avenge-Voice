"""GPT Realtime API service for Premium tier voice agents."""

import json
import types
import uuid
from typing import Any

import structlog
from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.integrations import get_workspace_integrations
from app.api.settings import get_user_api_keys
from app.core.auth import user_id_to_uuid
from app.services.tools.registry import ToolRegistry

logger = structlog.get_logger()

# Language code to human-readable name mapping
LANGUAGE_NAMES: dict[str, str] = {
    "en-US": "English",
    "en-GB": "English (British)",
    "es-ES": "Spanish",
    "es-MX": "Spanish (Mexican)",
    "fr-FR": "French",
    "de-DE": "German",
    "it-IT": "Italian",
    "pt-BR": "Portuguese (Brazilian)",
    "pt-PT": "Portuguese",
    "nl-NL": "Dutch",
    "ja-JP": "Japanese",
    "ko-KR": "Korean",
    "zh-CN": "Chinese (Mandarin)",
    "zh-TW": "Chinese (Traditional)",
    "ru-RU": "Russian",
    "ar-SA": "Arabic",
    "hi-IN": "Hindi",
    "pl-PL": "Polish",
    "tr-TR": "Turkish",
    "vi-VN": "Vietnamese",
    "th-TH": "Thai",
    "id-ID": "Indonesian",
    "ms-MY": "Malay",
    "fil-PH": "Filipino",
}


def build_instructions_with_language(
    system_prompt: str,
    language: str,
    enabled_tools: list[str] | None = None,
    timezone: str | None = None,
    knowledge_base_info: dict[str, Any] | None = None,
) -> str:
    """Build comprehensive voice agent instructions.

    Wraps the user's custom system prompt with voice-specific configuration
    including language requirements, conversation guidelines, and tool context.

    Args:
        system_prompt: The agent's custom system prompt (from frontend UI)
        language: Language code (e.g., "en-US", "es-ES")
        enabled_tools: List of enabled tool IDs (optional, for context)
        timezone: Workspace timezone (e.g., "America/New_York", "UTC")
        knowledge_base_info: Info about uploaded documents (optional)
            - document_count: Number of documents
            - document_names: List of document filenames

    Returns:
        Complete instructions string optimized for voice conversations
    """
    language_name = LANGUAGE_NAMES.get(language, language)
    tz_name = timezone or "UTC"

    # Get current date/time in the workspace timezone for context
    from datetime import datetime

    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(tz_name)
        now = datetime.now(tz)
        current_datetime = now.strftime("%A, %B %d, %Y at %I:%M %p")
    except Exception:
        # Fallback if timezone is invalid
        current_datetime = datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")

    # Build knowledge base section if available
    knowledge_base_section = ""
    if knowledge_base_info and knowledge_base_info.get("document_count", 0) > 0:
        doc_count = knowledge_base_info["document_count"]
        doc_names = knowledge_base_info.get("document_names", [])

        # Format document list (limit for brevity)
        max_docs_to_show = 10
        if doc_names:
            doc_list = ", ".join(doc_names[:max_docs_to_show])
            if len(doc_names) > max_docs_to_show:
                doc_list += f", and {len(doc_names) - max_docs_to_show} more"
        else:
            doc_list = f"{doc_count} documents"

        knowledge_base_section = f"""
[KNOWLEDGE BASE]
You have access to a knowledge base with {doc_count} uploaded document(s): {doc_list}

IMPORTANT: When the user asks questions about products, services, pricing, policies, FAQs,
or any information that might be in your documentation, you MUST use the search_knowledge_base
tool to find accurate information. Do NOT make up answers - always search first.

Examples of when to search:
- "What are your prices?" -> search_knowledge_base("pricing rates cost")
- "How does X work?" -> search_knowledge_base("how X works features")
- "What's your return policy?" -> search_knowledge_base("return policy refund")
- "Tell me about your services" -> search_knowledge_base("services offerings")
"""

    # Build the complete voice agent instructions
    instructions = f"""[CONTEXT]
Language: {language_name}
Timezone: {tz_name}
Current: {current_datetime}

[RULES]
- Speak ONLY in {language_name}
- All times are in {tz_name} timezone
- For booking tools, use ISO format with timezone offset (e.g., 2024-12-01T14:00:00-05:00)
- Keep responses concise - this is voice, not text
- Summarize tool results naturally
{knowledge_base_section}
[YOUR ROLE]
{system_prompt}"""

    return instructions


class TranscriptEntry:
    """Single transcript entry representing one turn in the conversation."""

    def __init__(self, role: str, content: str, timestamp: str | None = None) -> None:
        from datetime import UTC, datetime

        self.role = role  # "user" or "assistant"
        self.content = content
        self.timestamp = timestamp or datetime.now(UTC).isoformat()

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content, "timestamp": self.timestamp}


class GPTRealtimeSession:
    """Manages a GPT Realtime API session for a voice call.

    Handles:
    - WebSocket connection to OpenAI Realtime API
    - Internal tool integration
    - Audio streaming
    - Tool call routing to internal tool handlers
    - Transcript accumulation
    """

    def __init__(
        self,
        db: AsyncSession,
        user_id: int,
        agent_config: dict[str, Any],
        session_id: str | None = None,
        workspace_id: uuid.UUID | None = None,
    ) -> None:
        """Initialize GPT Realtime session.

        Args:
            db: Database session
            user_id: User ID (int, from users.id)
            agent_config: Agent configuration (system prompt, enabled integrations, etc.)
            session_id: Optional session ID
            workspace_id: Workspace UUID (required for API key isolation)
        """
        self.db = db
        self.user_id = user_id  # int for ToolRegistry (Contact queries)
        self.user_id_uuid = user_id_to_uuid(user_id)  # UUID for UserSettings queries
        self.workspace_id = workspace_id  # For workspace-isolated API key lookup
        self.agent_config = agent_config
        self.session_id = session_id or str(uuid.uuid4())
        self.connection: Any = None
        self.tool_registry: ToolRegistry | None = None
        self.client: AsyncOpenAI | None = None
        # Transcript accumulation
        self._transcript_entries: list[TranscriptEntry] = []
        self._current_assistant_text: str = ""
        # Initial greeting (triggered after event loop starts to avoid race condition)
        self._pending_initial_greeting: str | None = None
        self._greeting_triggered: bool = False
        self.logger = logger.bind(
            component="gpt_realtime",
            session_id=self.session_id,
            user_id=str(user_id),
            workspace_id=str(workspace_id) if workspace_id else None,
        )

    async def initialize(self) -> None:
        """Initialize the Realtime session with internal tools."""
        self.logger.info("gpt_realtime_session_initializing")

        # Get user's API keys from settings (uses UUID)
        # Workspace isolation: only use workspace-specific API keys, no fallback
        user_settings = await get_user_api_keys(
            self.user_id_uuid, self.db, workspace_id=self.workspace_id
        )

        # Strictly use workspace API key - no fallback to global key for billing isolation
        if not user_settings or not user_settings.openai_api_key:
            self.logger.warning("workspace_missing_openai_key", workspace_id=str(self.workspace_id))
            raise ValueError(
                "OpenAI API key not configured for this workspace. Please add it in Settings > Workspace API Keys."
            )
        api_key = user_settings.openai_api_key
        self.logger.info("using_workspace_openai_key")

        # Initialize OpenAI client with user's or global API key
        self.client = AsyncOpenAI(api_key=api_key)

        # Get integration credentials for the workspace
        integrations: dict[str, Any] = {}
        if self.workspace_id:
            integrations = await get_workspace_integrations(
                self.user_id_uuid, self.workspace_id, self.db
            )

        # Merge agent's tool_configs into integrations (agent-specific settings override workspace)
        tool_configs = self.agent_config.get("tool_configs", {})
        if tool_configs:
            integrations.update(tool_configs)

        # Get agent_id from config if available
        agent_id_str = self.agent_config.get("agent_id")
        agent_id = uuid.UUID(agent_id_str) if agent_id_str else None

        # Initialize tool registry with enabled tools and workspace context
        # Pass OpenAI API key for RAG embeddings fallback
        self.tool_registry = ToolRegistry(
            self.db,
            self.user_id,
            integrations=integrations,
            workspace_id=self.workspace_id,
            agent_id=agent_id,
            openai_api_key=api_key,
        )

        # Connect to OpenAI Realtime API
        await self._connect_realtime_api()

        self.logger.info("gpt_realtime_session_initialized")

    async def _connect_realtime_api(self) -> None:
        """Establish connection to OpenAI Realtime API using official SDK."""
        if not self.client:
            raise ValueError("OpenAI client not initialized")

        # Use the latest production gpt-realtime model (released Aug 2025)
        model = "gpt-realtime-2025-08-28"
        self.logger.info("connecting_to_openai_realtime", model=model)

        try:
            # Use official SDK's realtime.connect() method
            self.connection = await self.client.beta.realtime.connect(model=model).__aenter__()

            self.logger.info("realtime_connection_established")

            # Configure session with internal tools
            await self._configure_session()

            self.logger.info("connected_to_openai_realtime")

        except Exception as e:
            self.logger.exception(
                "realtime_connection_failed", error=str(e), error_type=type(e).__name__
            )
            raise

    async def _configure_session(self) -> None:
        """Configure Realtime API session with agent settings and internal tools."""
        if not self.connection or not self.tool_registry:
            self.logger.warning(
                "session_config_skipped",
                has_connection=bool(self.connection),
                has_registry=bool(self.tool_registry),
            )
            return

        # Get tool definitions from registry
        enabled_tools = self.agent_config.get("enabled_tools", [])
        tools = self.tool_registry.get_all_tool_definitions(enabled_tools)

        # Get workspace timezone if available
        workspace_timezone = "UTC"
        if self.workspace_id:
            from app.models.workspace import Workspace

            result = await self.db.execute(
                select(Workspace).where(Workspace.id == self.workspace_id)
            )
            workspace = result.scalar_one_or_none()
            if workspace and workspace.settings:
                workspace_timezone = workspace.settings.get("timezone", "UTC")

        # Get knowledge base info if agent has documents
        knowledge_base_info: dict[str, Any] | None = None
        agent_id_str = self.agent_config.get("agent_id")
        if agent_id_str and "knowledge_base" in enabled_tools:
            from app.models.document import Document

            agent_uuid = uuid.UUID(agent_id_str)
            # Query ready documents for this agent
            result = await self.db.execute(
                select(Document.filename)
                .where(Document.agent_id == agent_uuid)
                .where(Document.status == "ready")
            )
            doc_names = [row[0] for row in result.fetchall()]
            if doc_names:
                knowledge_base_info = {
                    "document_count": len(doc_names),
                    "document_names": doc_names,
                }
                self.logger.info(
                    "knowledge_base_context_loaded",
                    document_count=len(doc_names),
                )

        # Build instructions with language directive and timezone
        system_prompt = self.agent_config.get("system_prompt", "You are a helpful voice assistant.")
        language = self.agent_config.get("language", "en-US")
        # Default to marin for natural conversational tone
        voice = self.agent_config.get("voice", "marin")
        temperature = self.agent_config.get("temperature", 0.6)
        instructions = build_instructions_with_language(
            system_prompt,
            language,
            timezone=workspace_timezone,
            knowledge_base_info=knowledge_base_info,
        )

        session_config = {
            "modalities": ["text", "audio"],
            "instructions": instructions,
            "voice": voice,
            "speed": 1.1,  # Slightly faster speech (1.0 = normal, range: 0.25-1.5)
            "temperature": temperature,  # Lower for consistent, natural delivery
            # Use g711_ulaw for Twilio/Telnyx compatibility (mulaw at 8kHz)
            "input_audio_format": "g711_ulaw",
            "output_audio_format": "g711_ulaw",
            "input_audio_transcription": {"model": "whisper-1"},
            "turn_detection": {
                "type": "server_vad",
                "threshold": 0.5,
                "prefix_padding_ms": 200,
                "silence_duration_ms": 200,
            },
            "tools": tools,
            "tool_choice": "auto",
        }

        self.logger.info("configuring_session", tool_count=len(tools), enabled_tools=enabled_tools)

        try:
            # Build session configuration using SDK
            await self.connection.session.update(session=session_config)

            self.logger.info(
                "session_configured",
                tool_count=len(tools),
            )

            # Store initial greeting for later - triggered after event loop starts
            # to avoid race condition where audio events arrive before listener is ready
            initial_greeting = self.agent_config.get("initial_greeting")
            if initial_greeting:
                self._pending_initial_greeting = initial_greeting
                self.logger.info(
                    "initial_greeting_pending",
                    greeting=initial_greeting[:50],
                )
        except Exception as e:
            self.logger.exception(
                "session_config_failed", error=str(e), error_type=type(e).__name__
            )
            raise

    async def handle_tool_call(self, tool_call: dict[str, Any]) -> dict[str, Any]:
        """Handle tool call from GPT Realtime by routing to internal tools.

        Args:
            tool_call: Tool call from GPT Realtime

        Returns:
            Tool result
        """
        if not self.tool_registry:
            return {"success": False, "error": "Tool registry not initialized"}

        tool_name = tool_call.get("name", "")
        arguments = tool_call.get("arguments", {})

        self.logger.info(
            "handling_tool_call",
            tool_name=tool_name,
            arguments=arguments,
        )

        # Execute tool via internal tool registry
        result = await self.tool_registry.execute_tool(tool_name, arguments)

        return result

    async def process_realtime_events(self) -> None:
        """Process events from OpenAI Realtime API using official SDK.

        This is the main event loop that:
        1. Receives events from OpenAI
        2. Handles tool calls by routing to internal tool handlers
        3. Sends responses back to OpenAI
        """
        if not self.connection:
            raise RuntimeError("Realtime connection not established")

        try:
            async for event in self.connection:
                try:
                    event_type = event.type

                    self.logger.debug("realtime_event_received", event_type=event_type)

                    # Handle function/tool calls
                    if event_type == "response.function_call_arguments.done":
                        await self.handle_function_call_event(event)

                    # Handle audio output
                    elif event_type == "response.audio.delta":
                        # Audio data available in event.delta
                        pass

                    # Handle transcription
                    elif event_type == "conversation.item.input_audio_transcription.completed":
                        # Transcription available in event.transcript
                        pass

                    # Handle errors
                    elif event_type == "error":
                        self.logger.error("realtime_api_error", error=event.error)

                except Exception as e:
                    self.logger.exception("event_processing_error", error=str(e))

        except Exception as e:
            self.logger.exception("realtime_event_loop_error", error=str(e))
            raise

    async def handle_function_call_event(self, event: Any) -> dict[str, Any]:
        """Handle function call from GPT Realtime.

        Args:
            event: Function call event from SDK

        Returns:
            Tool execution result with optional 'action' field for call control
        """
        call_id = event.call_id
        name = event.name

        # Parse arguments safely - GPT may send incomplete/malformed JSON
        try:
            arguments = (
                json.loads(event.arguments) if isinstance(event.arguments, str) else event.arguments
            )
        except json.JSONDecodeError as e:
            self.logger.warning(
                "function_call_json_parse_error",
                call_id=call_id,
                tool_name=name,
                raw_arguments=str(event.arguments)[:200],
                error=str(e),
            )
            # Return error to GPT so it can retry
            if self.connection:
                await self.connection.conversation.item.create(
                    item={
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": json.dumps({"success": False, "error": "Invalid JSON arguments"}),
                    }
                )
            return {"success": False, "error": "Invalid JSON arguments"}

        # Execute tool via internal tool registry
        result = await self.handle_tool_call({"name": name, "arguments": arguments})

        # Send result back using SDK
        if self.connection:
            await self.connection.conversation.item.create(
                item={
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": json.dumps(result),
                }
            )
            # Trigger GPT to generate a response after the function call
            await self.connection.response.create()

        self.logger.info(
            "function_call_completed",
            call_id=call_id,
            tool_name=name,
            success=result.get("success"),
            action=result.get("action"),
        )

        return result

    async def trigger_initial_greeting(self) -> bool:
        """Trigger the initial greeting if one is pending.

        This should be called AFTER the event listener has started to avoid
        race conditions where audio events arrive before the listener is ready.

        Returns:
            True if greeting was triggered, False if no greeting pending or already triggered
        """
        if not self._pending_initial_greeting or self._greeting_triggered:
            return False

        if not self.connection:
            self.logger.warning("cannot_trigger_greeting_no_connection")
            return False

        self._greeting_triggered = True
        greeting = self._pending_initial_greeting

        self.logger.info("triggering_initial_greeting", greeting=greeting[:50])

        try:
            # Clear any buffered input audio to prevent line noise from
            # triggering VAD and cancelling the greeting response
            await self.connection.input_audio_buffer.clear()

            # Standard OpenAI Realtime pattern:
            # 1. Create a conversation item with the prompt
            # 2. Call response.create() to trigger the response
            # This follows the official OpenAI examples
            await self.connection.conversation.item.create(
                item={
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": f"[Call connected. Say this greeting now: {greeting}]",
                        }
                    ],
                }
            )
            # Trigger response generation (no parameters needed)
            await self.connection.response.create()
            return True
        except Exception as e:
            self.logger.exception("initial_greeting_failed", error=str(e))
            return False

    async def send_audio(self, audio_data: bytes) -> None:
        """Send audio input to GPT Realtime using SDK.

        Args:
            audio_data: PCM16 audio data (raw bytes)
        """
        if not self.connection:
            self.logger.error("send_audio_failed_no_connection")
            return

        try:
            import base64

            # Convert raw bytes to base64 string as required by OpenAI Realtime API
            audio_base64 = base64.b64encode(audio_data).decode("utf-8")

            # Use SDK's input_audio_buffer.append method
            await self.connection.input_audio_buffer.append(audio=audio_base64)
            self.logger.debug(
                "audio_sent_to_realtime",
                size_bytes=len(audio_data),
                base64_length=len(audio_base64),
            )
        except Exception as e:
            self.logger.exception("send_audio_error", error=str(e), error_type=type(e).__name__)

    def add_user_transcript(self, text: str) -> None:
        """Add a user transcript entry.

        Args:
            text: Transcribed user speech
        """
        if text.strip():
            self._transcript_entries.append(TranscriptEntry(role="user", content=text.strip()))
            self.logger.debug("user_transcript_added", text_length=len(text))

    def add_assistant_transcript(self, text: str) -> None:
        """Add an assistant transcript entry.

        Args:
            text: Assistant response text
        """
        if text.strip():
            self._transcript_entries.append(TranscriptEntry(role="assistant", content=text.strip()))
            self.logger.debug("assistant_transcript_added", text_length=len(text))

    def accumulate_assistant_text(self, delta: str) -> None:
        """Accumulate assistant text delta for transcript.

        Args:
            delta: Text delta from response.text.delta event
        """
        self._current_assistant_text += delta

    def flush_assistant_text(self) -> None:
        """Flush accumulated assistant text to transcript."""
        if self._current_assistant_text.strip():
            self.add_assistant_transcript(self._current_assistant_text)
        self._current_assistant_text = ""

    def get_transcript(self) -> str:
        """Get the full transcript as formatted text.

        Returns:
            Formatted transcript string
        """
        lines = []
        for entry in self._transcript_entries:
            role_label = "User" if entry.role == "user" else "Assistant"
            lines.append(f"[{role_label}]: {entry.content}")
        return "\n\n".join(lines)

    def get_transcript_entries(self) -> list[dict[str, str]]:
        """Get transcript entries as list of dicts.

        Returns:
            List of transcript entry dictionaries
        """
        return [entry.to_dict() for entry in self._transcript_entries]

    async def cleanup(self) -> None:
        """Cleanup resources."""
        self.logger.info("gpt_realtime_session_cleanup_started")

        # Flush any remaining assistant text
        self.flush_assistant_text()

        # Close Realtime connection
        if self.connection:
            try:
                # Try close() method first (if available)
                if hasattr(self.connection, "close"):
                    await self.connection.close()
                # Otherwise try aclose() for async generators
                elif hasattr(self.connection, "aclose"):
                    await self.connection.aclose()
                self.logger.info("realtime_connection_closed")
            except Exception as e:
                self.logger.warning("connection_close_failed", error=str(e))

        # Cleanup tool registry
        if self.tool_registry:
            # No cleanup needed for internal tools
            pass

        self.logger.info(
            "gpt_realtime_session_cleanup_completed",
            transcript_entries=len(self._transcript_entries),
        )

    async def __aenter__(self) -> "GPTRealtimeSession":
        """Async context manager entry."""
        await self.initialize()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Async context manager exit."""
        await self.cleanup()
