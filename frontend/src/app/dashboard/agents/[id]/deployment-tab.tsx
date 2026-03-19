"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  RefreshCw,
  Container,
  CheckCircle2,
  XCircle,
  Clock,
  StopCircle,
  ExternalLink,
  Server,
  AlertCircle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getDeploymentStatus, deployAgent, type AgentDeployment } from "@/lib/api/agents";

interface DeploymentTabProps {
  agentId: string;
}

function StatusBadge({ status }: { status: AgentDeployment["status"] }) {
  const map = {
    running: {
      icon: CheckCircle2,
      label: "Running",
      className: "bg-green-500/10 text-green-600 border-green-500/20",
    },
    pending: {
      icon: Clock,
      label: "Deploying…",
      className: "bg-yellow-500/10 text-yellow-600 border-yellow-500/20",
    },
    stopped: {
      icon: StopCircle,
      label: "Stopped",
      className: "bg-muted text-muted-foreground",
    },
    failed: {
      icon: XCircle,
      label: "Failed",
      className: "bg-destructive/10 text-destructive border-destructive/20",
    },
  } as const;

  const cfg = map[status];
  const Icon = cfg.icon;

  return (
    <Badge variant="outline" className={`gap-1.5 px-2 py-0.5 text-xs font-medium ${cfg.className}`}>
      <Icon className="h-3 w-3" />
      {cfg.label}
    </Badge>
  );
}

function InfoRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2 text-sm">
      <span className="shrink-0 text-muted-foreground">{label}</span>
      <span className="break-all text-right font-mono text-xs">{value}</span>
    </div>
  );
}

export function DeploymentTab({ agentId }: DeploymentTabProps) {
  const queryClient = useQueryClient();

  const {
    data: deployment,
    isLoading,
    error,
  } = useQuery<AgentDeployment | null>({
    queryKey: ["deployment", agentId],
    queryFn: async () => {
      try {
        return await getDeploymentStatus(agentId);
      } catch (e) {
        if (e instanceof Error && e.message === "NOT_FOUND") return null;
        throw e;
      }
    },
    // Poll every 5s while deploying
    refetchInterval: (query) => {
      const d = query.state.data;
      return d?.status === "pending" ? 5000 : false;
    },
  });

  const deployMutation = useMutation({
    mutationFn: () => deployAgent(agentId),
    onSuccess: () => {
      toast.success("Deployment triggered — container is starting up");
      void queryClient.invalidateQueries({ queryKey: ["deployment", agentId] });
      setTimeout(() => {
        void queryClient.invalidateQueries({ queryKey: ["deployment", agentId] });
      }, 3000);
    },
    onError: (err: Error) => {
      if (err.message.includes("ENABLE_AGENT_CONTAINERS")) {
        toast.error("Container deployment is disabled on this server", {
          description: "Set ENABLE_AGENT_CONTAINERS=true in your backend .env to enable it.",
        });
      } else {
        toast.error(err.message);
      }
    },
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16 text-sm text-muted-foreground">
        Loading deployment status…
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-16">
        <AlertCircle className="h-8 w-8 text-destructive" />
        <p className="text-sm text-muted-foreground">Failed to load deployment status</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2 text-sm font-medium">
              <Container className="h-4 w-4" />
              Agent Container
            </CardTitle>
            <Button
              size="sm"
              variant={deployment?.status === "running" ? "outline" : "default"}
              className="h-7 px-3 text-xs"
              onClick={() => deployMutation.mutate()}
              disabled={deployMutation.isPending || deployment?.status === "pending"}
            >
              <RefreshCw
                className={`mr-1.5 h-3 w-3 ${deployMutation.isPending || deployment?.status === "pending" ? "animate-spin" : ""}`}
              />
              {deployment ? "Redeploy" : "Deploy"}
            </Button>
          </div>
        </CardHeader>

        <CardContent className="space-y-1 pt-0">
          {!deployment ? (
            <div className="flex flex-col items-center gap-2 py-8 text-center">
              <Server className="h-10 w-10 text-muted-foreground/40" />
              <p className="text-sm font-medium">No container deployed</p>
              <p className="max-w-xs text-xs text-muted-foreground">
                Deploy a dedicated container for this agent to isolate its voice sessions.
              </p>
            </div>
          ) : (
            <div className="divide-y divide-border/50">
              <div className="flex items-center justify-between py-2">
                <span className="text-sm text-muted-foreground">Status</span>
                <StatusBadge status={deployment.status} />
              </div>

              {deployment.backend && (
                <InfoRow
                  label="Backend"
                  value={
                    <Badge variant="secondary" className="text-xs font-normal">
                      {deployment.backend}
                    </Badge>
                  }
                />
              )}

              {deployment.container_name && (
                <InfoRow label="Container" value={deployment.container_name} />
              )}

              {deployment.container_url && (
                <InfoRow
                  label="Internal URL"
                  value={
                    <span className="flex items-center gap-1">
                      {deployment.container_url}
                      <ExternalLink className="h-3 w-3 shrink-0 text-muted-foreground" />
                    </span>
                  }
                />
              )}

              <InfoRow
                label="Last updated"
                value={new Date(deployment.updated_at).toLocaleString()}
              />

              {deployment.error_message && (
                <div className="mt-2 rounded-md bg-destructive/10 p-3">
                  <p className="text-xs font-medium text-destructive">Error</p>
                  <p className="mt-1 font-mono text-xs text-destructive/80">
                    {deployment.error_message}
                  </p>
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      <p className="text-xs text-muted-foreground">
        Containers are only active when{" "}
        <code className="rounded bg-muted px-1 py-0.5">ENABLE_AGENT_CONTAINERS=true</code> is set on
        the server. WS calls fall back to local handling while a container is deploying.
      </p>
    </div>
  );
}
