"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { speakText } from "@/lib/api/workflow-test";
import type { VoiceConfig, StepOut } from "@/lib/api/workflow-test";

export type VoiceInputMode = "off" | "ptt" | "hands-free";
export type VoiceState =
  | "idle"
  | "agent-speaking"
  | "caller-ready"
  | "listening"
  | "recording"
  | "processing";

interface UseVoiceModeProps {
  workflowId: string;
  sessionId: string | null;
  voiceConfig: VoiceConfig | null;
  onStep: (text: string) => void;
}

export interface UseVoiceModeReturn {
  inputMode: VoiceInputMode;
  setInputMode: (mode: VoiceInputMode) => void;
  voiceState: VoiceState;
  handleStepDone: (result: StepOut) => void;
  startPTT: () => void;
  stopPTT: () => void;
}

const SILENCE_TIMEOUT_MS = 1500;
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export function useVoiceMode({
  workflowId,
  sessionId,
  voiceConfig,
  onStep,
}: UseVoiceModeProps): UseVoiceModeReturn {
  const [inputMode, setInputModeState] = useState<VoiceInputMode>("off");
  const [voiceState, setVoiceState] = useState<VoiceState>("idle");

  const audioCtxRef = useRef<AudioContext | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const silenceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const lastSpokenRef = useRef<string>("");
  const onStepRef = useRef(onStep);
  onStepRef.current = onStep;
  const sessionIdRef = useRef(sessionId);
  sessionIdRef.current = sessionId;
  const voiceConfigRef = useRef(voiceConfig);
  voiceConfigRef.current = voiceConfig;
  const inputModeRef = useRef(inputMode);
  inputModeRef.current = inputMode;

  function getAudioContext(): AudioContext {
    if (!audioCtxRef.current || audioCtxRef.current.state === "closed") {
      audioCtxRef.current = new AudioContext();
    }
    return audioCtxRef.current;
  }

  const speakAndThen = useCallback(
    async (text: string, afterSpeak: () => void): Promise<void> => {
      const cfg = voiceConfigRef.current;
      const sid = sessionIdRef.current;

      const browserFallback = () => {
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.onend = afterSpeak;
        window.speechSynthesis.speak(utterance);
      };

      if (!cfg || cfg.provider === "browser" || !cfg.available || !sid) {
        browserFallback();
        return;
      }

      try {
        const arrayBuffer = await speakText(workflowId, sid, text);
        const ctx = getAudioContext();
        const audioBuffer = await ctx.decodeAudioData(arrayBuffer);
        const source = ctx.createBufferSource();
        source.buffer = audioBuffer;
        source.connect(ctx.destination);
        source.onended = afterSpeak;
        source.start();
      } catch {
        browserFallback();
      }
    },
    [workflowId]
  );

  const stopRecording = useCallback(() => {
    if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);
    mediaRecorderRef.current?.stop();
  }, []);

  const startRecording = useCallback(async (): Promise<void> => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (e) => chunksRef.current.push(e.data);
      recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        setVoiceState("processing");
        const blob = new Blob(chunksRef.current, { type: "audio/webm" });
        const formData = new FormData();
        formData.append("audio", blob);
        try {
          const token = localStorage.getItem("access_token") ?? "";
          const res = await fetch(`${API_BASE}/api/v1/realtime/transcribe`, {
            method: "POST",
            body: formData,
            headers: { Authorization: `Bearer ${token}` },
          });
          if (res.ok) {
            const { text } = (await res.json()) as { text: string };
            if (text.trim()) {
              onStepRef.current(text.trim());
              return;
            }
          }
        } catch {
          // fall through to reset
        }
        setVoiceState("caller-ready");
      };
      mediaRecorderRef.current = recorder;
      recorder.start();
      setVoiceState("recording");
    } catch {
      setVoiceState("caller-ready");
    }
  }, []);

  const handleStepDone = useCallback(
    (result: StepOut): void => {
      if (inputModeRef.current === "off") return;

      const { node_output, is_complete, current_node_type } = result;

      // Skip output already spoken (entry node pre-routes to instruction, producing duplicate)
      const textToSpeak = node_output && node_output !== lastSpokenRef.current ? node_output : "";
      if (node_output) lastSpokenRef.current = node_output;

      const afterSpeak = () => {
        if (is_complete) {
          setVoiceState("idle");
          return;
        }
        if (current_node_type === "categorize") {
          setVoiceState("caller-ready");
          if (inputModeRef.current === "hands-free") {
            void startRecording();
          }
        } else {
          setVoiceState("processing");
          onStepRef.current("");
        }
      };

      if (textToSpeak) {
        setVoiceState("agent-speaking");
        void speakAndThen(textToSpeak, afterSpeak);
      } else {
        afterSpeak();
      }
    },
    [speakAndThen, startRecording]
  );

  const setInputMode = useCallback((mode: VoiceInputMode) => {
    setInputModeState(mode);
    if (mode === "off") {
      setVoiceState("idle");
      window.speechSynthesis.cancel();
      audioCtxRef.current?.close().catch(() => null);
      lastSpokenRef.current = "";
    }
  }, []);

  const startPTT = useCallback(() => {
    if (voiceState !== "caller-ready") return;
    void startRecording();
  }, [voiceState, startRecording]);

  const stopPTT = useCallback(() => {
    if (voiceState !== "recording") return;
    stopRecording();
  }, [voiceState, stopRecording]);

  // Hands-free: auto silence timeout
  useEffect(() => {
    if (inputMode !== "hands-free" || voiceState !== "recording") return;
    silenceTimerRef.current = setTimeout(() => {
      stopRecording();
    }, SILENCE_TIMEOUT_MS);
    return () => {
      if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);
    };
  }, [inputMode, voiceState, stopRecording]);

  return { inputMode, setInputMode, voiceState, handleStepDone, startPTT, stopPTT };
}
