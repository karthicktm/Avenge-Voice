"use client";

import { use, useCallback, useEffect, useReducer, useRef } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { toast } from "sonner";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { getAgent } from "@/lib/api/agents";
import {
  startTestCall,
  stopTestCall,
  createTestCallWebSocket,
} from "@/lib/api/agent-test";
import {
  TestCallSetup,
  type TestCallStatus,
} from "@/components/agent/test/TestCallSetup";
import {
  TestCallTranscript,
  type TranscriptEntry,
} from "@/components/agent/test/TestCallTranscript";
import {
  TestCallAgentState,
  type ToolCallEntry,
  type WorkflowNodeInfo,
} from "@/components/agent/test/TestCallAgentState";

// ── State ─────────────────────────────────────────────────────────────────────

interface PageState {
  persona: string;
  goal: string;
  sessionId: string | null;
  status: TestCallStatus;
  transcript: TranscriptEntry[];
  toolCalls: ToolCallEntry[];
  currentWorkflowNode: WorkflowNodeInfo | null;
  errorMessage: string | null;
}

type Action =
  | { type: "SET_PERSONA"; persona: string }
  | { type: "SET_GOAL"; goal: string }
  | { type: "SESSION_CREATED"; sessionId: string }
  | { type: "WS_OPEN" }
  | { type: "WS_EVENT"; event: Record<string, unknown> }
  | { type: "STOP" }
  | { type: "RESET" };

function initialState(): PageState {
  return {
    persona: "",
    goal: "",
    sessionId: null,
    status: "idle",
    transcript: [],
    toolCalls: [],
    currentWorkflowNode: null,
    errorMessage: null,
  };
}

