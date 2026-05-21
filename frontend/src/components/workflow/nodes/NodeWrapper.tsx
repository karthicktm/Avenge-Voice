"use client";

import type { ReactNode } from "react";
import { Handle, Position } from "@xyflow/react";

export interface NodeWrapperProps {
  selected?: boolean;
  accentColor: string;
  badge: string;
  icon: ReactNode;
  label: string;
  preview?: string;
  hasTarget?: boolean;
  hasSource?: boolean;
  /** Extra source handles beside the default bottom one */
  extraHandles?: Array<{ id: string; position: Position; label?: string; style?: string }>;
  children?: ReactNode;
}

export function NodeWrapper({
  selected,
  accentColor,
  badge,
  icon,
  label,
  preview,
  hasTarget = true,
  hasSource = true,
  extraHandles,
  children,
}: NodeWrapperProps) {
  return (
    <div
      className={`relative min-w-[200px] max-w-[240px] rounded-lg border bg-card shadow-sm transition-shadow ${
        selected ? "shadow-lg ring-2 ring-offset-1" : "hover:shadow-md"
      } ${selected ? accentColor.replace("bg-", "ring-") : "border-border"}`}
    >
      {hasTarget && (
        <Handle
          type="target"
          position={Position.Top}
          className="!h-3 !w-3 !rounded-full !border-2 !border-background !bg-muted-foreground"
        />
      )}

      {/* Colored top bar */}
      <div className={`flex items-center gap-2 rounded-t-lg px-3 py-2 ${accentColor}`}>
        <span className="text-white opacity-90">{icon}</span>
        <span className="text-xs font-semibold uppercase tracking-wider text-white opacity-90">
          {badge}
        </span>
      </div>

      {/* Content */}
      <div className="px-3 py-2">
        <p className="truncate text-sm font-semibold text-foreground">{label}</p>
        {preview && <p className="mt-0.5 truncate text-xs text-muted-foreground">{preview}</p>}
        {children}
      </div>

      {hasSource && !extraHandles && (
        <Handle
          type="source"
          position={Position.Bottom}
          className="!h-3 !w-3 !rounded-full !border-2 !border-background !bg-muted-foreground"
        />
      )}

      {extraHandles?.map((h) => (
        <Handle
          key={h.id}
          id={h.id}
          type="source"
          position={h.position}
          className={`!h-3 !w-3 !rounded-full !border-2 !border-background ${h.style ?? "!bg-muted-foreground"}`}
        />
      ))}
    </div>
  );
}
