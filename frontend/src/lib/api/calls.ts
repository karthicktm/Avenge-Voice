/**
 * API client for call history
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

function getAuthHeaders(): HeadersInit {
  if (typeof window === "undefined") return {};
  const token = localStorage.getItem("access_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export interface CallRecord {
  id: string;
  provider: string;
  provider_call_id: string;
  agent_id: string | null;
  agent_name: string | null;
  contact_id: number | null;
  contact_name: string | null;
  workspace_id: string | null;
  workspace_name: string | null;
  direction: "inbound" | "outbound";
  status: string;
  from_number: string;
  to_number: string;
  duration_seconds: number;
  recording_url: string | null;
  transcript: string | null;
  started_at: string;
  answered_at: string | null;
  ended_at: string | null;
  category_path: string[] | null;
  category_code: string | null;
}

export interface CallRecordListResponse {
  calls: CallRecord[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface ListCallsParams {
  page?: number;
  page_size?: number;
  agent_id?: string;
  workspace_id?: string;
  direction?: "inbound" | "outbound";
  status?: string;
}

export interface CallStats {
  total_calls: number;
  completed_calls: number;
  inbound_calls: number;
  outbound_calls: number;
  total_duration_seconds: number;
  average_duration_seconds: number;
}

/**
 * List call records with pagination and filtering
 */
export async function listCalls(params: ListCallsParams = {}): Promise<CallRecordListResponse> {
  const searchParams = new URLSearchParams();
  if (params.page) searchParams.set("page", params.page.toString());
  if (params.page_size) searchParams.set("page_size", params.page_size.toString());
  if (params.agent_id) searchParams.set("agent_id", params.agent_id);
  if (params.workspace_id) searchParams.set("workspace_id", params.workspace_id);
  if (params.direction) searchParams.set("direction", params.direction);
  if (params.status) searchParams.set("status", params.status);

  const response = await fetch(`${API_BASE}/api/v1/calls?${searchParams.toString()}`, {
    headers: getAuthHeaders(),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail ?? "Failed to fetch calls");
  }

  return response.json();
}

/**
 * Get a specific call record
 */
export async function getCall(callId: string): Promise<CallRecord> {
  const response = await fetch(`${API_BASE}/api/v1/calls/${callId}`, {
    headers: getAuthHeaders(),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail ?? "Failed to fetch call");
  }

  return response.json();
}

/**
 * Download a call recording as an MP3 file via the backend proxy
 */
export async function downloadCallRecording(callId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/api/v1/calls/${callId}/recording`, {
    headers: getAuthHeaders(),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error((error as { detail?: string }).detail ?? "Failed to download recording");
  }

  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `recording-${callId}.mp3`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

/**
 * Get call statistics for an agent
 */
export async function getAgentCallStats(agentId: string): Promise<CallStats> {
  const response = await fetch(`${API_BASE}/api/v1/calls/agent/${agentId}/stats`, {
    headers: getAuthHeaders(),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail ?? "Failed to fetch agent call stats");
  }

  return response.json();
}
