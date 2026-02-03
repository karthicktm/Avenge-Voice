"use client";

import { useState, useCallback, memo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  fetchSettings,
  updateSettings,
  type SettingsResponse,
  type UpdateSettingsRequest,
} from "@/lib/api/settings";
import { api } from "@/lib/api";
import { useAuth } from "@/hooks/use-auth";
import { RoleBadge } from "@/components/auth/role-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  FolderOpen,
  Check,
  Settings as SettingsIcon,
  Loader2,
  Trash2,
  Eye,
  EyeOff,
  ExternalLink,
  Brain,
  Mic,
  Volume2,
  Phone,
  User as UserIcon,
  Mail,
  Calendar,
  CheckCircle2,
  XCircle,
} from "lucide-react";

interface Workspace {
  id: string;
  name: string;
  description: string | null;
  is_default: boolean;
}

// Define API key providers with their configuration
interface ApiKeyProvider {
  id: string;
  name: string;
  description: string;
  category: "voice-ai" | "telephony";
  icon: React.ComponentType<{ className?: string }>;
  documentationUrl: string;
  fields: {
    name: keyof UpdateSettingsRequest;
    label: string;
    placeholder: string;
    settingsKey: keyof SettingsResponse;
  }[];
}

const API_KEY_PROVIDERS: ApiKeyProvider[] = [
  {
    id: "openai",
    name: "OpenAI",
    description:
      "Powers the AI brain of your voice agents with GPT-4o for language understanding and responses.",
    category: "voice-ai",
    icon: Brain,
    documentationUrl: "https://platform.openai.com/api-keys",
    fields: [
      {
        name: "openai_api_key",
        label: "API Key",
        placeholder: "sk-...",
        settingsKey: "openai_api_key_set",
      },
    ],
  },
  {
    id: "deepgram",
    name: "Deepgram",
    description: "Fast and accurate speech-to-text transcription for real-time voice recognition.",
    category: "voice-ai",
    icon: Mic,
    documentationUrl: "https://console.deepgram.com/",
    fields: [
      {
        name: "deepgram_api_key",
        label: "API Key",
        placeholder: "Enter your Deepgram API key",
        settingsKey: "deepgram_api_key_set",
      },
    ],
  },
  {
    id: "elevenlabs",
    name: "ElevenLabs",
    description: "Premium text-to-speech synthesis for natural-sounding voice output.",
    category: "voice-ai",
    icon: Volume2,
    documentationUrl: "https://elevenlabs.io/app/settings/api-keys",
    fields: [
      {
        name: "elevenlabs_api_key",
        label: "API Key",
        placeholder: "Enter your ElevenLabs API key",
        settingsKey: "elevenlabs_api_key_set",
      },
    ],
  },
  {
    id: "telnyx",
    name: "Telnyx",
    description: "Primary telephony provider for phone numbers and call routing.",
    category: "telephony",
    icon: Phone,
    documentationUrl: "https://portal.telnyx.com/#/app/api-keys",
    fields: [
      {
        name: "telnyx_api_key",
        label: "API Key",
        placeholder: "KEY...",
        settingsKey: "telnyx_api_key_set",
      },
    ],
  },
  {
    id: "twilio",
    name: "Twilio",
    description: "Alternative telephony provider for phone numbers and messaging.",
    category: "telephony",
    icon: Phone,
    documentationUrl: "https://console.twilio.com/",
    fields: [
      {
        name: "twilio_account_sid",
        label: "Account SID",
        placeholder: "AC...",
        settingsKey: "twilio_account_sid_set",
      },
      {
        name: "twilio_auth_token",
        label: "Auth Token",
        placeholder: "Enter your Auth Token",
        settingsKey: "twilio_account_sid_set", // Using same key since both are required
      },
    ],
  },
];

