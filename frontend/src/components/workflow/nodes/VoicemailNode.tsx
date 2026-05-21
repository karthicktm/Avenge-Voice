"use client";

import { Voicemail } from "lucide-react";
import type { NodeProps } from "@xyflow/react";
import { NodeWrapper } from "./NodeWrapper";
import type { WorkflowNode } from "@/lib/api/workflows";

export function VoicemailNode({ data, selected }: NodeProps) {
  const d = data as unknown as WorkflowNode;
  const cfg = (d.config ?? {}) as Record<string, string>;
  return (
    <NodeWrapper
      selected={selected}
      accentColor="bg-rose-500"
      badge="Voicemail"
      icon={<Voicemail className="h-3.5 w-3.5" />}
      label={d.label ?? "Record voicemail"}
      preview={cfg.prompt ? cfg.prompt.substring(0, 40) : undefined}
    />
  );
}
