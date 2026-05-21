"use client";

import { CalendarPlus } from "lucide-react";
import type { NodeProps } from "@xyflow/react";
import { NodeWrapper } from "./NodeWrapper";
import type { WorkflowNode } from "@/lib/api/workflows";

export function AppointmentNode({ data, selected }: NodeProps) {
  const d = data as unknown as WorkflowNode;
  const cfg = (d.config ?? {}) as Record<string, string>;
  return (
    <NodeWrapper
      selected={selected}
      accentColor="bg-indigo-500"
      badge="Appointment"
      icon={<CalendarPlus className="h-3.5 w-3.5" />}
      label={d.label ?? "Book appointment"}
      preview={cfg.calendar_id ? `Calendar: ${cfg.calendar_id}` : undefined}
    />
  );
}
