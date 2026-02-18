"use client";

import { useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Plus,
  PhoneOutgoing,
  Loader2,
  AlertCircle,
  Play,
  Pause,
  Square,
  Users,
  Clock,
  CheckCircle2,
  XCircle,
  FolderOpen,
  BarChart3,
  RotateCcw,
} from "lucide-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { fetchAgents, type Agent } from "@/lib/api/agents";
import {
  listCampaigns,
  createCampaign,
  deleteCampaign,
  startCampaign,
  pauseCampaign,
  stopCampaign,
  restartCampaign,
  getCampaignStats,
  addContactsToCampaign,
  type Campaign,
  type CampaignStatus,
  type CampaignStats,
  type CreateCampaignRequest,
} from "@/lib/api/campaigns";
import { listPhoneNumbers, type PhoneNumber, type Provider } from "@/lib/api/telephony";
import { toast } from "sonner";
import Link from "next/link";

interface Workspace {
  id: string;
  name: string;
  description: string | null;
  is_default: boolean;
}

interface Contact {
  id: number;
  first_name: string;
  last_name: string | null;
  phone_number: string;
}

type CampaignFormData = {
  name: string;
  description: string;
  script: string;
  campaign_greeting: string;
  agent_id: string;
  from_phone_number: string;
  calls_per_minute: number;
  max_concurrent_calls: number;
  max_attempts_per_contact: number;
  retry_delay_minutes: number;
};

const emptyFormData: CampaignFormData = {
  name: "",
  description: "",
  script: "",
  campaign_greeting: "",
  agent_id: "",
  from_phone_number: "",
  calls_per_minute: 5,
  max_concurrent_calls: 2,
  max_attempts_per_contact: 3,
  retry_delay_minutes: 60,
};

