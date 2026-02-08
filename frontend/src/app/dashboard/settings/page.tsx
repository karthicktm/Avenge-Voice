"use client";

import { useState, useCallback, memo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  fetchSettings,
  updateSettings,
  fetchSystemSettings,
  updateSystemSettings,
  type SettingsResponse,
  type UpdateSettingsRequest,
  type UpdateSystemSettingsRequest,
} from "@/lib/api/settings";
import {
  fetchCurrentOrganization,
  fetchAvailablePlans,
  changePlan,
  PLAN_DISPLAY_INFO,
} from "@/lib/api/organizations";
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
  Shield,
  Zap,
  Users,
  Bot,
  Clock,
  HardDrive,
  Sparkles,
  CreditCard,
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
  const { user } = useAuth();
  const isSuperuser = user?.role === "super_admin";

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
            {isSuperuser && <TabsTrigger value="system">System</TabsTrigger>}
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
              <h2 className="text-lg font-medium text-foreground">Voice & AI Providers</h2>
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
              <h2 className="text-lg font-medium text-foreground">Telephony Providers</h2>
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
          <BillingTab />
        </TabsContent>

        {isSuperuser && (
          <TabsContent value="system" className="mt-6 space-y-4">
            <SystemSettingsTab />
          </TabsContent>
        )}
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
                  <h2 className="text-xl font-semibold">
                    {user.full_name ?? user.username ?? "User"}
                  </h2>
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
                      <span className="text-sm text-orange-600 dark:text-orange-400">
                        Not Verified
                      </span>
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

