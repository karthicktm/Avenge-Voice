# Agent Test Call — Design Spec

**Date:** 2026-05-27  
**Status:** Approved

---

## Context

Voice agents deployed on Railway need to be tested before going live with real customers. The existing **Workflow Debugger** (`/dashboard/workflows/[id]/test`) tests workflow logic in isolation via text input — it does not exercise the live voice agent, its STT/TTS pipeline, or its full conversational behavior.

This feature adds a **voice agent test caller**: an AI-powered caller that connects to the live voice agent via two bridged OpenAI Realtime sessions on the backend. The tester configures a persona + goal (e.g. "frustrated customer who wants a refund"), clicks Start, and watches a real AI-vs-AI conversation happen in real time — including tool calls and workflow progression.

---

## Architecture

```
Browser (Dashboard page)
  │
  ├── POST /api/v1/agents/{id}/test-calls   → { session_id }
  └── WS  /ws/agent-test/{session_id}       ← event stream
                    │
            ┌───────────────────────────────┐
            │      AgentTestBridge          │
            │                               │
            │  Caller Realtime Session      │
            │  (new OpenAI connection)      │
            │  • system: persona + goal     │
            │  • voice: "alloy" (fixed)     │
            │  • tool: end_call()           │
            │           ↕ audio             │
            │  Agent Realtime Session       │
            │  (GPTRealtimeSession reuse)   │
            │  • full agent config/tools    │
            │  • workflow engine active     │
            └───────────────────────────────┘
                    │
              events → browser WebSocket
```

Transport: both Realtime sessions use WebSocket to OpenAI. The browser only receives text events — no audio plumbing in the browser.

---

## Backend

### New: `backend/app/services/agent_test_bridge.py`

```python
class AgentTestBridge:
    def __init__(
        self,
        agent_id: uuid.UUID,
        scenario: TestScenario,          # persona + goal strings
        db: AsyncSession,
        user_id: int,
        workspace_id: uuid.UUID,
        openai_api_key: str,
    ) -> None: ...

    # Public interface
    async def start(self) -> None        # connect both sessions, trigger caller greeting
    async def run(self) -> None          # run 4 concurrent tasks until session ends
    async def stop(self) -> None         # graceful shutdown of both connections

    # Internal coroutines (asyncio.gather in run())
    async def _caller_event_loop(self) -> None         # collect caller audio, handle end_call, emit caller.speech.*
    async def _agent_event_loop(self) -> None          # collect agent audio, call handle_function_call_event, emit agent.*
    async def _forward_caller_audio_to_agent(self) -> None   # caller audio queue → agent_session.send_audio(bytes)
    async def _forward_agent_audio_to_caller(self) -> None   # agent audio queue → caller_conn.input_audio_buffer.append
```

