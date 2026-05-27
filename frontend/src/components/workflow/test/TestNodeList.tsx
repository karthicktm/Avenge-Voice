"use client";

import { cn } from "@/lib/utils";
import type { NodeStatus } from "@/lib/api/workflow-test";
import type { WorkflowNode } from "@/lib/api/workflows";

interface Props {
  nodes: WorkflowNode[];
  currentNodeId: string;
  nodeStatuses: Record<string, NodeStatus>;
  breakpoints: Set<string>;
  onToggleBreakpoint: (nodeId: string) => void;
}

const STATUS_DOT: Record<NodeStatus, string> = {
  pending: "bg-muted-foreground/40 rounded-sm",
  running: "bg-blue-500 rounded-full animate-pulse",
  completed: "bg-green-500 rounded-full",
  paused: "bg-yellow-400 rounded-full",
  simulated: "bg-red-400 rounded-full",
};

const STATUS_ROW: Record<NodeStatus, string> = {
  pending: "text-muted-foreground",
  running: "bg-blue-500/10 border border-blue-500/40 text-blue-300",
  completed: "bg-green-500/10 text-green-300",
  paused: "bg-yellow-400/10 border border-yellow-400/40 text-yellow-300",
  simulated: "border border-dashed border-red-500/50 text-red-300",
};

export function TestNodeList({
  nodes,
  currentNodeId,
  nodeStatuses,
  breakpoints,
  onToggleBreakpoint,
}: Props) {
  return (
    <div className="flex w-[190px] shrink-0 flex-col border-r border-border bg-background/50">
      <div className="border-b border-border px-3 py-2">
        <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
          Flow — {nodes.length} nodes
        </span>
      </div>
      <div className="flex-1 space-y-1 overflow-y-auto p-2">
        {nodes.map((node) => {
          const status: NodeStatus = nodeStatuses[node.id] ?? "pending";
          const hasBreakpoint = breakpoints.has(node.id);
          const isCurrent = node.id === currentNodeId;
          return (
            <button
              key={node.id}
              className={cn(
                "flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-[10px] transition-colors",
                STATUS_ROW[status],
                !isCurrent && "hover:bg-muted/50"
              )}
              title={hasBreakpoint ? "Click to remove breakpoint" : "Click to set breakpoint"}
              onClick={() => onToggleBreakpoint(node.id)}
            >
              <div className={cn("h-2 w-2 shrink-0", STATUS_DOT[status])} />
              <span className="flex-1 truncate font-medium">{node.label ?? node.type}</span>
              {status === "completed" && <span className="text-green-400">✓</span>}
              {hasBreakpoint && (
                <span className="text-red-400" title="Breakpoint">
                  ⊙
                </span>
              )}
              {status === "running" && <span className="text-blue-400">▶</span>}
            </button>
          );
        })}
        <div className="mt-3 rounded border border-border bg-muted/20 p-2 text-[9px] text-muted-foreground">
          Click any node to toggle a breakpoint ⊙
        </div>
      </div>
    </div>
  );
}
