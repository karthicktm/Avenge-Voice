"use client";

import { useState, useEffect } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  PhoneIncoming,
  Settings2,
  Copy,
  Check,
  Loader2,
  Phone,
  PhoneCall,
  ExternalLink,
} from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  listPhoneNumbers,
  getWebhookInfo,
  configurePhoneNumberWebhook,
  type Provider,
} from "@/lib/api/telephony";
import type { Agent } from "@/lib/api/agents";
import { api } from "@/lib/api";

interface AgentWorkspace {
  workspace_id: string;
  workspace_name: string;
}

interface GetCallDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  agent: Agent;
  workspaceId?: string;
}

export function GetCallDialog({ open, onOpenChange, agent, workspaceId }: GetCallDialogProps) {
  const [copied, setCopied] = useState(false);
  const [webhookConfigured, setWebhookConfigured] = useState(false);

  // Fetch agent's workspaces if workspaceId not provided
  const { data: agentWorkspaces = [] } = useQuery<AgentWorkspace[]>({
    queryKey: ["agent-workspaces", agent.id],
    queryFn: async () => {
      const response = await api.get<AgentWorkspace[]>(`/api/v1/workspaces/agent/${agent.id}`);
      return response.data;
    },
    enabled: open && !workspaceId,
  });

  const effectiveWorkspaceId = workspaceId ?? agentWorkspaces[0]?.workspace_id;

  // Fetch phone numbers from both providers to find the assigned one
  const { data: twilioNumbers = [] } = useQuery({
    queryKey: ["phone-numbers", "twilio", effectiveWorkspaceId],
    queryFn: () =>
      effectiveWorkspaceId ? listPhoneNumbers("twilio", effectiveWorkspaceId) : Promise.resolve([]),
    enabled: open && !!effectiveWorkspaceId && !!agent.phone_number_id,
  });

  const { data: telnyxNumbers = [] } = useQuery({
    queryKey: ["phone-numbers", "telnyx", effectiveWorkspaceId],
    queryFn: () =>
      effectiveWorkspaceId ? listPhoneNumbers("telnyx", effectiveWorkspaceId) : Promise.resolve([]),
    enabled: open && !!effectiveWorkspaceId && !!agent.phone_number_id,
  });

  // Find the assigned phone number and detect provider
  const allNumbers = [...twilioNumbers, ...telnyxNumbers];
  const assignedNumber = allNumbers.find((n) => n.id === agent.phone_number_id);
  const provider: Provider = twilioNumbers.find((n) => n.id === agent.phone_number_id)
    ? "twilio"
    : "telnyx";

  // Fetch webhook info from the backend
  const { data: webhookInfo } = useQuery({
    queryKey: ["webhook-info", provider, effectiveWorkspaceId],
    queryFn: () =>
      effectiveWorkspaceId ? getWebhookInfo(provider, effectiveWorkspaceId) : Promise.resolve(null),
    enabled: open && !!effectiveWorkspaceId && !!agent.phone_number_id,
  });

  const configureMutation = useMutation({
    mutationFn: () => {
      if (!agent.phone_number_id || !effectiveWorkspaceId) {
        throw new Error("No phone number or workspace available");
      }
      return configurePhoneNumberWebhook(agent.phone_number_id, provider, effectiveWorkspaceId);
    },
    onSuccess: () => {
      setWebhookConfigured(true);
      toast.success("Webhook configured successfully");
    },
    onError: (error: Error) => {
      toast.error(`Failed to configure webhook: ${error.message}`);
    },
  });

  const handleCopy = (text: string) => {
    void navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  // Reset state when dialog closes
  useEffect(() => {
    if (!open) {
      setWebhookConfigured(false);
      setCopied(false);
    }
  }, [open]);

  const displayNumber = assignedNumber?.phone_number ?? agent.phone_number_id;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <PhoneIncoming className="h-5 w-5" />
            Receive Inbound Calls
          </DialogTitle>
          <DialogDescription>
            Configure inbound call handling for agent &quot;{agent.name}&quot;
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          {!agent.phone_number_id ? (
            <div className="rounded-lg border border-dashed p-6 text-center">
              <Phone className="mx-auto mb-3 h-10 w-10 text-muted-foreground" />
              <p className="text-sm font-medium">No phone number assigned</p>
              <p className="mt-1 text-xs text-muted-foreground">
                Assign a phone number in the agent&apos;s Advanced settings to enable inbound calls.
              </p>
            </div>
          ) : (
            <>
              {/* Assigned phone number */}
              <div className="rounded-lg border p-3">
                <p className="text-xs font-medium text-muted-foreground">Assigned Phone Number</p>
                <div className="mt-1 flex items-center justify-between">
                  <span className="text-base font-semibold">{displayNumber}</span>
                  <Badge variant="outline" className="capitalize">
                    {provider}
                  </Badge>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  Callers dial this number to reach the voice agent
                </p>
              </div>

              {/* Webhook URL */}
              {webhookInfo?.voice_url && (
                <div className="space-y-1.5">
                  <p className="text-xs font-medium">
                    Voice Webhook URL{" "}
                    <span className="font-normal text-muted-foreground">
                      (set this in your {provider} console)
                    </span>
                  </p>
                  <div className="flex items-center gap-2 rounded-md bg-muted px-3 py-2">
                    <code className="flex-1 truncate text-xs">{webhookInfo.voice_url}</code>
                    <Button
                      size="icon"
                      variant="ghost"
                      className="h-6 w-6 shrink-0"
                      onClick={() => handleCopy(webhookInfo.voice_url ?? "")}
                    >
                      {copied ? (
                        <Check className="h-3 w-3 text-green-500" />
                      ) : (
                        <Copy className="h-3 w-3" />
                      )}
                    </Button>
                  </div>
                </div>
              )}

              {/* Auto-configure section */}
              <div className="space-y-3 rounded-lg border p-3">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <p className="text-sm font-medium">Auto-Configure Webhook</p>
                    <p className="text-xs text-muted-foreground">
                      Automatically set the webhook on your {provider} number
                    </p>
                  </div>
                  {webhookConfigured && (
                    <Badge className="shrink-0 bg-green-500">
                      <Check className="mr-1 h-3 w-3" />
                      Configured
                    </Badge>
                  )}
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => configureMutation.mutate()}
                  disabled={configureMutation.isPending || webhookConfigured}
                  className="w-full"
                >
                  {configureMutation.isPending ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <Settings2 className="mr-2 h-4 w-4" />
                  )}
                  {webhookConfigured ? "Webhook Configured" : "Configure Webhook Now"}
                </Button>
              </div>

              {/* Twilio console link */}
              {provider === "twilio" && (
                <div className="flex items-center justify-between rounded-md bg-muted/50 px-3 py-2">
                  <p className="text-xs text-muted-foreground">Configure manually in Twilio</p>
                  <Button size="sm" variant="ghost" className="h-7 gap-1 text-xs" asChild>
                    <a
                      href="https://console.twilio.com/us1/develop/phone-numbers/manage/incoming"
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      Open Console
                      <ExternalLink className="h-3 w-3" />
                    </a>
                  </Button>
                </div>
              )}

              {/* Success state */}
              {webhookConfigured && (
                <div className="rounded-lg border border-green-200 bg-green-50 p-3 dark:border-green-800 dark:bg-green-950">
                  <div className="flex items-center gap-2">
                    <PhoneCall className="h-4 w-4 text-green-600 dark:text-green-400" />
                    <p className="text-sm font-medium text-green-700 dark:text-green-300">
                      Ready to Receive Calls!
                    </p>
                  </div>
                  <p className="mt-1 text-xs text-green-600 dark:text-green-400">
                    Call <span className="font-mono font-semibold">{displayNumber}</span> to test
                    the agent.
                  </p>
                </div>
              )}
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