const SystemSettingsTab = memo(function SystemSettingsTab() {
  const queryClient = useQueryClient();
  // Resend settings
  const [resendApiKey, setResendApiKey] = useState("");
  const [resendFromEmail, setResendFromEmail] = useState("");
  const [showResendApiKey, setShowResendApiKey] = useState(false);
  // Stripe settings
  const [stripeSecretKey, setStripeSecretKey] = useState("");
  const [stripePublishableKey, setStripePublishableKey] = useState("");
  const [stripeWebhookSecret, setStripeWebhookSecret] = useState("");
  const [stripePriceFree, setStripePriceFree] = useState("");
  const [stripePriceStarter, setStripePriceStarter] = useState("");
  const [stripePriceProfessional, setStripePriceProfessional] = useState("");
  const [stripePriceEnterprise, setStripePriceEnterprise] = useState("");
  const [showStripeSecretKey, setShowStripeSecretKey] = useState(false);
  const [showStripeWebhookSecret, setShowStripeWebhookSecret] = useState(false);

  const { data: systemSettings, isLoading } = useQuery({
    queryKey: ["systemSettings"],
    queryFn: fetchSystemSettings,
  });

  const updateMutation = useMutation({
    mutationFn: (request: UpdateSystemSettingsRequest) => updateSystemSettings(request),
    onSuccess: () => {
      toast.success("System settings updated successfully");
      void queryClient.invalidateQueries({ queryKey: ["systemSettings"] });
      // Clear sensitive fields
      setResendApiKey("");
      setStripeSecretKey("");
      setStripeWebhookSecret("");
    },
    onError: (error: Error) => {
      toast.error(error.message ?? "Failed to update system settings");
    },
  });

  const handleResendSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const request: UpdateSystemSettingsRequest = {};
    if (resendApiKey.trim()) {
      request.resend_api_key = resendApiKey;
    }
    if (resendFromEmail.trim()) {
      request.resend_from_email = resendFromEmail;
    }
    if (Object.keys(request).length === 0) {
      toast.error("Please enter at least one value to update");
      return;
    }
    updateMutation.mutate(request);
  };

  const handleStripeSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const request: UpdateSystemSettingsRequest = {};
    if (stripeSecretKey.trim()) {
      request.stripe_secret_key = stripeSecretKey;
    }
    if (stripePublishableKey.trim()) {
      request.stripe_publishable_key = stripePublishableKey;
    }
    if (stripeWebhookSecret.trim()) {
      request.stripe_webhook_secret = stripeWebhookSecret;
    }
    if (stripePriceFree.trim()) {
      request.stripe_price_free = stripePriceFree;
    }
    if (stripePriceStarter.trim()) {
      request.stripe_price_starter = stripePriceStarter;
    }
    if (stripePriceProfessional.trim()) {
      request.stripe_price_professional = stripePriceProfessional;
    }
    if (stripePriceEnterprise.trim()) {
      request.stripe_price_enterprise = stripePriceEnterprise;
    }
    if (Object.keys(request).length === 0) {
      toast.error("Please enter at least one value to update");
      return;
    }
    updateMutation.mutate(request);
  };

  if (isLoading) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-16">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header Card */}
      <Card>
        <CardContent className="p-6">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10">
              <Shield className="h-5 w-5 text-primary" />
            </div>
            <div>
              <h2 className="text-lg font-semibold">System Settings</h2>
              <p className="text-sm text-muted-foreground">
                Global configuration for the platform (Superadmin only)
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Email Service (Resend) */}
      <Card>
        <CardContent className="p-6">
          <form onSubmit={handleResendSubmit} className="space-y-6">
            <div className="space-y-4">
              <div className="flex items-center gap-2">
                <Mail className="h-4 w-4 text-muted-foreground" />
                <h3 className="font-medium">Email Service (Resend)</h3>
                {systemSettings?.resend_api_key_set && (
                  <Badge variant="secondary" className="ml-2">
                    <Check className="mr-1 h-3 w-3" />
                    Configured
                  </Badge>
                )}
              </div>
              <p className="text-sm text-muted-foreground">
                Configure Resend API for sending verification emails and notifications.
              </p>

              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="resend_api_key">Resend API Key</Label>
                  <div className="relative">
                    <Input
                      id="resend_api_key"
                      type={showResendApiKey ? "text" : "password"}
                      placeholder={systemSettings?.resend_api_key_set ? "••••••••" : "re_..."}
                      value={resendApiKey}
                      onChange={(e) => setResendApiKey(e.target.value)}
                      className="pr-10"
                    />
                    <button
                      type="button"
                      onClick={() => setShowResendApiKey(!showResendApiKey)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                    >
                      {showResendApiKey ? (
                        <EyeOff className="h-4 w-4" />
                      ) : (
                        <Eye className="h-4 w-4" />
                      )}
                    </button>
                  </div>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="resend_from_email">From Email Address</Label>
                  <Input
                    id="resend_from_email"
                    type="email"
                    placeholder={systemSettings?.resend_from_email ?? "noreply@yourdomain.com"}
                    value={resendFromEmail}
                    onChange={(e) => setResendFromEmail(e.target.value)}
                  />
                  {systemSettings?.resend_from_email && (
                    <p className="text-xs text-muted-foreground">
                      Current: {systemSettings.resend_from_email}
                    </p>
                  )}
                </div>
              </div>

              <div className="rounded-lg border bg-muted/50 p-3">
                <p className="text-xs text-muted-foreground">
                  Get your API key from{" "}
                  <a
                    href="https://resend.com/api-keys"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="font-medium text-primary hover:underline"
                  >
                    resend.com/api-keys
                    <ExternalLink className="ml-1 inline h-3 w-3" />
                  </a>
                </p>
              </div>
            </div>

            <Button type="submit" disabled={updateMutation.isPending}>
              {updateMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Save Email Settings
            </Button>
          </form>
        </CardContent>
      </Card>

      {/* Stripe Billing Configuration */}
      <Card>
        <CardContent className="p-6">
          <form onSubmit={handleStripeSubmit} className="space-y-6">
            <div className="space-y-4">
              <div className="flex items-center gap-2">
                <CreditCard className="h-4 w-4 text-muted-foreground" />
                <h3 className="font-medium">Billing (Stripe)</h3>
                {systemSettings?.stripe_secret_key_set && (
                  <Badge variant="secondary" className="ml-2">
                    <Check className="mr-1 h-3 w-3" />
                    Configured
                  </Badge>
                )}
              </div>
              <p className="text-sm text-muted-foreground">
                Configure Stripe for subscription billing and payment processing.
              </p>

              {/* API Keys */}
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="stripe_secret_key">Secret Key</Label>
                  <div className="relative">
                    <Input
                      id="stripe_secret_key"
                      type={showStripeSecretKey ? "text" : "password"}
                      placeholder={
                        systemSettings?.stripe_secret_key_set
                          ? "••••••••"
                          : "sk_live_... or sk_test_..."
                      }
                      value={stripeSecretKey}
                      onChange={(e) => setStripeSecretKey(e.target.value)}
                      className="pr-10"
                    />
                    <button
                      type="button"
                      onClick={() => setShowStripeSecretKey(!showStripeSecretKey)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                    >
                      {showStripeSecretKey ? (
                        <EyeOff className="h-4 w-4" />
                      ) : (
                        <Eye className="h-4 w-4" />
                      )}
                    </button>
                  </div>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="stripe_publishable_key">Publishable Key</Label>
                  <Input
                    id="stripe_publishable_key"
                    type="text"
                    placeholder={
                      systemSettings?.stripe_publishable_key ?? "pk_live_... or pk_test_..."
                    }
                    value={stripePublishableKey}
                    onChange={(e) => setStripePublishableKey(e.target.value)}
                  />
                  {systemSettings?.stripe_publishable_key && (
                    <p className="text-xs text-muted-foreground">
                      Current: {systemSettings.stripe_publishable_key.substring(0, 20)}...
                    </p>
                  )}
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="stripe_webhook_secret">Webhook Secret</Label>
                <div className="relative">
                  <Input
                    id="stripe_webhook_secret"
                    type={showStripeWebhookSecret ? "text" : "password"}
                    placeholder={
                      systemSettings?.stripe_webhook_secret_set ? "••••••••" : "whsec_..."
                    }
                    value={stripeWebhookSecret}
                    onChange={(e) => setStripeWebhookSecret(e.target.value)}
                    className="pr-10"
                  />
                  <button
                    type="button"
                    onClick={() => setShowStripeWebhookSecret(!showStripeWebhookSecret)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                  >
                    {showStripeWebhookSecret ? (
                      <EyeOff className="h-4 w-4" />
                    ) : (
                      <Eye className="h-4 w-4" />
                    )}
                  </button>
                </div>
                <p className="text-xs text-muted-foreground">
                  Required for processing subscription events from Stripe
                </p>
              </div>

              {/* Price IDs */}
              <div className="space-y-3 border-t pt-4">
                <h4 className="text-sm font-medium">Plan Price IDs</h4>
                <p className="text-xs text-muted-foreground">
                  Enter Stripe Price IDs for each subscription plan
                </p>

                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="stripe_price_free">Free Plan</Label>
                    <Input
                      id="stripe_price_free"
                      type="text"
                      placeholder={systemSettings?.stripe_price_free ?? "price_..."}
                      value={stripePriceFree}
                      onChange={(e) => setStripePriceFree(e.target.value)}
                    />
                    {systemSettings?.stripe_price_free && (
                      <p className="text-xs text-muted-foreground">
                        Current: {systemSettings.stripe_price_free}
                      </p>
                    )}
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="stripe_price_starter">Starter Plan</Label>
                    <Input
                      id="stripe_price_starter"
                      type="text"
                      placeholder={systemSettings?.stripe_price_starter ?? "price_..."}
                      value={stripePriceStarter}
                      onChange={(e) => setStripePriceStarter(e.target.value)}
                    />
                    {systemSettings?.stripe_price_starter && (
                      <p className="text-xs text-muted-foreground">
                        Current: {systemSettings.stripe_price_starter}
                      </p>
                    )}
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="stripe_price_professional">Professional Plan</Label>
                    <Input
                      id="stripe_price_professional"
                      type="text"
                      placeholder={systemSettings?.stripe_price_professional ?? "price_..."}
                      value={stripePriceProfessional}
                      onChange={(e) => setStripePriceProfessional(e.target.value)}
                    />
                    {systemSettings?.stripe_price_professional && (
                      <p className="text-xs text-muted-foreground">
                        Current: {systemSettings.stripe_price_professional}
                      </p>
                    )}
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="stripe_price_enterprise">Enterprise Plan</Label>
                    <Input
                      id="stripe_price_enterprise"
                      type="text"
                      placeholder={systemSettings?.stripe_price_enterprise ?? "price_..."}
                      value={stripePriceEnterprise}
                      onChange={(e) => setStripePriceEnterprise(e.target.value)}
                    />
                    {systemSettings?.stripe_price_enterprise && (
                      <p className="text-xs text-muted-foreground">
                        Current: {systemSettings.stripe_price_enterprise}
                      </p>
                    )}
                  </div>
                </div>
              </div>

              <div className="rounded-lg border bg-muted/50 p-3">
                <p className="text-xs text-muted-foreground">
                  Get your API keys from{" "}
                  <a
                    href="https://dashboard.stripe.com/apikeys"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="font-medium text-primary hover:underline"
                  >
                    dashboard.stripe.com/apikeys
                    <ExternalLink className="ml-1 inline h-3 w-3" />
                  </a>
                  . Create products and prices in{" "}
                  <a
                    href="https://dashboard.stripe.com/products"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="font-medium text-primary hover:underline"
                  >
                    Products
                    <ExternalLink className="ml-1 inline h-3 w-3" />
                  </a>
                  .
                </p>
              </div>
            </div>

            <Button type="submit" disabled={updateMutation.isPending}>
              {updateMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Save Billing Settings
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
});

const BillingTab = memo(function BillingTab() {
  const queryClient = useQueryClient();
  const [selectedPlan, setSelectedPlan] = useState<string | null>(null);
  const [showConfirmDialog, setShowConfirmDialog] = useState(false);

  const { data: organization, isLoading: orgLoading } = useQuery({
    queryKey: ["organization"],
    queryFn: fetchCurrentOrganization,
  });

  const { data: plans, isLoading: plansLoading } = useQuery({
    queryKey: ["plans"],
    queryFn: fetchAvailablePlans,
  });

  const changePlanMutation = useMutation({
    mutationFn: (planType: string) => changePlan(planType),
    onSuccess: (data) => {
      toast.success(data.message);
      void queryClient.invalidateQueries({ queryKey: ["organization"] });
      setShowConfirmDialog(false);
      setSelectedPlan(null);
    },
    onError: (error: Error) => {
      toast.error(error.message ?? "Failed to change plan");
    },
  });

  const handleChangePlan = (planType: string) => {
    if (planType === organization?.plan_type) return;
    setSelectedPlan(planType);
    setShowConfirmDialog(true);
  };

  const confirmPlanChange = () => {
    if (selectedPlan) {
      changePlanMutation.mutate(selectedPlan);
    }
  };

  if (orgLoading || plansLoading) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-16">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      {/* Current Plan & Usage */}
      <Card>
        <CardContent className="p-6">
          <div className="mb-6 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10">
                <Zap className="h-5 w-5 text-primary" />
              </div>
              <div>
                <h2 className="text-lg font-semibold">Current Plan</h2>
                <p className="text-sm text-muted-foreground">
                  {organization?.name ?? "Your Organization"}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Badge variant="secondary" className="text-sm">
                {PLAN_DISPLAY_INFO[organization?.plan_type ?? "free"]?.name ?? "Free"}
              </Badge>
              {organization?.subscription_status === "trial" && (
                <Badge variant="outline" className="border-yellow-500 text-yellow-600">
                  Trial
                </Badge>
              )}
            </div>
          </div>

          {/* Usage Stats */}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <UsageCard
              icon={Users}
              label="Users"
              current={organization?.current_users_count ?? 0}
              max={organization?.max_users ?? 0}
            />
            <UsageCard
              icon={Bot}
              label="Agents"
              current={organization?.current_agents_count ?? 0}
              max={organization?.max_agents ?? 0}
            />
            <UsageCard
              icon={FolderOpen}
              label="Workspaces"
              current={organization?.current_workspaces_count ?? 0}
              max={organization?.max_workspaces ?? 0}
            />
            <UsageCard
              icon={Clock}
              label="Call Minutes"
              current={organization?.current_month_call_minutes ?? 0}
              max={organization?.max_call_minutes_per_month ?? 0}
              suffix="/mo"
            />
          </div>
        </CardContent>
      </Card>

      {/* Available Plans */}
      <div className="space-y-4">
        <div>
          <h2 className="text-lg font-medium">Available Plans</h2>
          <p className="text-sm text-muted-foreground">Choose the plan that best fits your needs</p>
        </div>

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {plans?.map((plan) => {
            const displayInfo = PLAN_DISPLAY_INFO[plan.plan_type];
            const isCurrentPlan = plan.plan_type === organization?.plan_type;

            return (
              <Card
                key={plan.plan_type}
                className={`relative transition-all ${
                  isCurrentPlan ? "border-primary bg-primary/5" : "hover:border-primary/50"
                } ${displayInfo?.popular ? "ring-2 ring-primary/20" : ""}`}
              >
                {displayInfo?.popular && (
                  <div className="absolute -top-3 left-1/2 -translate-x-1/2">
                    <Badge className="bg-primary text-primary-foreground">
                      <Sparkles className="mr-1 h-3 w-3" />
                      Popular
                    </Badge>
                  </div>
                )}
                <CardContent className="p-4 pt-6">
                  <div className="mb-4 text-center">
                    <h3 className="text-lg font-semibold">{displayInfo?.name}</h3>
                    <p className="text-2xl font-bold">{displayInfo?.price}</p>
                    <p className="text-xs text-muted-foreground">{displayInfo?.description}</p>
                  </div>

                  <div className="mb-4 space-y-2 text-xs">
                    <div className="flex items-center gap-2">
                      <Users className="h-3 w-3 text-muted-foreground" />
                      <span>{plan.max_users} users</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <Bot className="h-3 w-3 text-muted-foreground" />
                      <span>{plan.max_agents} agents</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <FolderOpen className="h-3 w-3 text-muted-foreground" />
                      <span>{plan.max_workspaces} workspaces</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <Clock className="h-3 w-3 text-muted-foreground" />
                      <span>{plan.max_call_minutes_per_month} min/mo</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <HardDrive className="h-3 w-3 text-muted-foreground" />
                      <span>{plan.max_storage_gb} GB storage</span>
                    </div>
                  </div>

                  <Button
                    variant={isCurrentPlan ? "secondary" : "default"}
                    size="sm"
                    className="w-full"
                    disabled={isCurrentPlan || changePlanMutation.isPending}
                    onClick={() => handleChangePlan(plan.plan_type)}
                  >
                    {isCurrentPlan ? (
                      <>
                        <Check className="mr-2 h-4 w-4" />
                        Current Plan
                      </>
                    ) : (
                      "Select Plan"
                    )}
                  </Button>
                </CardContent>
              </Card>
            );
          })}
        </div>
      </div>

      {/* Plan Change Confirmation Dialog */}
      <AlertDialog open={showConfirmDialog} onOpenChange={setShowConfirmDialog}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Change Plan</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to change to the{" "}
              <strong>{PLAN_DISPLAY_INFO[selectedPlan ?? ""]?.name}</strong> plan?
              {selectedPlan && organization?.plan_type && (
                <>
                  {" "}
                  {["starter", "professional", "enterprise"].indexOf(selectedPlan) <
                  ["starter", "professional", "enterprise"].indexOf(organization.plan_type)
                    ? "Downgrading may affect your current usage if you exceed the new limits."
                    : "Your new limits will be applied immediately."}
                </>
              )}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={confirmPlanChange} disabled={changePlanMutation.isPending}>
              {changePlanMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Confirm Change
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
});

interface UsageCardProps {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  current: number;
  max: number;
  suffix?: string;
}

function UsageCard({ icon: Icon, label, current, max, suffix = "" }: UsageCardProps) {
  const percentage = max > 0 ? Math.round((current / max) * 100) : 0;
  const isNearLimit = percentage >= 80;
  const isAtLimit = percentage >= 100;

  return (
    <div className="rounded-lg border bg-card p-4">
      <div className="mb-2 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Icon className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm font-medium">{label}</span>
        </div>
        <span
          className={`text-xs font-medium ${
            isAtLimit ? "text-red-500" : isNearLimit ? "text-yellow-500" : "text-muted-foreground"
          }`}
        >
          {percentage}%
        </span>
      </div>
      <div className="mb-1 h-2 overflow-hidden rounded-full bg-muted">
        <div
          className={`h-full transition-all ${
            isAtLimit ? "bg-red-500" : isNearLimit ? "bg-yellow-500" : "bg-primary"
          }`}
          style={{ width: `${Math.min(percentage, 100)}%` }}
        />
      </div>
      <div className="text-xs text-muted-foreground">
        {current} / {max}
        {suffix}
      </div>
    </div>
  );
}
