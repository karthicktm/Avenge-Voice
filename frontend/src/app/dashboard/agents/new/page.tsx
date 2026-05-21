"use client";

import { useMemo, useEffect } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm, useWatch } from "react-hook-form";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import * as z from "zod";
import Link from "next/link";
import { createAgent, type CreateAgentRequest } from "@/lib/api/agents";
import { AVAILABLE_INTEGRATIONS } from "@/lib/integrations";
import { getLanguagesForTier, getFallbackLanguage } from "@/lib/languages";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
import { Checkbox } from "@/components/ui/checkbox";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { ChevronDown, AlertTriangle, Shield, ShieldAlert } from "lucide-react";

const agentFormSchema = z.object({
  name: z.string().min(2, "Name must be at least 2 characters"),
  description: z.string().optional(),
  language: z.string().min(1, "Please select a language"),

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
  turnDetectionMode: z.enum(["server-vad", "pushToTalk"]).default("server-vad"),

  // Tools & Integrations
  enabledTools: z.array(z.string()).default([]),
  enabledToolIds: z.record(z.string(), z.array(z.string())).default({}),
});

type AgentFormValues = z.infer<typeof agentFormSchema>;

// Get integrations that have tools defined
const INTEGRATIONS_WITH_TOOLS = AVAILABLE_INTEGRATIONS.filter((i) => i.tools && i.tools.length > 0);

// Helper to get risk level badge color and icon
function getRiskLevelBadge(level: "safe" | "moderate" | "high") {
  switch (level) {
    case "safe":
      return {
        variant: "secondary" as const,
        icon: Shield,
        className: "text-green-600 border-green-200 bg-green-50",
      };
    case "moderate":
      return {
        variant: "secondary" as const,
        icon: AlertTriangle,
        className: "text-yellow-600 border-yellow-200 bg-yellow-50",
      };
    case "high":
      return {
        variant: "secondary" as const,
        icon: ShieldAlert,
        className: "text-red-600 border-red-200 bg-red-50",
      };
  }
}

const defaultValues: Partial<AgentFormValues> = {
  language: "en-US",
  ttsProvider: "elevenlabs",
  elevenLabsModel: "turbo-v2.5",
  ttsSpeed: 1,
  sttProvider: "deepgram",
  deepgramModel: "nova-3",
  llmProvider: "openai-realtime",
  llmModel: "gpt-realtime",
  temperature: 0.7,
  maxTokens: 2000,
  telephonyProvider: "telnyx",
  enableRecording: true,
  enableTranscript: true,
  turnDetectionMode: "server-vad",
  enabledTools: [],
  enabledToolIds: {},
};

