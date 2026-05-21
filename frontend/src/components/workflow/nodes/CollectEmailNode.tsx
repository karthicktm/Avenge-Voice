"use client";

import { Mail } from "lucide-react";
import type { NodeProps } from "@xyflow/react";
import { NodeWrapper } from "./NodeWrapper";
import type { WorkflowNode } from "@/lib/api/workflows";

export function CollectEmailNode({ data, selected }: NodeProps) {
  const d = data as unknown as WorkflowNode;
  const cfg = (d.config ?? {}) as Record<string, string>;
  return (
    <NodeWrapper
      selected={selected}
      accentColor="bg-violet-500"
      badge="Collect + Email"
      icon={<Mail className="h-3.5 w-3.5" />}
      label={d.label ?? "Collect info & email"}
      preview={cfg.email_target ? `✉ ${cfg.email_target}` : undefined}
    />
  );
}
