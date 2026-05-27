"use client";

import { useRef, useState } from "react";
import { Bot, HandMetal, Keyboard, Mic, MicOff, Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import type { TestMode } from "@/lib/api/workflow-test";

interface Props {
  mode: TestMode;
  persona: string;
  currentNodeType: string;
  isPaused: boolean;
  isRunning: boolean;
  copilotSuggestions: string[];
  onModeChange: (mode: TestMode) => void;
  onPersonaChange: (persona: string) => void;
  onManualStep: (input: string) => void;
  onCopilotPick: (suggestion: string) => void;
  onAutopilotToggle: () => void;
}

const NEEDS_INPUT = new Set(["categorize"]);

export function TestInputBar({
  mode,
  persona,
  currentNodeType,
  isPaused,
  isRunning,
  copilotSuggestions,
  onModeChange,
  onPersonaChange,
  onManualStep,
  onCopilotPick,
  onAutopilotToggle,
}: Props) {
  const [text, setText] = useState("");
  const [voiceActive, setVoiceActive] = useState(false);
  const mediaRef = useRef<MediaRecorder | null>(null);

  const needsInput = NEEDS_INPUT.has(currentNodeType);

  async function startVoice() {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const recorder = new MediaRecorder(stream);
    const chunks: Blob[] = [];
    recorder.ondataavailable = (e) => chunks.push(e.data);
    recorder.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      const blob = new Blob(chunks, { type: "audio/webm" });
      const formData = new FormData();
      formData.append("audio", blob);
      try {
        const res = await fetch("/api/v1/realtime/transcribe", {
          method: "POST",
          body: formData,
          headers: {
            Authorization: `Bearer ${localStorage.getItem("access_token") ?? ""}`,
          },
        });
        if (res.ok) {
          const { text: transcribed } = (await res.json()) as { text: string };
          setText(transcribed);
        }
      } catch {
        // Transcription endpoint unavailable — user can still type
      }
      setVoiceActive(false);
    };
    mediaRef.current = recorder;
    recorder.start();
    setVoiceActive(true);
  }

  function stopVoice() {
    mediaRef.current?.stop();
  }

  function handleStep() {
    if (!text.trim() && needsInput) return;
    onManualStep(text.trim());
    setText("");
  }

  return (
    <div className="space-y-2 border-t border-border bg-background p-3">
      {/* Mode switcher */}
      <div className="flex gap-1">
        {(["manual", "copilot", "autopilot"] as TestMode[]).map((m) => (
          <Button
            key={m}
            size="sm"
            variant={mode === m ? "default" : "outline"}
            className="h-7 px-2 text-[10px]"
            onClick={() => onModeChange(m)}
          >
            {m === "manual" && <Keyboard className="mr-1 h-3 w-3" />}
            {m === "copilot" && <HandMetal className="mr-1 h-3 w-3" />}
            {m === "autopilot" && <Bot className="mr-1 h-3 w-3" />}
            {m.charAt(0).toUpperCase() + m.slice(1)}
          </Button>
        ))}
      </div>

      {/* Persona input (co-pilot + autopilot) */}
      {mode !== "manual" && (
        <Input
          className="h-7 text-xs"
          placeholder="Caller persona (e.g. frustrated billing customer)..."
          value={persona}
          onChange={(e) => onPersonaChange(e.target.value)}
        />
      )}

      {/* Manual input */}
      {mode === "manual" && (
        <div className="flex gap-2">
          <Button
            size="sm"
            variant={voiceActive ? "destructive" : "outline"}
            className="h-8 w-8 shrink-0 p-0"
            onClick={voiceActive ? stopVoice : () => void startVoice()}
            title={voiceActive ? "Stop recording" : "Record voice input"}
          >
            {voiceActive ? <MicOff className="h-3.5 w-3.5" /> : <Mic className="h-3.5 w-3.5" />}
          </Button>
          <Textarea
            className="min-h-[32px] resize-none text-sm"
            rows={1}
            placeholder={
              needsInput
                ? "Type what the caller says..."
                : "No input needed — press Step to advance"
            }
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleStep();
              }
            }}
          />
          <Button
            size="sm"
            className="h-8 shrink-0"
            disabled={isRunning || isPaused || (needsInput && !text.trim())}
            onClick={handleStep}
          >
            <Send className="mr-1 h-3.5 w-3.5" />
            Step
          </Button>
        </div>
      )}

      {/* Co-pilot suggestions */}
      {mode === "copilot" && copilotSuggestions.length > 0 && (
        <div className="space-y-1">
          <div className="text-[9px] text-muted-foreground">AI suggests:</div>
          {copilotSuggestions.map((s, i) => (
            <button
              key={i}
              className="w-full rounded border border-primary/30 bg-primary/5 px-2 py-1.5 text-left text-xs text-primary hover:bg-primary/10"
              onClick={() => onCopilotPick(s)}
            >
              → {s}
            </button>
          ))}
          <div className="flex gap-2 pt-1">
            <Textarea
              className="min-h-[28px] resize-none text-xs"
              rows={1}
              placeholder="or type your own..."
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  onCopilotPick(text);
                  setText("");
                }
              }}
            />
            <Button
              size="sm"
              className="h-8 shrink-0"
              onClick={() => {
                onCopilotPick(text);
                setText("");
              }}
            >
              Send
            </Button>
          </div>
        </div>
      )}

      {/* Autopilot controls */}
      {mode === "autopilot" && (
        <Button
          size="sm"
          className="w-full"
          variant={isRunning ? "outline" : "default"}
          onClick={onAutopilotToggle}
        >
          {isRunning ? "⏸ Pause Autopilot" : "▶ Run Autopilot"}
        </Button>
      )}
    </div>
  );
}
