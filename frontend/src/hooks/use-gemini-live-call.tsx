"use client";

import { useState, useRef, useCallback } from "react";
import { Room, RoomEvent, Track, type RemoteTrack } from "livekit-client";

export type GeminiConnectionStatus = "idle" | "connecting" | "connected" | "disconnected";

export type GeminiTranscriptItem = {
  id: string;
  speaker: "user" | "assistant" | "system";
  text: string;
  timestamp: Date;
};

type UseGeminiLiveCallOptions = {
  onTranscriptUpdate?: (items: GeminiTranscriptItem[]) => void;
};

export function useGeminiLiveCall({ onTranscriptUpdate }: UseGeminiLiveCallOptions = {}) {
  const [status, setStatus] = useState<GeminiConnectionStatus>("idle");
  const [transcript, setTranscript] = useState<GeminiTranscriptItem[]>([]);
  const roomRef = useRef<Room | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const addItem = useCallback(
    (item: Omit<GeminiTranscriptItem, "id" | "timestamp">) => {
      const entry: GeminiTranscriptItem = {
        ...item,
        id: crypto.randomUUID(),
        timestamp: new Date(),
      };
      setTranscript((prev) => {
        const updated = [...prev, entry];
        onTranscriptUpdate?.(updated);
        return updated;
      });
    },
    [onTranscriptUpdate]
  );

  const startCall = useCallback(
    async (agentId: string, workspaceId: string) => {
      if (!agentId || !workspaceId) return;
      setStatus("connecting");
      setTranscript([]);

      try {
        const apiBase = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
        const authToken =
          typeof window !== "undefined" ? localStorage.getItem("access_token") : null;

        const resp = await fetch(
          `${apiBase}/api/v1/gemini/token/${agentId}?workspace_id=${workspaceId}`,
          {
            headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
          }
        );
        if (!resp.ok) {
          throw new Error(`Token request failed: ${resp.status}`);
        }
        const data = (await resp.json()) as {
          livekit_url: string;
          token: string;
          agent: { name: string; initial_greeting?: string };
        };

        const room = new Room({
          audioCaptureDefaults: { echoCancellation: true, noiseSuppression: true },
        });
        roomRef.current = room;

        room.on(RoomEvent.TrackSubscribed, (track: RemoteTrack) => {
          if (track.kind === Track.Kind.Audio) {
            if (!audioRef.current) {
              audioRef.current = document.createElement("audio");
              audioRef.current.autoplay = true;
              document.body.appendChild(audioRef.current);
            }
            track.attach(audioRef.current);
          }
        });

        room.on(RoomEvent.DataReceived, (payload: Uint8Array) => {
          try {
            const msg = JSON.parse(new TextDecoder().decode(payload)) as {
              type: string;
              speaker: "user" | "assistant";
              text: string;
            };
            if (msg.type === "transcript") {
              addItem({ speaker: msg.speaker, text: msg.text });
            }
          } catch {
            /* ignore */
          }
        });

        room.on(RoomEvent.Disconnected, () => setStatus("disconnected"));

        await room.connect(data.livekit_url, data.token);
        await room.localParticipant.setMicrophoneEnabled(true);

        setStatus("connected");
        addItem({ speaker: "system", text: "Connected to Gemini Live agent" });
        if (data.agent.initial_greeting) {
          addItem({ speaker: "assistant", text: data.agent.initial_greeting });
        }
      } catch (err) {
        console.error("Gemini call failed:", err);
        setStatus("idle");
        addItem({ speaker: "system", text: "Failed to connect to Gemini agent" });
      }
    },
    [addItem]
  );

  const stopCall = useCallback(() => {
    void roomRef.current?.disconnect();
    roomRef.current = null;
    if (audioRef.current) {
      audioRef.current.remove();
      audioRef.current = null;
    }
    setStatus("idle");
    addItem({ speaker: "system", text: "Call ended" });
  }, [addItem]);

  return { status, transcript, startCall, stopCall };
}