export default function SettingsPage() {
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState<string>("all");

  // Fetch workspaces
  const { data: workspaces = [] } = useQuery<Workspace[]>({
    queryKey: ["workspaces"],
    queryFn: async () => {
      const response = await api.get("/api/v1/workspaces");
      return response.data;
    },
  });

  // Fetch existing settings for selected workspace
  const { data: settings } = useQuery({
    queryKey: ["settings", selectedWorkspaceId],
    queryFn: () => fetchSettings(selectedWorkspaceId === "all" ? undefined : selectedWorkspaceId),
  });

  const voiceAiProviders = API_KEY_PROVIDERS.filter((p) => p.category === "voice-ai");
  const telephonyProviders = API_KEY_PROVIDERS.filter((p) => p.category === "telephony");

  const connectedCount = API_KEY_PROVIDERS.filter((provider) =>
    provider.fields.some((field) => settings?.[field.settingsKey])
  ).length;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Settings</h1>
          <p className="text-sm text-muted-foreground">
            Configure your platform settings and API keys
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Select
            value={selectedWorkspaceId}
            onValueChange={(value) => {
              setSelectedWorkspaceId(value);
              const wsName =
                value === "all" ? "All Workspaces" : workspaces.find((ws) => ws.id === value)?.name;
              toast.info(`Switched to ${wsName}`);
            }}
          >
            <SelectTrigger className="h-8 w-[220px] text-sm">
              <FolderOpen className="mr-2 h-3.5 w-3.5" />
              <SelectValue placeholder="All Workspaces" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Workspaces (Admin)</SelectItem>
              {workspaces.map((ws) => (
                <SelectItem key={ws.id} value={ws.id}>
                  {ws.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <Tabs defaultValue="api-keys" className="w-full">
        <div className="flex items-center justify-between">
          <TabsList>
            <TabsTrigger value="api-keys">API Keys</TabsTrigger>
            <TabsTrigger value="profile">Profile</TabsTrigger>
            <TabsTrigger value="billing">Billing</TabsTrigger>
          </TabsList>
          <div className="flex items-center gap-2">
            <Badge variant="secondary" className="font-normal">
              {connectedCount} Connected
            </Badge>
            <Badge variant="outline" className="font-normal">
              {API_KEY_PROVIDERS.length} Available
            </Badge>
          </div>
        </div>

        <TabsContent value="api-keys" className="mt-6 space-y-8">
          {/* Voice & AI Providers Section */}
          <div className="space-y-4">
            <div>
              <h2 className="text-lg font-medium">Voice & AI Providers</h2>
              <p className="text-sm text-muted-foreground">
                Configure speech recognition, text-to-speech, and language model providers
              </p>
            </div>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {voiceAiProviders.map((provider) => (
                <ApiKeyCard
                  key={provider.id}
                  provider={provider}
                  settings={settings}
                  selectedWorkspaceId={
                    selectedWorkspaceId === "all" ? undefined : selectedWorkspaceId
                  }
                />
              ))}
            </div>
          </div>

          {/* Telephony Providers Section */}
          <div className="space-y-4">
            <div>
              <h2 className="text-lg font-medium">Telephony Providers</h2>
              <p className="text-sm text-muted-foreground">
                Configure phone number and call routing providers
              </p>
            </div>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {telephonyProviders.map((provider) => (
                <ApiKeyCard
                  key={provider.id}
                  provider={provider}
                  settings={settings}
                  selectedWorkspaceId={
                    selectedWorkspaceId === "all" ? undefined : selectedWorkspaceId
                  }
                />
              ))}
            </div>
          </div>
        </TabsContent>

        <TabsContent value="profile" className="mt-6 space-y-4">
          <ProfileTab />
        </TabsContent>

        <TabsContent value="billing" className="mt-6 space-y-4">
          <Card>
            <CardContent className="flex flex-col items-center justify-center py-16">
              <SettingsIcon className="mb-4 h-16 w-16 text-muted-foreground/50" />
              <h3 className="mb-2 text-lg font-semibold">Billing & Usage</h3>
              <p className="text-sm text-muted-foreground">Coming soon...</p>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}

const ApiKeyCard = memo(function ApiKeyCard({
  provider,
  settings,
  selectedWorkspaceId,
}: {
  provider: ApiKeyProvider;
  settings?: SettingsResponse;
  selectedWorkspaceId?: string;
}) {
  const [isConfigDialogOpen, setIsConfigDialogOpen] = useState(false);
  const Icon = provider.icon;
  const isConnected = provider.fields.some((field) => settings?.[field.settingsKey]);

  return (
    <Card className="group transition-all hover:border-primary/50">
      <CardContent className="p-4">
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2.5 overflow-hidden">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-primary/10">
              <Icon className="h-4 w-4 text-primary" />
            </div>
            <div className="min-w-0">
              <h3 className="truncate text-sm font-medium">{provider.name}</h3>
              <p className="text-xs text-muted-foreground">
                {provider.category === "voice-ai" ? "Voice & AI" : "Telephony"}
              </p>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            {isConnected && <Check className="h-4 w-4 text-green-500" />}
          </div>
        </div>

        <p className="mt-2.5 line-clamp-2 min-h-[2lh] text-xs text-muted-foreground">
          {provider.description}
        </p>

        <div className="mt-3 flex gap-2 border-t border-border/50 pt-3">
          <Dialog open={isConfigDialogOpen} onOpenChange={setIsConfigDialogOpen}>
            <DialogTrigger asChild>
              <Button
                variant={isConnected ? "ghost" : "default"}
                size="sm"
                className="h-7 flex-1 text-xs"
              >
                {isConnected ? (
                  <>
                    <SettingsIcon className="mr-1 h-3 w-3" />
                    Configure
                  </>
                ) : (
                  "Connect"
                )}
              </Button>
            </DialogTrigger>
            <DialogContent className="max-w-md">
              <DialogHeader>
                <DialogTitle className="flex items-center gap-2">
                  <Icon className="h-5 w-5" />
                  {isConnected ? `Configure ${provider.name}` : `Connect ${provider.name}`}
                </DialogTitle>
                <DialogDescription>Enter your API credentials below</DialogDescription>
              </DialogHeader>
              <ApiKeyConfigForm
                provider={provider}
                isConnected={isConnected}
                selectedWorkspaceId={selectedWorkspaceId}
                onClose={() => setIsConfigDialogOpen(false)}
              />
            </DialogContent>
          </Dialog>
          <Button variant="ghost" size="sm" className="h-7 text-xs" asChild>
            <a href={provider.documentationUrl} target="_blank" rel="noopener noreferrer">
              <ExternalLink className="mr-1 h-3 w-3" />
              Docs
            </a>
          </Button>
        </div>
      </CardContent>
    </Card>
  );
});

const ApiKeyConfigForm = memo(function ApiKeyConfigForm({
  provider,
  isConnected,
  selectedWorkspaceId,
  onClose,
}: {
  provider: ApiKeyProvider;
  isConnected: boolean;
  selectedWorkspaceId?: string;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [credentials, setCredentials] = useState<Record<string, string>>({});
  const [showPasswords, setShowPasswords] = useState<Record<string, boolean>>({});
  const [showDisconnectDialog, setShowDisconnectDialog] = useState(false);

  const updateMutation = useMutation({
    mutationFn: async () => {
      const request: UpdateSettingsRequest = {};
      provider.fields.forEach((field) => {
        const value = credentials[field.name];
        if (value && value !== "••••••••") {
          request[field.name] = value;
        }
      });
      return updateSettings(request, selectedWorkspaceId);
    },
    onSuccess: () => {
      toast.success(`${provider.name} updated successfully`);
      void queryClient.invalidateQueries({ queryKey: ["settings"] });
      onClose();
    },
    onError: (error: Error) => {
      toast.error(error.message ?? `Failed to update ${provider.name}`);
    },
  });

  const clearMutation = useMutation({
    mutationFn: async () => {
      const request: UpdateSettingsRequest = {};
      provider.fields.forEach((field) => {
        request[field.name] = "";
      });
      return updateSettings(request, selectedWorkspaceId);
    },
    onSuccess: () => {
      toast.success(`${provider.name} disconnected`);
      void queryClient.invalidateQueries({ queryKey: ["settings"] });
      setShowDisconnectDialog(false);
      onClose();
    },
    onError: (error: Error) => {
      toast.error(error.message ?? `Failed to disconnect ${provider.name}`);
    },
  });

  const handleFieldChange = useCallback((fieldName: string, value: string) => {
    setCredentials((prev) => ({ ...prev, [fieldName]: value }));
  }, []);

  const togglePasswordVisibility = useCallback((fieldName: string) => {
    setShowPasswords((prev) => ({ ...prev, [fieldName]: !prev[fieldName] }));
  }, []);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    // Validate required fields (at least one field must have a value)
    const hasValue = provider.fields.some((field) => {
      const value = credentials[field.name];
      return value?.trim() && value !== "••••••••";
    });

    if (!hasValue && !isConnected) {
      toast.error("Please enter at least one credential");
      return;
    }

    updateMutation.mutate();
  };

  const isLoading = updateMutation.isPending;

  return (
    <>
      <form onSubmit={handleSubmit} className="space-y-4">
        {/* Show connection status if already connected */}
        {isConnected && (
          <div className="rounded-lg border border-green-500/20 bg-green-500/10 p-3">
            <div className="flex items-center gap-2 text-green-600 dark:text-green-400">
              <Check className="h-4 w-4" />
              <span className="text-sm font-medium">Connected</span>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              Enter new credentials to update, or leave blank to keep existing.
            </p>
          </div>
        )}

        {/* Credential fields */}
        {provider.fields.map((field) => (
          <div key={field.name} className="space-y-2">
            <Label htmlFor={field.name} className="text-sm">
              {field.label}
            </Label>
            <div className="relative">
              <Input
                id={field.name}
                type={showPasswords[field.name] ? "text" : "password"}
                placeholder={isConnected ? "••••••••" : field.placeholder}
                value={credentials[field.name] ?? ""}
                onChange={(e) => handleFieldChange(field.name, e.target.value)}
                className="pr-10"
              />
              <button
                type="button"
                onClick={() => togglePasswordVisibility(field.name)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              >
                {showPasswords[field.name] ? (
                  <EyeOff className="h-4 w-4" />
                ) : (
                  <Eye className="h-4 w-4" />
                )}
              </button>
            </div>
          </div>
        ))}

        {/* Documentation link */}
        <div className="rounded-lg border bg-muted/50 p-3">
          <p className="text-xs text-muted-foreground">
            Need help finding your API key?{" "}
            <a
              href={provider.documentationUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="font-medium text-primary hover:underline"
            >
              Visit {provider.name} documentation
              <ExternalLink className="ml-1 inline h-3 w-3" />
            </a>
          </p>
        </div>

        {/* Action buttons */}
        <div className="flex gap-2 pt-2">
          {isConnected ? (
            <>
              <Button type="submit" className="flex-1" disabled={isLoading}>
                {isLoading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Update Credentials
              </Button>
              <Button
                type="button"
                variant="destructive"
                onClick={() => setShowDisconnectDialog(true)}
                disabled={clearMutation.isPending}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </>
          ) : (
            <Button type="submit" className="w-full" disabled={isLoading}>
              {isLoading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Connect
            </Button>
          )}
        </div>
      </form>

      {/* Disconnect confirmation dialog */}
      <AlertDialog open={showDisconnectDialog} onOpenChange={setShowDisconnectDialog}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Disconnect {provider.name}?</AlertDialogTitle>
            <AlertDialogDescription>
              This will remove your stored API credentials. Any agents using this service will no
              longer function properly.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => clearMutation.mutate()}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {clearMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Disconnect
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
});

const ProfileTab = memo(function ProfileTab() {
  const { user } = useAuth();

  if (!user) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center py-16">
          <Loader2 className="mb-4 h-16 w-16 animate-spin text-muted-foreground/50" />
          <p className="text-sm text-muted-foreground">Loading profile...</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="p-6">
          <div className="space-y-6">
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-4">
                <div className="flex h-16 w-16 items-center justify-center rounded-full bg-primary/10">
                  <UserIcon className="h-8 w-8 text-primary" />
                </div>
                <div>
                  <h2 className="text-xl font-semibold">{user.full_name || user.username || "User"}</h2>
                  <p className="text-sm text-muted-foreground">{user.email}</p>
                </div>
              </div>
              <RoleBadge role={user.role} />
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label className="text-sm text-muted-foreground">Email Address</Label>
                <div className="flex items-center gap-2">
                  <Mail className="h-4 w-4 text-muted-foreground" />
                  <span className="text-sm">{user.email}</span>
                </div>
              </div>

              <div className="space-y-2">
                <Label className="text-sm text-muted-foreground">Email Verification</Label>
                <div className="flex items-center gap-2">
                  {user.email_verified ? (
                    <>
                      <CheckCircle2 className="h-4 w-4 text-green-500" />
                      <span className="text-sm text-green-600 dark:text-green-400">Verified</span>
                    </>
                  ) : (
                    <>
                      <XCircle className="h-4 w-4 text-orange-500" />
                      <span className="text-sm text-orange-600 dark:text-orange-400">Not Verified</span>
                    </>
                  )}
                </div>
              </div>

              <div className="space-y-2">
                <Label className="text-sm text-muted-foreground">Account Status</Label>
                <div className="flex items-center gap-2">
                  {user.is_active ? (
                    <>
                      <CheckCircle2 className="h-4 w-4 text-green-500" />
                      <span className="text-sm text-green-600 dark:text-green-400">Active</span>
                    </>
                  ) : (
                    <>
                      <XCircle className="h-4 w-4 text-red-500" />
                      <span className="text-sm text-red-600 dark:text-red-400">Inactive</span>
                    </>
                  )}
                </div>
              </div>

              <div className="space-y-2">
                <Label className="text-sm text-muted-foreground">Member Since</Label>
                <div className="flex items-center gap-2">
                  <Calendar className="h-4 w-4 text-muted-foreground" />
                  <span className="text-sm">
                    {new Date(user.created_at).toLocaleDateString("en-US", {
                      year: "numeric",
                      month: "long",
                      day: "numeric",
                    })}
                  </span>
                </div>
              </div>
            </div>

            {user.organization_id && (
              <div className="space-y-2 rounded-lg border bg-muted/50 p-4">
                <Label className="text-sm text-muted-foreground">Organization ID</Label>
                <p className="font-mono text-xs text-muted-foreground">{user.organization_id}</p>
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-6">
          <h3 className="mb-4 text-lg font-semibold">Account Actions</h3>
          <div className="space-y-3">
            <Button variant="outline" className="w-full justify-start" disabled>
              <SettingsIcon className="mr-2 h-4 w-4" />
              Change Password (Coming Soon)
            </Button>
            <Button variant="outline" className="w-full justify-start" disabled>
              <Mail className="mr-2 h-4 w-4" />
              Update Email (Coming Soon)
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
});