export default function CampaignsPage() {
  const queryClient = useQueryClient();
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [isContactsModalOpen, setIsContactsModalOpen] = useState(false);
  const [isStatsModalOpen, setIsStatsModalOpen] = useState(false);
  const [selectedCampaign, setSelectedCampaign] = useState<Campaign | null>(null);
  const [selectedCampaignStats, setSelectedCampaignStats] = useState<CampaignStats | null>(null);
  const [formData, setFormData] = useState<CampaignFormData>(emptyFormData);
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState<string>("all");
  const [isDeleteDialogOpen, setIsDeleteDialogOpen] = useState(false);
  const [selectedContactIds, setSelectedContactIds] = useState<number[]>([]);

  // Fetch workspaces
  const { data: workspaces = [] } = useQuery<Workspace[]>({
    queryKey: ["workspaces"],
    queryFn: async () => {
      const response = await api.get("/api/v1/workspaces");
      return response.data;
    },
  });

  // Get active workspace ID
  const activeWorkspaceId = selectedWorkspaceId !== "all" ? selectedWorkspaceId : workspaces[0]?.id;

  // Fetch campaigns
  const {
    data: campaigns = [],
    isLoading,
    error,
  } = useQuery<Campaign[]>({
    queryKey: ["campaigns", activeWorkspaceId],
    queryFn: async () => {
      if (!activeWorkspaceId) return [];
      return listCampaigns({ workspace_id: activeWorkspaceId });
    },
    enabled: !!activeWorkspaceId,
  });

  // Fetch agents
  const { data: agents = [] } = useQuery<Agent[]>({
    queryKey: ["agents"],
    queryFn: () => fetchAgents(),
  });

  // Fetch phone numbers
  const { data: phoneNumbers = [] } = useQuery<PhoneNumber[]>({
    queryKey: ["phoneNumbers", activeWorkspaceId],
    queryFn: async () => {
      if (!activeWorkspaceId) return [];
      const providers: Provider[] = ["twilio", "telnyx"];
      const results = await Promise.all(
        providers.map((provider) => listPhoneNumbers(provider, activeWorkspaceId))
      );
      return results.flat();
    },
    enabled: !!activeWorkspaceId,
  });

  // Fetch contacts for adding to campaign
  const { data: contacts = [] } = useQuery<Contact[]>({
    queryKey: ["contacts", activeWorkspaceId],
    queryFn: async () => {
      const url = activeWorkspaceId
        ? `/api/v1/crm/contacts?workspace_id=${activeWorkspaceId}`
        : "/api/v1/crm/contacts";
      const response = await api.get(url);
      return response.data;
    },
    enabled: !!activeWorkspaceId,
  });

  // Create campaign mutation
  const createCampaignMutation = useMutation({
    mutationFn: async (data: CreateCampaignRequest) => {
      return createCampaign(data);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["campaigns"] });
      toast.success("Campaign created successfully");
      setIsCreateModalOpen(false);
      setFormData(emptyFormData);
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to create campaign");
    },
  });

  // Delete campaign mutation
  const deleteCampaignMutation = useMutation({
    mutationFn: async (campaignId: string) => {
      return deleteCampaign(campaignId);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["campaigns"] });
      toast.success("Campaign deleted successfully");
      setSelectedCampaign(null);
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to delete campaign");
    },
  });

  // Start campaign mutation
  const startCampaignMutation = useMutation({
    mutationFn: async (campaignId: string) => {
      return startCampaign(campaignId);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["campaigns"] });
      toast.success("Campaign started");
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to start campaign");
    },
  });

  // Pause campaign mutation
  const pauseCampaignMutation = useMutation({
    mutationFn: async (campaignId: string) => {
      return pauseCampaign(campaignId);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["campaigns"] });
      toast.success("Campaign paused");
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to pause campaign");
    },
  });

  // Stop campaign mutation
  const stopCampaignMutation = useMutation({
    mutationFn: async (campaignId: string) => {
      return stopCampaign(campaignId);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["campaigns"] });
      toast.success("Campaign stopped");
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to stop campaign");
    },
  });

  // Restart campaign mutation
  const restartCampaignMutation = useMutation({
    mutationFn: async (campaignId: string) => {
      return restartCampaign(campaignId);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["campaigns"] });
      toast.success("Campaign restarted");
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to restart campaign");
    },
  });

  // Add contacts mutation
  const addContactsMutation = useMutation({
    mutationFn: async ({
      campaignId,
      contactIds,
    }: {
      campaignId: string;
      contactIds: number[];
    }) => {
      return addContactsToCampaign(campaignId, contactIds);
    },
    onSuccess: (data) => {
      void queryClient.invalidateQueries({ queryKey: ["campaigns"] });
      toast.success(`Added ${data.added} contacts to campaign`);
      setIsContactsModalOpen(false);
      setSelectedContactIds([]);
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to add contacts");
    },
  });

  const openCreateModal = () => {
    setFormData(emptyFormData);
    // Pre-select first agent and phone number
    const firstAgent = agents[0];
    const firstPhone = phoneNumbers[0];
    if (firstAgent) {
      setFormData((prev) => ({ ...prev, agent_id: firstAgent.id }));
    }
    if (firstPhone) {
      setFormData((prev) => ({ ...prev, from_phone_number: firstPhone.phone_number }));
    }
    setIsCreateModalOpen(true);
  };

  const openContactsModal = (campaign: Campaign) => {
    setSelectedCampaign(campaign);
    setSelectedContactIds([]);
    setIsContactsModalOpen(true);
  };

  const openStatsModal = async (campaign: Campaign) => {
    setSelectedCampaign(campaign);
    try {
      const stats = await getCampaignStats(campaign.id);
      setSelectedCampaignStats(stats);
      setIsStatsModalOpen(true);
    } catch {
      toast.error("Failed to load campaign statistics");
    }
  };

  const handleCreateCampaign = (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeWorkspaceId) {
      toast.error("Please select a workspace");
      return;
    }
    createCampaignMutation.mutate({
      workspace_id: activeWorkspaceId,
      agent_id: formData.agent_id,
      name: formData.name,
      description: formData.description || undefined,
      script: formData.script || undefined,
      campaign_greeting: formData.campaign_greeting || undefined,
      from_phone_number: formData.from_phone_number,
      calls_per_minute: formData.calls_per_minute,
      max_concurrent_calls: formData.max_concurrent_calls,
      max_attempts_per_contact: formData.max_attempts_per_contact,
      retry_delay_minutes: formData.retry_delay_minutes,
    });
  };

  const handleDeleteCampaign = () => {
    if (selectedCampaign) {
      deleteCampaignMutation.mutate(selectedCampaign.id);
    }
    setIsDeleteDialogOpen(false);
  };

  const handleAddContacts = () => {
    if (selectedCampaign && selectedContactIds.length > 0) {
      addContactsMutation.mutate({
        campaignId: selectedCampaign.id,
        contactIds: selectedContactIds,
      });
    }
  };

  const toggleContactSelection = (contactId: number) => {
    setSelectedContactIds((prev) =>
      prev.includes(contactId) ? prev.filter((id) => id !== contactId) : [...prev, contactId]
    );
  };

  const selectAllContacts = () => {
    setSelectedContactIds(contacts.map((c) => c.id));
  };

  const deselectAllContacts = () => {
    setSelectedContactIds([]);
  };

  const allContactsSelected = contacts.length > 0 && selectedContactIds.length === contacts.length;

  const getStatusColor = (status: CampaignStatus) => {
    const colors: Record<CampaignStatus, string> = {
      draft: "bg-gray-100 text-gray-800",
      scheduled: "bg-blue-100 text-blue-800",
      running: "bg-green-100 text-green-800",
      paused: "bg-yellow-100 text-yellow-800",
      completed: "bg-purple-100 text-purple-800",
      canceled: "bg-red-100 text-red-800",
    };
    return colors[status] ?? "bg-gray-100 text-gray-800";
  };

  const getStatusIcon = (status: CampaignStatus) => {
    switch (status) {
      case "running":
        return <Play className="h-3 w-3" />;
      case "paused":
        return <Pause className="h-3 w-3" />;
      case "completed":
        return <CheckCircle2 className="h-3 w-3" />;
      case "canceled":
        return <XCircle className="h-3 w-3" />;
      default:
        return <Clock className="h-3 w-3" />;
    }
  };

  if (error) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-xl font-semibold">Campaigns</h1>
          <p className="text-sm text-muted-foreground">Manage your outbound calling campaigns</p>
        </div>
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12">
            <AlertCircle className="mb-4 h-12 w-12 text-destructive" />
            <h3 className="mb-2 text-lg font-semibold">Failed to load campaigns</h3>
            <p className="text-sm text-muted-foreground">
              {error instanceof Error ? error.message : "An error occurred"}
            </p>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Campaigns</h1>
          <p className="text-sm text-muted-foreground">Manage your outbound calling campaigns</p>
        </div>
        <div className="flex items-center gap-3">
          {workspaces.length > 0 ? (
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
          ) : (
            <Link
              href="/dashboard/workspaces"
              className="text-sm text-muted-foreground hover:text-foreground"
            >
              Create a workspace
            </Link>
          )}
          <Button size="sm" onClick={openCreateModal} disabled={agents.length === 0}>
            <Plus className="mr-2 h-4 w-4" />
            New Campaign
          </Button>
        </div>
      </div>

      {/* Stats Cards */}
      <div className="grid gap-3 md:grid-cols-4">
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-muted-foreground">Total Campaigns</p>
                <p className="text-lg font-semibold">{campaigns.length}</p>
              </div>
              <PhoneOutgoing className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-muted-foreground">Running</p>
                <p className="text-lg font-semibold">
                  {campaigns.filter((c) => c.status === "running").length}
                </p>
              </div>
              <Play className="h-4 w-4 text-green-500" />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-muted-foreground">Total Contacts</p>
                <p className="text-lg font-semibold">
                  {campaigns.reduce((sum, c) => sum + c.total_contacts, 0)}
                </p>
              </div>
              <Users className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-muted-foreground">Completed Calls</p>
                <p className="text-lg font-semibold">
                  {campaigns.reduce((sum, c) => sum + c.contacts_completed, 0)}
                </p>
              </div>
              <CheckCircle2 className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Campaigns List */}
      {isLoading ? (
        <Card>
          <CardContent className="flex items-center justify-center py-16">
            <Loader2 className="mr-2 h-6 w-6 animate-spin" />
            <p className="text-muted-foreground">Loading campaigns...</p>
          </CardContent>
        </Card>
      ) : campaigns.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16">
            <PhoneOutgoing className="mb-4 h-16 w-16 text-muted-foreground/50" />
            <h3 className="mb-2 text-lg font-semibold">No campaigns yet</h3>
            <p className="mb-4 max-w-sm text-center text-sm text-muted-foreground">
              Create your first campaign to start making outbound calls to your contacts
            </p>
            <Button size="sm" onClick={openCreateModal} disabled={agents.length === 0}>
              <Plus className="mr-2 h-4 w-4" />
              Create Your First Campaign
            </Button>
            {agents.length === 0 && (
              <p className="mt-2 text-xs text-muted-foreground">
                You need to{" "}
                <Link href="/dashboard/agents" className="text-primary hover:underline">
                  create an agent
                </Link>{" "}
                first
              </p>
            )}
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {campaigns.map((campaign) => (
            <Card
              key={campaign.id}
              className="group cursor-pointer transition-all hover:border-primary/50"
            >
              <CardContent className="p-4">
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2.5 overflow-hidden">
                    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-primary/10">
                      <PhoneOutgoing className="h-4 w-4 text-primary" />
                    </div>
                    <div className="min-w-0">
                      <h3 className="truncate text-sm font-medium">{campaign.name}</h3>
                      <p className="truncate text-xs text-muted-foreground">
                        {campaign.agent_name ?? "No agent"}
                      </p>
                    </div>
                  </div>
                  <span
                    className={`inline-flex h-5 shrink-0 items-center gap-1 rounded-full px-1.5 text-[10px] font-medium ${getStatusColor(campaign.status)}`}
                  >
                    {getStatusIcon(campaign.status)}
                    {campaign.status}
                  </span>
                </div>

                <div className="mt-3 grid grid-cols-3 gap-2 text-xs text-muted-foreground">
                  <div>
                    <p className="font-medium text-foreground">{campaign.total_contacts}</p>
                    <p>Contacts</p>
                  </div>
                  <div>
                    <p className="font-medium text-foreground">{campaign.contacts_completed}</p>
                    <p>Completed</p>
                  </div>
                  <div>
                    <p className="font-medium text-foreground">{campaign.contacts_failed}</p>
                    <p>Failed</p>
                  </div>
                </div>

                {/* Error display */}
                {campaign.error_count > 0 && (
                  <div className="mt-2 rounded-md border border-destructive/30 bg-destructive/10 px-2.5 py-1.5">
                    <div className="flex items-start gap-1.5 text-xs text-destructive">
                      <AlertCircle className="mt-0.5 h-3 w-3 shrink-0" />
                      <div className="min-w-0">
                        <p className="font-medium">
                          {campaign.error_count} error{campaign.error_count > 1 ? "s" : ""}
                        </p>
                        {campaign.last_error && (
                          <p className="mt-0.5 truncate text-destructive/80">
                            {campaign.last_error}
                          </p>
                        )}
                      </div>
                    </div>
                  </div>
                )}

                <div className="mt-3 flex items-center justify-between gap-2 border-t border-border/50 pt-3">
                  <div className="flex items-center gap-1">
                    {campaign.status === "draft" && (
                      <>
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-7 px-2"
                          onClick={(e) => {
                            e.stopPropagation();
                            openContactsModal(campaign);
                          }}
                        >
                          <Users className="mr-1 h-3 w-3" />
                          Add Contacts
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-7 px-2"
                          onClick={(e) => {
                            e.stopPropagation();
                            startCampaignMutation.mutate(campaign.id);
                          }}
                          disabled={
                            campaign.total_contacts === 0 || startCampaignMutation.isPending
                          }
                        >
                          <Play className="mr-1 h-3 w-3" />
                          Start
                        </Button>
                      </>
                    )}
                    {campaign.status === "running" && (
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-7 px-2"
                        onClick={(e) => {
                          e.stopPropagation();
                          pauseCampaignMutation.mutate(campaign.id);
                        }}
                        disabled={pauseCampaignMutation.isPending}
                      >
                        <Pause className="mr-1 h-3 w-3" />
                        Pause
                      </Button>
                    )}
                    {campaign.status === "paused" && (
                      <>
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-7 px-2"
                          onClick={(e) => {
                            e.stopPropagation();
                            startCampaignMutation.mutate(campaign.id);
                          }}
                          disabled={startCampaignMutation.isPending}
                        >
                          <Play className="mr-1 h-3 w-3" />
                          Resume
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-7 px-2"
                          onClick={(e) => {
                            e.stopPropagation();
                            stopCampaignMutation.mutate(campaign.id);
                          }}
                          disabled={stopCampaignMutation.isPending}
                        >
                          <Square className="mr-1 h-3 w-3" />
                          Stop
                        </Button>
                      </>
                    )}
                    {(campaign.status === "completed" || campaign.status === "canceled") && (
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-7 px-2"
                        onClick={(e) => {
                          e.stopPropagation();
                          restartCampaignMutation.mutate(campaign.id);
                        }}
                        disabled={restartCampaignMutation.isPending}
                      >
                        <RotateCcw className="mr-1 h-3 w-3" />
                        Restart
                      </Button>
                    )}
                  </div>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-7 px-2"
                    onClick={(e) => {
                      e.stopPropagation();
                      void openStatsModal(campaign);
                    }}
                  >
                    <BarChart3 className="mr-1 h-3 w-3" />
                    Stats
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Create Campaign Modal */}
      <Dialog open={isCreateModalOpen} onOpenChange={setIsCreateModalOpen}>
        <DialogContent className="sm:max-w-[500px]">
          <DialogHeader>
            <DialogTitle>Create New Campaign</DialogTitle>
            <DialogDescription>
              Set up your outbound calling campaign with an agent and phone number.
            </DialogDescription>
          </DialogHeader>

          <form onSubmit={handleCreateCampaign}>
            <div className="grid gap-4 py-4">
              <div className="space-y-2">
                <Label htmlFor="name">Campaign Name *</Label>
                <Input
                  id="name"
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  placeholder="e.g., Q1 Sales Outreach"
                  required
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="description">Description</Label>
                <Textarea
                  id="description"
                  value={formData.description}
                  onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                  placeholder="Campaign description..."
                  rows={2}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="script">Campaign Script / Objective</Label>
                <Textarea
                  id="script"
                  value={formData.script}
                  onChange={(e) => setFormData({ ...formData, script: e.target.value })}
                  placeholder="e.g., Introduce our new product line, qualify interest, and book a demo..."
                  rows={3}
                />
                <p className="text-xs text-muted-foreground">
                  The AI agent will follow this script during calls
                </p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="campaignGreeting">Outbound Greeting</Label>
                <Textarea
                  id="campaignGreeting"
                  value={formData.campaign_greeting}
                  onChange={(e) => setFormData({ ...formData, campaign_greeting: e.target.value })}
                  placeholder="e.g., Hi {name}, this is Sarah from Acme Corp..."
                  rows={2}
                />
                <p className="text-xs text-muted-foreground">
                  Overrides the agent&apos;s default greeting for this campaign
                </p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="agent">Voice Agent *</Label>
                {agents.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    No agents available.{" "}
                    <Link href="/dashboard/agents" className="text-primary hover:underline">
                      Create an agent
                    </Link>{" "}
                    first.
                  </p>
                ) : (
                  <Select
                    value={formData.agent_id}
                    onValueChange={(value) => setFormData({ ...formData, agent_id: value })}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Select an agent" />
                    </SelectTrigger>
                    <SelectContent>
                      {agents.map((agent) => (
                        <SelectItem key={agent.id} value={agent.id}>
                          {agent.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              </div>

              <div className="space-y-2">
                <Label htmlFor="fromNumber">Call From *</Label>
                {phoneNumbers.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    No phone numbers available.{" "}
                    <Link href="/dashboard/phone-numbers" className="text-primary hover:underline">
                      Add a phone number
                    </Link>{" "}
                    first.
                  </p>
                ) : (
                  <Select
                    value={formData.from_phone_number}
                    onValueChange={(value) =>
                      setFormData({ ...formData, from_phone_number: value })
                    }
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Select a phone number" />
                    </SelectTrigger>
                    <SelectContent>
                      {phoneNumbers.map((phone) => (
                        <SelectItem key={phone.id} value={phone.phone_number}>
                          {phone.phone_number}
                          {phone.friendly_name && ` (${phone.friendly_name})`}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="callsPerMinute">Calls/Minute</Label>
                  <Input
                    id="callsPerMinute"
                    type="number"
                    min={1}
                    max={60}
                    value={formData.calls_per_minute}
                    onChange={(e) =>
                      setFormData({ ...formData, calls_per_minute: parseInt(e.target.value) || 5 })
                    }
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="maxConcurrent">Max Concurrent</Label>
                  <Input
                    id="maxConcurrent"
                    type="number"
                    min={1}
                    max={10}
                    value={formData.max_concurrent_calls}
                    onChange={(e) =>
                      setFormData({
                        ...formData,
                        max_concurrent_calls: parseInt(e.target.value) || 2,
                      })
                    }
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="maxAttempts">Max Attempts</Label>
                  <Input
                    id="maxAttempts"
                    type="number"
                    min={1}
                    max={10}
                    value={formData.max_attempts_per_contact}
                    onChange={(e) =>
                      setFormData({
                        ...formData,
                        max_attempts_per_contact: parseInt(e.target.value) || 3,
                      })
                    }
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="retryDelay">Retry Delay (min)</Label>
                  <Input
                    id="retryDelay"
                    type="number"
                    min={1}
                    max={1440}
                    value={formData.retry_delay_minutes}
                    onChange={(e) =>
                      setFormData({
                        ...formData,
                        retry_delay_minutes: parseInt(e.target.value) || 60,
                      })
                    }
                  />
                </div>
              </div>
            </div>

            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setIsCreateModalOpen(false)}>
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={
                  !formData.name ||
                  !formData.agent_id ||
                  !formData.from_phone_number ||
                  createCampaignMutation.isPending
                }
              >
                {createCampaignMutation.isPending && (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                )}
                Create Campaign
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Add Contacts Modal */}
      <Dialog open={isContactsModalOpen} onOpenChange={setIsContactsModalOpen}>
        <DialogContent className="sm:max-w-[500px]">
          <DialogHeader>
            <DialogTitle>Add Contacts to Campaign</DialogTitle>
            <DialogDescription>
              Select contacts to add to &quot;{selectedCampaign?.name}&quot;
            </DialogDescription>
          </DialogHeader>

          <div className="py-4">
            {contacts.length === 0 ? (
              <p className="text-center text-sm text-muted-foreground">
                No contacts available.{" "}
                <Link href="/dashboard/crm" className="text-primary hover:underline">
                  Add contacts
                </Link>{" "}
                first.
              </p>
            ) : (
              <>
                {/* Select All / Deselect All buttons */}
                <div className="mb-3 flex items-center justify-between">
                  <p className="text-sm text-muted-foreground">
                    {selectedContactIds.length} of {contacts.length} selected
                  </p>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={allContactsSelected ? deselectAllContacts : selectAllContacts}
                  >
                    {allContactsSelected ? "Deselect All" : "Select All"}
                  </Button>
                </div>
                <div className="max-h-[260px] space-y-2 overflow-y-auto">
                  {contacts.map((contact) => (
                    <div
                      key={contact.id}
                      className={`flex cursor-pointer items-center justify-between rounded-md border p-3 transition-colors ${
                        selectedContactIds.includes(contact.id)
                          ? "border-primary bg-primary/5"
                          : "hover:border-primary/50"
                      }`}
                      onClick={() => toggleContactSelection(contact.id)}
                    >
                      <div>
                        <p className="text-sm font-medium">
                          {contact.first_name} {contact.last_name}
                        </p>
                        <p className="text-xs text-muted-foreground">{contact.phone_number}</p>
                      </div>
                      <div
                        className={`h-4 w-4 rounded-full border-2 ${
                          selectedContactIds.includes(contact.id)
                            ? "border-primary bg-primary"
                            : "border-muted-foreground"
                        }`}
                      />
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setIsContactsModalOpen(false)}>
              Cancel
            </Button>
            <Button
              type="button"
              onClick={handleAddContacts}
              disabled={selectedContactIds.length === 0 || addContactsMutation.isPending}
            >
              {addContactsMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Add {selectedContactIds.length} Contact{selectedContactIds.length !== 1 ? "s" : ""}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Campaign Stats Modal */}
      <Dialog open={isStatsModalOpen} onOpenChange={setIsStatsModalOpen}>
        <DialogContent className="sm:max-w-[400px]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <BarChart3 className="h-5 w-5" />
              Campaign Statistics
            </DialogTitle>
            <DialogDescription>{selectedCampaign?.name}</DialogDescription>
          </DialogHeader>

          {selectedCampaignStats && (
            <div className="grid gap-4 py-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="rounded-md border p-3">
                  <p className="text-xs text-muted-foreground">Total Contacts</p>
                  <p className="text-xl font-semibold">{selectedCampaignStats.total_contacts}</p>
                </div>
                <div className="rounded-md border p-3">
                  <p className="text-xs text-muted-foreground">Completion Rate</p>
                  <p className="text-xl font-semibold">
                    {(selectedCampaignStats.completion_rate * 100).toFixed(1)}%
                  </p>
                </div>
              </div>

              <div className="grid grid-cols-3 gap-4">
                <div className="rounded-md border p-3">
                  <p className="text-xs text-muted-foreground">Pending</p>
                  <p className="text-lg font-semibold">{selectedCampaignStats.contacts_pending}</p>
                </div>
                <div className="rounded-md border p-3">
                  <p className="text-xs text-muted-foreground">Completed</p>
                  <p className="text-lg font-semibold text-green-600">
                    {selectedCampaignStats.contacts_completed}
                  </p>
                </div>
                <div className="rounded-md border p-3">
                  <p className="text-xs text-muted-foreground">Failed</p>
                  <p className="text-lg font-semibold text-red-600">
                    {selectedCampaignStats.contacts_failed}
                  </p>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="rounded-md border p-3">
                  <p className="text-xs text-muted-foreground">Total Calls Made</p>
                  <p className="text-lg font-semibold">{selectedCampaignStats.total_calls_made}</p>
                </div>
                <div className="rounded-md border p-3">
                  <p className="text-xs text-muted-foreground">Avg Call Duration</p>
                  <p className="text-lg font-semibold">
                    {Math.round(selectedCampaignStats.average_call_duration_seconds)}s
                  </p>
                </div>
              </div>

              <div className="rounded-md border p-3">
                <p className="text-xs text-muted-foreground">Total Call Duration</p>
                <p className="text-lg font-semibold">
                  {Math.round(selectedCampaignStats.total_call_duration_seconds / 60)} minutes
                </p>
              </div>
            </div>
          )}

          <DialogFooter>
            <Button type="button" onClick={() => setIsStatsModalOpen(false)}>
              Close
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <AlertDialog open={isDeleteDialogOpen} onOpenChange={setIsDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Campaign</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete &quot;{selectedCampaign?.name}&quot;? This action
              cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDeleteCampaign}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
