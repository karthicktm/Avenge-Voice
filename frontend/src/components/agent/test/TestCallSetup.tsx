"use client";

import { Play, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

export type TestCallStatus = "idle" | "connecting" | "running" | "complete" | "error";

const STATUS_CONFIG: Record<TestCallStatus, { label: string; className: string }> = {
  idle: { label: "Idle", className: "bg-muted text-muted-foreground" },
  connecting: { label: "Connecting…", className: "bg-yellow-500/20 text-yellow-400" },
  running: { label: "In Progress", className: "bg-green-500/20 text-green-400" },
  complete: { label: "Complete", className: "bg-blue-500/20 text-blue-400" },
  error: { label: "Error", className: "bg-red-500/20 text-red-400" },
};

interface Props {
  persona: string;
  goal: string;
  status: TestCallStatus;
  onPersonaChange: (v: string) => void;
  onGoalChange: (v: string) => void;
  onStart: () => void;
  onStop: () => void;
}

export function TestCallSetup({
  persona,
  goal,
  status,
  onPersonaChange,
  onGoalChange,
  onStart,
  onStop,
}: Props) {
  const isActive = status === "connecting" || status === "running";
  const { label, className } = STATUS_CONFIG[status];

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
          Setup
        </span>
        <span className={`rounded px-2 py-0.5 text-[10px] font-medium ${className}`}>{label}</span>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="tc-persona" className="text-xs">
          Caller Persona
        </Label>
        <Textarea
          id="tc-persona"
          placeholder="e.g. frustrated customer with a broken product"
          value={persona}
          onChange={(e) => onPersonaChange(e.target.value)}
          disabled={isActive}
          rows={3}
          className="text-sm"
        />
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="tc-goal" className="text-xs">
          Goal
        </Label>
        <Textarea
          id="tc-goal"
          placeholder="e.g. get a full refund and file a complaint"
          value={goal}
          onChange={(e) => onGoalChange(e.target.value)}
          disabled={isActive}
          rows={3}
          className="text-sm"
        />
      </div>

      {isActive ? (
        <Button variant="destructive" size="sm" onClick={onStop} className="w-full gap-2">
          <Square className="h-3 w-3" />
          Stop Test
        </Button>
      ) : (
        <Button
          size="sm"
          onClick={onStart}
          disabled={!persona.trim() || !goal.trim()}
          className="w-full gap-2"
        >
          <Play className="h-3 w-3" />
          Start Test
        </Button>
      )}
    </div>
  );
}
