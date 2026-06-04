"use client";

import type { Node } from "@xyflow/react";
import { X, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import type { WorkflowNode } from "@/lib/api/workflows";

interface Props {
  node: Node;
  availableTrees: string[];
  onChange: (nodeId: string, config: WorkflowNode["config"]) => void;
  onLabelChange: (nodeId: string, label: string) => void;
  onDelete: (nodeId: string) => void;
  onClose: () => void;
}

const TEMPLATE_VARS = [
  "code",
  "label",
  "path_string",
  "action_type",
  "transfer_target",
  "email_target",
  "required_information",
  "approved_script",
  "urgency_level",
  "info_to_collect",
  "confidence",
  "caller_name",
  "caller_number",
];

const LLM_MODELS = [
  { provider: "openai", model: "gpt-4o-mini", label: "GPT-4o Mini (fast)" },
  { provider: "openai", model: "gpt-4o", label: "GPT-4o" },
  { provider: "anthropic", model: "claude-haiku-4-5-20251001", label: "Claude Haiku (fast)" },
  { provider: "anthropic", model: "claude-sonnet-4-6", label: "Claude Sonnet" },
  { provider: "google", model: "gemini-2.0-flash", label: "Gemini Flash (fast)" },
];

const HTTP_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"];

function TemplateField({
  value,
  onChange,
  rows = 4,
  placeholder = "Use {{variable}} tokens…",
}: {
  value: string;
  onChange: (v: string) => void;
  rows?: number;
  placeholder?: string;
}) {
  return (
    <div>
      <Label>Template</Label>
      <Textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={rows}
        placeholder={placeholder}
        className="font-mono text-xs"
      />
      <div className="mt-2 flex flex-wrap gap-1">
        {TEMPLATE_VARS.map((v) => (
          <button
            key={v}
            type="button"
            className="rounded bg-muted px-2 py-0.5 font-mono text-[10px] text-muted-foreground hover:bg-muted/80"
            onClick={() => onChange(`${value}{{${v}}}`)}
          >
            {`{{${v}}}`}
          </button>
        ))}
      </div>
    </div>
  );
}

export function NodeConfigPanel({
  node,
  availableTrees,
  onChange,
  onLabelChange,
  onDelete,
  onClose,
}: Props) {
  const data = node.data as unknown as WorkflowNode;
  const cfg = (data.config ?? {}) as Record<string, string>;
  const type = data.type;

  function set(key: string, value: string) {
    onChange(node.id, { ...cfg, [key]: value });
  }

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b px-4 py-3">
        <span className="text-sm font-semibold capitalize">{type?.replace(/_/g, " ")} node</span>
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            className="text-destructive hover:bg-destructive/10 hover:text-destructive"
            title="Delete node"
            onClick={() => onDelete(node.id)}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
          <Button variant="ghost" size="icon" onClick={onClose}>
            <X className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {/* Fields */}
      <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4">
        {/* Label */}
        <div>
          <Label>Label</Label>
          <Input
            value={(data.label as string) ?? ""}
            onChange={(e) => onLabelChange(node.id, e.target.value)}
            placeholder="Node label"
          />
        </div>

        {/* CATEGORIZE */}
        {type === "categorize" && (
          <>
            <div>
              <Label>Category Tree</Label>
              <Select value={cfg.tree_name ?? ""} onValueChange={(v) => set("tree_name", v)}>
                <SelectTrigger>
                  <SelectValue placeholder="Select tree…" />
                </SelectTrigger>
                <SelectContent>
                  {availableTrees.map((t) => (
                    <SelectItem key={t} value={t}>
                      {t}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>LLM Model</Label>
              <Select
                value={`${cfg.llm_provider ?? "openai"}::${cfg.llm_model ?? "gpt-4o-mini"}`}
                onValueChange={(v) => {
                  const [provider, model] = v.split("::");
                  onChange(node.id, { ...cfg, llm_provider: provider, llm_model: model });
                }}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select model…" />
                </SelectTrigger>
                <SelectContent>
                  {LLM_MODELS.map((m) => (
                    <SelectItem
                      key={`${m.provider}::${m.model}`}
                      value={`${m.provider}::${m.model}`}
                    >
                      {m.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </>
        )}

        {/* CONDITION */}
        {type === "condition" && (
          <>
            <div>
              <Label>Condition expression</Label>
              <Input
                value={cfg.condition ?? ""}
                onChange={(e) => set("condition", e.target.value)}
                placeholder="action_type == transfer"
                className="font-mono text-xs"
              />
              <p className="mt-1 text-xs text-muted-foreground">
                Supports: <code>key == value</code> or <code>key != value</code>.<br />
                The <strong>Yes</strong> (left) handle fires when true; <strong>No</strong> (right)
                when false.
              </p>
            </div>
          </>
        )}

        {/* TRANSFER */}
        {type === "transfer" && (
          <>
            <div>
              <Label>Transfer target</Label>
              <Input
                value={cfg.transfer_target ?? ""}
                onChange={(e) => set("transfer_target", e.target.value)}
                placeholder="+4915123456789 or {{transfer_target}}"
              />
            </div>
            <TemplateField
              value={cfg.template ?? ""}
              onChange={(v) => set("template", v)}
              placeholder="Say before transferring…"
            />
          </>
        )}

        {/* COLLECT + EMAIL */}
        {type === "collect_email" && (
          <>
            <div>
              <Label>Email target</Label>
              <Input
                value={cfg.email_target ?? ""}
                onChange={(e) => set("email_target", e.target.value)}
                placeholder="support@example.com or {{email_target}}"
              />
            </div>
            <TemplateField
              value={cfg.template ?? ""}
              onChange={(v) => set("template", v)}
              placeholder="What to collect before sending…"
            />
          </>
        )}

        {/* INSTRUCTION */}
        {type === "instruction" && (
          <TemplateField
            value={cfg.template ?? ""}
            onChange={(v) => set("template", v)}
            rows={6}
            placeholder="Read this script to the caller…"
          />
        )}

        {/* LOOKUP + TRANSFER */}
        {type === "lookup_transfer" && (
          <TemplateField
            value={cfg.template ?? ""}
            onChange={(v) => set("template", v)}
            placeholder="Look up {{contact_person}}, then transfer…"
          />
        )}

        {/* WEBHOOK */}
        {type === "webhook" && (
          <>
            <div className="flex gap-2">
              <div className="w-24 shrink-0">
                <Label>Method</Label>
                <Select value={cfg.method ?? "POST"} onValueChange={(v) => set("method", v)}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {HTTP_METHODS.map((m) => (
                      <SelectItem key={m} value={m}>
                        {m}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex-1">
                <Label>URL</Label>
                <Input
                  value={cfg.url ?? ""}
                  onChange={(e) => set("url", e.target.value)}
                  placeholder="https://api.example.com/webhook"
                  className="font-mono text-xs"
                />
              </div>
            </div>
            <div>
              <Label>Response key (store in context)</Label>
              <Input
                value={cfg.response_key ?? ""}
                onChange={(e) => set("response_key", e.target.value)}
                placeholder="webhook_result"
                className="font-mono text-xs"
              />
              <p className="mt-1 text-xs text-muted-foreground">
                The response body is stored under this key in the context bag.
              </p>
            </div>
            <div>
              <Label>Request body template</Label>
              <Textarea
                value={cfg.body_template ?? ""}
                onChange={(e) => set("body_template", e.target.value)}
                rows={4}
                placeholder='{"caller": "{{caller_number}}", "issue": "{{label}}"}'
                className="font-mono text-xs"
              />
            </div>
          </>
        )}

        {/* SMS */}
        {type === "sms" && (
          <>
            <div>
              <Label>Recipient</Label>
              <Input
                value={cfg.to ?? ""}
                onChange={(e) => set("to", e.target.value)}
                placeholder="{{caller_number}} or +4915123456789"
              />
            </div>
            <TemplateField
              value={cfg.template ?? ""}
              onChange={(v) => set("template", v)}
              rows={4}
              placeholder="SMS message text…"
            />
          </>
        )}

        {/* APPOINTMENT */}
        {type === "appointment" && (
          <>
            <div>
              <Label>Calendar ID</Label>
              <Input
                value={cfg.calendar_id ?? ""}
                onChange={(e) => set("calendar_id", e.target.value)}
                placeholder="Cal.com link or calendar identifier"
              />
            </div>
            <TemplateField
              value={cfg.template ?? ""}
              onChange={(v) => set("template", v)}
              placeholder="Collect name, date, time preference…"
            />
          </>
        )}

        {/* VOICEMAIL */}
        {type === "voicemail" && (
          <>
            <div>
              <Label>Agent prompt</Label>
              <Textarea
                value={cfg.prompt ?? ""}
                onChange={(e) => set("prompt", e.target.value)}
                rows={4}
                placeholder="Please leave your message after the tone…"
              />
            </div>
            <div>
              <Label>Max seconds</Label>
              <Input
                type="number"
                value={cfg.max_seconds ?? "60"}
                onChange={(e) => set("max_seconds", e.target.value)}
                min={10}
                max={300}
              />
            </div>
            <div>
              <Label>Email recording to</Label>
              <Input
                value={cfg.email_target ?? ""}
                onChange={(e) => set("email_target", e.target.value)}
                placeholder="voicemail@example.com"
              />
            </div>
          </>
        )}

        {/* SUBAGENT */}
        {type === "subagent" && (
          <>
            <div>
              <Label>Override system prompt</Label>
              <Textarea
                value={cfg.system_prompt ?? ""}
                onChange={(e) => set("system_prompt", e.target.value)}
                rows={5}
                placeholder="You are a specialist in…"
              />
              <p className="mt-1 text-xs text-muted-foreground">
                Replaces the agent system prompt for this step only.
              </p>
            </div>
            <div>
              <Label>Override LLM Model</Label>
              <Select
                value={`${cfg.llm_provider ?? ""}::${cfg.llm_model ?? ""}`}
                onValueChange={(v) => {
                  const [provider, model] = v.split("::");
                  onChange(node.id, { ...cfg, llm_provider: provider, llm_model: model });
                }}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Same as agent (no override)" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="::">Same as agent</SelectItem>
                  {LLM_MODELS.map((m) => (
                    <SelectItem
                      key={`${m.provider}::${m.model}`}
                      value={`${m.provider}::${m.model}`}
                    >
                      {m.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>Override voice</Label>
              <Input
                value={cfg.voice ?? ""}
                onChange={(e) => set("voice", e.target.value)}
                placeholder="ElevenLabs voice ID (optional)"
              />
            </div>
          </>
        )}
      </div>
    </div>
  );
}
