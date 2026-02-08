"use client";

import { useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
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
import { Plus, Loader2, AlertCircle, FolderOpen, Users, Bot, Settings, Trash2 } from "lucide-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { useAuth } from "@/hooks/use-auth";
import { Badge } from "@/components/ui/badge";
import { InfoTooltip } from "@/components/ui/info-tooltip";

interface WorkspaceSettings {
  timezone?: string;
  business_hours?: Record<string, { start: string; end: string; enabled: boolean }>;
  booking_buffer_minutes?: number;
  max_advance_booking_days?: number;
  default_appointment_duration?: number;
  allow_same_day_booking?: boolean;
}

interface Workspace {
  id: string;
  user_id: number;
  name: string;
  description: string | null;
  settings: WorkspaceSettings;
  is_default: boolean;
  agent_count: number;
  contact_count: number;
}

interface WorkspaceAgent {
  agent_id: string;
  agent_name: string;
  is_default: boolean;
  pricing_tier: string;
}

type WorkspaceFormData = {
  name: string;
  description: string;
  timezone: string;
  booking_buffer_minutes: number;
  max_advance_booking_days: number;
  default_appointment_duration: number;
  allow_same_day_booking: boolean;
};

const TIMEZONES = [
  "America/New_York",
  "America/Chicago",
  "America/Denver",
  "America/Los_Angeles",
  "America/Phoenix",
  "America/Anchorage",
  "Pacific/Honolulu",
  "Europe/London",
  "Europe/Paris",
  "Europe/Berlin",
  "Asia/Tokyo",
  "Asia/Shanghai",
  "Asia/Singapore",
  "Australia/Sydney",
  "UTC",
];

const emptyFormData: WorkspaceFormData = {
  name: "",
  description: "",
  timezone: "America/New_York",
  booking_buffer_minutes: 15,
  max_advance_booking_days: 30,
  default_appointment_duration: 30,
  allow_same_day_booking: true,
};

export default function WorkspacesPage() {
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const isSuperAdmin = user?.role === "super_admin";
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isAgentsModalOpen, setIsAgentsModalOpen] = useState(false);
  const [isDeleteDialogOpen, setIsDeleteDialogOpen] = useState(false);
  const [modalMode, setModalMode] = useState<"add" | "edit" | "view">("add");
  const [selectedWorkspace, setSelectedWorkspace] = useState<Workspace | null>(null);
  const [formData, setFormData] = useState<WorkspaceFormData>(emptyFormData);

  // Fetch workspaces
  const {
    data: workspaces = [],
    isLoading,
    error,
  } = useQuery<Workspace[]>({
    queryKey: ["workspaces"],
    queryFn: async () => {
      const response = await api.get("/api/v1/workspaces");
      return response.data;
    },
  });

  // Fetch agents for selected workspace
  const { data: workspaceAgents = [], isLoading: isLoadingAgents } = useQuery<WorkspaceAgent[]>({
    queryKey: ["workspace-agents", selectedWorkspace?.id],
    queryFn: async () => {
      if (!selectedWorkspace) return [];
      const response = await api.get(`/api/v1/workspaces/${selectedWorkspace.id}/agents`);
      return response.data;
    },
    enabled: !!selectedWorkspace && isAgentsModalOpen,
  });

  // Create workspace mutation
  const createWorkspaceMutation = useMutation({
    mutationFn: async (data: WorkspaceFormData) => {
      const payload = {
        name: data.name,
        description: data.description || null,
        settings: {
          timezone: data.timezone,
          booking_buffer_minutes: data.booking_buffer_minutes,
          max_advance_booking_days: data.max_advance_booking_days,
          default_appointment_duration: data.default_appointment_duration,
          allow_same_day_booking: data.allow_same_day_booking,
        },
      };
      const response = await api.post("/api/v1/workspaces", payload);
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["workspaces"] });
      toast.success("Workspace created successfully");
      closeModal();
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to create workspace");
    },
  });

  // Update workspace mutation
  const updateWorkspaceMutation = useMutation({
    mutationFn: async ({ id, data }: { id: string; data: WorkspaceFormData }) => {
      const payload = {
        name: data.name,
        description: data.description || null,
        settings: {
          timezone: data.timezone,
          booking_buffer_minutes: data.booking_buffer_minutes,
          max_advance_booking_days: data.max_advance_booking_days,
          default_appointment_duration: data.default_appointment_duration,
          allow_same_day_booking: data.allow_same_day_booking,
        },
      };
      const response = await api.put(`/api/v1/workspaces/${id}`, payload);
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["workspaces"] });
      toast.success("Workspace updated successfully");
      closeModal();
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to update workspace");
    },
  });

  // Delete workspace mutation
  const deleteWorkspaceMutation = useMutation({
    mutationFn: async (id: string) => {
      try {
        await api.delete(`/api/v1/workspaces/${id}`);
      } catch (error) {
        // Extract error message from response
        if (error && typeof error === "object" && "response" in error) {
          const axiosError = error as {
            response?: { data?: { detail?: string }; status?: number };
          };
          if (axiosError.response?.status === 403) {
            throw new Error("Only super admins can delete workspaces");
          }
          if (axiosError.response?.data?.detail) {
            throw new Error(axiosError.response.data.detail);
          }
        }
        throw error;
      }
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["workspaces"] });
      toast.success("Workspace and associated users deleted successfully");
      closeModal();
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to delete workspace");
    },
  });

  const openAddModal = () => {
    setFormData(emptyFormData);
    setSelectedWorkspace(null);
    setModalMode("add");
    setIsModalOpen(true);
  };

  const openViewModal = (workspace: Workspace) => {
    setSelectedWorkspace(workspace);
    setFormData({
      name: workspace.name,
      description: workspace.description ?? "",
      timezone: workspace.settings.timezone ?? "America/New_York",
      booking_buffer_minutes: workspace.settings.booking_buffer_minutes ?? 15,
      max_advance_booking_days: workspace.settings.max_advance_booking_days ?? 30,
      default_appointment_duration: workspace.settings.default_appointment_duration ?? 30,
      allow_same_day_booking: workspace.settings.allow_same_day_booking ?? true,
    });
    setModalMode("view");
    setIsModalOpen(true);
  };

  const openAgentsModal = (workspace: Workspace) => {
    setSelectedWorkspace(workspace);
    setIsAgentsModalOpen(true);
  };

  const switchToEditMode = () => {
    setModalMode("edit");
  };

  const closeModal = () => {
    setIsModalOpen(false);
    setSelectedWorkspace(null);
    setFormData(emptyFormData);
  };

  const closeAgentsModal = () => {
    setIsAgentsModalOpen(false);
    setSelectedWorkspace(null);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (modalMode === "add") {
      createWorkspaceMutation.mutate(formData);
    } else if (modalMode === "edit" && selectedWorkspace) {
      updateWorkspaceMutation.mutate({ id: selectedWorkspace.id, data: formData });
    }
  };

  const handleDelete = () => {
    if (selectedWorkspace) {
      if (selectedWorkspace.is_default) {
        toast.error("Cannot delete the default workspace");
        return;
      }
      setIsDeleteDialogOpen(true);
    }
  };

  const confirmDelete = () => {
    if (selectedWorkspace) {
      deleteWorkspaceMutation.mutate(selectedWorkspace.id);
    }
    setIsDeleteDialogOpen(false);
  };

  const isSubmitting = createWorkspaceMutation.isPending || updateWorkspaceMutation.isPending;

  if (error) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-xl font-semibold">Workspaces</h1>
          <p className="text-sm text-muted-foreground">
            Organize your agents, contacts, and appointments into separate workspaces
          </p>
        </div>
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12">
            <AlertCircle className="mb-4 h-12 w-12 text-destructive" />
            <h3 className="mb-2 text-lg font-semibold">Failed to load workspaces</h3>
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
          <h1 className="text-xl font-semibold">Workspaces</h1>
          <p className="text-sm text-muted-foreground">
            Organize your agents, contacts, and appointments
          </p>
        </div>
        <Button size="sm" onClick={openAddModal}>
          <Plus className="mr-2 h-4 w-4" />
          New Workspace
        </Button>
      </div>

      {/* Stats Cards */}
      <div className="grid gap-3 md:grid-cols-3">
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-muted-foreground">Total Workspaces</p>
                <p className="text-lg font-semibold">{workspaces.length}</p>
              </div>
              <FolderOpen className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-muted-foreground">Total Contacts</p>
                <p className="text-lg font-semibold">
                  {workspaces.reduce((sum, w) => sum + w.contact_count, 0)}
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
                <p className="text-xs text-muted-foreground">Assigned Agents</p>
                <p className="text-lg font-semibold">
                  {workspaces.reduce((sum, w) => sum + w.agent_count, 0)}
                </p>
              </div>
              <Bot className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Workspaces List */}
      {isLoading ? (
        <Card>
          <CardContent className="flex items-center justify-center py-16">
            <p className="text-muted-foreground">Loading workspaces...</p>
          </CardContent>
        </Card>
      ) : workspaces.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16">
            <FolderOpen className="mb-4 h-16 w-16 text-muted-foreground/50" />
            <h3 className="mb-2 text-lg font-semibold">No workspaces yet</h3>
            <p className="mb-4 max-w-sm text-center text-sm text-muted-foreground">
              Create workspaces to organize your agents, contacts, and appointments
            </p>
            <Button onClick={openAddModal}>
              <Plus className="mr-2 h-4 w-4" />
              Create Your First Workspace
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {workspaces.map((workspace) => (
            <Card
              key={workspace.id}
              className="group cursor-pointer transition-all hover:border-primary/50"
              onClick={() => openViewModal(workspace)}
            >
              <CardContent className="p-4">
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2.5 overflow-hidden">
                    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-primary/10">
                      <FolderOpen className="h-4 w-4 text-primary" />
                    </div>
                    <div className="min-w-0">
                      <h3 className="truncate text-sm font-medium">{workspace.name}</h3>
                      <p className="truncate text-xs text-muted-foreground">
                        {workspace.settings.timezone ?? "No timezone"}
                      </p>
                    </div>
                  </div>
                  {workspace.is_default && (
                    <Badge variant="secondary" className="h-5 shrink-0 px-1.5 text-[10px]">
                      Default
                    </Badge>
                  )}
                </div>

                <div className="mt-3 flex items-center gap-3 text-xs text-muted-foreground">
                  <div className="flex items-center gap-1">
                    <Users className="h-3 w-3" />
                    <span>{workspace.contact_count}</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <Bot className="h-3 w-3" />
                    <span>{workspace.agent_count}</span>
                  </div>
                </div>

                <div className="mt-3 flex gap-2 border-t border-border/50 pt-3">
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 flex-1 text-xs"
                    onClick={(e) => {
                      e.stopPropagation();
                      openViewModal(workspace);
                    }}
                  >
                    <Settings className="mr-1 h-3 w-3" />
                    Settings
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 flex-1 text-xs"
                    onClick={(e) => {
                      e.stopPropagation();
                      openAgentsModal(workspace);
                    }}
                  >
                    <Bot className="mr-1 h-3 w-3" />
                    Agents
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Workspace Settings Modal */}
      <Dialog open={isModalOpen} onOpenChange={setIsModalOpen}>
        <DialogContent className="sm:max-w-[550px]">
          <DialogHeader>
            <DialogTitle>
              {modalMode === "add" && "Create New Workspace"}
              {modalMode === "edit" && "Edit Workspace"}
              {modalMode === "view" && "Workspace Settings"}
            </DialogTitle>
            <DialogDescription>
              {modalMode === "add" &&
                "Create a new workspace to organize your agents and CRM data."}
              {modalMode === "edit" && "Update workspace settings."}
              {modalMode === "view" && "View and manage workspace settings."}
            </DialogDescription>
          </DialogHeader>

          <form onSubmit={handleSubmit}>
            <div className="grid gap-4 py-4">
              <div className="space-y-2">
                <Label htmlFor="name">Workspace Name *</Label>
                <Input
                  id="name"
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  disabled={modalMode === "view"}
                  required
                  placeholder="e.g., Sales Team, Support, Marketing"
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="description">Description</Label>
                <Textarea
                  id="description"
                  value={formData.description}
                  onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                  disabled={modalMode === "view"}
                  rows={2}
                  placeholder="Describe what this workspace is for..."
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="timezone">Timezone</Label>
                <Select
                  value={formData.timezone}
                  onValueChange={(value) => setFormData({ ...formData, timezone: value })}
                  disabled={modalMode === "view"}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select timezone" />
                  </SelectTrigger>
                  <SelectContent>
                    {TIMEZONES.map((tz) => (
                      <SelectItem key={tz} value={tz}>
                        {tz}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label
                    htmlFor="default_appointment_duration"
                    className="flex items-center gap-1.5"
                  >
                    Default Duration (min)
                    <InfoTooltip content="Standard length of appointments in this workspace. Can be overridden per appointment. 30-60 minutes is typical for most services." />
                  </Label>
                  <Input
                    id="default_appointment_duration"
                    type="number"
                    min="5"
                    max="480"
                    value={formData.default_appointment_duration}
                    onChange={(e) =>
                      setFormData({
                        ...formData,
                        default_appointment_duration: parseInt(e.target.value) || 30,
                      })
                    }
                    disabled={modalMode === "view"}
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="booking_buffer_minutes" className="flex items-center gap-1.5">
                    Buffer Time (min)
                    <InfoTooltip content="Gap between appointments for preparation or travel. A 15-min buffer means a 30-min appointment blocks a 45-min slot. Prevents back-to-back scheduling." />
                  </Label>
                  <Input
                    id="booking_buffer_minutes"
                    type="number"
                    min="0"
                    max="120"
                    value={formData.booking_buffer_minutes}
                    onChange={(e) =>
                      setFormData({
                        ...formData,
                        booking_buffer_minutes: parseInt(e.target.value) || 0,
                      })
                    }
                    disabled={modalMode === "view"}
                  />
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="max_advance_booking_days" className="flex items-center gap-1.5">
                  Max Advance Booking (days)
                  <InfoTooltip content="How far in the future customers can book appointments. 30 days is typical. Lower values give more control over your schedule." />
                </Label>
                <Input
                  id="max_advance_booking_days"
                  type="number"
                  min="1"
                  max="365"
                  value={formData.max_advance_booking_days}
                  onChange={(e) =>
                    setFormData({
                      ...formData,
                      max_advance_booking_days: parseInt(e.target.value) || 30,
                    })
                  }
                  disabled={modalMode === "view"}
                />
              </div>

              <div className="flex items-center justify-between rounded-lg border p-4">
                <div className="space-y-0.5">
                  <Label htmlFor="allow_same_day_booking" className="flex items-center gap-1.5">
                    Allow Same-Day Booking
                    <InfoTooltip content="Whether customers can book appointments for today. Disable for services needing preparation time (e.g., consultations, inspections)." />
                  </Label>
                  <p className="text-sm text-muted-foreground">
                    Allow customers to book appointments for today
                  </p>
                </div>
                <Switch
                  id="allow_same_day_booking"
                  checked={formData.allow_same_day_booking}
                  onCheckedChange={(checked) =>
                    setFormData({ ...formData, allow_same_day_booking: checked })
                  }
                  disabled={modalMode === "view"}
                />
              </div>
            </div>

            <DialogFooter className="gap-2">
              {modalMode === "view" && (
                <>
                  {isSuperAdmin && !selectedWorkspace?.is_default && (
                    <Button
                      type="button"
                      variant="destructive"
                      onClick={handleDelete}
                      disabled={deleteWorkspaceMutation.isPending}
                    >
                      {deleteWorkspaceMutation.isPending ? (
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      ) : (
                        <Trash2 className="mr-2 h-4 w-4" />
                      )}
                      Delete
                    </Button>
                  )}
                  <Button type="button" onClick={switchToEditMode}>
                    Edit Workspace
                  </Button>
                </>
              )}
              {(modalMode === "add" || modalMode === "edit") && (
                <>
                  <Button type="button" variant="outline" onClick={closeModal}>
                    Cancel
                  </Button>
                  <Button type="submit" disabled={isSubmitting}>
                    {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                    {modalMode === "add" ? "Create Workspace" : "Save Changes"}
                  </Button>
                </>
              )}
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Workspace Agents Modal */}
      <Dialog open={isAgentsModalOpen} onOpenChange={setIsAgentsModalOpen}>
        <DialogContent className="sm:max-w-[500px]">
          <DialogHeader>
            <DialogTitle>Agents in {selectedWorkspace?.name}</DialogTitle>
            <DialogDescription>
              View and manage which agents are assigned to this workspace.
            </DialogDescription>
          </DialogHeader>

          <div className="py-4">
            {isLoadingAgents ? (
              <div className="flex flex-col items-center justify-center py-8">
                <Loader2 className="mb-4 h-8 w-8 animate-spin text-muted-foreground" />
                <p className="text-sm text-muted-foreground">Loading agents...</p>
              </div>
            ) : workspaceAgents.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-8 text-center">
                <div className="mb-4 rounded-full bg-muted p-3">
                  <Bot className="h-6 w-6 text-muted-foreground" />
                </div>
                <p className="text-lg font-medium">No agents assigned</p>
                <p className="mb-4 text-sm text-muted-foreground">
                  Assign agents to this workspace from the Voice Agents page
                </p>
              </div>
            ) : (
              <div className="space-y-3">
                {workspaceAgents.map((agent) => (
                  <div
                    key={agent.agent_id}
                    className="flex items-center justify-between rounded-lg border p-3"
                  >
                    <div className="flex items-center gap-3">
                      <div className="flex h-10 w-10 items-center justify-center rounded-full bg-primary/10">
                        <Bot className="h-5 w-5 text-primary" />
                      </div>
                      <div>
                        <p className="font-medium">{agent.agent_name}</p>
                        <div className="flex items-center gap-2">
                          <Badge variant="outline" className="text-xs">
                            {agent.pricing_tier}
                          </Badge>
                          {agent.is_default && (
                            <Badge variant="secondary" className="text-xs">
                              Default
                            </Badge>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={closeAgentsModal}>
              Close
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Workspace Confirmation Dialog */}
      <AlertDialog open={isDeleteDialogOpen} onOpenChange={setIsDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Workspace</AlertDialogTitle>
            <AlertDialogDescription className="space-y-2">
              <p>
                Are you sure you want to delete <strong>{selectedWorkspace?.name}</strong>?
              </p>
              <p className="font-semibold text-destructive">
                Warning: All users who are members of this workspace will also be permanently
                deleted.
              </p>
              <p>This action cannot be undone.</p>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={confirmDelete}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Delete Workspace and Users
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
