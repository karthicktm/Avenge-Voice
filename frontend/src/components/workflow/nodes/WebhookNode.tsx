"use client";

import { Webhook } from "lucide-react";
import type { NodeProps } from "@xyflow/react";
import { NodeWrapper } from "./NodeWrapper";
import type { WorkflowNode } from "@/lib/api/workflows";

export function WebhookNode({ data, selected }: NodeProps) {
  const d = data as unknown as WorkflowNode;
  const cfg = (d.config ?? {}) as Record<string, string>;
  const method = cfg.method ?? "POST";
  const url = cfg.url ?? "";
  const preview = url ? `${method} ${url.substring(0, 30)}` : undefined;
  return (
    <NodeWrapper
      selected={selected}
      accentColor="bg-cyan-600"
      badge="Webhook"
      icon={<Webhook className="h-3.5 w-3.5" />}
      label={d.label ?? "HTTP request"}
      preview={preview}
    />
  );
}
