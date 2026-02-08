"use client";

import { useState, useMemo, memo, useCallback } from "react";
import { useDebounce } from "use-debounce";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { api, integrationsApi, type IntegrationResponse } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Search,
  Check,
  Settings as SettingsIcon,
  Zap,
  Calendar,
  Users,
  Database,
  MessageSquare,
  Mail,
  Table,
  CreditCard,
  LifeBuoy,
  Code,
  Briefcase,
  FileText,
  Send,
  Clock,
  FolderOpen,
  Loader2,
  Trash2,
  Eye,
  EyeOff,
  ExternalLink,
} from "lucide-react";
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
import { AVAILABLE_INTEGRATIONS, type Integration } from "@/lib/integrations";

interface Workspace {
  id: string;
  name: string;
  description: string | null;
  is_default: boolean;
}

const getIntegrationIcon = (integrationId: string) => {
  const iconMap: Record<string, React.ComponentType<{ className?: string }>> = {
    salesforce: Users,
    hubspot: Users,
    pipedrive: Users,
    "zoho-crm": Users,
    "google-calendar": Calendar,
    "microsoft-calendar": Calendar,
    "cal-com": Clock,
    airtable: Table,
    notion: FileText,
    "google-sheets": Table,
    slack: MessageSquare,
    gmail: Mail,
    sendgrid: Send,
    intercom: MessageSquare,
    stripe: CreditCard,
    github: Code,
    jira: Briefcase,
    zendesk: LifeBuoy,
  };
  return iconMap[integrationId] ?? Database;
};

