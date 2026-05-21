"use client";

import { MessageCircle } from "lucide-react";
import type { NodeProps } from "@xyflow/react";
import { NodeWrapper } from "./NodeWrapper";
import type { WorkflowNode } from "@/lib/api/workflows";

export function SmsNode({ data, selected }: NodeProps) {
  const d = data as unknown as WorkflowNode;
  const cfg = (d.config ?? {}) as Record<string, string>;
  return (
    <NodeWrapper
      selected={selected}
      accentColor="bg-pink-500"
      badge="SMS"
      icon={<MessageCircle className="h-3.5 w-3.5" />}
      label={d.label ?? "Send SMS"}
      preview={cfg.template ? cfg.template.substring(0, 40) : undefined}
    />
  );
}