export default function NewAgentPage() {
  const router = useRouter();
  const queryClient = useQueryClient();

  const form = useForm<AgentFormValues>({
    resolver: zodResolver(agentFormSchema),
    defaultValues,
  });

  // Watch llmProvider and llmModel to derive pricing tier for language filtering
  const llmProvider = useWatch({ control: form.control, name: "llmProvider" });
  const llmModel = useWatch({ control: form.control, name: "llmModel" });
  const currentLanguage = useWatch({ control: form.control, name: "language" });

  // Derive pricing tier from LLM provider selection
  const derivedTier = useMemo((): "budget" | "balanced" | "premium" => {
    if (llmProvider === "openai-realtime") return "premium";
    if (llmModel === "gpt-4o-mini" || llmModel === "claude-haiku-4-5") return "budget";
    return "balanced";
  }, [llmProvider, llmModel]);

  // Get available languages for the derived tier
  const availableLanguages = useMemo(() => getLanguagesForTier(derivedTier), [derivedTier]);

  // Reset language to fallback if current selection is not valid for new tier
  useEffect(() => {
    const fallback = getFallbackLanguage(currentLanguage, derivedTier);
    if (fallback !== currentLanguage) {
      form.setValue("language", fallback);
    }
  }, [derivedTier, currentLanguage, form]);

  const createAgentMutation = useMutation({
    mutationFn: createAgent,
    onSuccess: () => {
      toast.success("Agent created successfully");
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
      router.push("/dashboard/agents");
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to create agent");
    },
  });

  function onSubmit(data: AgentFormValues) {
    // Map form data to API request format
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

    const request: CreateAgentRequest = {
      name: data.name,
      description: data.description,
      pricing_tier: pricingTier,
      system_prompt: data.systemPrompt,
      language: data.language,
      enabled_tools: enabledIntegrations,
      enabled_tool_ids: data.enabledToolIds,
      phone_number_id: data.phoneNumberId,
      enable_recording: data.enableRecording,
      enable_transcript: data.enableTranscript,
      initial_greeting: data.initialGreeting?.trim() ? data.initialGreeting.trim() : undefined,
    };

    createAgentMutation.mutate(request);
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Create Voice Agent</h1>
        <p className="text-sm text-muted-foreground">
          Configure your AI voice agent for inbound and outbound calls
        </p>
      </div>

      <Form {...form}>
        <form
          onSubmit={(e) => {
            void form.handleSubmit(onSubmit)(e);
          }}
          className="space-y-6"
        >
          <Tabs defaultValue="basic" className="w-full">
            <TabsList className="grid w-full grid-cols-5">
              <TabsTrigger value="basic">Basic</TabsTrigger>
              <TabsTrigger value="voice">Voice & Speech</TabsTrigger>
              <TabsTrigger value="llm">AI Model</TabsTrigger>
              <TabsTrigger value="tools">Tools</TabsTrigger>
              <TabsTrigger value="advanced">Advanced</TabsTrigger>
            </TabsList>

            <TabsContent value="basic" className="mt-6 space-y-4">
              <Card>
                <CardHeader>
                  <CardTitle>Basic Information</CardTitle>
                  <CardDescription>General settings for your voice agent</CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <FormField
                    control={form.control}
                    name="name"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Agent Name</FormLabel>
                        <FormControl>
                          <Input placeholder="Customer Support Agent" {...field} />
                        </FormControl>
                        <FormDescription>A friendly name to identify this agent</FormDescription>
                        <FormMessage />
                      </FormItem>
                    )}
                  />

                  <FormField
                    control={form.control}
                    name="description"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Description</FormLabel>
                        <FormControl>
                          <Textarea
                            placeholder="Handles customer inquiries and support"
                            {...field}
                          />
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
                        <Select onValueChange={field.onChange} value={field.value}>
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
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="voice" className="mt-6 space-y-4">
              <Card>
                <CardHeader>
                  <CardTitle>Text-to-Speech (TTS)</CardTitle>
                  <CardDescription>Configure how your agent speaks</CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <FormField
                    control={form.control}
                    name="ttsProvider"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>TTS Provider</FormLabel>
                        <Select onValueChange={field.onChange} defaultValue={field.value}>
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
                        <Select onValueChange={field.onChange} defaultValue={field.value}>
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
                        <Select onValueChange={field.onChange}>
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
                <CardHeader>
                  <CardTitle>Speech-to-Text (STT)</CardTitle>
                  <CardDescription>Configure how your agent listens</CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <FormField
                    control={form.control}
                    name="sttProvider"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>STT Provider</FormLabel>
                        <Select onValueChange={field.onChange} defaultValue={field.value}>
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
                        <Select onValueChange={field.onChange} defaultValue={field.value}>
                          <FormControl>
                            <SelectTrigger>
                              <SelectValue />
                            </SelectTrigger>
                          </FormControl>
                          <SelectContent>
                            <SelectItem value="nova-3">Nova-3 (Latest - 54% better WER)</SelectItem>
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

            <TabsContent value="llm" className="mt-6 space-y-4">
              <Card>
                <CardHeader>
                  <CardTitle>Language Model Configuration</CardTitle>
                  <CardDescription>Configure the AI brain of your voice agent</CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <FormField
                    control={form.control}
                    name="llmProvider"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>LLM Provider</FormLabel>
                        <Select onValueChange={field.onChange} defaultValue={field.value}>
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
                        <FormDescription>
                          Realtime API: End-to-end speech, SIP support, production-ready
                        </FormDescription>
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
                        <Select onValueChange={field.onChange} defaultValue={field.value}>
                          <FormControl>
                            <SelectTrigger>
                              <SelectValue />
                            </SelectTrigger>
                          </FormControl>
                          <SelectContent>
                            <SelectItem value="gpt-realtime">
                              gpt-realtime (GA - Best for Voice)
                            </SelectItem>
                            <SelectItem value="gpt-4o">
                              GPT-4o (Multimodal - 232ms latency)
                            </SelectItem>
                            <SelectItem value="gpt-4o-mini">
                              GPT-4o-mini (25x cheaper, fast)
                            </SelectItem>
                            <SelectItem value="claude-sonnet-4-5">
                              Claude Sonnet 4.5 (Sep 2025 - Best coding/agents)
                            </SelectItem>
                            <SelectItem value="claude-opus-4-1">
                              Claude Opus 4.1 (Aug 2025 - Most capable)
                            </SelectItem>
                            <SelectItem value="claude-haiku-4-5">
                              Claude Haiku 4.5 (Oct 2025 - Fast & cheap)
                            </SelectItem>
                            <SelectItem value="gemini-2.5-flash">
                              Gemini 2.5 Flash (Multimodal voice)
                            </SelectItem>
                          </SelectContent>
                        </Select>
                        <FormDescription>
                          gpt-realtime: Voice | Claude Sonnet 4.5: Agents/Coding | Haiku 4.5: Budget
                        </FormDescription>
                        <FormMessage />
                      </FormItem>
                    )}
                  />

                  <FormField
                    control={form.control}
                    name="systemPrompt"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>System Prompt</FormLabel>
                        <FormControl>
                          <Textarea
                            placeholder="You are a helpful customer support agent. Be polite, professional, and concise..."
                            className="min-h-[120px]"
                            {...field}
                          />
                        </FormControl>
                        <FormDescription>
                          Instructions that define your agent&apos;s personality and behavior
                        </FormDescription>
                        <FormMessage />
                      </FormItem>
                    )}
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
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Temperature</FormLabel>
                          <FormControl>
                            <Input
                              type="number"
                              step="0.1"
                              min="0"
                              max="2"
                              {...field}
                              onChange={(e) => field.onChange(parseFloat(e.target.value))}
                            />
                          </FormControl>
                          <FormDescription>0 = focused, 2 = creative</FormDescription>
                          <FormMessage />
                        </FormItem>
                      )}
                    />

                    <FormField
                      control={form.control}
                      name="maxTokens"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Max Tokens</FormLabel>
                          <FormControl>
                            <Input
                              type="number"
                              step="100"
                              min="100"
                              max="4000"
                              {...field}
                              onChange={(e) => field.onChange(parseInt(e.target.value))}
                            />
                          </FormControl>
                          <FormDescription>Response length limit</FormDescription>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  </div>
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="tools" className="mt-6 space-y-4">
              <Card>
                <CardHeader>
                  <CardTitle>Integrations & Tools</CardTitle>
                  <CardDescription>
                    Select integrations and configure which tools each agent can access. Tools with
                    higher risk levels require explicit enabling.
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
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
                                  <FormControl>
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
                                              form.getValues("enabledToolIds") || {};
                                            form.setValue("enabledToolIds", {
                                              ...currentToolIds,
                                              [integration.id]: defaultTools,
                                            });
                                          }
                                        } else {
                                          field.onChange(
                                            current.filter((v) => v !== integration.id)
                                          );
                                          // Clear tool selection when integration is disabled
                                          const currentToolIds =
                                            form.getValues("enabledToolIds") || {};
                                          const { [integration.id]: _removed, ...rest } =
                                            currentToolIds;
                                          form.setValue("enabledToolIds", rest);
                                        }
                                      }}
                                    />
                                  </FormControl>
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
                                        {form.watch(`enabledToolIds.${integration.id}`)?.length ||
                                          0}{" "}
                                        / {integration.tools.length} tools
                                      </span>
                                    </Button>
                                  </CollapsibleTrigger>
                                )}
                              </div>

                              {isEnabled && integration.tools && integration.tools.length > 0 && (
                                <CollapsibleContent>
                                  <Separator />
                                  <div className="bg-muted/30 p-4">
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
                                              form.getValues("enabledToolIds") || {};
                                            form.setValue("enabledToolIds", {
                                              ...currentToolIds,
                                              [integration.id]: allToolIds,
                                            });
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
                                              form.getValues("enabledToolIds") || {};
                                            form.setValue("enabledToolIds", {
                                              ...currentToolIds,
                                              [integration.id]: [],
                                            });
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
                                        return (
                                          <FormField
                                            key={tool.id}
                                            control={form.control}
                                            name="enabledToolIds"
                                            render={({ field: toolField }) => {
                                              const currentTools =
                                                toolField.value?.[integration.id] ?? [];
                                              const isToolEnabled = currentTools.includes(tool.id);
                                              return (
                                                <div className="flex items-center justify-between rounded-md border bg-background p-3">
                                                  <div className="flex items-center space-x-3">
                                                    <Checkbox
                                                      checked={isToolEnabled}
                                                      onCheckedChange={(checked) => {
                                                        const newTools = checked
                                                          ? [...currentTools, tool.id]
                                                          : currentTools.filter(
                                                              (t) => t !== tool.id
                                                            );
                                                        toolField.onChange({
                                                          ...toolField.value,
                                                          [integration.id]: newTools,
                                                        });
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
                                                  <Badge
                                                    variant={riskBadge.variant}
                                                    className={riskBadge.className}
                                                  >
                                                    <RiskIcon className="mr-1 h-3 w-3" />
                                                    {tool.riskLevel}
                                                  </Badge>
                                                </div>
                                              );
                                            }}
                                          />
                                        );
                                      })}
                                    </div>
                                  </div>
                                </CollapsibleContent>
                              )}
                            </div>
                          </Collapsible>
                        );
                      }}
                    />
                  ))}
                  <div className="pt-4">
                    <Button type="button" variant="outline" size="sm" asChild>
                      <Link href="/dashboard/integrations">Manage Integrations</Link>
                    </Button>
                  </div>
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="advanced" className="mt-6 space-y-4">
              <Card>
                <CardHeader>
                  <CardTitle>Telephony Settings</CardTitle>
                  <CardDescription>Phone number and call settings</CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <FormField
                    control={form.control}
                    name="telephonyProvider"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Telephony Provider</FormLabel>
                        <Select onValueChange={field.onChange} defaultValue={field.value}>
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
                        <FormLabel>Phone Number</FormLabel>
                        <Select onValueChange={field.onChange}>
                          <FormControl>
                            <SelectTrigger>
                              <SelectValue placeholder="Select a phone number" />
                            </SelectTrigger>
                          </FormControl>
                          <SelectContent>
                            <SelectItem value="none">No phone number assigned</SelectItem>
                          </SelectContent>
                        </Select>
                        <FormDescription>Assign a phone number to this agent</FormDescription>
                        <FormMessage />
                      </FormItem>
                    )}
                  />

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

                  <FormField
                    control={form.control}
                    name="turnDetectionMode"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Turn Detection</FormLabel>
                        <Select onValueChange={field.onChange} defaultValue={field.value}>
                          <FormControl>
                            <SelectTrigger>
                              <SelectValue />
                            </SelectTrigger>
                          </FormControl>
                          <SelectContent>
                            <SelectItem value="server-vad">Server VAD (Recommended)</SelectItem>
                            <SelectItem value="pushToTalk">Push to Talk</SelectItem>
                          </SelectContent>
                        </Select>
                        <FormDescription>
                          How the agent detects when the user has finished speaking
                        </FormDescription>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </CardContent>
              </Card>
            </TabsContent>
          </Tabs>

          <div className="flex justify-end gap-4">
            <Button
              type="button"
              variant="outline"
              asChild
              disabled={createAgentMutation.isPending}
            >
              <Link href="/dashboard/agents">Cancel</Link>
            </Button>
            <Button type="submit" disabled={createAgentMutation.isPending}>
              {createAgentMutation.isPending ? "Creating..." : "Create Agent"}
            </Button>
          </div>
        </form>
      </Form>
    </div>
  );
}
