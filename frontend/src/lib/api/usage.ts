/**
 * Usage API client for resource tracking and monitoring
 */

import { api } from "../api";

// =============================================================================
// Types
// =============================================================================

export interface ResourceUsage {
  resource_type: string;
  current: number;
  limit: number | null;
  percentage: number;
  remaining: number | null;
  unlimited: boolean;
}

export interface UsageOverview {
  resources: Record<string, ResourceUsage>;
  period: string;
  period_start: string;
  period_end: string;
}

export interface UsageHistoryEntry {
  period: string;
  resource_type: string;
  amount: number;
}

export interface UsageBreakdown {
  entity_type: string;
  entity_id: string;
  entity_name: string | null;
  usage: Record<string, number>;
}

export interface UsageAlert {
  id: string;
  resource_type: string;
  threshold: string;
  status: string;
  current_usage: number;
  limit: number;
  percentage: number;
  created_at: string;
  acknowledged_at: string | null;
}

export interface ResourceTypeInfo {
  value: string;
  name: string;
}

// =============================================================================
// API Functions
// =============================================================================

export const usageApi = {
  // Current Usage
  getCurrentOverview: async (): Promise<UsageOverview> => {
    const response = await api.get<UsageOverview>("/api/v1/usage/current");
    return response.data;
  },

  getResourceUsage: async (resourceType: string): Promise<ResourceUsage> => {
    const response = await api.get<ResourceUsage>(`/api/v1/usage/current/${resourceType}`);
    return response.data;
  },

  // History
  getHistory: async (resourceType?: string, months = 6): Promise<UsageHistoryEntry[]> => {
    const params: Record<string, string | number> = { months };
    if (resourceType) {
      params.resource_type = resourceType;
    }
    const response = await api.get<UsageHistoryEntry[]>("/api/v1/usage/history", { params });
    return response.data;
  },

  // Breakdown
  getBreakdown: async (
    breakdownBy: "workspace" | "agent" | "user" = "workspace"
  ): Promise<UsageBreakdown[]> => {
    const response = await api.get<UsageBreakdown[]>("/api/v1/usage/breakdown", {
      params: { breakdown_by: breakdownBy },
    });
    return response.data;
  },

  // Alerts
  getAlerts: async (pendingOnly = false, limit = 20): Promise<UsageAlert[]> => {
    const response = await api.get<UsageAlert[]>("/api/v1/usage/alerts", {
      params: { pending_only: pendingOnly, limit },
    });
    return response.data;
  },

  getPendingAlertsCount: async (): Promise<{ count: number }> => {
    const response = await api.get<{ count: number }>("/api/v1/usage/alerts/pending/count");
    return response.data;
  },

  acknowledgeAlert: async (alertId: string): Promise<UsageAlert> => {
    const response = await api.post<UsageAlert>(`/api/v1/usage/alerts/${alertId}/acknowledge`);
    return response.data;
  },

  // Resource Types
  listResourceTypes: async (): Promise<ResourceTypeInfo[]> => {
    const response = await api.get<ResourceTypeInfo[]>("/api/v1/usage/resource-types");
    return response.data;
  },
};

// =============================================================================
// Utility Functions
// =============================================================================

export function getUsageColor(percentage: number): string {
  if (percentage >= 100) return "red";
  if (percentage >= 90) return "orange";
  if (percentage >= 80) return "yellow";
  return "green";
}

export function formatResourceValue(value: number, resourceType: string): string {
  // Format based on resource type
  if (resourceType.includes("minutes")) {
    if (value >= 60) {
      const hours = Math.floor(value / 60);
      const mins = Math.round(value % 60);
      return mins > 0 ? `${hours}h ${mins}m` : `${hours}h`;
    }
    return `${Math.round(value)}m`;
  }

  if (resourceType.includes("tokens")) {
    if (value >= 1_000_000) {
      return `${(value / 1_000_000).toFixed(1)}M`;
    }
    if (value >= 1_000) {
      return `${(value / 1_000).toFixed(1)}K`;
    }
    return Math.round(value).toString();
  }

  if (resourceType.includes("gb") || resourceType.includes("storage")) {
    if (value >= 1024) {
      return `${(value / 1024).toFixed(1)} TB`;
    }
    return `${value.toFixed(1)} GB`;
  }

  // Default formatting
  if (value >= 1_000_000) {
    return `${(value / 1_000_000).toFixed(1)}M`;
  }
  if (value >= 1_000) {
    return `${(value / 1_000).toFixed(1)}K`;
  }
  return Math.round(value).toLocaleString();
}

export function getResourceDisplayName(resourceType: string): string {
  const names: Record<string, string> = {
    voice_minutes: "Voice Minutes",
    concurrent_calls: "Concurrent Calls",
    calls_per_day: "Calls Per Day",
    llm_tokens: "LLM Tokens",
    llm_input_tokens: "LLM Input Tokens",
    llm_output_tokens: "LLM Output Tokens",
    llm_requests: "LLM Requests",
    realtime_session_minutes: "Realtime Sessions",
    audio_processing_minutes: "Audio Processing",
    image_generations: "Image Generations",
    video_minutes: "Video Minutes",
    sms_messages: "SMS Messages",
    email_sends: "Emails Sent",
    storage_gb: "Storage",
    documents: "Documents",
    agents: "Agents",
    workspaces: "Workspaces",
    members: "Team Members",
    contacts: "Contacts",
  };
  return (
    names[resourceType] ?? resourceType.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
  );
}

export function getAlertSeverity(threshold: string): "info" | "warning" | "error" {
  const t = parseInt(threshold, 10);
  if (t >= 100) return "error";
  if (t >= 80) return "warning";
  return "info";
}
