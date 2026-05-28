"use client";

import { useState } from "react";
import { Info, Loader2, Wand2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { generateWorkflowFromPrompt, type GenerateWorkflowResponse } from "@/lib/api/workflows";

const MODELS = [
  {
    value: "openai:gpt-4o-mini",
    label: "GPT-4o Mini (fast)",
    provider: "openai" as const,
    model: "gpt-4o-mini",
  },
  { value: "openai:gpt-4o", label: "GPT-4o", provider: "openai" as const, model: "gpt-4o" },
  {
    value: "anthropic:claude-haiku-4-5-20251001",
    label: "Claude Haiku (fast)",
    provider: "anthropic" as const,
    model: "claude-haiku-4-5-20251001",
  },
  {
    value: "anthropic:claude-sonnet-4-6",
    label: "Claude Sonnet",
    provider: "anthropic" as const,
    model: "claude-sonnet-4-6",
  },
  {
    value: "google:gemini-2.0-flash",
    label: "Gemini Flash (fast)",
    provider: "google" as const,
    model: "gemini-2.0-flash",
  },
];

interface PromptBarProps {
  workspaceId: string;
  workflowId: string;
  /** Name of the agent attached to this workflow, if any. Used to show context status. */
  agentName: string | null;
  onGenerated: (result: GenerateWorkflowResponse) => void;
  onClose: () => void;
}

export function PromptBar({
  workspaceId,
  workflowId,
  agentName,
  onGenerated,
  onClose,
}: PromptBarProps) {
  const [prompt, setPrompt] = useState("");
  const [model, setModel] = useState("openai:gpt-4o-mini");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleGenerate() {
    if (!prompt.trim() || loading) return;
    setLoading(true);
    setError(null);
    try {
      const selectedModel = MODELS.find((m) => m.value === model);
      if (!selectedModel) return;
      const result = await generateWorkflowFromPrompt({
        workspace_id: workspaceId,
        workflow_id: workflowId,
        prompt,
        provider: selectedModel.provider,
        model: selectedModel.model,
      });
      onGenerated(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Generation failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="absolute left-1/2 top-4 z-50 -translate-x-1/2">
      {/* Context status banner */}
      {agentName ? (
        <div className="mb-1.5 flex items-center gap-1.5 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-1 text-xs text-emerald-700">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
          Using <strong>{agentName}</strong> context for generation
        </div>
      ) : (
        <div className="mb-1.5 flex items-center gap-1.5 rounded-md border border-amber-200 bg-amber-50 px-3 py-1 text-xs text-amber-700">
          <Info className="h-3 w-3 shrink-0" />
          For best results, attach this workflow to an agent via the agent&apos;s Workflow tab.
        </div>
      )}

      {/* Main input row */}
      <div className="flex min-w-[600px] items-center gap-2 rounded-lg border bg-background p-2.5 shadow-lg">
        <Wand2 className="h-4 w-4 shrink-0 text-muted-foreground" />
        <Input
          autoFocus
          placeholder='Describe your workflow or node… e.g. "add a transfer to sales" or "build a dental clinic intake flow"'
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void handleGenerate();
            if (e.key === "Escape") onClose();
          }}
          className="flex-1 border-0 shadow-none focus-visible:ring-0"
          disabled={loading}
        />
        <Select value={model} onValueChange={setModel} disabled={loading}>
          <SelectTrigger className="w-[190px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {MODELS.map((m) => (
              <SelectItem key={m.value} value={m.value}>
                {m.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button
          size="sm"
          onClick={() => void handleGenerate()}
          disabled={loading || !prompt.trim()}
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : "Generate"}
        </Button>
        <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close prompt bar">
          <X className="h-4 w-4" />
        </Button>
      </div>

      {error && <p className="mt-1 text-xs text-destructive">{error}</p>}
    </div>
  );
}