export default function IntegrationsPage() {
  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedSearchQuery] = useDebounce(searchQuery, 300);
  const [selectedCategory, setSelectedCategory] = useState<string>("all");
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState<string>("all");

  // Fetch workspaces
  const { data: workspaces = [] } = useQuery<Workspace[]>({
    queryKey: ["workspaces"],
    queryFn: async () => {
      const response = await api.get("/api/v1/workspaces");
      return response.data;
    },
  });

  // Fetch connected integrations
  const { data: connectedIntegrationsData } = useQuery({
    queryKey: ["integrations", selectedWorkspaceId],
    queryFn: async () => {
      const wsId = selectedWorkspaceId === "all" ? undefined : selectedWorkspaceId;
      return integrationsApi.list(wsId);
    },
  });

  // Build set of connected integration IDs
  const connectedIntegrations = useMemo(() => {
    const internalTools = new Set<string>(["call_control", "crm", "bookings"]);
    const connected = connectedIntegrationsData?.integrations ?? [];
    const connectedIds = new Set(connected.map((i) => i.integration_id));
    return new Set([...internalTools, ...connectedIds]);
  }, [connectedIntegrationsData]);

  // Map of integration_id to connection data
  const connectionDataMap = useMemo(() => {
    const map = new Map<string, IntegrationResponse>();
    (connectedIntegrationsData?.integrations ?? []).forEach((i) => {
      map.set(i.integration_id, i);
    });
    return map;
  }, [connectedIntegrationsData]);

  const categories = [
    { value: "all", label: "All" },
    { value: "crm", label: "CRM" },
    { value: "calendar", label: "Calendar" },
    { value: "database", label: "Database" },
    { value: "communication", label: "Communication" },
    { value: "productivity", label: "Productivity" },
    { value: "other", label: "Other" },
  ];

  // Memoize filtered integrations to prevent unnecessary recalculations
  const filteredIntegrations = useMemo(() => {
    return AVAILABLE_INTEGRATIONS.filter((integration) => {
      const matchesSearch =
        integration.name.toLowerCase().includes(debouncedSearchQuery.toLowerCase()) ||
        integration.description.toLowerCase().includes(debouncedSearchQuery.toLowerCase());
      const matchesCategory =
        selectedCategory === "all" || integration.category === selectedCategory;
      return matchesSearch && matchesCategory;
    });
  }, [debouncedSearchQuery, selectedCategory]);

  const connectedCount = connectedIntegrations.size;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Integrations & Tools</h1>
          <p className="text-sm text-muted-foreground">
            Connect external services for your voice agents to use
          </p>
        </div>
        <div className="flex items-center gap-2">
          {workspaces.length > 0 && (
            <Select
              value={selectedWorkspaceId}
              onValueChange={(value) => {
                setSelectedWorkspaceId(value);
                const wsName =
                  value === "all"
                    ? "All Workspaces"
                    : workspaces.find((ws) => ws.id === value)?.name;
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
          )}
          <div className="relative w-[250px]">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder="Search integrations..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="h-8 pl-9 text-sm"
            />
          </div>
        </div>
      </div>

      <Tabs defaultValue="all" onValueChange={setSelectedCategory}>
        <div className="flex items-center justify-between">
          <TabsList>
            {categories.map((cat) => (
              <TabsTrigger key={cat.value} value={cat.value}>
                {cat.label}
              </TabsTrigger>
            ))}
          </TabsList>
          <div className="flex items-center gap-2">
            <Badge variant="secondary" className="font-normal">
              {connectedCount} Connected
            </Badge>
            <Badge variant="outline" className="font-normal">
              {AVAILABLE_INTEGRATIONS.length} Available
            </Badge>
          </div>
        </div>

        <TabsContent value={selectedCategory} className="mt-6">
          {filteredIntegrations.length === 0 ? (
            <Card>
              <CardContent className="flex flex-col items-center justify-center py-16">
                <Zap className="mb-4 h-16 w-16 text-muted-foreground/50" />
                <h3 className="mb-2 text-lg font-semibold">No integrations found</h3>
                <p className="text-sm text-muted-foreground">
                  Try adjusting your search or category filter
                </p>
              </CardContent>
            </Card>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {filteredIntegrations.map((integration) => (
                <IntegrationCard
                  key={integration.id}
                  integration={integration}
                  isConnected={connectedIntegrations.has(integration.id)}
                  connectionData={connectionDataMap.get(integration.id)}
                  selectedWorkspaceId={
                    selectedWorkspaceId === "all" ? undefined : selectedWorkspaceId
                  }
                />
              ))}
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}

const IntegrationCard = memo(function IntegrationCard({
  integration,
  isConnected,
  connectionData,
  selectedWorkspaceId,
}: {
  integration: Integration;
  isConnected: boolean;
  connectionData?: IntegrationResponse;
  selectedWorkspaceId?: string;
}) {
  const [isConfigDialogOpen, setIsConfigDialogOpen] = useState(false);
  const Icon = getIntegrationIcon(integration.id);

  return (
    <Card className="group transition-all hover:border-primary/50">
      <CardContent className="p-4">
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2.5 overflow-hidden">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-primary/10">
              <Icon className="h-4 w-4 text-primary" />
            </div>
            <div className="min-w-0">
              <h3 className="truncate text-sm font-medium">{integration.name}</h3>
              <p className="text-xs text-muted-foreground">
                {integration.category.charAt(0).toUpperCase() + integration.category.slice(1)}
              </p>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            {integration.isPopular && (
              <Badge variant="secondary" className="h-5 px-1.5 text-[10px]">
                Popular
              </Badge>
            )}
            {isConnected && <Check className="h-4 w-4 text-green-500" />}
          </div>
        </div>

        <p className="mt-2.5 line-clamp-2 min-h-[2lh] text-xs text-muted-foreground">
          {integration.description}
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
                  {isConnected ? `Configure ${integration.name}` : `Connect ${integration.name}`}
                </DialogTitle>
                <DialogDescription>
                  {integration.authType === "oauth"
                    ? "Click Connect to authorize access via OAuth"
                    : integration.authType === "none"
                      ? "This integration is always available"
                      : "Enter your API credentials below"}
                </DialogDescription>
              </DialogHeader>
              <IntegrationConfigForm
                integration={integration}
                isConnected={isConnected}
                connectionData={connectionData}
                selectedWorkspaceId={selectedWorkspaceId}
                onClose={() => setIsConfigDialogOpen(false)}
              />
            </DialogContent>
          </Dialog>
          {integration.documentationUrl && (
            <Button variant="ghost" size="sm" className="h-7 text-xs" asChild>
              <a href={integration.documentationUrl} target="_blank" rel="noopener noreferrer">
                <ExternalLink className="mr-1 h-3 w-3" />
                Docs
              </a>
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
});

const IntegrationConfigForm = memo(function IntegrationConfigForm({
  integration,
  isConnected,
  connectionData,
  selectedWorkspaceId,
  onClose,
}: {
  integration: Integration;
  isConnected: boolean;
  connectionData?: IntegrationResponse;
  selectedWorkspaceId?: string;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [credentials, setCredentials] = useState<Record<string, string>>({});
  const [showPasswords, setShowPasswords] = useState<Record<string, boolean>>({});
  const [showDisconnectDialog, setShowDisconnectDialog] = useState(false);

  // Connect mutation
  const connectMutation = useMutation({
    mutationFn: async () => {
      return integrationsApi.connect({
        integration_id: integration.id,
        integration_name: integration.name,
        workspace_id: selectedWorkspaceId ?? null,
        credentials,
      });
    },
    onSuccess: () => {
      toast.success(`${integration.name} connected successfully`);
      void queryClient.invalidateQueries({ queryKey: ["integrations"] });
      onClose();
    },
    onError: (error: Error & { response?: { data?: { detail?: string } } }) => {
      toast.error(error.response?.data?.detail ?? `Failed to connect ${integration.name}`);
    },
  });

  // Update mutation
  const updateMutation = useMutation({
    mutationFn: async () => {
      return integrationsApi.update(integration.id, { credentials }, selectedWorkspaceId);
    },
    onSuccess: () => {
      toast.success(`${integration.name} updated successfully`);
      void queryClient.invalidateQueries({ queryKey: ["integrations"] });
      onClose();
    },
    onError: (error: Error & { response?: { data?: { detail?: string } } }) => {
      toast.error(error.response?.data?.detail ?? `Failed to update ${integration.name}`);
    },
  });

  // Disconnect mutation
  const disconnectMutation = useMutation({
    mutationFn: async () => {
      return integrationsApi.disconnect(integration.id, selectedWorkspaceId);
    },
    onSuccess: () => {
      toast.success(`${integration.name} disconnected`);
      void queryClient.invalidateQueries({ queryKey: ["integrations"] });
      setShowDisconnectDialog(false);
      onClose();
    },
    onError: (error: Error & { response?: { data?: { detail?: string } } }) => {
      toast.error(error.response?.data?.detail ?? `Failed to disconnect ${integration.name}`);
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

    // Validate required fields
    const requiredFields = integration.fields?.filter((f) => f.required) ?? [];
    const missingFields = requiredFields.filter((f) => !credentials[f.name]?.trim());

    if (missingFields.length > 0) {
      toast.error(`Please fill in: ${missingFields.map((f) => f.label).join(", ")}`);
      return;
    }

    if (isConnected) {
      updateMutation.mutate();
    } else {
      connectMutation.mutate();
    }
  };

  const isLoading = connectMutation.isPending || updateMutation.isPending;

  // For internal tools (authType: "none"), just show info
  if (integration.authType === "none") {
    return (
      <div className="space-y-4">
        <div className="rounded-lg border border-green-500/20 bg-green-500/10 p-4">
          <div className="flex items-center gap-2 text-green-600 dark:text-green-400">
            <Check className="h-4 w-4" />
            <span className="text-sm font-medium">Always Available</span>
          </div>
          <p className="mt-2 text-sm text-muted-foreground">
            This is an internal tool that works with your existing data. No configuration needed.
          </p>
        </div>
        <Button onClick={onClose} className="w-full">
          Close
        </Button>
      </div>
    );
  }

  // No fields defined - show placeholder
  if (!integration.fields || integration.fields.length === 0) {
    return (
      <div className="space-y-4">
        <div className="rounded-lg border p-4">
          <p className="text-sm text-muted-foreground">
            This integration requires OAuth authentication which is coming soon.
          </p>
        </div>
        <Button onClick={onClose} className="w-full">
          Close
        </Button>
      </div>
    );
  }

  return (
    <>
      <form onSubmit={handleSubmit} className="space-y-4">
        {/* Show connection status if already connected */}
        {isConnected && connectionData && (
          <div className="rounded-lg border border-green-500/20 bg-green-500/10 p-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-green-600 dark:text-green-400">
                <Check className="h-4 w-4" />
                <span className="text-sm font-medium">Connected</span>
              </div>
              {connectionData.connected_at && (
                <span className="text-xs text-muted-foreground">
                  Since {new Date(connectionData.connected_at).toLocaleDateString()}
                </span>
              )}
            </div>
            {connectionData.credential_fields.length > 0 && (
              <p className="mt-1 text-xs text-muted-foreground">
                Credentials set: {connectionData.credential_fields.join(", ")}
              </p>
            )}
          </div>
        )}

        {/* Credential fields */}
        {integration.fields.map((field) => (
          <div key={field.name} className="space-y-2">
            <Label htmlFor={field.name} className="text-sm">
              {field.label}
              {field.required && <span className="ml-1 text-destructive">*</span>}
            </Label>
            {field.type === "select" && field.options ? (
              <Select
                value={credentials[field.name] ?? ""}
                onValueChange={(value) => handleFieldChange(field.name, value)}
              >
                <SelectTrigger>
                  <SelectValue placeholder={`Select ${field.label.toLowerCase()}`} />
                </SelectTrigger>
                <SelectContent>
                  {field.options.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : (
              <div className="relative">
                <Input
                  id={field.name}
                  type={
                    field.type === "password" && !showPasswords[field.name] ? "password" : "text"
                  }
                  placeholder={field.placeholder ?? `Enter ${field.label.toLowerCase()}`}
                  value={credentials[field.name] ?? ""}
                  onChange={(e) => handleFieldChange(field.name, e.target.value)}
                  className={field.type === "password" ? "pr-10" : ""}
                />
                {field.type === "password" && (
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
                )}
              </div>
            )}
            {field.description && (
              <p className="text-xs text-muted-foreground">{field.description}</p>
            )}
          </div>
        ))}

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
                disabled={disconnectMutation.isPending}
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
            <AlertDialogTitle>Disconnect {integration.name}?</AlertDialogTitle>
            <AlertDialogDescription>
              This will remove your stored credentials. Any agents using this integration will no
              longer have access to it.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => disconnectMutation.mutate()}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {disconnectMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Disconnect
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
});
