# Workflow Test — Voice Simulation Design

**Date:** 2026-05-28  
**Status:** Draft

---

## Goal

Turn the workflow step-through test into a realistic voice simulation. When you open the test page you should feel like you're actually on a phone call with the agent: the agent speaks its responses using the same voice it would use in production, and you respond by talking (or typing). The existing node list, context bag, and simulation detail panels stay visible so the workflow can still be debugged while it runs.

---

## Conversation Flow

The real voice agent works as a continuous loop:

```
agent speaks greeting → caller speaks → categorize → agent speaks instruction → repeat
```

The test page mimics this loop step by step:

1. Session starts at the **entry** node — auto-step immediately (no output)
2. Move to **instruction** node — speak `node_output` via TTS
3. Move to **categorize** node — wait for caller voice/text input
4. Caller speaks (or types) → transcribe → POST step with `caller_input`
5. Categorize runs → **condition** node — auto-step (no caller input needed)
6. Move to next **instruction/transfer/end_call** — speak output, then auto-step or end

**Rule:** after every step, speak `node_output` if present, then:
- `is_complete = true` → call ended
- new current node type is `categorize` → wait for caller input
- any other type → auto-step (empty `caller_input`) after TTS finishes

---

## Voice Config Resolution

At session start, the backend resolves which voice to use:

1. Query `Agent WHERE workflow_id = {workflow_id}` — find attached agent
2. Read `agent.pricing_tier` and `agent.voice` to determine provider + voice ID
3. Verify the required API key exists in workspace settings
4. Return config to frontend; frontend caches it for the session

| Pricing tier | TTS provider | Model | Voice field |
|---|---|---|---|
| `premium` / `premium-mini` | OpenAI (`tts-1`) | `tts-1` | `agent.voice` (e.g. "shimmer") |
| `budget` | ElevenLabs | `eleven_flash_v2_5` | `agent.voice` (ElevenLabs voice ID) |
| `balanced` | OpenAI (`tts-1`) | `tts-1` | `agent.voice` (falls back to "shimmer") |

If no agent is attached to the workflow, use OpenAI `tts-1` with `shimmer` and the workspace OpenAI key.  
If no API key is available at all, fall back silently to browser `speechSynthesis`.

---

## Backend Changes

### 1. `GET /api/v1/workflows/{workflow_id}/test/voice-config`

Returns the resolved voice config for this workflow's agent. Called once at session start.

**Response:**
```json
{
  "provider": "openai",          // "openai" | "elevenlabs" | "browser"
  "tts_model": "tts-1",
  "voice": "shimmer",
  "available": true              // false = no API key, will fall back to browser
}
```

`provider: "browser"` means the backend has no key; frontend uses `speechSynthesis` directly.

### 2. `POST /api/v1/workflows/{workflow_id}/test/speak`

Converts text to audio using the agent's configured voice. Returns raw MP3 bytes with `Content-Type: audio/mpeg`.

**Request:** `multipart/form-data` with fields:
- `text` (string) — the text to speak
- `session_id` (string) — used to validate workspace access (reuses session auth pattern)

**Provider routing:**
- **OpenAI:** `client.audio.speech.create(model="tts-1", voice=voice, input=text)` → stream MP3
- **ElevenLabs:** `POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}` with `xi-api-key` header

**Error handling:** 502 if the provider call fails; frontend falls back to browser `speechSynthesis`.

---

## Frontend Changes

### State machine: `useVoiceMode` hook

Manages the voice conversation loop independently of the test page's step logic.

**States:**
```
idle → agent-speaking → caller-ready (PTT) / listening (hands-free)
       ↑                      ↓
       └──── processing ←── recording
```

- `idle` — voice mode off or session not started
- `agent-speaking` — TTS audio is playing; mic is blocked
- `caller-ready` — agent finished speaking; PTT: waiting for button press; hands-free: mic auto-starts
- `listening` — hands-free: mic is hot, silence detection active
- `recording` — mic capturing audio
- `processing` — transcribing audio + firing step

**Inputs consumed:**
- `nodeOutput: string` — text to speak after each step (from `STEP_DONE`)
- `isComplete: boolean` — stop the loop
- `currentNodeType: string` — determines whether to wait for caller or auto-step
- `onStep(text)` — fires the next step with the given caller text

**Key behaviours:**
- After `STEP_DONE`: if `node_output` → speak it; when TTS ends → check whether to wait or auto-step
- PTT mode: voice mode on, but mic only activates on button hold/click
- Hands-free mode: mic activates automatically after TTS ends
- Auto-step: if new current node does not require caller input, call `onStep("")` immediately after TTS
- Any step error → return to `caller-ready`; don't loop infinitely

### `VoiceModeBar` component

New bar above `TestInputBar` (only visible when voice mode is on). Contains:

- **Voice mode toggle** (off / PTT / hands-free) — 3-state segmented control
- **Speaking indicator** — animated waveform while agent TTS is playing
- **Mic indicator** — red dot while recording
- **"Listening…"** label in hands-free state
- PTT mode: large **"Hold to Talk"** / **"Release to Send"** button

### Changes to test page (`page.tsx`)

- On `STEP_DONE`, pass `result.node_output` to `useVoiceMode` to trigger TTS
- Pass `onStep` from `executeStep` into `useVoiceMode`
- Pass `workspaceId` and `workflowId` so the hook can call `/speak`
- Fetch voice config after session starts; pass to hook
- `VoiceModeBar` sits between the top bar and the 3-panel body; hidden when voice mode is `off`
- `TestInputBar` is hidden when voice mode is `PTT` or `hands-free` (no need to type)

---

## API Client (`workflow-test.ts`)

Two new functions:
```ts
getVoiceConfig(workflowId): Promise<VoiceConfig>
speakText(workflowId, sessionId, text): Promise<ArrayBuffer>  // returns MP3 bytes
```

Audio playback uses the Web Audio API (`AudioContext.decodeAudioData`) for reliable playback and completion detection. Completion fires the auto-step or mic-enable logic.

---

## Fallback Chain

```
1. Agent's configured provider (OpenAI / ElevenLabs)
   ↓ (no API key or 502)
2. Workspace OpenAI key with default voice "shimmer"
   ↓ (no OpenAI key)
3. Browser speechSynthesis (no backend call)
```

The frontend always gets audio; it never blocks the conversation loop on a TTS failure.

---

## Out of scope

- VAD (voice activity detection) for automatic silence-based stop — user manually stops in PTT; hands-free uses a fixed silence timeout (1.5s)
- Interruption (barge-in) — agent finishes speaking before mic activates
- Recording the full simulated call
- Multiple agents attached to the same workflow