**Caller session config:**
- Model: same as agent's `llm_model` (or `gpt-4o-realtime-preview` as fallback)
- Voice: `"alloy"` (always distinct from agent's configured voice)
- Turn detection: server_vad, threshold 0.5
- System prompt:
  ```
  You are simulating a caller on a phone support line.
  Persona: {persona}
  Goal: {goal}
  Speak naturally. One or two sentences per turn.
  When your goal is complete or you choose to end the call, use end_call().
  ```
- Tools: only `end_call()` — no-arg function that signals test completion

**Agent session:** Initialized using existing `GPTRealtimeSession` with the real agent's full config (system_prompt, voice, enabled_tools, enabled_tool_ids, tool_configs, workflow_id, etc.). All existing initialization logic including `ToolRegistry` and `WorkflowExecutor` is reused.

**Audio bridge mechanics:**
- Caller's `response.audio.delta` events (base64 PCM16) → `agent.connection.input_audio_buffer.append`
- Agent's `response.audio.delta` events → `caller_conn.input_audio_buffer.append`
- No echo: audio from session A never routes back to session A
- Both sessions' VAD handles turn detection independently

**End conditions:**
- Caller invokes `end_call()` tool
- 50 turns reached (max_turns guard)
- 10 minutes elapsed (max_duration guard)
- Either Realtime connection drops

**Events emitted to browser queue:**

```python
{ "type": "session.started" }
{ "type": "caller.speech.delta", "text": str }
{ "type": "caller.speech.done",  "text": str }
{ "type": "agent.speech.delta",  "text": str }
{ "type": "agent.speech.done",   "text": str }
{ "type": "agent.tool_call",     "tool": str, "args": dict }
{ "type": "agent.tool_result",   "tool": str, "result": dict, "elapsed_ms": float }
{ "type": "agent.workflow_node", "node_id": str, "node_type": str, "node_label": str }
{ "type": "session.complete",    "reason": "end_call" | "max_turns" | "max_duration" }
{ "type": "session.error",       "message": str }
```

---

### New: `backend/app/api/agent_test.py`

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `POST` | `/api/v1/agents/{agent_id}/test-calls` | VerifiedUser | Create bridge session → `{ session_id }` |
| `DELETE` | `/api/v1/agents/{agent_id}/test-calls/{session_id}` | VerifiedUser | Stop and clean up |
| `WS GET` | `/ws/agent-test/{session_id}` | token query param | Stream events to browser |

**POST request body:**
```python
class TestCallRequest(BaseModel):
    persona: str   # e.g. "angry customer with a broken product"
    goal: str      # e.g. "get a full refund and complaint filed"
```

**Session state in Redis:** Key `agent_test:{session_id}`, TTL 3600s. Stores agent_id, user_id, workspace_id, scenario, status.

**Validation:** Verify user owns the agent's workspace before creating session.

---

### Modified: `backend/app/main.py`

Register `agent_test.router` after `workflow_test.router`.

---

## Frontend

### New page: `frontend/src/app/dashboard/agents/[id]/test-call/page.tsx`

State via `useReducer`. WebSocket lifecycle: POST → get `session_id` → open WS → dispatch events → close on complete/error.

**3-panel layout:**

```
┌──────────────────────────────────────────────────┐
│  Test Call: {Agent Name}            [Stop Test]  │
├───────────────┬──────────────────┬───────────────┤
│ SETUP         │ CONVERSATION     │ AGENT STATE   │
│               │                  │               │
│ Persona:      │ Streaming        │ Tool calls    │
│ [textarea]    │ transcript       │ timeline      │
│               │ (caller=blue,    │               │
│ Goal:         │  agent=green)    │ Workflow node │
│ [textarea]    │                  │ badge         │
│               │ Status badge     │               │
│ [Start Test]  │                  │               │
└───────────────┴──────────────────┴───────────────┘
```

### New components:

- `frontend/src/components/agent/test/TestCallSetup.tsx` — persona/goal form, start/stop, status indicator
- `frontend/src/components/agent/test/TestCallTranscript.tsx` — streaming transcript with delta updates
- `frontend/src/components/agent/test/TestCallAgentState.tsx` — tool calls timeline + workflow node badge

### New API client: `frontend/src/lib/api/agent-test.ts`

```typescript
startTestCall(agentId: string, persona: string, goal: string): Promise<{ session_id: string }>
stopTestCall(agentId: string, sessionId: string): Promise<void>
```

### Modified: agent detail page

Add "Test Call" button navigating to `/dashboard/agents/{id}/test-call`.

---

## Key Reusable Code

| What to reuse | Where |
|---------------|-------|
| `GPTRealtimeSession` initialization | `backend/app/services/gpt_realtime.py:518` |
| `handle_function_call_event()` for tool calls | `backend/app/services/gpt_realtime.py:1027` |
| `send_audio(bytes)` to feed audio into agent | `backend/app/services/gpt_realtime.py:1591` |
| `realtime_to_client()` event loop pattern | `backend/app/api/realtime.py:317` |
| Agent config loading (tools, workspace, workflow) | `backend/app/api/realtime.py:93–250` |
| `get_openai_api_key_for_workspace()` | `backend/app/api/realtime.py:32` |
| Redis session pattern (key format, TTL, load/save) | `backend/app/api/workflow_test.py:63–99` |
| `VerifiedUser` auth dependency | `backend/app/core/auth.py` |
| 3-panel layout pattern | `frontend/src/app/dashboard/workflows/[id]/test/page.tsx` |
| Streaming transcript pattern | `frontend/src/components/workflow/test/TestConversation.tsx` |

---

## Files to Create / Modify

**Create:**
- `backend/app/api/agent_test.py`
- `backend/app/services/agent_test_bridge.py`
- `frontend/src/app/dashboard/agents/[id]/test-call/page.tsx`
- `frontend/src/components/agent/test/TestCallSetup.tsx`
- `frontend/src/components/agent/test/TestCallTranscript.tsx`
- `frontend/src/components/agent/test/TestCallAgentState.tsx`
- `frontend/src/lib/api/agent-test.ts`

**Modify:**
- `backend/app/main.py` — register `agent_test.router`
- `frontend/src/app/dashboard/agents/[id]/page.tsx` — add "Test Call" button

---

## Verification

1. `cd backend && uv run uvicorn app.main:app --reload`
2. `cd frontend && npm run dev`
3. Open `/dashboard/agents/{id}/test-call`
4. Enter persona: "frustrated customer with billing issue" / goal: "get credited $50"
5. Click Start Test — observe streaming conversation, tool calls, workflow node
6. Verify test completes when caller invokes `end_call()`
7. `cd backend && uv run ruff check app --fix && uv run mypy app`
8. `cd frontend && npm run check`
