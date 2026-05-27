const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

function getAuthHeaders(): HeadersInit {
  if (typeof window === "undefined") return {};
  const token = localStorage.getItem("access_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function apiFetch(url: string, options: RequestInit = {}): Promise<Response> {
  const headers = {
    "Content-Type": "application/json",
    ...getAuthHeaders(),
    ...(options.headers ?? {}),
  };
  return fetch(url, { ...options, headers });
}

export type NodeStatus = "pending" | "running" | "completed" | "paused" | "simulated";
export type TestMode = "manual" | "copilot" | "autopilot";

export interface TestSessionOut {
  session_id: string;
  current_node_id: string;
  current_node_type: string;
  current_node_label: string;
  context_bag: Record<string, unknown>;
  is_complete: boolean;
}

export interface StepOut {
  session_id: string;
  current_node_id: string;
  current_node_type: string;
  current_node_label: string;
  context_bag: Record<string, unknown>;
  node_output: string;
  simulated: boolean;
  simulation_detail: Record<string, unknown> | null;
  elapsed_ms: number;
  resolution_layer: string | null;
  is_complete: boolean;
}

export interface AiStepOut {
  session_id: string;
  mode: string;
  ai_input: string | null;
  suggestions: string[] | null;
  step_result: StepOut | null;
}

export interface TranscriptMessage {
  id: string;
  speaker: "agent" | "caller";
  text: string;
  nodeId: string;
  nodeLabel: string;
  mode: TestMode | "ai";
  elapsedMs?: number;
  resolutionLayer?: string | null;
  simulated?: boolean;
  simulationDetail?: Record<string, unknown> | null;
  timestamp: number;
}

export async function startTestSession(workflowId: string): Promise<TestSessionOut> {
  const res = await apiFetch(`${API_BASE}/api/v1/workflows/${workflowId}/test/start`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(`Failed to start test session: ${res.statusText}`);
  return res.json() as Promise<TestSessionOut>;
}

export async function stepTestSession(
  workflowId: string,
  sessionId: string,
  callerInput: string
): Promise<StepOut> {
  const res = await apiFetch(`${API_BASE}/api/v1/workflows/${workflowId}/test/${sessionId}/step`, {
    method: "POST",
    body: JSON.stringify({ caller_input: callerInput }),
  });
  if (res.status === 404) throw new Error("SESSION_EXPIRED");
  if (!res.ok) throw new Error(`Step failed: ${res.statusText}`);
  return res.json() as Promise<StepOut>;
}

export async function aiStepTestSession(
  workflowId: string,
  sessionId: string,
  persona: string,
  mode: "autopilot" | "copilot",
  transcript: string
): Promise<AiStepOut> {
  const res = await apiFetch(
    `${API_BASE}/api/v1/workflows/${workflowId}/test/${sessionId}/ai-step`,
    { method: "POST", body: JSON.stringify({ persona, mode, transcript }) }
  );
  if (res.status === 404) throw new Error("SESSION_EXPIRED");
  if (!res.ok) throw new Error(`AI step failed: ${res.statusText}`);
  return res.json() as Promise<AiStepOut>;
}

export async function patchTestContext(
  workflowId: string,
  sessionId: string,
  contextBag: Record<string, unknown>
): Promise<TestSessionOut> {
  const res = await apiFetch(
    `${API_BASE}/api/v1/workflows/${workflowId}/test/${sessionId}/context`,
    { method: "PATCH", body: JSON.stringify({ context_bag: contextBag }) }
  );
  if (!res.ok) throw new Error(`Patch context failed: ${res.statusText}`);
  return res.json() as Promise<TestSessionOut>;
}

export async function deleteTestSession(workflowId: string, sessionId: string): Promise<void> {
  await apiFetch(`${API_BASE}/api/v1/workflows/${workflowId}/test/${sessionId}`, {
    method: "DELETE",
  });
}
