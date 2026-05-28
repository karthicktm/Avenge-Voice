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

export type WorkflowNodeType =
  | "entry"
  | "categorize"
  | "condition"
  | "transfer"
  | "collect_email"
  | "instruction"
  | "lookup_transfer"
  | "webhook"
  | "sms"
  | "appointment"
  | "voicemail"
  | "subagent"
  | "end_call";

export interface WorkflowNode {
  id: string;
  type: WorkflowNodeType;
  label?: string;
  config?: Record<string, unknown>;
  position?: { x: number; y: number };
}

export interface WorkflowEdge {
  id: string;
  from: string;
  to: string;
  condition?: string;
  label?: string;
  sourceHandle?: string;
}

export interface Workflow {
  id: string;
  workspace_id: string;
  name: string;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
}

export async function listWorkflows(workspaceId: string): Promise<Workflow[]> {
  const res = await apiFetch(`${API_BASE}/api/v1/workflows?workspace_id=${workspaceId}`);
  if (!res.ok) throw new Error(`Failed to list workflows: ${res.statusText}`);
  return res.json();
}

export async function getWorkflow(id: string): Promise<Workflow> {
  const res = await apiFetch(`${API_BASE}/api/v1/workflows/${id}`);
  if (!res.ok) throw new Error(`Failed to get workflow: ${res.statusText}`);
  return res.json();
}

export async function createWorkflow(data: {
  workspace_id: string;
  name: string;
  nodes?: WorkflowNode[];
  edges?: WorkflowEdge[];
}): Promise<Workflow> {
  const res = await apiFetch(`${API_BASE}/api/v1/workflows`, {
    method: "POST",
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(`Failed to create workflow: ${res.statusText}`);
  return res.json();
}

export async function updateWorkflow(
  id: string,
  data: { name?: string; nodes?: WorkflowNode[]; edges?: WorkflowEdge[] }
): Promise<Workflow> {
  const res = await apiFetch(`${API_BASE}/api/v1/workflows/${id}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(`Failed to update workflow: ${res.statusText}`);
  return res.json();
}

export async function deleteWorkflow(id: string): Promise<void> {
  const res = await apiFetch(`${API_BASE}/api/v1/workflows/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`Failed to delete workflow: ${res.statusText}`);
}

export async function attachWorkflow(workflowId: string, agentId: string): Promise<void> {
  const res = await apiFetch(`${API_BASE}/api/v1/workflows/${workflowId}/attach/${agentId}`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(`Failed to attach workflow: ${res.statusText}`);
}

export async function detachWorkflow(workflowId: string, agentId: string): Promise<void> {
  const res = await apiFetch(`${API_BASE}/api/v1/workflows/${workflowId}/detach/${agentId}`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(`Failed to detach workflow: ${res.statusText}`);
}

// ── AI workflow generation ─────────────────────────────────────────────────────

export interface GenerateWorkflowRequest {
  workspace_id: string;
  workflow_id: string;
  prompt: string;
  provider: "openai" | "anthropic" | "google";
  model: string;
}

export interface GenerateWorkflowResponse {
  intent: "node" | "workflow";
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  agent_name: string | null;
}

export async function generateWorkflowFromPrompt(
  request: GenerateWorkflowRequest
): Promise<GenerateWorkflowResponse> {
  const res = await apiFetch(`${API_BASE}/api/v1/workflows/generate`, {
    method: "POST",
    body: JSON.stringify(request),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? "Failed to generate workflow");
  }
  return res.json();
}
