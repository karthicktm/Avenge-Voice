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

export async function startTestCall(
  agentId: string,
  persona: string,
  goal: string
): Promise<{ session_id: string }> {
  const res = await apiFetch(`${API_BASE}/api/v1/agents/${agentId}/test-calls`, {
    method: "POST",
    body: JSON.stringify({ persona, goal }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json() as Promise<{ session_id: string }>;
}

export async function stopTestCall(agentId: string, sessionId: string): Promise<void> {
  await apiFetch(`${API_BASE}/api/v1/agents/${agentId}/test-calls/${sessionId}`, {
    method: "DELETE",
  });
}

export function createTestCallWebSocket(sessionId: string): WebSocket {
  const token = typeof window !== "undefined" ? (localStorage.getItem("access_token") ?? "") : "";
  const wsBase = API_BASE.replace(/^http/, "ws");
  return new WebSocket(`${wsBase}/ws/agent-test/${sessionId}?token=${encodeURIComponent(token)}`);
}
