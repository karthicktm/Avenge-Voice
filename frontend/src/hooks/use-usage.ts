"use client";

/**
 * React hooks for usage tracking
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  usageApi,
  type UsageOverview,
  type UsageAlert,
  type UsageBreakdown,
  type UsageHistoryEntry,
} from "@/lib/api/usage";

// =============================================================================
// Query Keys
// =============================================================================

export const usageKeys = {
  all: ["usage"] as const,
  overview: () => [...usageKeys.all, "overview"] as const,
  resource: (resourceType: string) => [...usageKeys.all, "resource", resourceType] as const,
  history: (resourceType?: string, months?: number) =>
    [...usageKeys.all, "history", resourceType, months] as const,
  breakdown: (breakdownBy: string) => [...usageKeys.all, "breakdown", breakdownBy] as const,
  alerts: (pendingOnly?: boolean) => [...usageKeys.all, "alerts", pendingOnly] as const,
  alertsCount: () => [...usageKeys.all, "alerts-count"] as const,
  resourceTypes: () => [...usageKeys.all, "resource-types"] as const,
};

// =============================================================================
// Hooks
// =============================================================================

export function useUsageOverview() {
  return useQuery<UsageOverview>({
    queryKey: usageKeys.overview(),
    queryFn: usageApi.getCurrentOverview,
    refetchInterval: 30000, // Refetch every 30 seconds
  });
}

export function useResourceUsage(resourceType: string) {
  return useQuery({
    queryKey: usageKeys.resource(resourceType),
    queryFn: () => usageApi.getResourceUsage(resourceType),
    refetchInterval: 30000,
  });
}

export function useUsageHistory(resourceType?: string, months = 6) {
  return useQuery<UsageHistoryEntry[]>({
    queryKey: usageKeys.history(resourceType, months),
    queryFn: () => usageApi.getHistory(resourceType, months),
  });
}

export function useUsageBreakdown(breakdownBy: "workspace" | "agent" | "user" = "workspace") {
  return useQuery<UsageBreakdown[]>({
    queryKey: usageKeys.breakdown(breakdownBy),
    queryFn: () => usageApi.getBreakdown(breakdownBy),
  });
}

export function useUsageAlerts(pendingOnly = false, limit = 20) {
  return useQuery<UsageAlert[]>({
    queryKey: usageKeys.alerts(pendingOnly),
    queryFn: () => usageApi.getAlerts(pendingOnly, limit),
    refetchInterval: 60000, // Check for new alerts every minute
  });
}

export function usePendingAlertsCount() {
  return useQuery({
    queryKey: usageKeys.alertsCount(),
    queryFn: usageApi.getPendingAlertsCount,
    refetchInterval: 60000,
  });
}

export function useResourceTypes() {
  return useQuery({
    queryKey: usageKeys.resourceTypes(),
    queryFn: usageApi.listResourceTypes,
    staleTime: 1000 * 60 * 60, // Resource types don't change often
  });
}

// =============================================================================
// Mutations
// =============================================================================

export function useAcknowledgeAlert() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: usageApi.acknowledgeAlert,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: usageKeys.alerts() });
      void queryClient.invalidateQueries({ queryKey: usageKeys.alertsCount() });
    },
  });
}
