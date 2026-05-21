"use client";

import { GitBranch } from "lucide-react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { WorkflowNode } from "@/lib/api/workflows";

export function ConditionNode({ data, selected }: NodeProps) {
  const d = data as unknown as WorkflowNode;
  const cfg = (d.config ?? {}) as Record<string, string>;
  return (
    <div
      className={`relative min-w-[200px] max-w-[240px] rounded-xl border bg-white shadow-sm transition-shadow ${
        selected ? "shadow-lg ring-2 ring-orange-400 ring-offset-1" : "hover:shadow-md"
      }`}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!h-3 !w-3 !rounded-full !border-2 !border-white !bg-gray-400"
      />

      <div className="flex items-center gap-2 rounded-t-xl bg-orange-500 px-3 py-2">
        <GitBranch className="h-3.5 w-3.5 text-white opacity-90" />
        <span className="text-xs font-semibold uppercase tracking-wider text-white opacity-90">
          Condition
        </span>
      </div>

      <div className="px-3 py-2">
        <p className="truncate text-sm font-semibold text-gray-800">{d.label ?? "Branch"}</p>
        {cfg.condition && (
          <p className="mt-0.5 truncate font-mono text-xs text-gray-400">{cfg.condition}</p>
        )}
      </div>

      {/* Yes handle — bottom-left */}
      <div className="relative flex items-end justify-between px-3 pb-1">
        <span className="text-[10px] font-medium text-emerald-600">Yes</span>
        <span className="text-[10px] font-medium text-red-500">No</span>
      </div>

      <Handle
        id="yes"
        type="source"
        position={Position.Bottom}
        style={{ left: "30%" }}
        className="!h-3 !w-3 !rounded-full !border-2 !border-white !bg-emerald-500"
      />
      <Handle
        id="no"
        type="source"
        position={Position.Bottom}
        style={{ left: "70%" }}
        className="!h-3 !w-3 !rounded-full !border-2 !border-white !bg-red-500"
      />
    </div>
  );
}
