"use client";

import { Tags } from "lucide-react";
import type { NodeProps } from "@xyflow/react";
import { NodeWrapper } from "./NodeWrapper";
import type { WorkflowNode } from "@/lib/api/workflows";

export function CategorizeNode({ data, selected }: NodeProps) {
  const d = data as unknown as WorkflowNode;
  const cfg = (d.config ?? {}) as Record<string, string>;
  return (
    <NodeWrapper
      selected={selected}
      accentColor="bg-blue-500"
      badge="Categorize"
      icon={<Tags className="h-3.5 w-3.5" />}
      label={d.label ?? "Classify caller"}
      preview={cfg.tree_name ? `Tree: ${cfg.tree_name}` : cfg.llm_model}
    />
  );
}
