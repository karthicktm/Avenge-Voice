"use client";

import { use, useState, useEffect, useRef, useMemo } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import * as z from "zod";
import Link from "next/link";
import {
  getAgent,
  updateAgent,
  deleteAgent,
  getEmbedSettings,
  updateEmbedSettings,
  type UpdateAgentRequest,
} from "@/lib/api/agents";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import {
  AlertCircle,
  ArrowLeft,
  Loader2,
  Trash2,
  FolderOpen,
  ChevronDown,
  Shield,
  AlertTriangle,
  ShieldAlert,
  Wand2,
  Copy,
  Check,
  Settings2,
  PhoneIncoming,
} from "lucide-react";
import { api } from "@/lib/api";
import { getWebhookInfo, configurePhoneNumberWebhook } from "@/lib/api/telephony";
import { listCategoryTrees, type TreeMeta } from "@/lib/api/category-trees";
import { listWorkflows, attachWorkflow, detachWorkflow, type Workflow } from "@/lib/api/workflows";
import { listCollections, type LookupCollection } from "@/lib/api/lookup";
import { getLanguagesForTier, getFallbackLanguage } from "@/lib/languages";
import { AVAILABLE_INTEGRATIONS } from "@/lib/integrations";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { KnowledgeBaseTab } from "./knowledge-base-tab";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Checkbox } from "@/components/ui/checkbox";
import { Slider } from "@/components/ui/slider";
import { cn } from "@/lib/utils";
import { InfoTooltip } from "@/components/ui/info-tooltip";
import { GitBranch, ExternalLink } from "lucide-react";

// ── WorkflowTab ───────────────────────────────────────────────────────────────

