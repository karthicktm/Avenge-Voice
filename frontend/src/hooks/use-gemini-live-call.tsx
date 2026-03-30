"use client";

import { useState, useRef, useCallback } from "react";
import { Room, RoomEvent, Track, type RemoteTrack } from "livekit-client";
import { api } from "@/lib/api";

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
  // Track whether disconnect was user-initiated so we don't flicker to "disconnected"
  const intentionalDisconnectRef = useRef(false);

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
    async (agentId: string, workspaceId: string): Promise<boolean> => {
      if (!agentId || !workspaceId) return false;
      if (roomRef.current) return false; // double-connect guard
      setStatus("connecting");
      setTranscript([]);

      try {
        const { data } = await api.get<{
          livekit_url: string;
          token: string;
          agent: { name: string; initial_greeting?: string };
        }>(`/api/v1/gemini/token/${agentId}`, {
          params: { workspace_id: workspaceId },
        });

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

        room.on(RoomEvent.Disconnected, () => {
          // Only mark as disconnected if the server dropped us unexpectedly
          if (!intentionalDisconnectRef.current) {
            setStatus("idle");
            addItem({ speaker: "system", text: "Call ended" });
          }
          roomRef.current = null;
          if (audioRef.current) {
            audioRef.current.remove();
            audioRef.current = null;
          }
        });

        await room.connect(data.livekit_url, data.token);
        await room.localParticipant.setMicrophoneEnabled(true);

        setStatus("connected");
        addItem({ speaker: "system", text: "Connected to Gemini Live agent" });
        if (data.agent.initial_greeting) {
          addItem({ speaker: "assistant", text: data.agent.initial_greeting });
        }
        return true;
      } catch (err) {
        console.error("Gemini call failed:", err);
        setStatus("idle");
        addItem({ speaker: "system", text: "Failed to connect to Gemini agent" });
        return false;
      }
    },
    [addItem]
  );

  const stopCall = useCallback(() => {
    intentionalDisconnectRef.current = true;
    void roomRef.current?.disconnect();
    roomRef.current = null;
    if (audioRef.current) {
      audioRef.current.remove();
      audioRef.current = null;
    }
    intentionalDisconnectRef.current = false;
    setStatus("idle");
    addItem({ speaker: "system", text: "Call ended" });
  }, [addItem]);

  return { status, transcript, startCall, stopCall };
}
