"use client";

import { useEffect, useRef } from "react";

export interface TranscriptEntry {
  id: string;
  speaker: "caller" | "agent";
  text: string;
  isDelta: boolean;
}

interface Props {
  entries: TranscriptEntry[];
  isRunning: boolean;
}

export function TestCallTranscript({ entries, isRunning }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [entries.length]);

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="flex-1 space-y-3 overflow-y-auto p-4">
        <div className="text-center text-[10px] text-muted-foreground">── Test started ──</div>

        {entries.map((entry) => {
          const isCaller = entry.speaker === "caller";
          return (
            <div
              key={entry.id}
              className={`flex items-start gap-2 ${isCaller ? "flex-row-reverse" : ""}`}
            >
              <div
                className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[9px] font-bold text-white ${
                  isCaller ? "bg-blue-600" : "bg-primary"
                }`}
              >
                {isCaller ? "C" : "A"}
              </div>
              <div
                className={`max-w-[75%] rounded-lg px-3 py-2 text-sm ${
                  isCaller
                    ? "border border-blue-500/30 bg-blue-500/10 text-blue-200"
                    : "border border-border bg-muted/50"
                }`}
              >
                <div className="mb-1 text-[9px] text-muted-foreground">
                  {isCaller ? "Caller" : "Agent"}
                </div>
                <div className={entry.isDelta ? "opacity-60" : ""}>{entry.text}</div>
              </div>
            </div>
          );
        })}

        {isRunning && (
          <div className="flex items-center gap-2 rounded border border-green-500/20 bg-green-500/5 px-3 py-2 text-[10px] text-muted-foreground">
            <div className="h-1.5 w-1.5 animate-pulse rounded-full bg-green-500" />
            Conversation in progress…
          </div>
        )}

        <div ref={bottomRef} />
      </div>
    </div>
  );
}
