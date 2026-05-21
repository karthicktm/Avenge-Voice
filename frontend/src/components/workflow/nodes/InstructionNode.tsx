"use client";

import { MessageSquare } from "lucide-react";
import type { NodeProps } from "@xyflow/react";
import { NodeWrapper } from "./NodeWrapper";
import type { WorkflowNode } from "@/lib/api/workflows";

export function InstructionNode({ data, selected }: NodeProps) {
  const d = data as unknown as WorkflowNode;
  const cfg = (d.config ?? {}) as Record<string, string>;
  return (
    <NodeWrapper
      selected={selected}
      accentColor="bg-amber-500"
      badge="Instruction"
      icon={<MessageSquare className="h-3.5 w-3.5" />}
      label={d.label ?? "Read script"}
      preview={cfg.template ? cfg.template.substring(0, 40) : undefined}
    />
  );
}
