"use client";

import { useCallback, useEffect, useReducer, useRef } from "react";
import { useParams, useRouter } from "next/navigation";
import { toast } from "sonner";
import { ArrowLeft, FastForward, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { TestContextBag } from "@/components/workflow/test/TestContextBag";
import { TestConversation } from "@/components/workflow/test/TestConversation";
import { TestInputBar } from "@/components/workflow/test/TestInputBar";
import { TestNodeList } from "@/components/workflow/test/TestNodeList";
import {
  aiStepTestSession,
  deleteTestSession,
  patchTestContext,
  startTestSession,
  stepTestSession,
  type AiStepOut,
  type NodeStatus,
  type StepOut,
  type TestMode,
  type TranscriptMessage,
} from "@/lib/api/workflow-test";
import { getWorkflow, type WorkflowNode } from "@/lib/api/workflows";

// ── State ─────────────────────────────────────────────────────────────────────

interface PageState {
  sessionId: string | null;
  nodes: WorkflowNode[];
  currentNodeId: string;
  nodeStatuses: Record<string, NodeStatus>;
  contextBag: Record<string, unknown>;
  transcript: TranscriptMessage[];
  breakpoints: Set<string>;
  mode: TestMode;
  persona: string;
  isRunning: boolean;
  isPaused: boolean;
  isComplete: boolean;
  copilotSuggestions: string[];
  lastSimulationDetail: Record<string, unknown> | null;
  workflowName: string;
}

type Action =
  | {
      type: "SESSION_STARTED";
      sessionId: string;
      nodes: WorkflowNode[];
      nodeId: string;
      workflowName: string;
    }
  | { type: "STEP_DONE"; result: StepOut; callerText: string; inputMode: TestMode | "ai" }
  | { type: "SET_MODE"; mode: TestMode }
  | { type: "SET_PERSONA"; persona: string }
  | { type: "TOGGLE_BREAKPOINT"; nodeId: string }
  | { type: "SET_RUNNING"; value: boolean }
  | { type: "SET_PAUSED"; value: boolean }
  | { type: "SET_COPILOT_SUGGESTIONS"; suggestions: string[] }
  | { type: "CONTEXT_PATCHED"; contextBag: Record<string, unknown> }
  | { type: "RESET" };

function initialState(): PageState {
  return {
    sessionId: null,
    nodes: [],
    currentNodeId: "",
    nodeStatuses: {},
    contextBag: {},
    transcript: [],
    breakpoints: new Set(),
    mode: "manual",
    persona: "",
    isRunning: false,
    isPaused: false,
    isComplete: false,
    copilotSuggestions: [],
    lastSimulationDetail: null,
    workflowName: "",
  };
}

function reducer(state: PageState, action: Action): PageState {
  switch (action.type) {
    case "SESSION_STARTED": {
      const statuses: Record<string, NodeStatus> = {};
      for (const n of action.nodes) statuses[n.id] = "pending";
      statuses[action.nodeId] = "running";
      return {
        ...initialState(),
        sessionId: action.sessionId,
        nodes: action.nodes,
        currentNodeId: action.nodeId,
        nodeStatuses: statuses,
        workflowName: action.workflowName,
        isComplete: false,
      };
    }
    case "STEP_DONE": {
      const r = action.result;
      const statuses = { ...state.nodeStatuses };
      if (state.currentNodeId && state.currentNodeId !== r.current_node_id) {
        statuses[state.currentNodeId] = r.simulated ? "simulated" : "completed";
      }
      statuses[r.current_node_id] = r.is_complete ? "completed" : "running";

      const msgs: TranscriptMessage[] = [...state.transcript];
      if (action.callerText) {
        msgs.push({
          id: `caller-${Date.now()}`,
          speaker: "caller",
          text: action.callerText,
          nodeId: state.currentNodeId,
          nodeLabel: "",
          mode: action.inputMode,
          timestamp: Date.now(),
        });
      }
      if (r.node_output) {
        msgs.push({
          id: `agent-${Date.now()}`,
          speaker: "agent",
          text: r.node_output,
          nodeId: r.current_node_id,
          nodeLabel: r.current_node_label,
          mode: state.mode,
          elapsedMs: r.elapsed_ms,
          resolutionLayer: r.resolution_layer,
          simulated: r.simulated,
          simulationDetail: r.simulation_detail ?? undefined,
          timestamp: Date.now(),
        });
      }

      const pausedAtBreakpoint = state.breakpoints.has(r.current_node_id) && !r.is_complete;
      return {
        ...state,
        currentNodeId: r.current_node_id,
        nodeStatuses: statuses,
        contextBag: r.context_bag,
        transcript: msgs,
        lastSimulationDetail: r.simulation_detail,
        isPaused: pausedAtBreakpoint,
        isRunning: false,
        isComplete: r.is_complete,
        copilotSuggestions: [],
      };
    }
    case "SET_MODE":
      return { ...state, mode: action.mode, copilotSuggestions: [] };
    case "SET_PERSONA":
      return { ...state, persona: action.persona };
    case "TOGGLE_BREAKPOINT": {
      const bp = new Set(state.breakpoints);
      if (bp.has(action.nodeId)) bp.delete(action.nodeId);
      else bp.add(action.nodeId);
      return { ...state, breakpoints: bp };
    }
    case "SET_RUNNING":
      return { ...state, isRunning: action.value };
    case "SET_PAUSED":
      return { ...state, isPaused: action.value };
    case "SET_COPILOT_SUGGESTIONS":
      return { ...state, copilotSuggestions: action.suggestions };
    case "CONTEXT_PATCHED":
      return { ...state, contextBag: action.contextBag, isPaused: false, isComplete: false };
    case "RESET":
      return initialState();
    default:
      return state;
  }
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function WorkflowTestPage() {
  const { id: workflowId } = useParams<{ id: string }>();
  const router = useRouter();
  const [state, dispatch] = useReducer(reducer, undefined, initialState);
  const autopilotRef = useRef(false);

  useEffect(() => {
    async function init() {
      try {
        const [wf, session] = await Promise.all([
          getWorkflow(workflowId),
          startTestSession(workflowId),
        ]);
        dispatch({
          type: "SESSION_STARTED",
          sessionId: session.session_id,
          nodes: wf.nodes,
          nodeId: session.current_node_id,
          workflowName: wf.name,
        });
      } catch {
        toast.error("Failed to start test session");
      }
    }
    void init();
    return () => {
      if (state.sessionId) {
        void deleteTestSession(workflowId, state.sessionId).catch(() => null);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workflowId]);

  const executeStep = useCallback(
    async (callerText: string, inputMode: TestMode | "ai") => {
      if (!state.sessionId || state.isRunning || state.isPaused) return;
      dispatch({ type: "SET_RUNNING", value: true });
      try {
        const result = await stepTestSession(workflowId, state.sessionId, callerText);
        dispatch({ type: "STEP_DONE", result, callerText, inputMode });
      } catch (err) {
        if (err instanceof Error && err.message === "SESSION_EXPIRED") {
          toast.error("Test session expired. Restarting...");
          dispatch({ type: "RESET" });
        } else {
          toast.error("Step failed");
          dispatch({ type: "SET_RUNNING", value: false });
        }
      }
    },
    [state.sessionId, state.isRunning, state.isPaused, workflowId]
  );

  const executeAiStep = useCallback(async () => {
    if (!state.sessionId || state.isRunning || state.isPaused) return;
    const transcriptText = state.transcript.map((m) => `${m.speaker}: ${m.text}`).join("\n");
    dispatch({ type: "SET_RUNNING", value: true });
    try {
      const result: AiStepOut = await aiStepTestSession(
        workflowId,
        state.sessionId,
        state.persona || "a caller",
        "autopilot",
        transcriptText
      );
      if (result.step_result) {
        dispatch({
          type: "STEP_DONE",
          result: result.step_result,
          callerText: result.ai_input ?? "",
          inputMode: "ai",
        });
      }
    } catch {
      toast.error("AI step failed");
      dispatch({ type: "SET_RUNNING", value: false });
    }
  }, [
    state.sessionId,
    state.isRunning,
    state.isPaused,
    state.transcript,
    state.persona,
    workflowId,
  ]);

  useEffect(() => {
    if (!state.isRunning && autopilotRef.current && !state.isPaused && !state.isComplete) {
      if (state.mode === "autopilot" && state.sessionId) {
        void executeAiStep();
      }
    }
  }, [
    state.isRunning,
    state.isPaused,
    state.isComplete,
    state.mode,
    state.sessionId,
    executeAiStep,
  ]);

  async function handleCopilotFetch() {
    if (!state.sessionId) return;
    const transcriptText = state.transcript.map((m) => `${m.speaker}: ${m.text}`).join("\n");
    try {
      const result = await aiStepTestSession(
        workflowId,
        state.sessionId,
        state.persona || "a caller",
        "copilot",
        transcriptText
      );
      dispatch({ type: "SET_COPILOT_SUGGESTIONS", suggestions: result.suggestions ?? [] });
    } catch {
      toast.error("Failed to get AI suggestions");
    }
  }

  async function handleContextApply(edits: Record<string, unknown>) {
    if (!state.sessionId) return;
    try {
      const updated = await patchTestContext(workflowId, state.sessionId, edits);
      dispatch({ type: "CONTEXT_PATCHED", contextBag: updated.context_bag });
    } catch {
      toast.error("Failed to apply context changes");
    }
  }

  async function handleReset() {
    if (state.sessionId) await deleteTestSession(workflowId, state.sessionId).catch(() => null);
    dispatch({ type: "RESET" });
    const [wf, session] = await Promise.all([
      getWorkflow(workflowId),
      startTestSession(workflowId),
    ]);
    dispatch({
      type: "SESSION_STARTED",
      sessionId: session.session_id,
      nodes: wf.nodes,
      nodeId: session.current_node_id,
      workflowName: wf.name,
    });
  }

  const currentNode = state.nodes.find((n) => n.id === state.currentNodeId);

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      {/* Top bar */}
      <div className="flex shrink-0 items-center justify-between border-b border-border bg-background px-4 py-2">
        <div className="flex items-center gap-3">
          <Button
            variant="ghost"
            size="sm"
            className="h-7 text-xs"
            onClick={() => router.push("/dashboard/workflows")}
          >
            <ArrowLeft className="mr-1 h-3.5 w-3.5" />
            Workflows
          </Button>
          <span className="text-muted-foreground">|</span>
          <span className="text-sm font-semibold">{state.workflowName || "Workflow"}</span>
          {state.sessionId && (
            <span className="rounded-full border border-green-500/30 bg-green-500/10 px-2 py-0.5 text-[10px] text-green-400">
              ● Testing
            </span>
          )}
          {state.isPaused && (
            <span className="rounded-full border border-yellow-400/30 bg-yellow-400/10 px-2 py-0.5 text-[10px] text-yellow-400">
              ⊙ Paused at breakpoint
            </span>
          )}
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-xs"
            onClick={() => void handleReset()}
          >
            <RotateCcw className="mr-1 h-3.5 w-3.5" /> Restart
          </Button>
          <Button
            size="sm"
            className="h-7 bg-purple-600 text-xs hover:bg-purple-700"
            disabled={state.isRunning || state.isPaused || state.mode !== "manual"}
            onClick={() => void executeStep("", "manual")}
          >
            <FastForward className="mr-1 h-3.5 w-3.5" /> Run All
          </Button>
        </div>
      </div>

      {/* 3-panel body */}
      <div className="flex flex-1 overflow-hidden">
        <TestNodeList
          nodes={state.nodes}
          currentNodeId={state.currentNodeId}
          nodeStatuses={state.nodeStatuses}
          breakpoints={state.breakpoints}
          onToggleBreakpoint={(id) => dispatch({ type: "TOGGLE_BREAKPOINT", nodeId: id })}
        />

        <div className="flex flex-1 flex-col overflow-hidden">
          <TestConversation
            transcript={state.transcript}
            isRunning={state.isRunning}
            currentNodeType={currentNode?.type ?? ""}
          />
          <TestInputBar
            mode={state.mode}
            persona={state.persona}
            currentNodeType={currentNode?.type ?? ""}
            isPaused={state.isPaused}
            isRunning={state.isRunning}
            copilotSuggestions={state.copilotSuggestions}
            onModeChange={(m) => {
              dispatch({ type: "SET_MODE", mode: m });
              if (m === "copilot") void handleCopilotFetch();
              if (m !== "autopilot") autopilotRef.current = false;
            }}
            onPersonaChange={(p) => dispatch({ type: "SET_PERSONA", persona: p })}
            onManualStep={(input) => void executeStep(input, "manual")}
            onCopilotPick={(s) => void executeStep(s, "copilot")}
            onAutopilotToggle={() => {
              autopilotRef.current = !autopilotRef.current;
              if (autopilotRef.current) void executeAiStep();
            }}
          />
        </div>

        <TestContextBag
          contextBag={state.contextBag}
          isPaused={state.isPaused}
          simulationDetail={state.lastSimulationDetail}
          onApplyEdits={(edits) => void handleContextApply(edits)}
        />
      </div>
    </div>
  );
}