function reducer(state: PageState, action: Action): PageState {
  switch (action.type) {
    case "SET_PERSONA":
      return { ...state, persona: action.persona };
    case "SET_GOAL":
      return { ...state, goal: action.goal };
    case "SESSION_CREATED":
      return { ...state, sessionId: action.sessionId, status: "connecting" };
    case "WS_OPEN":
      return { ...state, status: "running" };
    case "STOP":
      return { ...state, status: "idle", sessionId: null };
    case "RESET":
      return initialState();
    case "WS_EVENT": {
      const et = action.event.type as string;

      if (et === "session.started") {
        return { ...state, status: "running" };
      }

      if (et === "caller.speech.delta" || et === "agent.speech.delta") {
        const speaker = et.startsWith("caller")
          ? ("caller" as const)
          : ("agent" as const);
        const text = action.event.text as string;
        const last = state.transcript[state.transcript.length - 1];
        if (last?.speaker === speaker && last.isDelta) {
          return {
            ...state,
            transcript: [
              ...state.transcript.slice(0, -1),
              { ...last, text },
            ],
          };
        }
        return {
          ...state,
          transcript: [
            ...state.transcript,
            { id: crypto.randomUUID(), speaker, text, isDelta: true },
          ],
        };
      }

      if (et === "caller.speech.done" || et === "agent.speech.done") {
        const speaker = et.startsWith("caller")
          ? ("caller" as const)
          : ("agent" as const);
        const text = action.event.text as string;
        const last = state.transcript[state.transcript.length - 1];
        if (last?.speaker === speaker) {
          return {
            ...state,
            transcript: [
              ...state.transcript.slice(0, -1),
              { ...last, text, isDelta: false },
            ],
          };
        }
        return {
          ...state,
          transcript: [
            ...state.transcript,
            { id: crypto.randomUUID(), speaker, text, isDelta: false },
          ],
        };
      }

      if (et === "agent.tool_call") {
        const newEntry: ToolCallEntry = {
          id: crypto.randomUUID(),
          tool: action.event.tool as string,
          args: action.event.args as Record<string, unknown>,
        };
        return { ...state, toolCalls: [...state.toolCalls, newEntry] };
      }

      if (et === "agent.tool_result") {
        const tool = action.event.tool as string;
        const result = action.event.result as Record<string, unknown>;
        const elapsedMs = action.event.elapsed_ms as number;
        const idx = [...state.toolCalls]
          .reverse()
          .findIndex((tc) => tc.tool === tool && tc.result === undefined);
        if (idx >= 0) {
          const realIdx = state.toolCalls.length - 1 - idx;
          const updated = [...state.toolCalls];
          const existing = updated[realIdx];
          if (existing) {
            updated[realIdx] = {
              id: existing.id,
              tool: existing.tool,
              args: existing.args,
              result,
              elapsedMs,
            };
          }
          return { ...state, toolCalls: updated };
        }
        return state;
      }

      if (et === "agent.workflow_node") {
        return {
          ...state,
          currentWorkflowNode: {
            nodeId: action.event.node_id as string,
            nodeType: action.event.node_type as string,
            nodeLabel: action.event.node_label as string,
          },
        };
      }

      if (et === "session.complete") {
        return { ...state, status: "complete" };
      }

      if (et === "session.error") {
        return {
          ...state,
          status: "error",
          errorMessage: action.event.message as string,
        };
      }

      return state;
    }
  }
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function AgentTestCallPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id: agentId } = use(params);
  const router = useRouter();
  const [state, dispatch] = useReducer(reducer, undefined, initialState);
  const wsRef = useRef<WebSocket | null>(null);

  const { data: agent } = useQuery({
    queryKey: ["agent", agentId],
    queryFn: () => getAgent(agentId),
  });

  // Close WebSocket on unmount
  useEffect(() => {
    return () => {
      wsRef.current?.close();
    };
  }, []);

  const handleStart = useCallback(async () => {
    try {
      const { session_id } = await startTestCall(
        agentId,
        state.persona,
        state.goal,
      );
      dispatch({ type: "SESSION_CREATED", sessionId: session_id });

      const ws = createTestCallWebSocket(session_id);
      wsRef.current = ws;

      ws.onopen = () => dispatch({ type: "WS_OPEN" });
      ws.onmessage = (e: MessageEvent<string>) => {
        try {
          const event = JSON.parse(e.data) as Record<string, unknown>;
          dispatch({ type: "WS_EVENT", event });
        } catch {
          // ignore malformed
        }
      };
      ws.onerror = () => {
        toast.error("WebSocket error");
        dispatch({
          type: "WS_EVENT",
          event: { type: "session.error", message: "Connection error" },
        });
      };
      ws.onclose = () => {
        wsRef.current = null;
      };
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to start test call",
      );
    }
  }, [agentId, state.persona, state.goal]);

  const handleStop = useCallback(async () => {
    wsRef.current?.close();
    wsRef.current = null;
    if (state.sessionId) {
      await stopTestCall(agentId, state.sessionId).catch(() => null);
    }
    dispatch({ type: "STOP" });
  }, [agentId, state.sessionId]);

  const isRunning =
    state.status === "running" || state.status === "connecting";

  return (
    <div className="flex h-screen flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b px-4 py-3">
        <div className="flex items-center gap-3">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => router.push(`/dashboard/agents/${agentId}`)}
            className="gap-1 text-xs"
          >
            <ArrowLeft className="h-3 w-3" />
            Back
          </Button>
          <span className="text-sm font-semibold">
            Test Call{agent ? `: ${agent.name}` : ""}
          </span>
        </div>
      </div>

      {/* 3-panel body */}
      <div className="flex min-h-0 flex-1">
        {/* Left: Setup */}
        <div className="w-64 shrink-0 border-r">
          <TestCallSetup
            persona={state.persona}
            goal={state.goal}
            status={state.status}
            onPersonaChange={(v) =>
              dispatch({ type: "SET_PERSONA", persona: v })
            }
            onGoalChange={(v) => dispatch({ type: "SET_GOAL", goal: v })}
            onStart={handleStart}
            onStop={handleStop}
          />
        </div>

        {/* Center: Transcript */}
        <div className="flex min-w-0 flex-1 flex-col">
          <TestCallTranscript
            entries={state.transcript}
            isRunning={isRunning}
          />
        </div>

        {/* Right: Agent State */}
        <div className="w-64 shrink-0 border-l">
          <TestCallAgentState
            toolCalls={state.toolCalls}
            currentWorkflowNode={state.currentWorkflowNode}
          />
        </div>
      </div>
    </div>
  );
}
