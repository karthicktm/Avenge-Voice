"use client";

import { PhoneForwarded } from "lucide-react";
import type { NodeProps } from "@xyflow/react";
import { NodeWrapper } from "./NodeWrapper";
import type { WorkflowNode } from "@/lib/api/workflows";

export function TransferNode({ data, selected }: NodeProps) {
  const d = data as unknown as WorkflowNode;
  const cfg = (d.config ?? {}) as Record<string, string>;
  return (
    <NodeWrapper
      selected={selected}
      accentColor="bg-orange-500"
      badge="Transfer"
      icon={<PhoneForwarded className="h-3.5 w-3.5" />}
      label={d.label ?? "Transfer call"}
      preview={cfg.transfer_target ? `→ ${cfg.transfer_target}` : undefined}
    />
  );
}
