"use client";

import { Bot } from "lucide-react";
import type { NodeProps } from "@xyflow/react";
import { NodeWrapper } from "./NodeWrapper";
import type { WorkflowNode } from "@/lib/api/workflows";

export function SubagentNode({ data, selected }: NodeProps) {
  const d = data as unknown as WorkflowNode;
  const cfg = (d.config ?? {}) as Record<string, string>;
  return (
    <NodeWrapper
      selected={selected}
      accentColor="bg-purple-600"
      badge="Subagent"
      icon={<Bot className="h-3.5 w-3.5" />}
      label={d.label ?? "Override agent"}
      preview={
        cfg.llm_model ? `Model: ${cfg.llm_model}` : cfg.voice ? `Voice: ${cfg.voice}` : undefined
      }
    />
  );
}
