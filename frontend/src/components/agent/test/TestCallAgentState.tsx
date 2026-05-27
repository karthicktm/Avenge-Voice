"use client";

export interface ToolCallEntry {
  id: string;
  tool: string;
  args: Record<string, unknown>;
  result?: Record<string, unknown>;
  elapsedMs?: number;
}

export interface WorkflowNodeInfo {
  nodeId: string;
  nodeType: string;
  nodeLabel: string;
}

interface Props {
  toolCalls: ToolCallEntry[];
  currentWorkflowNode: WorkflowNodeInfo | null;
}

export function TestCallAgentState({ toolCalls, currentWorkflowNode }: Props) {
  return (
    <div className="flex flex-col gap-4 overflow-y-auto p-4">
      <span className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
        Agent State
      </span>

      {currentWorkflowNode && (
        <div className="space-y-1">
          <div className="text-[10px] text-muted-foreground">Workflow Node</div>
          <div className="rounded border border-primary/20 bg-primary/5 px-2 py-1.5 text-xs">
            <div className="font-medium">{currentWorkflowNode.nodeLabel}</div>
            <div className="text-[10px] text-muted-foreground">{currentWorkflowNode.nodeType}</div>
          </div>
        </div>
      )}

      <div className="space-y-2">
        <div className="text-[10px] text-muted-foreground">Tool Calls</div>
        {toolCalls.length === 0 ? (
          <div className="text-[10px] text-muted-foreground/40">No tool calls yet</div>
        ) : (
          <div className="space-y-2">
            {toolCalls.map((tc) => (
              <div key={tc.id} className="rounded border border-border bg-muted/30 p-2 text-[10px]">
                <div className="flex items-center justify-between">
                  <span className="font-medium text-primary">{tc.tool}</span>
                  {tc.elapsedMs !== undefined && (
                    <span className="text-muted-foreground">{tc.elapsedMs.toFixed(0)}ms</span>
                  )}
                </div>
                {tc.result !== undefined && (
                  <div className="mt-1 text-muted-foreground">
                    {tc.result.success === true ? "✓ succeeded" : "✗ failed"}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
