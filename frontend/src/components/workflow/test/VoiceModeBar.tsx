"use client";

import { Mic, MicOff, Volume2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { VoiceInputMode, VoiceState } from "@/hooks/use-voice-mode";

interface Props {
  inputMode: VoiceInputMode;
  voiceState: VoiceState;
  onModeChange: (mode: VoiceInputMode) => void;
  onPTTStart: () => void;
  onPTTStop: () => void;
}

const MODES: { value: VoiceInputMode; label: string }[] = [
  { value: "off", label: "Off" },
  { value: "ptt", label: "PTT" },
  { value: "hands-free", label: "Hands-free" },
];

export function VoiceModeBar({
  inputMode,
  voiceState,
  onModeChange,
  onPTTStart,
  onPTTStop,
}: Props) {
  return (
    <div className="flex shrink-0 items-center gap-3 border-b border-border bg-muted/20 px-4 py-2">
      <span className="text-[10px] font-medium text-muted-foreground">Voice</span>
      <div className="flex gap-1">
        {MODES.map((m) => (
          <Button
            key={m.value}
            size="sm"
            variant={inputMode === m.value ? "default" : "outline"}
            className="h-7 px-2 text-[10px]"
            onClick={() => onModeChange(m.value)}
          >
            {m.label}
          </Button>
        ))}
      </div>

      {voiceState === "agent-speaking" && (
        <div className="flex items-center gap-1 text-[10px] text-blue-400">
          <Volume2 className="h-3 w-3 animate-pulse" />
          <span>Speaking…</span>
        </div>
      )}

      {voiceState === "recording" && (
        <div className="flex items-center gap-1 text-[10px] text-red-400">
          <span className="h-2 w-2 animate-pulse rounded-full bg-red-500" />
          <span>Recording</span>
        </div>
      )}

      {voiceState === "caller-ready" && inputMode === "hands-free" && (
        <span className="text-[10px] text-muted-foreground">Listening…</span>
      )}

      {voiceState === "processing" && (
        <span className="text-[10px] text-muted-foreground">Processing…</span>
      )}

      {inputMode === "ptt" && voiceState === "caller-ready" && (
        <Button
          size="sm"
          variant="outline"
          className="ml-auto h-8 select-none"
          onPointerDown={onPTTStart}
          onPointerUp={onPTTStop}
          onPointerLeave={onPTTStop}
        >
          <Mic className="mr-1 h-3.5 w-3.5" />
          Hold to Talk
        </Button>
      )}

      {inputMode === "ptt" && voiceState === "recording" && (
        <Button
          size="sm"
          variant="destructive"
          className="ml-auto h-8 select-none"
          onPointerUp={onPTTStop}
          onPointerLeave={onPTTStop}
        >
          <MicOff className="mr-1 h-3.5 w-3.5" />
          Release to Send
        </Button>
      )}
    </div>
  );
}
