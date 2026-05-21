"use client";

import { BookUser } from "lucide-react";
import type { NodeProps } from "@xyflow/react";
import { NodeWrapper } from "./NodeWrapper";
import type { WorkflowNode } from "@/lib/api/workflows";

export function LookupTransferNode({ data, selected }: NodeProps) {
  const d = data as unknown as WorkflowNode;
  return (
    <NodeWrapper
      selected={selected}
      accentColor="bg-teal-500"
      badge="Lookup + Transfer"
      icon={<BookUser className="h-3.5 w-3.5" />}
      label={d.label ?? "Phonebook lookup → transfer"}
    />
  );
}
