"use client";

import { useEffect, useRef } from "react";
import type { TranscriptMessage } from "@/lib/api/workflow-test";

interface Props {
  transcript: TranscriptMessage[];
  isRunning: boolean;
  currentNodeType: string;
}

function LayerBadge({
  layer,
  elapsedMs,
}: {
  layer: string | null | undefined;
  elapsedMs?: number;
}) {
  if (!layer && !elapsedMs) return null;
  return (
    <div className="mt-1 flex flex-wrap gap-1">
      {layer && (
        <span className="rounded border border-blue-500/20 bg-blue-500/10 px-1.5 py-0.5 text-[9px] text-blue-400">
          {layer}
        </span>
      )}
      {elapsedMs !== undefined && (
        <span className="rounded bg-muted/50 px-1.5 py-0.5 text-[9px] text-muted-foreground">
          {elapsedMs.toFixed(0)}ms
        </span>
      )}
    </div>
  );
}

function SimulationCard({ detail }: { detail: Record<string, unknown> }) {
  const wouldHave = detail.would_have as Record<string, unknown> | undefined;
  return (
    <div className="ml-8 rounded border border-dashed border-red-500/40 bg-red-500/5 p-2 text-[10px]">
      <div className="mb-1 font-medium text-red-400">
        ⊙ Simulated: {String(detail.node_label ?? detail.node_type)}
      </div>
      {wouldHave &&
        Object.entries(wouldHave)
          .filter(([, v]) => v)
          .map(([k, v]) => (
            <div key={k} className="text-muted-foreground">
              <span className="text-red-300">{k}:</span> {String(v)}
            </div>
          ))}
    </div>
  );
}

export function TestConversation({ transcript, isRunning, currentNodeType }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [transcript.length]);

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="flex-1 space-y-3 overflow-y-auto p-4">
        <div className="text-center text-[10px] text-muted-foreground">── Session started ──</div>

        {transcript.map((msg) => {
          const isAgent = msg.speaker === "agent";
          return (
            <div key={msg.id} className="space-y-1">
              <div className={`flex items-start gap-2 ${isAgent ? "" : "flex-row-reverse"}`}>
                <div
                  className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[9px] font-bold text-white ${
                    isAgent
                      ? "bg-primary"
                      : msg.mode === "ai"
                        ? "bg-purple-600"
                        : "bg-muted-foreground"
                  }`}
                >
                  {isAgent ? "A" : msg.mode === "ai" ? "AI" : "Y"}
                </div>
                <div
                  className={`max-w-[75%] rounded-lg px-3 py-2 text-sm ${
                    isAgent
                      ? "border border-border bg-muted/50"
                      : msg.mode === "ai"
                        ? "border border-purple-500/30 bg-purple-500/10 text-purple-200"
                        : "border border-primary/30 bg-primary/10"
                  }`}
                >
                  <div className="mb-1 text-[9px] text-muted-foreground">
                    {isAgent
                      ? `Agent · ${msg.nodeLabel}`
                      : msg.mode === "ai"
                        ? `AI · ${msg.nodeLabel}`
                        : "You"}
                  </div>
                  <div>{msg.text}</div>
                  {isAgent && <LayerBadge layer={msg.resolutionLayer} elapsedMs={msg.elapsedMs} />}
                </div>
              </div>
              {msg.simulated && msg.simulationDetail && (
                <SimulationCard detail={msg.simulationDetail} />
              )}
            </div>
          );
        })}

        {isRunning && (
          <div className="flex items-center gap-2 rounded border border-blue-500/20 bg-blue-500/5 px-3 py-2 text-[10px] text-muted-foreground">
            <div className="h-1.5 w-1.5 animate-pulse rounded-full bg-blue-500" />
            Running {currentNodeType} node...
          </div>
        )}

        <div ref={bottomRef} />
      </div>
    </div>
  );
}