function WorkflowTab({ agentId, workspaceId }: { agentId: string; workspaceId: string }) {
  const qc = useQueryClient();
  const [attachingId, setAttachingId] = useState<string | null>(null);

  const { data: workflows = [] } = useQuery<Workflow[]>({
    queryKey: ["workflows", workspaceId],
    queryFn: () => listWorkflows(workspaceId),
    enabled: !!workspaceId,
  });

  const { data: agentData } = useQuery({
    queryKey: ["agent", agentId],
    queryFn: async () => {
      const res = await api.get<{ workflow_id: string | null }>(`/api/v1/agents/${agentId}`);
      return res.data;
    },
  });

  const attachedId = agentData?.workflow_id ?? null;
  const attachedWorkflow = workflows.find((w) => w.id === attachedId);

  const attachMutation = useMutation({
    mutationFn: (wfId: string) => attachWorkflow(wfId, agentId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["agent", agentId] });
      toast.success("Workflow attached");
      setAttachingId(null);
    },
    onError: () => toast.error("Failed to attach workflow"),
  });

  const detachMutation = useMutation({
    mutationFn: () => detachWorkflow(attachedId ?? "", agentId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["agent", agentId] });
      toast.success("Workflow detached");
    },
    onError: () => toast.error("Failed to detach workflow"),
  });

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <GitBranch className="h-4 w-4 text-indigo-500" />
          Conversation Workflow
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {attachedWorkflow ? (
          <div className="flex items-center justify-between rounded-lg border bg-indigo-50 px-4 py-3">
            <div>
              <div className="flex items-center gap-2 font-medium">
                <GitBranch className="h-4 w-4 text-indigo-500" />
                {attachedWorkflow.name}
              </div>
              <div className="mt-0.5 text-xs text-gray-500">
                {attachedWorkflow.nodes.length} nodes · {attachedWorkflow.edges.length} edges
              </div>
            </div>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" asChild>
                <Link href="/dashboard/workflows">
                  <ExternalLink className="mr-1 h-3.5 w-3.5" />
                  Edit
                </Link>
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="text-red-500 hover:text-red-700"
                onClick={() => detachMutation.mutate()}
                disabled={detachMutation.isPending}
              >
                Detach
              </Button>
            </div>
          </div>
        ) : (
          <p className="text-sm text-gray-500">No workflow attached. Select one below:</p>
        )}

        {workflows.length > 0 && (
          <div className="space-y-2">
            {workflows
              .filter((w) => w.id !== attachedId)
              .map((wf) => (
                <div
                  key={wf.id}
                  className="flex items-center justify-between rounded-lg border px-3 py-2 text-sm"
                >
                  <span>{wf.name}</span>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={attachMutation.isPending && attachingId === wf.id}
                    onClick={() => {
                      setAttachingId(wf.id);
                      attachMutation.mutate(wf.id);
                    }}
                  >
                    Attach
                  </Button>
                </div>
              ))}
          </div>
        )}

        {workflows.length === 0 && (
          <Button variant="outline" size="sm" asChild>
            <Link href="/dashboard/workflows">
              <GitBranch className="mr-1 h-3.5 w-3.5" />
              Create a Workflow
            </Link>
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

// Best practices system prompt template based on OpenAI's 2025 GPT Realtime guidelines
const BEST_PRACTICES_PROMPT = `# Role & Identity
You are a helpful phone assistant for [COMPANY_NAME]. You help customers with questions, support requests, and general inquiries.

# Personality & Tone
- Warm, concise, and confident—never fawning or overly enthusiastic
- Keep responses to 2-3 sentences maximum
- Speak at a steady, unhurried pace
- Use occasional natural fillers like "let me check that" for conversational flow

# Language Rules
- ALWAYS respond in the same language the customer uses
- If audio is unclear, say: "Sorry, I didn't catch that. Could you repeat?"
- Never switch languages mid-conversation unless asked

# Turn-Taking
- Wait for the customer to finish speaking before responding
- Use brief acknowledgments: "Got it," "I understand," "Let me help with that"
- Vary your responses—never repeat the same phrase twice in a row

# Alphanumeric Handling
- When reading back phone numbers, spell digit by digit: "4-1-5-5-5-5-1-2-3-4"
- For confirmation codes, say each character separately
- Always confirm: "Just to verify, that's [X]. Is that correct?"

# Tool Usage
- For lookups: Call immediately, say "Let me check that for you"
- For changes: Confirm first: "I'll update that now. Is that correct?"

# Escalation
Transfer to a human when:
- Customer explicitly requests it
- Customer expresses frustration
- You cannot resolve their issue after 2 attempts
- Request is outside your capabilities

# Boundaries
- Stay focused on [COMPANY_NAME] services
- If unsure, say: "Let me transfer you to someone who can help with that"
- Be honest when you don't know something`;

// Get integrations that have tools defined
const INTEGRATIONS_WITH_TOOLS = AVAILABLE_INTEGRATIONS.filter((i) => i.tools && i.tools.length > 0);

// Helper to get risk level badge variant and icon
function getRiskLevelBadge(level: "safe" | "moderate" | "high") {
  switch (level) {
    case "safe":
      return {
        variant: "safe" as const,
        icon: Shield,
      };
    case "moderate":
      return {
        variant: "moderate" as const,
        icon: AlertTriangle,
      };
    case "high":
      return {
        variant: "high" as const,
        icon: ShieldAlert,
      };
  }
}

interface Workspace {
  id: string;
  name: string;
  description: string | null;
  is_default: boolean;
}

interface AgentWorkspace {
  workspace_id: string;
  workspace_name: string;
}

const agentFormSchema = z.object({
  name: z.string().min(2, "Name must be at least 2 characters"),
  description: z.string().optional(),
  language: z.string().min(1, "Please select a language"),
  useBestPractices: z.boolean().default(true),

  // Voice Settings
  ttsProvider: z.enum(["elevenlabs", "openai", "google"]),
  elevenLabsModel: z.string().default("turbo-v2.5"),
  elevenLabsVoiceId: z.string().optional(),
  ttsSpeed: z.number().min(0.5).max(2).default(1),

  // STT Settings
  sttProvider: z.enum(["deepgram", "openai", "google"]),
  deepgramModel: z.string().default("nova-3"),

  // LLM Settings
  llmProvider: z.enum(["openai", "openai-realtime", "anthropic", "google"]),
  llmModel: z.string().default("gpt-4o"),
  // AI Provider for premium tier (controls provider_config.provider)
  aiProvider: z.enum(["openai", "gemini-live"]).default("openai"),
  voice: z.string().default("marin"),
  systemPrompt: z.string().min(10, "System prompt is required"),
  initialGreeting: z.string().optional(),
  temperature: z.number().min(0).max(2).default(0.7),
  maxTokens: z.number().min(100).max(16000).default(2000),

  // Telephony
  telephonyProvider: z.enum(["telnyx", "twilio"]),
  phoneNumberId: z.string().optional(),

  // Advanced
  enableRecording: z.boolean().default(true),
  enableTranscript: z.boolean().default(true),
  transcriptionModel: z
    .enum(["whisper-1", "gpt-4o-transcribe", "gpt-4o-mini-transcribe"])
    .default("gpt-4o-transcribe"),
  turnDetectionMode: z.enum(["normal", "semantic", "disabled"]).default("normal"),
  turnDetectionThreshold: z.number().min(0).max(1).default(0.7),
  turnDetectionSilenceDurationMs: z.number().min(100).max(2000).default(700),
  isActive: z.boolean().default(true),

  // Tools & Integrations
  enabledTools: z.array(z.string()).default([]),
  enabledToolIds: z.record(z.string(), z.array(z.string())).default({}),
  toolConfigs: z.record(z.string(), z.record(z.string(), z.string())).default({}),

  // Workspaces
  selectedWorkspaces: z.array(z.string()).default([]),

  // Widget Settings
  widgetButtonText: z
    .string()
    .max(20, "Button text must be 20 characters or less")
    .default("Talk to us"),
});

type AgentFormValues = z.infer<typeof agentFormSchema>;

// Map fields to their respective tabs for error tracking
const TAB_FIELDS: Record<string, (keyof AgentFormValues)[]> = {
  basic: ["name", "description", "language", "useBestPractices", "selectedWorkspaces", "isActive"],
  voice: [
    "ttsProvider",
    "elevenLabsModel",
    "elevenLabsVoiceId",
    "ttsSpeed",
    "sttProvider",
    "deepgramModel",
  ],
  llm: [
    "llmProvider",
    "llmModel",
    "aiProvider",
    "voice",
    "systemPrompt",
    "temperature",
    "maxTokens",
  ],
  tools: ["enabledTools", "enabledToolIds"],
  advanced: [
    "telephonyProvider",
    "phoneNumberId",
    "enableRecording",
    "enableTranscript",
    "transcriptionModel",
    "turnDetectionMode",
    "turnDetectionThreshold",
    "turnDetectionSilenceDurationMs",
    "widgetButtonText",
  ],
};

interface EditAgentPageProps {
  params: Promise<{ id: string }>;
}

export default function EditAgentPage({ params }: EditAgentPageProps) {
  const { id: agentId } = use(params);
  const router = useRouter();
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState("basic");
  const [isDeleting, setIsDeleting] = useState(false);
  const isDeletingRef = useRef(false); // Ref for synchronous check
  const [formResetKey, setFormResetKey] = useState(0); // Increment after form.reset() to force Select remount
  const [webhookCopied, setWebhookCopied] = useState(false);
  const [webhookConfigured, setWebhookConfigured] = useState(false);

  const {
    data: agent,
    isLoading,
    error,
  } = useQuery({
    queryKey: ["agent", agentId],
    queryFn: () => {
      // Double-check with ref before fetching
      if (isDeletingRef.current) {
        return Promise.reject(new Error("Agent is being deleted"));
      }
      return getAgent(agentId);
    },
    enabled: !isDeleting, // Disable query when deleting to prevent 404
    retry: (failureCount, error) => {
      // Don't retry if we're deleting
      if (isDeletingRef.current) return false;
      // Don't retry on 404 (agent not found/deleted)
      if (error && typeof error === "object" && "response" in error) {
        const axiosError = error as { response?: { status?: number } };
        if (axiosError.response?.status === 404) {
          return false;
        }
      }
      // Don't retry if error message indicates deletion
      if (error instanceof Error && error.message.includes("being deleted")) {
        return false;
      }
      // Default: retry up to 3 times for other errors
      return failureCount < 3;
    },
  });

  // Redirect to agents list when agent is not found (404)
  useEffect(() => {
    if (error && typeof error === "object" && "response" in error) {
      const axiosError = error as { response?: { status?: number } };
      if (axiosError.response?.status === 404) {
        toast.error("Agent not found or has been deleted");
        router.replace("/dashboard/agents");
      }
    }
  }, [error, router]);

  // Fetch all workspaces
  const { data: workspaces = [] } = useQuery({
    queryKey: ["workspaces"],
    queryFn: async () => {
      const response = await api.get<Workspace[]>("/api/v1/workspaces");
      return response.data;
    },
  });

  // Fetch agent's current workspace assignments
  const { data: agentWorkspaces = [] } = useQuery({
    queryKey: ["agent-workspaces", agentId],
    queryFn: async () => {
      const response = await api.get<AgentWorkspace[]>(`/api/v1/workspaces/agent/${agentId}`);
      return response.data;
    },
    enabled: !!agentId && !!agent && !isDeleting, // Only fetch if agent exists and not deleting
    retry: (failureCount, error) => {
      // Don't retry on 404 (agent not found/deleted)
      if (error && typeof error === "object" && "response" in error) {
        const axiosError = error as { response?: { status?: number } };
        if (axiosError.response?.status === 404) {
          return false;
        }
      }
      return failureCount < 3;
    },
  });

  // Fetch embed settings
  const { data: embedSettings } = useQuery({
    queryKey: ["embed-settings", agentId],
    queryFn: () => getEmbedSettings(agentId),
    enabled: !!agentId && !!agent && !isDeleting,
  });

  const form = useForm<AgentFormValues>({
    resolver: zodResolver(agentFormSchema),
    defaultValues: {
      name: "",
      description: "",
      language: "en-US",
      ttsProvider: "elevenlabs",
      elevenLabsModel: "turbo-v2.5",
      elevenLabsVoiceId: undefined,
      ttsSpeed: 1,
      sttProvider: "deepgram",
      deepgramModel: "nova-3",
      llmProvider: "openai-realtime",
      llmModel: "gpt-realtime-2025-08-28",
      aiProvider: "openai",
      systemPrompt: "",
      initialGreeting: "",
      temperature: 0.7,
      maxTokens: 2000,
      telephonyProvider: "telnyx",
      phoneNumberId: undefined,
      enableRecording: true,
      enableTranscript: true,
      turnDetectionMode: "normal",
      turnDetectionThreshold: 0.7,
      turnDetectionSilenceDurationMs: 700,
      isActive: true,
      enabledTools: [],
      enabledToolIds: {},
      toolConfigs: {},
      selectedWorkspaces: [],
      widgetButtonText: "Talk to us",
    },
  });

  // Track if form has been initialized with agent data
  const formInitialized = useRef(false);
  const lastAgentId = useRef<string | null>(null);

  // Reset form when agent data loads (only once per agent load)
  useEffect(() => {
    // Reset initialization flag if agent ID changes (navigating between agents)
    if (agent?.id !== lastAgentId.current) {
      formInitialized.current = false;
      lastAgentId.current = agent?.id ?? null;
    }

    // Only initialize once we have the agent data
    if (agent && !formInitialized.current) {
      formInitialized.current = true;
      // Ensure language is valid for the agent's pricing tier
      const tier = (agent.pricing_tier ?? "balanced") as
        | "budget"
        | "balanced"
        | "premium-mini"
        | "premium";
      const validLanguage = getFallbackLanguage(agent.language || "en-US", tier);
      form.reset({
        name: agent.name,
        description: agent.description ?? "",
        language: validLanguage,
        useBestPractices: agent.use_best_practices ?? true,
        ttsProvider: "elevenlabs",
        elevenLabsModel: "turbo-v2.5",
        elevenLabsVoiceId: undefined,
        ttsSpeed: 1,
        sttProvider: "deepgram",
        deepgramModel: "nova-3",
        llmProvider: agent.pricing_tier === "premium" ? "openai-realtime" : "openai",
        llmModel: agent.pricing_tier === "premium" ? "gpt-realtime-2025-08-28" : "gpt-4o",
        aiProvider:
          (agent.provider_config?.provider as "openai" | "gemini-live" | undefined) ===
          "gemini-live"
            ? "gemini-live"
            : "openai",
        voice: agent.voice ?? "marin",
        systemPrompt: agent.system_prompt,
        initialGreeting: agent.initial_greeting ?? "",
        temperature: agent.temperature,
        maxTokens: agent.max_tokens,
        telephonyProvider: "telnyx",
        phoneNumberId: agent.phone_number_id ?? undefined,
        enableRecording: agent.enable_recording,
        enableTranscript: agent.enable_transcript,
        transcriptionModel:
          (agent.transcription_model as
            | "whisper-1"
            | "gpt-4o-transcribe"
            | "gpt-4o-mini-transcribe") ?? "gpt-4o-transcribe",
        turnDetectionMode: agent.turn_detection_mode ?? "normal",
        turnDetectionThreshold: agent.turn_detection_threshold ?? 0.7,
        turnDetectionSilenceDurationMs: agent.turn_detection_silence_duration_ms ?? 700,
        isActive: agent.is_active,
        enabledTools: agent.enabled_tools ?? [],
        enabledToolIds: agent.enabled_tool_ids ?? {},
        toolConfigs: agent.tool_configs ?? {},
        selectedWorkspaces: [],
      });
      // Increment key AFTER form.reset() to force Select components to remount with correct values
      setFormResetKey((prev) => prev + 1);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agent]);

  // Update workspaces when they load (separate from initial agent load)
  useEffect(() => {
    if (formInitialized.current && agentWorkspaces.length > 0) {
      form.setValue(
        "selectedWorkspaces",
        agentWorkspaces.map((aw) => aw.workspace_id)
      );
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentWorkspaces]);

  // Update widget button text when embed settings load
  useEffect(() => {
    if (formInitialized.current && embedSettings?.embed_settings?.button_text) {
      form.setValue("widgetButtonText", embedSettings.embed_settings.button_text);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [embedSettings]);

  // Get selected workspaces for phone number fetching
  const selectedWorkspaces = form.watch("selectedWorkspaces");
  const telephonyProvider = form.watch("telephonyProvider");

  // Fetch phone numbers from the first selected workspace
  const { data: phoneNumbers = [], isLoading: isLoadingPhoneNumbers } = useQuery({
    queryKey: ["phone-numbers", selectedWorkspaces[0], telephonyProvider],
    queryFn: async () => {
      if (!selectedWorkspaces[0]) return [];
      const response = await api.get<
        Array<{
          id: string;
          phone_number: string;
          friendly_name: string | null;
          provider: string;
          assigned_agent_id: string | null;
        }>
      >(
        `/api/v1/telephony/phone-numbers?workspace_id=${selectedWorkspaces[0]}&provider=${telephonyProvider}`
      );
      return response.data;
    },
    enabled: !!selectedWorkspaces[0] && !!agent && !isDeleting,
  });

  // Migrate legacy agents: phone_number_id used to store Twilio SID (PNxxx), now stores
  // the actual phone number string (+1...). When phone numbers load, detect and fix SIDs.
  useEffect(() => {
    const stored = form.getValues("phoneNumberId");
    if (stored && stored.startsWith("PN") && phoneNumbers.length > 0) {
      const match = phoneNumbers.find((pn) => pn.id === stored);
      if (match) form.setValue("phoneNumberId", match.phone_number);
    }
  }, [phoneNumbers, form]);

  // Watch current phone number assignment for webhook config
  const currentPhoneNumberId = form.watch("phoneNumberId");

  // Fetch webhook info when a phone number and workspace are selected
  const { data: webhookInfo } = useQuery({
    queryKey: ["webhook-info", telephonyProvider, selectedWorkspaces[0]],
    queryFn: () =>
      selectedWorkspaces[0]
        ? getWebhookInfo(telephonyProvider, selectedWorkspaces[0])
        : Promise.resolve(null),
    enabled: !!selectedWorkspaces[0] && !!currentPhoneNumberId && currentPhoneNumberId !== "none",
  });

  // Look up the SID for the currently selected phone number (needed for Twilio API)
  const selectedPhoneNumberSid = phoneNumbers.find(
    (pn) => pn.phone_number === currentPhoneNumberId
  )?.id;

  // Mutation to configure webhook on the assigned phone number
  const configureWebhookMutation = useMutation({
    mutationFn: () => {
      if (!selectedPhoneNumberSid || !selectedWorkspaces[0]) {
        throw new Error("No phone number or workspace selected");
      }
      return configurePhoneNumberWebhook(
        selectedPhoneNumberSid,
        telephonyProvider,
        selectedWorkspaces[0]
      );
    },
    onSuccess: () => {
      setWebhookConfigured(true);
      toast.success("Webhook configured on phone number");
    },
    onError: (error: Error) => {
      toast.error(`Failed to configure webhook: ${error.message}`);
    },
  });

  const handleWebhookCopy = (text: string) => {
    void navigator.clipboard.writeText(text);
    setWebhookCopied(true);
    setTimeout(() => setWebhookCopied(false), 2000);
  };

  // Watch turn detection mode to conditionally show/hide advanced VAD controls
  const turnDetectionMode = form.watch("turnDetectionMode");

  // Watch the LLM provider to conditionally show/hide Voice tab
  const llmProvider = form.watch("llmProvider");
  const isRealtimeProvider = llmProvider === "openai-realtime";

  // Watch AI provider for premium tier (Gemini Live vs OpenAI)
  const aiProvider = form.watch("aiProvider");
  const isGeminiLive = aiProvider === "gemini-live";

  // Check if Knowledge Base is enabled
  const enabledTools = form.watch("enabledTools");
  const hasKnowledgeBase = enabledTools?.includes("knowledge_base");

  // Fetch category trees for the agent's workspace (used in category_tree tool config)
  const { data: categoryTrees = [] } = useQuery<TreeMeta[]>({
    queryKey: ["category-trees", selectedWorkspaces[0]],
    queryFn: () => listCategoryTrees(selectedWorkspaces[0] ?? ""),
    enabled: !!selectedWorkspaces[0],
  });

  // Fetch lookup collections for the agent's workspace (used in lookup tool config)
  const { data: lookupCollections = [] } = useQuery<LookupCollection[]>({
    queryKey: ["lookup-collections", selectedWorkspaces[0]],
    queryFn: () => listCollections(selectedWorkspaces[0] ?? undefined),
    enabled: !!selectedWorkspaces[0],
  });

  // Get available languages based on agent's pricing tier
  const availableLanguages = useMemo(() => {
    const tier = (agent?.pricing_tier ?? "balanced") as
      | "budget"
      | "balanced"
      | "premium-mini"
      | "premium";
    return getLanguagesForTier(tier);
  }, [agent?.pricing_tier]);

  // Track user-initiated provider changes vs data-loading changes
  const previousProvider = useRef<string | null>(null);

  // Auto-select appropriate model when user changes the provider
  useEffect(() => {
    // Skip if this is the initial data load or provider hasn't changed
    if (previousProvider.current === null) {
      previousProvider.current = llmProvider;
      return;
    }

    // Skip if provider hasn't actually changed
    if (previousProvider.current === llmProvider) {
      return;
    }

    previousProvider.current = llmProvider;

    const defaultModels: Record<string, string> = {
      "openai-realtime": "gpt-realtime-2025-08-28",
      openai: "gpt-4o",
      anthropic: "claude-sonnet-4-5",
      google: "gemini-2.5-flash",
    };

    const defaultModel = defaultModels[llmProvider];
    if (defaultModel) {
      form.setValue("llmModel", defaultModel);
    }
  }, [llmProvider, form]);

  const updateAgentMutation = useMutation({
    mutationFn: (data: UpdateAgentRequest) => updateAgent(agentId, data),
    onSuccess: () => {
      toast.success("Agent updated successfully");
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
      void queryClient.invalidateQueries({ queryKey: ["agent", agentId] });
      router.push("/dashboard/agents");
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to update agent");
    },
  });

  // Handle delete - delete first, then navigate
  const handleDeleteAgent = async () => {
    // Set ref FIRST (synchronous) to block any queries
    isDeletingRef.current = true;
    setIsDeleting(true);

    // Cancel and remove ALL queries immediately to prevent refetching
    void queryClient.cancelQueries({ queryKey: ["agent", agentId] });
    void queryClient.cancelQueries({ queryKey: ["agent-workspaces", agentId] });
    void queryClient.cancelQueries({ queryKey: ["agents"] });
    queryClient.removeQueries({ queryKey: ["agent", agentId] });
    queryClient.removeQueries({ queryKey: ["agent-workspaces", agentId] });

    // Also remove agent from agents list cache immediately (optimistic)
    const previousAgents = queryClient.getQueryData<{ id: string }[]>(["agents"]);
    if (previousAgents) {
      queryClient.setQueryData(
        ["agents"],
        previousAgents.filter((a) => a.id !== agentId)
      );
    }

    try {
      // Delete the agent first
      await deleteAgent(agentId);
      // Then navigate - use replace to prevent back button issues
      router.replace("/dashboard/agents");
    } catch {
      // Even on error, navigate away - the agent page will show error or 404
      router.replace("/dashboard/agents");
    }
  };

  const assignWorkspacesMutation = useMutation({
    mutationFn: async (workspaceIds: string[]) => {
      await api.put(`/api/v1/workspaces/agent/${agentId}/workspaces`, {
        workspace_ids: workspaceIds,
      });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["agent-workspaces", agentId] });
    },
  });

  // Get error count for a specific tab
  const getTabErrorCount = (tabName: string): number => {
    const fields = TAB_FIELDS[tabName] ?? [];
    const errors = form.formState.errors;
    return fields.filter((field) => field in errors).length;
  };

  // Render tab trigger with optional error badge
  const TabTriggerWithErrors = ({ value, label }: { value: string; label: string }) => {
    const errorCount = getTabErrorCount(value);
    return (
      <TabsTrigger
        value={value}
        onClick={() => setActiveTab(value)}
        className={cn(errorCount > 0 && "text-destructive")}
      >
        {label}
        {errorCount > 0 && (
          <span className="ml-1.5 flex h-4 w-4 items-center justify-center rounded-full bg-destructive text-[10px] font-medium text-destructive-foreground">
            {errorCount}
          </span>
        )}
      </TabsTrigger>
    );
  };

  async function onSubmit(data: AgentFormValues) {
    // Determine pricing tier based on LLM provider
    let pricingTier: "budget" | "balanced" | "premium" = "balanced";
    if (data.llmProvider === "openai-realtime") {
      pricingTier = "premium";
    } else if (data.llmModel === "gpt-4o-mini" || data.llmModel === "claude-haiku-4-5") {
      pricingTier = "budget";
    }

    // Derive enabled_tools (integration IDs) from enabledToolIds
    // An integration is enabled if it has at least one tool selected
    const enabledIntegrations = Object.entries(data.enabledToolIds)
      .filter(([, toolIds]) => toolIds.length > 0)
      .map(([integrationId]) => integrationId);

    const request: UpdateAgentRequest = {
      name: data.name,
      description: data.description,
      pricing_tier: pricingTier,
      system_prompt: data.systemPrompt,
      initial_greeting: data.initialGreeting?.trim() ? data.initialGreeting.trim() : null,
      language: data.language,
      use_best_practices: data.useBestPractices,
      voice: data.voice,
      enabled_tools: enabledIntegrations,
      enabled_tool_ids: data.enabledToolIds,
      tool_configs: data.toolConfigs,
      phone_number_id: data.phoneNumberId,
      enable_recording: data.enableRecording,
      enable_transcript: data.enableTranscript,
      transcription_model:
        agent?.pricing_tier === "premium" || agent?.pricing_tier === "premium-mini"
          ? data.transcriptionModel
          : undefined,
      is_active: data.isActive,
      temperature: data.temperature,
      max_tokens: data.maxTokens,
      turn_detection_mode: data.turnDetectionMode,
      turn_detection_threshold: data.turnDetectionThreshold,
      turn_detection_silence_duration_ms: data.turnDetectionSilenceDurationMs,
      // For premium tier, propagate AI provider choice into provider_config
      provider_config:
        pricingTier === "premium" ||
        agent?.pricing_tier === "premium" ||
        agent?.pricing_tier === "premium-mini"
          ? { provider: data.aiProvider }
          : undefined,
    };

    // Update agent, workspaces, and embed settings
    try {
      await Promise.all([
        updateAgentMutation.mutateAsync(request),
        assignWorkspacesMutation.mutateAsync(data.selectedWorkspaces),
        updateEmbedSettings(agentId, {
          embed_settings: {
            button_text: data.widgetButtonText,
          },
        }),
      ]);
    } catch {
      // Error handling is done in individual mutations
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error || !agent) {
    // Check if it's a 404 error - we're redirecting, show loading
    const is404 =
      error &&
      typeof error === "object" &&
      "response" in error &&
      (error as { response?: { status?: number } }).response?.status === 404;

    if (is404) {
      return (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      );
    }

    return (
      <div className="space-y-6">
        <Button variant="ghost" asChild>
          <Link href="/dashboard/agents">
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back to Agents
          </Link>
        </Button>
        <Card className="border-destructive">
          <CardContent className="flex flex-col items-center justify-center py-16">
            <AlertCircle className="mb-4 h-16 w-16 text-destructive" />
            <h3 className="mb-2 text-lg font-semibold">Error loading agent</h3>
            <p className="mb-4 text-center text-sm text-muted-foreground">
              {error instanceof Error ? error.message : "Failed to load agent details"}
            </p>
            <Button asChild>
              <Link href="/dashboard/agents">Return to Agents</Link>
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="icon" className="h-8 w-8" asChild>
            <Link href="/dashboard/agents">
              <ArrowLeft className="h-4 w-4" />
            </Link>
          </Button>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-semibold">{agent.name}</h1>
            <Badge variant={agent.is_active ? "default" : "secondary"} className="h-5 text-[10px]">
              {agent.is_active ? "Active" : "Inactive"}
            </Badge>
          </div>
        </div>
        <AlertDialog>
          <AlertDialogTrigger asChild>
            <Button variant="destructive" size="sm" className="h-8">
              <Trash2 className="mr-1.5 h-3.5 w-3.5" />
              Delete
            </Button>
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle className="text-destructive">
                Delete &ldquo;{agent.name}&rdquo;?
              </AlertDialogTitle>
              <AlertDialogDescription asChild>
                <div className="space-y-3">
                  <p>This action cannot be undone. The following will be permanently deleted:</p>
                  <div className="rounded-md border border-destructive/20 bg-destructive/5 p-3">
                    <ul className="space-y-1 text-sm">
                      <li className="flex items-center justify-between">
                        <span>Call recordings & transcripts</span>
                        <span className="font-medium">{agent.total_calls} calls</span>
                      </li>
                      <li className="flex items-center justify-between">
                        <span>Total call duration</span>
                        <span className="font-medium">
                          {Math.round(agent.total_duration_seconds / 60)} minutes
                        </span>
                      </li>
                      <li className="flex items-center justify-between">
                        <span>Agent configuration</span>
                        <span className="font-medium">All settings</span>
                      </li>
                    </ul>
                  </div>
                  {agent.total_calls > 0 && (
                    <p className="text-sm font-medium text-destructive">
                      Warning: This agent has call history that will be lost.
                    </p>
                  )}
                </div>
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Cancel</AlertDialogCancel>
              <AlertDialogAction
                onClick={(e) => {
                  e.preventDefault();
                  void handleDeleteAgent();
                }}
                disabled={isDeleting}
                className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              >
                {isDeleting ? "Deleting..." : "Delete Permanently"}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </div>

      <Form {...form}>
        <form
          onSubmit={(e) => {
            void form.handleSubmit(onSubmit)(e);
          }}
          className="space-y-4"
        >
          <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
            <TabsList>
              <TabTriggerWithErrors value="basic" label="Basic" />
              {!isRealtimeProvider && <TabTriggerWithErrors value="voice" label="Voice" />}
              <TabTriggerWithErrors value="llm" label="AI Model" />
              <TabTriggerWithErrors value="tools" label="Tools" />
              {hasKnowledgeBase && (
                <TabTriggerWithErrors value="knowledge-base" label="Knowledge Base" />
              )}
              <TabTriggerWithErrors value="advanced" label="Advanced" />
              <TabTriggerWithErrors value="workflow" label="Workflow" />
            </TabsList>

            <TabsContent value="basic" className="mt-4 space-y-3">
              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm font-medium">Basic Information</CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div className="grid gap-3 md:grid-cols-2">
                    <FormField
                      control={form.control}
                      name="name"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Agent Name</FormLabel>
                          <FormControl>
                            <Input placeholder="Customer Support Agent" {...field} />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />

                    <FormField
                      control={form.control}
                      name="language"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Language ({availableLanguages.length} available)</FormLabel>
                          <Select
                            key={`language-${formResetKey}`}
                            onValueChange={field.onChange}
                            value={field.value}
                          >
                            <FormControl>
                              <SelectTrigger>
                                <SelectValue placeholder="Select a language" />
                              </SelectTrigger>
                            </FormControl>
                            <SelectContent className="max-h-[300px]">
                              {availableLanguages.map((lang) => (
                                <SelectItem key={lang.code} value={lang.code}>
                                  {lang.name}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                          <FormMessage />
                        </FormItem>
                      )}
                    />

                    <FormField
                      control={form.control}
                      name="useBestPractices"
                      render={({ field }) => (
                        <FormItem className="flex flex-row items-start space-x-3 space-y-0 rounded-md border p-4">
                          <FormControl>
                            <Checkbox checked={field.value} onCheckedChange={field.onChange} />
                          </FormControl>
                          <div className="space-y-1 leading-none">
                            <FormLabel>Use Best Practices</FormLabel>
                            <FormDescription>
                              Include language-specific conversation guidelines in the system prompt
                              (e.g., be concise, confirm understanding, ask clarifying questions)
                            </FormDescription>
                          </div>
                        </FormItem>
                      )}
                    />
                  </div>

                  <FormField
                    control={form.control}
                    name="description"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Description</FormLabel>
                        <FormControl>
                          <Textarea
                            placeholder="Handles customer inquiries and support"
                            className="min-h-[80px]"
                            {...field}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />

                  <FormField
                    control={form.control}
                    name="selectedWorkspaces"
                    render={() => (
                      <FormItem>
                        <div className="mb-4">
                          <FormLabel className="flex items-center gap-2 text-base">
                            <FolderOpen className="h-4 w-4" />
                            Workspaces
                          </FormLabel>
                          <FormDescription>
                            Assign this agent to workspaces. CRM contacts and appointments in these
                            workspaces will be accessible to this agent.
                          </FormDescription>
                        </div>
                        {workspaces.length === 0 ? (
                          <div className="rounded-lg border border-dashed p-4 text-center text-sm text-muted-foreground">
                            No workspaces created yet.{" "}
                            <Link href="/dashboard/workspaces" className="text-primary underline">
                              Create a workspace
                            </Link>{" "}
                            to organize your contacts and appointments.
                          </div>
                        ) : (
                          <div className="space-y-2">
                            {workspaces.map((workspace) => (
                              <FormField
                                key={workspace.id}
                                control={form.control}
                                name="selectedWorkspaces"
                                render={({ field }) => (
                                  <FormItem className="flex flex-row items-start space-x-3 space-y-0 rounded-md border p-3">
                                    <FormControl>
                                      <Checkbox
                                        checked={field.value?.includes(workspace.id)}
                                        onCheckedChange={(checked: boolean) => {
                                          const current = field.value ?? [];
                                          field.onChange(
                                            checked
                                              ? [...current, workspace.id]
                                              : current.filter((v) => v !== workspace.id)
                                          );
                                        }}
                                      />
                                    </FormControl>
                                    <div className="space-y-1 leading-none">
                                      <FormLabel className="cursor-pointer font-medium">
                                        {workspace.name}
                                        {workspace.is_default && (
                                          <Badge variant="secondary" className="ml-2">
                                            Default
                                          </Badge>
                                        )}
                                      </FormLabel>
                                      {workspace.description && (
                                        <FormDescription>{workspace.description}</FormDescription>
                                      )}
                                    </div>
                                  </FormItem>
                                )}
                              />
                            ))}
                          </div>
                        )}
                        <FormMessage />
                      </FormItem>
                    )}
                  />

                  <FormField
                    control={form.control}
                    name="isActive"
                    render={({ field }) => (
                      <FormItem className="flex flex-row items-center justify-between rounded-lg border p-4">
                        <div className="space-y-0.5">
                          <FormLabel className="text-base">Active Status</FormLabel>
                          <FormDescription>Enable or disable this agent</FormDescription>
                        </div>
                        <FormControl>
                          <Switch checked={field.value} onCheckedChange={field.onChange} />
                        </FormControl>
                      </FormItem>
                    )}
                  />
                </CardContent>
              </Card>
            </TabsContent>

            {!isRealtimeProvider && (
              <TabsContent value="voice" className="mt-4 space-y-3">
                <Card>
                  <CardHeader className="pb-3">
                    <CardTitle className="flex items-center gap-2 text-sm font-medium">
                      Text-to-Speech (TTS)
                      <InfoTooltip content="TTS converts your agent's text responses into natural-sounding speech. Different providers offer varying quality, latency, and voice options." />
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <FormField
                      control={form.control}
                      name="ttsProvider"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>TTS Provider</FormLabel>
                          <Select onValueChange={field.onChange} value={field.value}>
                            <FormControl>
                              <SelectTrigger>
                                <SelectValue />
                              </SelectTrigger>
                            </FormControl>
                            <SelectContent>
                              <SelectItem value="elevenlabs">ElevenLabs (Recommended)</SelectItem>
                              <SelectItem value="openai">OpenAI TTS</SelectItem>
                              <SelectItem value="google">Google Gemini TTS</SelectItem>
                            </SelectContent>
                          </Select>
                          <FormDescription>Choose your text-to-speech provider</FormDescription>
                          <FormMessage />
                        </FormItem>
                      )}
                    />

                    <FormField
                      control={form.control}
                      name="elevenLabsModel"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>ElevenLabs Model</FormLabel>
                          <Select onValueChange={field.onChange} value={field.value}>
                            <FormControl>
                              <SelectTrigger>
                                <SelectValue />
                              </SelectTrigger>
                            </FormControl>
                            <SelectContent>
                              <SelectItem value="eleven_turbo_v2_5">
                                Turbo v2.5 (Recommended - Best Quality)
                              </SelectItem>
                              <SelectItem value="eleven_flash_v2_5">
                                Flash v2.5 (Fastest - 75ms latency)
                              </SelectItem>
                              <SelectItem value="eleven_multilingual_v2">
                                Multilingual v2 (29 languages)
                              </SelectItem>
                              <SelectItem value="eleven_v3">
                                V3 Alpha (Most Expressive - 70+ languages)
                              </SelectItem>
                            </SelectContent>
                          </Select>
                          <FormDescription>
                            Turbo v2.5: ~300ms latency, best quality | Flash v2.5: ~75ms latency
                          </FormDescription>
                          <FormMessage />
                        </FormItem>
                      )}
                    />

                    <FormField
                      control={form.control}
                      name="elevenLabsVoiceId"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Voice</FormLabel>
                          <Select onValueChange={field.onChange} value={field.value}>
                            <FormControl>
                              <SelectTrigger>
                                <SelectValue placeholder="Select a voice" />
                              </SelectTrigger>
                            </FormControl>
                            <SelectContent>
                              <SelectItem value="21m00Tcm4TlvDq8ikWAM">
                                Rachel (Female, American)
                              </SelectItem>
                              <SelectItem value="ErXwobaYiN019PkySvjV">
                                Antoni (Male, American)
                              </SelectItem>
                              <SelectItem value="MF3mGyEYCl7XYWbV9V6O">
                                Elli (Female, American)
                              </SelectItem>
                              <SelectItem value="pNInz6obpgDQGcFmaJgB">
                                Adam (Male, American)
                              </SelectItem>
                            </SelectContent>
                          </Select>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader className="pb-3">
                    <CardTitle className="flex items-center gap-2 text-sm font-medium">
                      Speech-to-Text (STT)
                      <InfoTooltip content="STT converts caller speech into text for the AI to understand. Accuracy is measured by Word Error Rate (WER) - lower is better. Deepgram Nova-3 has 6.84% WER." />
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <FormField
                      control={form.control}
                      name="sttProvider"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>STT Provider</FormLabel>
                          <Select onValueChange={field.onChange} value={field.value}>
                            <FormControl>
                              <SelectTrigger>
                                <SelectValue />
                              </SelectTrigger>
                            </FormControl>
                            <SelectContent>
                              <SelectItem value="deepgram">Deepgram (Recommended)</SelectItem>
                              <SelectItem value="openai">OpenAI Whisper</SelectItem>
                              <SelectItem value="google">Google Gemini STT</SelectItem>
                            </SelectContent>
                          </Select>
                          <FormDescription>
                            Deepgram Nova-3: 6.84% WER, multilingual, PII redaction
                          </FormDescription>
                          <FormMessage />
                        </FormItem>
                      )}
                    />

                    <FormField
                      control={form.control}
                      name="deepgramModel"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Deepgram Model</FormLabel>
                          <Select onValueChange={field.onChange} value={field.value}>
                            <FormControl>
                              <SelectTrigger>
                                <SelectValue />
                              </SelectTrigger>
                            </FormControl>
                            <SelectContent>
                              <SelectItem value="nova-3">
                                Nova-3 (Latest - 54% better WER)
                              </SelectItem>
                              <SelectItem value="flux">
                                Flux (Voice Agents - end-of-turn detection)
                              </SelectItem>
                              <SelectItem value="nova-2">
                                Nova-2 (Legacy - still excellent)
                              </SelectItem>
                            </SelectContent>
                          </Select>
                          <FormDescription>
                            Nova-3: Multilingual, keyterm prompting, PII redaction
                          </FormDescription>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  </CardContent>
                </Card>
              </TabsContent>
            )}

            <TabsContent value="llm" className="mt-4 space-y-3">
              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="flex items-center gap-2 text-sm font-medium">
                    Language Model
                    <InfoTooltip content="The LLM (Large Language Model) is the AI brain that understands user intent and generates responses. Realtime API provides end-to-end voice with lowest latency." />
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div className="grid gap-3 md:grid-cols-2">
                    <FormField
                      control={form.control}
                      name="llmProvider"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>LLM Provider</FormLabel>
                          <Select onValueChange={field.onChange} value={field.value}>
                            <FormControl>
                              <SelectTrigger>
                                <SelectValue />
                              </SelectTrigger>
                            </FormControl>
                            <SelectContent>
                              <SelectItem value="openai-realtime">
                                OpenAI Realtime (Recommended)
                              </SelectItem>
                              <SelectItem value="openai">OpenAI Standard</SelectItem>
                              <SelectItem value="anthropic">Anthropic Claude</SelectItem>
                              <SelectItem value="google">Google Gemini</SelectItem>
                            </SelectContent>
                          </Select>
                          <FormMessage />
                        </FormItem>
                      )}
                    />

                    <FormField
                      control={form.control}
                      name="llmModel"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Model</FormLabel>
                          <Select onValueChange={field.onChange} value={field.value}>
                            <FormControl>
                              <SelectTrigger>
                                <SelectValue />
                              </SelectTrigger>
                            </FormControl>
                            <SelectContent>
                              {llmProvider === "openai-realtime" && (
                                <SelectItem value="gpt-realtime-2025-08-28">
                                  gpt-realtime (Latest - Best Voice)
                                </SelectItem>
                              )}
                              {llmProvider === "openai" && (
                                <>
                                  <SelectItem value="gpt-4o">
                                    GPT-4o (Multimodal - 232ms latency)
                                  </SelectItem>
                                  <SelectItem value="gpt-4o-mini">
                                    GPT-4o-mini (25x cheaper, fast)
                                  </SelectItem>
                                </>
                              )}
                              {llmProvider === "anthropic" && (
                                <>
                                  <SelectItem value="claude-sonnet-4-5">
                                    Claude Sonnet 4.5 (Best coding/agents)
                                  </SelectItem>
                                  <SelectItem value="claude-opus-4-1">
                                    Claude Opus 4.1 (Most capable)
                                  </SelectItem>
                                  <SelectItem value="claude-haiku-4-5">
                                    Claude Haiku 4.5 (Fast & cheap)
                                  </SelectItem>
                                </>
                              )}
                              {llmProvider === "google" && (
                                <>
                                  <SelectItem value="gemini-2.5-flash">
                                    Gemini 2.5 Flash (Multimodal)
                                  </SelectItem>
                                  <SelectItem value="gemini-2.5-pro">
                                    Gemini 2.5 Pro (Most capable)
                                  </SelectItem>
                                </>
                              )}
                            </SelectContent>
                          </Select>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  </div>

                  {(agent?.pricing_tier === "premium" ||
                    agent?.pricing_tier === "premium-mini") && (
                    <FormField
                      control={form.control}
                      name="aiProvider"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>AI Provider</FormLabel>
                          <Select onValueChange={field.onChange} value={field.value}>
                            <FormControl>
                              <SelectTrigger>
                                <SelectValue />
                              </SelectTrigger>
                            </FormControl>
                            <SelectContent>
                              <SelectItem value="openai">GPT Realtime</SelectItem>
                              <SelectItem value="gemini-live">Gemini Live</SelectItem>
                            </SelectContent>
                          </Select>
                          <FormDescription>
                            The AI provider powering this agent&apos;s voice conversation
                          </FormDescription>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  )}

                  {isRealtimeProvider && (
                    <FormField
                      control={form.control}
                      name="voice"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Voice</FormLabel>
                          <Select onValueChange={field.onChange} value={field.value}>
                            <FormControl>
                              <SelectTrigger>
                                <SelectValue placeholder="Select a voice" />
                              </SelectTrigger>
                            </FormControl>
                            <SelectContent>
                              {isGeminiLive ? (
                                <>
                                  <SelectItem value="Puck">Puck</SelectItem>
                                  <SelectItem value="Charon">Charon</SelectItem>
                                  <SelectItem value="Kore">Kore</SelectItem>
                                  <SelectItem value="Fenrir">Fenrir</SelectItem>
                                  <SelectItem value="Aoede">Aoede</SelectItem>
                                </>
                              ) : (
                                <>
                                  <SelectItem value="marin">Marin (Conversational)</SelectItem>
                                  <SelectItem value="cedar">Cedar (Friendly)</SelectItem>
                                  <SelectItem value="coral">Coral (Expressive)</SelectItem>
                                  <SelectItem value="sage">Sage (Calm)</SelectItem>
                                  <SelectItem value="alloy">Alloy (Neutral)</SelectItem>
                                  <SelectItem value="ash">Ash (Professional)</SelectItem>
                                  <SelectItem value="ballad">Ballad (Warm)</SelectItem>
                                  <SelectItem value="shimmer">Shimmer (Bright)</SelectItem>
                                  <SelectItem value="echo">Echo (Clear)</SelectItem>
                                  <SelectItem value="verse">Verse (Melodic)</SelectItem>
                                </>
                              )}
                            </SelectContent>
                          </Select>
                          <FormDescription>
                            The voice your agent will use for speech synthesis
                          </FormDescription>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  )}

                  <div className="flex items-center justify-between rounded-lg border border-dashed bg-muted/50 p-3">
                    <div>
                      <p className="text-sm font-medium">Need help writing a prompt?</p>
                      <p className="text-xs text-muted-foreground">
                        Start with our best practices template based on OpenAI guidelines
                      </p>
                    </div>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => form.setValue("systemPrompt", BEST_PRACTICES_PROMPT)}
                      className="shrink-0"
                    >
                      <Wand2 className="mr-1.5 h-3.5 w-3.5" />
                      Use Best Practices
                    </Button>
                  </div>

                  <FormField
                    control={form.control}
                    name="systemPrompt"
                    render={({ field }) => {
                      const charCount = field.value?.length ?? 0;
                      const isOptimal = charCount >= 100 && charCount <= 2000;
                      const isTooShort = charCount > 0 && charCount < 100;
                      const isTooLong = charCount > 2000;
                      return (
                        <FormItem>
                          <div className="flex items-center justify-between">
                            <FormLabel>System Prompt</FormLabel>
                            <span
                              className={cn(
                                "text-xs",
                                isOptimal && "text-green-600",
                                isTooShort && "text-yellow-600",
                                isTooLong && "text-destructive"
                              )}
                            >
                              {charCount.toLocaleString()} characters
                              {isTooShort && " (recommended: 100+)"}
                              {isTooLong && " (recommended: under 2,000)"}
                            </span>
                          </div>
                          <FormControl>
                            <Textarea
                              placeholder="You are a helpful customer support agent. Be polite, professional, and concise..."
                              className="min-h-[120px]"
                              {...field}
                            />
                          </FormControl>
                          <FormDescription>
                            Instructions that define your agent&apos;s personality and behavior. Aim
                            for 100-2,000 characters for best results.
                          </FormDescription>
                          <FormMessage />
                        </FormItem>
                      );
                    }}
                  />

                  <FormField
                    control={form.control}
                    name="initialGreeting"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Initial Greeting (Optional)</FormLabel>
                        <FormControl>
                          <Textarea
                            placeholder="Hello! Thank you for calling. How can I help you today?"
                            className="min-h-[80px]"
                            {...field}
                          />
                        </FormControl>
                        <FormDescription>
                          What the agent says when the call starts. Leave empty for a natural start.
                        </FormDescription>
                        <FormMessage />
                      </FormItem>
                    )}
                  />

                  <div className="grid grid-cols-2 gap-4">
                    <FormField
                      control={form.control}
                      name="temperature"
                      render={({ field }) => {
                        const getTemperatureLabel = (value: number) => {
                          if (value <= 0.3) return "Focused";
                          if (value <= 0.7) return "Balanced";
                          if (value <= 1.2) return "Creative";
                          return "Very Creative";
                        };
                        return (
                          <FormItem>
                            <div className="flex items-center justify-between">
                              <FormLabel className="flex items-center gap-1.5">
                                Temperature
                                <InfoTooltip content="Controls randomness in responses. Lower (0-0.3) = precise, consistent answers. Higher (0.8-2.0) = more creative, varied responses. 0.7 is a good default for conversations." />
                              </FormLabel>
                              <span className="text-sm font-medium">
                                {field.value?.toFixed(1) ?? "0.7"} (
                                {getTemperatureLabel(field.value ?? 0.7)})
                              </span>
                            </div>
                            <FormControl>
                              <div className="space-y-2">
                                <Slider
                                  min={0}
                                  max={2}
                                  step={0.1}
                                  value={[field.value ?? 0.7]}
                                  onValueChange={(value) => field.onChange(value[0])}
                                  className="w-full"
                                />
                                <div className="flex justify-between text-xs text-muted-foreground">
                                  <span>Focused</span>
                                  <span>Creative</span>
                                </div>
                              </div>
                            </FormControl>
                            <FormDescription>
                              Lower values produce more focused and deterministic responses
                            </FormDescription>
                            <FormMessage />
                          </FormItem>
                        );
                      }}
                    />

                    <FormField
                      control={form.control}
                      name="maxTokens"
                      render={({ field }) => (
                        <FormItem>
                          <div className="flex items-center justify-between">
                            <FormLabel className="flex items-center gap-1.5">
                              Max Tokens
                              <InfoTooltip content="Maximum response length in tokens (1 token ≈ 4 characters). Higher values allow longer responses but cost more. 1000-2000 is recommended for conversations." />
                            </FormLabel>
                            <span className="text-sm font-medium">
                              {(field.value ?? 2000).toLocaleString()}
                            </span>
                          </div>
                          <FormControl>
                            <div className="space-y-2">
                              <Slider
                                min={100}
                                max={4000}
                                step={100}
                                value={[field.value ?? 2000]}
                                onValueChange={(value) => field.onChange(value[0])}
                                className="w-full"
                              />
                              <div className="flex justify-between text-xs text-muted-foreground">
                                <span>100</span>
                                <span>4,000</span>
                              </div>
                            </div>
                          </FormControl>
                          <FormDescription>Maximum length of each response</FormDescription>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  </div>
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="tools" className="mt-4 space-y-3">
              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm font-medium">Integrations & Tools</CardTitle>
                  <p className="text-sm text-muted-foreground">
                    Enable integrations and select which tools your agent can access. High-risk
                    tools (like cancellations) are disabled by default for security.
                  </p>
                </CardHeader>
                <CardContent className="space-y-3">
                  {INTEGRATIONS_WITH_TOOLS.map((integration) => (
                    <FormField
                      key={integration.id}
                      control={form.control}
                      name="enabledTools"
                      render={({ field }) => {
                        const isEnabled = field.value?.includes(integration.id);
                        return (
                          <Collapsible>
                            <div className="rounded-lg border">
                              <div className="flex items-center justify-between p-4">
                                <div className="flex items-center space-x-3">
                                  <Checkbox
                                    checked={isEnabled}
                                    onCheckedChange={(checked) => {
                                      const current = field.value ?? [];
                                      if (checked) {
                                        field.onChange([...current, integration.id]);
                                        // Auto-enable default tools when integration is enabled
                                        const defaultTools =
                                          integration.tools
                                            ?.filter((t) => t.defaultEnabled)
                                            .map((t) => t.id) ?? [];
                                        if (defaultTools.length > 0) {
                                          const currentToolIds =
                                            form.getValues("enabledToolIds") ?? {};
                                          form.setValue(
                                            "enabledToolIds",
                                            {
                                              ...currentToolIds,
                                              [integration.id]: defaultTools,
                                            },
                                            { shouldDirty: true }
                                          );
                                        }
                                      } else {
                                        field.onChange(current.filter((v) => v !== integration.id));
                                        // Clear tool selection when integration is disabled
                                        const currentToolIds =
                                          form.getValues("enabledToolIds") ?? {};
                                        const { [integration.id]: _removed, ...rest } =
                                          currentToolIds;
                                        form.setValue("enabledToolIds", rest, {
                                          shouldDirty: true,
                                        });
                                      }
                                    }}
                                  />
                                  <div>
                                    <div className="flex items-center gap-2">
                                      <span className="font-medium">{integration.name}</span>
                                      {integration.isBuiltIn && (
                                        <Badge variant="secondary" className="text-xs">
                                          Built-in
                                        </Badge>
                                      )}
                                    </div>
                                    <p className="text-sm text-muted-foreground">
                                      {integration.description}
                                    </p>
                                  </div>
                                </div>
                                {isEnabled && integration.tools && integration.tools.length > 0 && (
                                  <CollapsibleTrigger asChild>
                                    <Button variant="ghost" size="sm">
                                      <ChevronDown className="h-4 w-4" />
                                      <span className="ml-1">
                                        {form.watch("enabledToolIds")?.[integration.id]?.length ??
                                          0}{" "}
                                        / {integration.tools.length} tools
                                      </span>
                                    </Button>
                                  </CollapsibleTrigger>
                                )}
                              </div>

                              {isEnabled && integration.tools && integration.tools.length > 0 && (
                                <CollapsibleContent>
                                  <div className="border-t bg-muted/30 p-4">
                                    <div className="mb-3 flex items-center justify-between">
                                      <span className="text-sm font-medium">Available Tools</span>
                                      <div className="flex gap-2">
                                        <Button
                                          type="button"
                                          variant="outline"
                                          size="sm"
                                          onClick={() => {
                                            const allToolIds =
                                              integration.tools?.map((t) => t.id) ?? [];
                                            const currentToolIds =
                                              form.getValues("enabledToolIds") ?? {};
                                            form.setValue(
                                              "enabledToolIds",
                                              {
                                                ...currentToolIds,
                                                [integration.id]: allToolIds,
                                              },
                                              { shouldDirty: true }
                                            );
                                          }}
                                        >
                                          Select All
                                        </Button>
                                        <Button
                                          type="button"
                                          variant="outline"
                                          size="sm"
                                          onClick={() => {
                                            const currentToolIds =
                                              form.getValues("enabledToolIds") ?? {};
                                            form.setValue(
                                              "enabledToolIds",
                                              {
                                                ...currentToolIds,
                                                [integration.id]: [],
                                              },
                                              { shouldDirty: true }
                                            );
                                          }}
                                        >
                                          Clear All
                                        </Button>
                                      </div>
                                    </div>
                                    <div className="space-y-2">
                                      {integration.tools.map((tool) => {
                                        const riskBadge = getRiskLevelBadge(tool.riskLevel);
                                        const RiskIcon = riskBadge.icon;
                                        const currentTools =
                                          form.watch("enabledToolIds")?.[integration.id] ?? [];
                                        const isToolEnabled = currentTools.includes(tool.id);
                                        return (
                                          <div
                                            key={tool.id}
                                            className="flex items-center justify-between rounded-md border bg-background p-3"
                                          >
                                            <div className="flex items-center space-x-3">
                                              <Checkbox
                                                checked={isToolEnabled}
                                                onCheckedChange={(checked) => {
                                                  const enabledToolIds =
                                                    form.getValues("enabledToolIds") ?? {};
                                                  const toolsForIntegration =
                                                    enabledToolIds[integration.id] ?? [];
                                                  const newTools = checked
                                                    ? [...toolsForIntegration, tool.id]
                                                    : toolsForIntegration.filter(
                                                        (t) => t !== tool.id
                                                      );
                                                  form.setValue(
                                                    "enabledToolIds",
                                                    {
                                                      ...enabledToolIds,
                                                      [integration.id]: newTools,
                                                    },
                                                    { shouldDirty: true }
                                                  );
                                                }}
                                              />
                                              <div>
                                                <span className="text-sm font-medium">
                                                  {tool.name}
                                                </span>
                                                <p className="text-xs text-muted-foreground">
                                                  {tool.description}
                                                </p>
                                              </div>
                                            </div>
                                            <Badge variant={riskBadge.variant}>
                                              <RiskIcon className="mr-1 h-3 w-3" />
                                              {tool.riskLevel}
                                            </Badge>
                                          </div>
                                        );
                                      })}
                                    </div>

                                    {/* Category Tree Configuration */}
                                    {integration.id === "category_tree" && (
                                      <div className="mt-4 space-y-3 rounded-lg border bg-background p-4">
                                        <h4 className="text-sm font-medium">
                                          Category Tree Configuration
                                        </h4>
                                        <p className="text-xs text-muted-foreground">
                                          Select the category tree this agent will use to classify
                                          caller issues.
                                        </p>
                                        <div className="space-y-1.5">
                                          <label className="text-xs font-medium">
                                            Category Tree
                                          </label>
                                          <Select
                                            value={
                                              form.watch("toolConfigs.categorize.tree_name") ||
                                              undefined
                                            }
                                            onValueChange={(val) => {
                                              const currentConfigs =
                                                form.getValues("toolConfigs") || {};
                                              form.setValue(
                                                "toolConfigs",
                                                {
                                                  ...currentConfigs,
                                                  categorize: {
                                                    ...currentConfigs.categorize,
                                                    tree_name: val,
                                                  },
                                                },
                                                { shouldDirty: true }
                                              );
                                            }}
                                          >
                                            <SelectTrigger className="h-8">
                                              <SelectValue placeholder="Select a category tree…" />
                                            </SelectTrigger>
                                            <SelectContent>
                                              {categoryTrees.length === 0 ? (
                                                <SelectItem value="_none" disabled>
                                                  No trees found — create one in Category Trees
                                                </SelectItem>
                                              ) : (
                                                categoryTrees.map((tree) => (
                                                  <SelectItem
                                                    key={tree.tree_name}
                                                    value={tree.tree_name}
                                                  >
                                                    {tree.tree_name}
                                                  </SelectItem>
                                                ))
                                              )}
                                            </SelectContent>
                                          </Select>
                                          <p className="text-xs text-muted-foreground">
                                            The agent will call{" "}
                                            <code className="font-mono">
                                              categorize(tree_name=&quot;…&quot;)
                                            </code>{" "}
                                            using this tree.
                                          </p>
                                        </div>
                                      </div>
                                    )}

                                    {/* Lookup Configuration */}
                                    {integration.id === "lookup" && (
                                      <div className="mt-4 space-y-3 rounded-lg border bg-background p-4">
                                        <h4 className="text-sm font-medium">
                                          Lookup Configuration
                                        </h4>
                                        <p className="text-xs text-muted-foreground">
                                          Optionally restrict the agent to search a specific
                                          collection only.
                                        </p>
                                        <div className="space-y-1.5">
                                          <label className="text-xs font-medium">
                                            Default Collection (Optional)
                                          </label>
                                          <Select
                                            value={
                                              form.watch(
                                                "toolConfigs.lookup_search.collection_id"
                                              ) || "_all"
                                            }
                                            onValueChange={(val) => {
                                              const currentConfigs =
                                                form.getValues("toolConfigs") || {};
                                              form.setValue(
                                                "toolConfigs",
                                                {
                                                  ...currentConfigs,
                                                  lookup_search: {
                                                    ...currentConfigs.lookup_search,
                                                    collection_id: val === "_all" ? "" : val,
                                                  },
                                                },
                                                { shouldDirty: true }
                                              );
                                            }}
                                          >
                                            <SelectTrigger className="h-8">
                                              <SelectValue placeholder="Search all collections" />
                                            </SelectTrigger>
                                            <SelectContent>
                                              <SelectItem value="_all">
                                                Search all collections
                                              </SelectItem>
                                              {lookupCollections.map((col) => (
                                                <SelectItem key={col.id} value={col.id}>
                                                  {col.name}
                                                </SelectItem>
                                              ))}
                                            </SelectContent>
                                          </Select>
                                          <p className="text-xs text-muted-foreground">
                                            Leave blank to search across all collections in the
                                            workspace.
                                          </p>
                                        </div>
                                      </div>
                                    )}

                                    {/* Site Search Configuration */}
                                    {integration.id === "site_search" && (
                                      <div className="mt-4 space-y-3 rounded-lg border bg-background p-4">
                                        <h4 className="text-sm font-medium">
                                          Site Search Configuration
                                        </h4>
                                        <p className="text-xs text-muted-foreground">
                                          Configure the website your agent can search during calls.
                                        </p>

                                        <div className="space-y-1.5">
                                          <label className="text-xs font-medium">Website URL</label>
                                          <Input
                                            type="url"
                                            placeholder="https://www.example.com"
                                            className="h-8"
                                            value={
                                              form.watch("toolConfigs.site_search.site_url") || ""
                                            }
                                            onChange={(e) => {
                                              const currentConfigs =
                                                form.getValues("toolConfigs") || {};
                                              form.setValue(
                                                "toolConfigs",
                                                {
                                                  ...currentConfigs,
                                                  site_search: {
                                                    ...currentConfigs.site_search,
                                                    site_url: e.target.value,
                                                  },
                                                },
                                                { shouldDirty: true }
                                              );
                                            }}
                                          />
                                          <p className="text-xs text-muted-foreground">
                                            The website to crawl and search during calls.
                                          </p>
                                        </div>

                                        <div className="space-y-1.5">
                                          <label className="text-xs font-medium">
                                            Site Description (Optional)
                                          </label>
                                          <Input
                                            type="text"
                                            placeholder="Apartment listings, product catalog..."
                                            className="h-8"
                                            value={
                                              form.watch(
                                                "toolConfigs.site_search.site_description"
                                              ) || ""
                                            }
                                            onChange={(e) => {
                                              const currentConfigs =
                                                form.getValues("toolConfigs") || {};
                                              form.setValue(
                                                "toolConfigs",
                                                {
                                                  ...currentConfigs,
                                                  site_search: {
                                                    ...currentConfigs.site_search,
                                                    site_description: e.target.value,
                                                  },
                                                },
                                                { shouldDirty: true }
                                              );
                                            }}
                                          />
                                          <p className="text-xs text-muted-foreground">
                                            Describe what this site contains to help the AI search
                                            more effectively.
                                          </p>
                                        </div>

                                        <div className="space-y-1.5">
                                          <label className="text-xs font-medium">
                                            Crawl Schedule
                                          </label>
                                          <Select
                                            value={
                                              form
                                                .watch(
                                                  "toolConfigs.site_search.crawl_schedule_hours"
                                                )
                                                ?.toString() || "0"
                                            }
                                            onValueChange={(val) => {
                                              const currentConfigs =
                                                form.getValues("toolConfigs") || {};
                                              form.setValue(
                                                "toolConfigs",
                                                {
                                                  ...currentConfigs,
                                                  site_search: {
                                                    ...currentConfigs.site_search,
                                                    crawl_schedule_hours: val,
                                                  },
                                                },
                                                { shouldDirty: true }
                                              );
                                            }}
                                          >
                                            <SelectTrigger className="h-8">
                                              <SelectValue />
                                            </SelectTrigger>
                                            <SelectContent>
                                              <SelectItem value="0">Manual only</SelectItem>
                                              <SelectItem value="6">Every 6 hours</SelectItem>
                                              <SelectItem value="12">Every 12 hours</SelectItem>
                                              <SelectItem value="24">Every 24 hours</SelectItem>
                                              <SelectItem value="48">Every 2 days</SelectItem>
                                              <SelectItem value="168">Weekly</SelectItem>
                                            </SelectContent>
                                          </Select>
                                          <p className="text-xs text-muted-foreground">
                                            Automatically re-crawl the site on a schedule to keep
                                            the knowledge base up-to-date.
                                          </p>
                                        </div>
                                      </div>
                                    )}
                                  </div>
                                </CollapsibleContent>
                              )}
                            </div>
                          </Collapsible>
                        );
                      }}
                    />
                  ))}

                  <div className="rounded-lg border border-dashed p-4">
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="text-sm font-medium">Need more integrations?</p>
                        <p className="text-xs text-muted-foreground">
                          Connect Google Calendar, Salesforce, HubSpot and more
                        </p>
                      </div>
                      <Button type="button" variant="outline" size="sm" asChild>
                        <Link href="/dashboard/integrations">Manage Integrations</Link>
                      </Button>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="advanced" className="mt-4 space-y-3">
              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm font-medium">Telephony Settings</CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  <FormField
                    control={form.control}
                    name="telephonyProvider"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Telephony Provider</FormLabel>
                        <Select onValueChange={field.onChange} value={field.value}>
                          <FormControl>
                            <SelectTrigger>
                              <SelectValue />
                            </SelectTrigger>
                          </FormControl>
                          <SelectContent>
                            <SelectItem value="telnyx">Telnyx (Recommended)</SelectItem>
                            <SelectItem value="twilio">Twilio</SelectItem>
                          </SelectContent>
                        </Select>
                        <FormMessage />
                      </FormItem>
                    )}
                  />

                  <FormField
                    control={form.control}
                    name="phoneNumberId"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Phone Number for Inbound Calls</FormLabel>
                        {selectedWorkspaces.length === 0 ? (
                          <div className="rounded-lg border border-dashed p-4">
                            <p className="text-sm text-muted-foreground">
                              Please select a workspace in the Basic tab first to see available
                              phone numbers.
                            </p>
                          </div>
                        ) : phoneNumbers.length === 0 && !isLoadingPhoneNumbers ? (
                          <div className="rounded-lg border border-dashed p-4">
                            <div className="flex items-center justify-between">
                              <div className="space-y-1">
                                <p className="text-sm font-medium">No phone numbers available</p>
                                <p className="text-xs text-muted-foreground">
                                  Purchase a phone number to enable inbound calls
                                </p>
                              </div>
                            </div>
                            <div className="mt-3">
                              <Button type="button" variant="outline" size="sm" asChild>
                                <Link href="/dashboard/phone-numbers">Purchase Phone Numbers</Link>
                              </Button>
                            </div>
                          </div>
                        ) : (
                          <>
                            <Select
                              onValueChange={field.onChange}
                              value={field.value ?? "none"}
                              disabled={isLoadingPhoneNumbers}
                            >
                              <FormControl>
                                <SelectTrigger>
                                  <SelectValue placeholder="Select a phone number" />
                                </SelectTrigger>
                              </FormControl>
                              <SelectContent>
                                <SelectItem value="none">
                                  No phone number (inbound disabled)
                                </SelectItem>
                                {phoneNumbers.map((pn) => (
                                  <SelectItem key={pn.id} value={pn.phone_number}>
                                    {pn.phone_number}
                                    {pn.friendly_name && ` (${pn.friendly_name})`}
                                    {pn.assigned_agent_id &&
                                      pn.assigned_agent_id !== agentId &&
                                      " - In use by another agent"}
                                  </SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                            <div className="mt-2 flex items-center justify-between">
                              <FormDescription>
                                Assign a phone number for this agent to receive inbound calls
                              </FormDescription>
                              <Button
                                type="button"
                                variant="link"
                                size="sm"
                                className="h-auto p-0"
                                asChild
                              >
                                <Link href="/dashboard/phone-numbers">Manage Numbers</Link>
                              </Button>
                            </div>
                          </>
                        )}
                        <FormMessage />
                      </FormItem>
                    )}
                  />

                  {/* Webhook Configuration */}
                  {currentPhoneNumberId &&
                    currentPhoneNumberId !== "none" &&
                    webhookInfo?.voice_url && (
                      <div className="space-y-3 rounded-lg border p-3">
                        <div className="flex items-center gap-2">
                          <PhoneIncoming className="h-4 w-4 text-muted-foreground" />
                          <p className="text-sm font-medium">Inbound Webhook</p>
                        </div>
                        <div className="space-y-1.5">
                          <p className="text-xs text-muted-foreground">
                            Set this URL as the Voice URL in your {telephonyProvider} console:
                          </p>
                          <div className="flex items-center gap-2 rounded-md bg-muted px-3 py-2">
                            <code className="flex-1 truncate text-xs">{webhookInfo.voice_url}</code>
                            <Button
                              type="button"
                              size="icon"
                              variant="ghost"
                              className="h-6 w-6 shrink-0"
                              onClick={() => handleWebhookCopy(webhookInfo.voice_url ?? "")}
                            >
                              {webhookCopied ? (
                                <Check className="h-3 w-3 text-green-500" />
                              ) : (
                                <Copy className="h-3 w-3" />
                              )}
                            </Button>
                          </div>
                        </div>
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          className="w-full"
                          onClick={() => configureWebhookMutation.mutate()}
                          disabled={configureWebhookMutation.isPending || webhookConfigured}
                        >
                          {configureWebhookMutation.isPending ? (
                            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                          ) : webhookConfigured ? (
                            <Check className="mr-2 h-4 w-4 text-green-500" />
                          ) : (
                            <Settings2 className="mr-2 h-4 w-4" />
                          )}
                          {webhookConfigured ? "Webhook Configured" : "Auto-Configure Webhook"}
                        </Button>
                      </div>
                    )}

                  <Separator />

                  <FormField
                    control={form.control}
                    name="enableRecording"
                    render={({ field }) => (
                      <FormItem className="flex flex-row items-center justify-between rounded-lg border p-4">
                        <div className="space-y-0.5">
                          <FormLabel className="text-base">Enable Call Recording</FormLabel>
                          <FormDescription>Record all calls for quality assurance</FormDescription>
                        </div>
                        <FormControl>
                          <Switch checked={field.value} onCheckedChange={field.onChange} />
                        </FormControl>
                      </FormItem>
                    )}
                  />

                  <FormField
                    control={form.control}
                    name="enableTranscript"
                    render={({ field }) => (
                      <FormItem className="flex flex-row items-center justify-between rounded-lg border p-4">
                        <div className="space-y-0.5">
                          <FormLabel className="text-base">Enable Transcripts</FormLabel>
                          <FormDescription>Save conversation transcripts</FormDescription>
                        </div>
                        <FormControl>
                          <Switch checked={field.value} onCheckedChange={field.onChange} />
                        </FormControl>
                      </FormItem>
                    )}
                  />

                  {(agent?.pricing_tier === "premium" ||
                    agent?.pricing_tier === "premium-mini") && (
                    <FormField
                      control={form.control}
                      name="transcriptionModel"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel className="flex items-center gap-1.5">
                            Transcription Model
                          </FormLabel>
                          <FormDescription>
                            Model used to transcribe speech to text during calls
                          </FormDescription>
                          <Select onValueChange={field.onChange} value={field.value}>
                            <FormControl>
                              <SelectTrigger>
                                <SelectValue />
                              </SelectTrigger>
                            </FormControl>
                            <SelectContent>
                              <SelectItem value="gpt-4o-transcribe">
                                GPT-4o Transcribe — Most consistent (default)
                              </SelectItem>
                              <SelectItem value="whisper-1">
                                Whisper — Fast &amp; accurate
                              </SelectItem>
                              <SelectItem value="gpt-4o-mini-transcribe">
                                GPT-4o Mini Transcribe — Cost-effective
                              </SelectItem>
                            </SelectContent>
                          </Select>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  )}

                  <FormField
                    control={form.control}
                    name="turnDetectionMode"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel className="flex items-center gap-1.5">
                          Turn Detection
                          <InfoTooltip content="How the agent knows when the caller finished speaking. Normal uses Voice Activity Detection. Semantic VAD understands speech context — better for noisy environments. Disabled requires explicit Push to Talk signals." />
                        </FormLabel>
                        <Select onValueChange={field.onChange} value={field.value}>
                          <FormControl>
                            <SelectTrigger>
                              <SelectValue />
                            </SelectTrigger>
                          </FormControl>
                          <SelectContent>
                            <SelectItem value="normal">Normal (Server VAD)</SelectItem>
                            <SelectItem value="semantic">
                              Semantic VAD (Better for noisy environments)
                            </SelectItem>
                            <SelectItem value="disabled">Disabled (Push to Talk)</SelectItem>
                          </SelectContent>
                        </Select>
                        <FormDescription>
                          How the agent detects when the user has finished speaking
                        </FormDescription>
                        <FormMessage />
                      </FormItem>
                    )}
                  />

                  {turnDetectionMode === "normal" && (
                    <FormField
                      control={form.control}
                      name="turnDetectionThreshold"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel className="flex items-center justify-between gap-1.5">
                            <span className="flex items-center gap-1.5">
                              Noise Sensitivity
                              <InfoTooltip content="How sensitive the VAD is to audio input. Higher values require louder speech to trigger, reducing false positives from background noise." />
                            </span>
                            <span className="font-normal text-muted-foreground">
                              {field.value.toFixed(2)}
                            </span>
                          </FormLabel>
                          <FormControl>
                            <Slider
                              min={0}
                              max={1}
                              step={0.05}
                              value={[field.value]}
                              onValueChange={([v]) => field.onChange(v)}
                            />
                          </FormControl>
                          <FormDescription>
                            Higher values reduce false triggers from background noise (default: 0.7)
                          </FormDescription>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  )}

                  {(turnDetectionMode === "normal" || turnDetectionMode === "semantic") && (
                    <FormField
                      control={form.control}
                      name="turnDetectionSilenceDurationMs"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel className="flex items-center justify-between gap-1.5">
                            <span className="flex items-center gap-1.5">
                              End of Speech Detection
                              <InfoTooltip content="How long the agent waits after speech stops before responding. Longer values give callers more time to pause between sentences." />
                            </span>
                            <span className="font-normal text-muted-foreground">
                              {field.value}ms
                            </span>
                          </FormLabel>
                          <FormControl>
                            <Slider
                              min={100}
                              max={2000}
                              step={100}
                              value={[field.value]}
                              onValueChange={([v]) => field.onChange(v)}
                            />
                          </FormControl>
                          <FormDescription>
                            How long the agent waits after speech stops before responding (default:
                            700ms)
                          </FormDescription>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  )}
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm font-medium">Widget Settings</CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  <FormField
                    control={form.control}
                    name="widgetButtonText"
                    render={({ field }) => {
                      const charCount = field.value?.length ?? 0;
                      const isOverLimit = charCount > 20;
                      return (
                        <FormItem>
                          <div className="flex items-center justify-between">
                            <FormLabel>Button Text</FormLabel>
                            <span
                              className={cn(
                                "text-xs",
                                isOverLimit ? "text-destructive" : "text-muted-foreground"
                              )}
                            >
                              {charCount}/20 characters
                            </span>
                          </div>
                          <FormControl>
                            <Input placeholder="Talk to us" maxLength={20} {...field} />
                          </FormControl>
                          <FormDescription>
                            Text displayed on the widget button (max 20 characters)
                          </FormDescription>
                          <FormMessage />
                        </FormItem>
                      );
                    }}
                  />
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm font-medium">Statistics</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                    <div className="rounded-md border p-3">
                      <p className="text-xs text-muted-foreground">Total Calls</p>
                      <p className="text-lg font-semibold">{agent.total_calls}</p>
                    </div>
                    <div className="rounded-md border p-3">
                      <p className="text-xs text-muted-foreground">Total Duration</p>
                      <p className="text-lg font-semibold">
                        {Math.round(agent.total_duration_seconds / 60)}m
                      </p>
                    </div>
                    <div className="rounded-md border p-3">
                      <p className="text-xs text-muted-foreground">Created</p>
                      <p className="text-sm font-medium">
                        {new Date(agent.created_at).toLocaleDateString()}
                      </p>
                    </div>
                    <div className="rounded-md border p-3">
                      <p className="text-xs text-muted-foreground">Last Call</p>
                      <p className="text-sm font-medium">
                        {agent.last_call_at
                          ? new Date(agent.last_call_at).toLocaleDateString()
                          : "Never"}
                      </p>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </TabsContent>

            {hasKnowledgeBase && (
              <TabsContent value="knowledge-base" className="mt-4">
                <KnowledgeBaseTab
                  agentId={agentId}
                  siteUrl={form.watch("toolConfigs.site_search.site_url") || ""}
                  lastCrawlAt={form.watch("toolConfigs.site_search.last_crawl_at") || ""}
                  crawlScheduleHours={
                    Number(form.watch("toolConfigs.site_search.crawl_schedule_hours")) || 0
                  }
                />
              </TabsContent>
            )}
            <TabsContent value="workflow" className="mt-4">
              <WorkflowTab agentId={agentId} workspaceId={selectedWorkspaces[0] ?? ""} />
            </TabsContent>
          </Tabs>

          <div className="flex justify-end gap-3">
            <Button
              type="button"
              variant="outline"
              size="sm"
              asChild
              disabled={updateAgentMutation.isPending}
            >
              <Link href="/dashboard/agents">Cancel</Link>
            </Button>
            <Button type="submit" size="sm" disabled={updateAgentMutation.isPending}>
              {updateAgentMutation.isPending ? "Saving..." : "Save Changes"}
            </Button>
          </div>
        </form>
      </Form>
    </div>
  );
}
