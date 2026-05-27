"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface Props {
  contextBag: Record<string, unknown>;
  isPaused: boolean;
  simulationDetail: Record<string, unknown> | null;
  onApplyEdits: (bag: Record<string, unknown>) => void;
}

const KNOWN_KEYS = [
  "action_type",
  "label",
  "confidence",
  "transfer_target",
  "email_target",
  "approved_script",
  "urgency_level",
  "info_to_collect",
  "resolution_layer",
  "caller_name",
  "caller_number",
];

export function TestContextBag({ contextBag, isPaused, simulationDetail, onApplyEdits }: Props) {
  const [edits, setEdits] = useState<Record<string, string>>({});

  const extraKeys = Object.keys(contextBag).filter((k) => !KNOWN_KEYS.includes(k));

  function handleApply() {
    const merged: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(edits)) {
      if (v.trim()) merged[k] = v;
    }
    onApplyEdits(merged);
    setEdits({});
  }

  function renderValue(key: string) {
    const val = contextBag[key];
    const hasVal = val !== undefined && val !== null;
    if (isPaused) {
      return (
        <Input
          className="h-6 font-mono text-[10px]"
          defaultValue={hasVal ? String(val) : ""}
          onChange={(e) => setEdits((prev) => ({ ...prev, [key]: e.target.value }))}
        />
      );
    }
    return (
      <div
        className={cn(
          "rounded border px-1.5 py-0.5 font-mono text-[10px]",
          hasVal
            ? "border-green-500/30 bg-green-500/5 text-green-400"
            : "border-dashed border-border text-muted-foreground/40"
        )}
      >
        {hasVal ? String(val) : "—"}
      </div>
    );
  }

  return (
    <div className="flex w-[220px] shrink-0 flex-col border-l border-border bg-background/50">
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
          Context Bag
        </span>
        {isPaused && (
          <span className="rounded border border-yellow-500/30 bg-yellow-400/10 px-1.5 py-0.5 text-[8px] text-yellow-400">
            editable
          </span>
        )}
      </div>
      <div className="flex-1 space-y-2 overflow-y-auto p-2">
        {[...KNOWN_KEYS, ...extraKeys].map((key) => (
          <div key={key}>
            <div className="mb-0.5 text-[8px] text-muted-foreground">{key}</div>
            {renderValue(key)}
          </div>
        ))}
      </div>
      {isPaused && (
        <div className="border-t border-border p-2">
          <Button size="sm" className="w-full text-xs" onClick={handleApply}>
            Apply Changes
          </Button>
        </div>
      )}
      {simulationDetail && (
        <div className="border-t border-border p-2">
          <div className="rounded border border-dashed border-red-500/40 bg-red-500/5 p-2">
            <div className="mb-1 text-[9px] font-medium text-red-400">
              ⊙ Simulated: {String(simulationDetail.node_label ?? simulationDetail.node_type)}
            </div>
            {simulationDetail.would_have != null &&
              typeof simulationDetail.would_have === "object" && (
                <div className="text-[9px] text-muted-foreground">
                  {Object.entries(simulationDetail.would_have as Record<string, unknown>)
                    .filter(([, v]) => v != null)
                    .map(([k, v]) => (
                      <div key={k}>
                        <span className="text-red-300">{k}:</span> {String(v)}
                      </div>
                    ))}
                </div>
              )}
          </div>
        </div>
      )}
    </div>
  );
}
