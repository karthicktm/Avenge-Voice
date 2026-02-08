"use client";

/**
 * WebSocket hook for real-time usage updates
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { usageKeys } from "./use-usage";

// =============================================================================
// Types
// =============================================================================

export interface UsageUpdateMessage {
  type: "usage_update";
  resource_type: string;
  current: number;
  timestamp: string;
}

export interface UsageAlertMessage {
  type: "usage_alert";
  resource_type: string;
  threshold: string;
  current: number;
  limit: number;
  percentage: number;
  timestamp: string;
}

export type UsageMessage = UsageUpdateMessage | UsageAlertMessage;

export interface UseUsageWebSocketOptions {
  organizationId: string;
  onUpdate?: (message: UsageUpdateMessage) => void;
  onAlert?: (message: UsageAlertMessage) => void;
  enabled?: boolean;
}

export interface UseUsageWebSocketResult {
  isConnected: boolean;
  lastMessage: UsageMessage | null;
  error: Error | null;
  reconnect: () => void;
}

// =============================================================================
// Constants
// =============================================================================

const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000";
const RECONNECT_DELAY = 3000;
const MAX_RECONNECT_ATTEMPTS = 5;

// =============================================================================
// Hook
// =============================================================================

export function useUsageWebSocket({
  organizationId,
  onUpdate,
  onAlert,
  enabled = true,
}: UseUsageWebSocketOptions): UseUsageWebSocketResult {
  const [isConnected, setIsConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState<UsageMessage | null>(null);
  const [error, setError] = useState<Error | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  const queryClient = useQueryClient();

  // Get access token from localStorage
  const getToken = useCallback(() => {
    if (typeof window === "undefined") return null;
    return localStorage.getItem("access_token");
  }, []);

  // Connect to WebSocket
  const connect = useCallback(() => {
    if (!enabled || !organizationId) return;

    const token = getToken();
    if (!token) {
      setError(new Error("No authentication token available"));
      return;
    }

    // Close existing connection
    if (wsRef.current) {
      wsRef.current.close();
    }

    const wsUrl = `${WS_URL}/ws/usage/${organizationId}?token=${encodeURIComponent(token)}`;

    try {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        setIsConnected(true);
        setError(null);
        reconnectAttemptsRef.current = 0;
      };

      ws.onclose = (event) => {
        setIsConnected(false);
        wsRef.current = null;

        // Don't reconnect on intentional closure or auth errors
        if (event.code === 1000 || event.code === 4001 || event.code === 4000) {
          return;
        }

        // Attempt to reconnect
        if (reconnectAttemptsRef.current < MAX_RECONNECT_ATTEMPTS) {
          reconnectAttemptsRef.current++;
          reconnectTimeoutRef.current = setTimeout(connect, RECONNECT_DELAY);
        } else {
          setError(new Error("Maximum reconnection attempts reached"));
        }
      };

      ws.onerror = (event) => {
        console.error("Usage WebSocket error:", event);
        setError(new Error("WebSocket connection error"));
      };

      ws.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data) as UsageMessage;
          setLastMessage(message);

          if (message.type === "usage_update") {
            // Invalidate usage queries to trigger refetch
            void queryClient.invalidateQueries({ queryKey: usageKeys.overview() });
            void queryClient.invalidateQueries({
              queryKey: usageKeys.resource(message.resource_type),
            });
            onUpdate?.(message);
          } else if (message.type === "usage_alert") {
            // Invalidate alerts queries
            void queryClient.invalidateQueries({ queryKey: usageKeys.alerts() });
            void queryClient.invalidateQueries({ queryKey: usageKeys.alertsCount() });
            onAlert?.(message);
          }
        } catch {
          // Silently ignore parse errors for malformed messages
        }
      };
    } catch (e) {
      console.error("Failed to create WebSocket:", e);
      setError(e instanceof Error ? e : new Error("Failed to connect"));
    }
  }, [enabled, organizationId, getToken, queryClient, onUpdate, onAlert]);

  // Reconnect function
  const reconnect = useCallback(() => {
    reconnectAttemptsRef.current = 0;
    connect();
  }, [connect]);

  // Connect on mount and when dependencies change
  useEffect(() => {
    connect();

    return () => {
      // Cleanup on unmount
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close(1000, "Component unmounted");
      }
    };
  }, [connect]);

  return {
    isConnected,
    lastMessage,
    error,
    reconnect,
  };
}

// =============================================================================
// Utility Hook - Simple usage update listener
// =============================================================================

export function useUsageUpdates(
  organizationId: string | undefined,
  onUsageChange?: (resourceType: string, current: number) => void
) {
  const { isConnected, lastMessage, error } = useUsageWebSocket({
    organizationId: organizationId ?? "",
    enabled: !!organizationId,
    onUpdate: (message) => {
      onUsageChange?.(message.resource_type, message.current);
    },
  });

  return { isConnected, lastMessage, error };
}
