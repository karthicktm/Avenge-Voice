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
  Phone,
  PhoneOutgoing,
  Mail,
  Building2,
  Tag,
  Loader2,
  AlertCircle,
  X,
  FolderOpen,
} from "lucide-react";
import { InfoTooltip } from "@/components/ui/info-tooltip";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { fetchAgents, type Agent } from "@/lib/api/agents";
import {
  initiateCall,
  listPhoneNumbers,
  type PhoneNumber,
  type Provider,
} from "@/lib/api/telephony";
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
  user_id: number;
  workspace_id: string | null;
  first_name: string;
  last_name: string | null;
  email: string | null;
  phone_number: string;
  company_name: string | null;
  status: string;
  tags: string | null;
  notes: string | null;
}

type ContactFormData = {
  first_name: string;
  last_name: string;
  email: string;
  phone_number: string;
  company_name: string;
  status: string;
  tags: string;
  notes: string;
  workspace_id: string;
};

const emptyFormData: ContactFormData = {
  first_name: "",
  last_name: "",
  email: "",
  phone_number: "",
  company_name: "",
  status: "new",
  tags: "",
  notes: "",
  workspace_id: "",
};

// Type for validation errors from 422 responses
interface ValidationError {
  loc: (string | number)[];
  msg: string;
  type: string;
}

interface FieldErrors {
  [key: string]: string;
}

// Parse validation errors from FastAPI 422 response
function parseValidationErrors(error: unknown): FieldErrors {
  const fieldErrors: FieldErrors = {};

  if (error && typeof error === "object" && "response" in error) {
    const response = (error as { response?: { data?: { detail?: ValidationError[] } } }).response;
    const detail = response?.data?.detail;

    if (Array.isArray(detail)) {
      for (const err of detail) {
        // Get the field name from loc array (usually ['body', 'field_name'])
        const fieldName = err.loc[err.loc.length - 1];
        if (typeof fieldName === "string") {
          // Make error messages more user-friendly
          let message = err.msg;
          // Replace "Value error, " prefix from Pydantic validators
          message = message.replace(/^Value error,\s*/i, "");
          // Capitalize first letter
          message = message.charAt(0).toUpperCase() + message.slice(1);
          fieldErrors[fieldName] = message;
        }
      }
    }
  }

  return fieldErrors;
}

export default function CRMPage() {
  const queryClient = useQueryClient();
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [modalMode, setModalMode] = useState<"add" | "edit" | "view">("add");
  const [selectedContact, setSelectedContact] = useState<Contact | null>(null);
  const [formData, setFormData] = useState<ContactFormData>(emptyFormData);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState<string>("all");
  const [isDeleteDialogOpen, setIsDeleteDialogOpen] = useState(false);
  const [isCallModalOpen, setIsCallModalOpen] = useState(false);
  const [selectedAgentId, setSelectedAgentId] = useState<string>("");
  const [selectedFromNumber, setSelectedFromNumber] = useState<string>("");

  // Fetch workspaces
  const { data: workspaces = [] } = useQuery<Workspace[]>({
    queryKey: ["workspaces"],
    queryFn: async () => {
      const response = await api.get("/api/v1/workspaces");
      return response.data;
    },
  });

  const {
    data: contacts = [],
    isLoading,
    error,
  } = useQuery<Contact[]>({
    queryKey: ["contacts", selectedWorkspaceId],
    queryFn: async () => {
      const url =
        selectedWorkspaceId && selectedWorkspaceId !== "all"
          ? `/api/v1/crm/contacts?workspace_id=${selectedWorkspaceId}`
          : "/api/v1/crm/contacts";
      const response = await api.get(url);
      return response.data;
    },
  });

  // Get the active workspace ID for fetching agents and phone numbers
  const activeWorkspaceId = selectedWorkspaceId !== "all" ? selectedWorkspaceId : workspaces[0]?.id;

  // Fetch agents for calling
  const { data: agents = [] } = useQuery<Agent[]>({
    queryKey: ["agents"],
    queryFn: () => fetchAgents(),
  });

  // Fetch phone numbers from both providers
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

  const createContactMutation = useMutation({
    mutationFn: async (data: ContactFormData) => {
      const response = await api.post("/api/v1/crm/contacts", data);
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["contacts"] });
      toast.success("Contact created successfully");
      setFieldErrors({});
      closeModal();
    },
    onError: (error: unknown) => {
      const errors = parseValidationErrors(error);
      if (Object.keys(errors).length > 0) {
        setFieldErrors(errors);
        // Show a summary toast with the first error
        const firstError = Object.values(errors)[0];
        toast.error(`Validation error: ${firstError}`);
      } else {
        const message = error instanceof Error ? error.message : "Failed to create contact";
        toast.error(message);
      }
    },
  });

  const updateContactMutation = useMutation({
    mutationFn: async ({ id, data }: { id: number; data: ContactFormData }) => {
      const response = await api.put(`/api/v1/crm/contacts/${id}`, data);
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["contacts"] });
      toast.success("Contact updated successfully");
      setFieldErrors({});
      closeModal();
    },
    onError: (error: unknown) => {
      const errors = parseValidationErrors(error);
      if (Object.keys(errors).length > 0) {
        setFieldErrors(errors);
        const firstError = Object.values(errors)[0];
        toast.error(`Validation error: ${firstError}`);
      } else {
        const message = error instanceof Error ? error.message : "Failed to update contact";
        toast.error(message);
      }
    },
  });

  const deleteContactMutation = useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`/api/v1/crm/contacts/${id}`);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["contacts"] });
      toast.success("Contact deleted successfully");
      closeModal();
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to delete contact");
    },
  });

  const initiateCallMutation = useMutation({
    mutationFn: async ({
      toNumber,
      fromNumber,
      agentId,
    }: {
      toNumber: string;
      fromNumber: string;
      agentId: string;
    }) => {
      if (!activeWorkspaceId) throw new Error("No workspace available");
      return initiateCall(
        {
          to_number: toNumber,
          from_number: fromNumber,
          agent_id: agentId,
        },
        activeWorkspaceId
      );
    },
    onSuccess: (data) => {
      toast.success(`Call initiated! Call ID: ${data.call_id}`);
      setIsCallModalOpen(false);
      setSelectedAgentId("");
      setSelectedFromNumber("");
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to initiate call");
    },
  });

  const openCallModal = () => {
    if (!selectedContact) return;
    // Pre-select first agent and phone number if available
    if (agents.length > 0 && !selectedAgentId && agents[0]) {
      setSelectedAgentId(agents[0].id);
    }
    if (phoneNumbers.length > 0 && !selectedFromNumber && phoneNumbers[0]) {
      setSelectedFromNumber(phoneNumbers[0].phone_number);
    }
    setIsCallModalOpen(true);
  };

  const handleInitiateCall = () => {
    if (!selectedContact || !selectedAgentId || !selectedFromNumber) {
      toast.error("Please select an agent and phone number");
      return;
    }
    initiateCallMutation.mutate({
      toNumber: selectedContact.phone_number,
      fromNumber: selectedFromNumber,
      agentId: selectedAgentId,
    });
  };

  const openAddModal = () => {
    // Pre-fill workspace_id if a workspace is selected
    const defaultWorkspaceId =
      selectedWorkspaceId !== "all" ? selectedWorkspaceId : (workspaces[0]?.id ?? "");
    setFormData({ ...emptyFormData, workspace_id: defaultWorkspaceId });
    setSelectedContact(null);
    setModalMode("add");
    setIsModalOpen(true);
  };

  const openViewModal = (contact: Contact) => {
    setSelectedContact(contact);
    setFormData({
      first_name: contact.first_name,
      last_name: contact.last_name ?? "",
      email: contact.email ?? "",
      phone_number: contact.phone_number,
      company_name: contact.company_name ?? "",
      status: contact.status,
      tags: contact.tags ?? "",
      notes: contact.notes ?? "",
      workspace_id: contact.workspace_id ?? "",
    });
    setModalMode("view");
    setIsModalOpen(true);
  };

  const switchToEditMode = () => {
    setModalMode("edit");
  };

  const closeModal = () => {
    setIsModalOpen(false);
    setSelectedContact(null);
    setFormData(emptyFormData);
    setFieldErrors({});
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (modalMode === "add") {
      createContactMutation.mutate(formData);
    } else if (modalMode === "edit" && selectedContact) {
      updateContactMutation.mutate({ id: selectedContact.id, data: formData });
    }
  };

  const handleDelete = () => {
    setIsDeleteDialogOpen(true);
  };

  const confirmDelete = () => {
    if (selectedContact) {
      deleteContactMutation.mutate(selectedContact.id);
    }
    setIsDeleteDialogOpen(false);
  };

  const getStatusColor = (status: string) => {
    const colors: Record<string, string> = {
      new: "bg-blue-100 text-blue-800",
      contacted: "bg-yellow-100 text-yellow-800",
      qualified: "bg-green-100 text-green-800",
      converted: "bg-purple-100 text-purple-800",
      lost: "bg-gray-100 text-gray-800",
    };
    return colors[status] ?? "bg-gray-100 text-gray-800";
  };

  const isSubmitting = createContactMutation.isPending || updateContactMutation.isPending;

  if (error) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-xl font-semibold">CRM</h1>
          <p className="text-sm text-muted-foreground">
            Manage your contacts, appointments, and call interactions
          </p>
        </div>
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12">
            <AlertCircle className="mb-4 h-12 w-12 text-destructive" />
            <h3 className="mb-2 text-lg font-semibold">Failed to load contacts</h3>
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
          <h1 className="text-xl font-semibold">CRM</h1>
          <p className="text-sm text-muted-foreground">Manage your contacts and interactions</p>
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
          <Button size="sm" onClick={openAddModal}>
            <Plus className="mr-2 h-4 w-4" />
            Add Contact
          </Button>
        </div>
      </div>

      {/* Stats Cards */}
      <div className="grid gap-3 md:grid-cols-3">
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-muted-foreground">Total Contacts</p>
                <p className="text-lg font-semibold">{contacts.length}</p>
              </div>
              <Phone className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-muted-foreground">Appointments</p>
                <p className="text-lg font-semibold">0</p>
              </div>
              <Building2 className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-muted-foreground">Call Interactions</p>
                <p className="text-lg font-semibold">0</p>
              </div>
              <Phone className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Contacts List */}
      {isLoading ? (
        <Card>
          <CardContent className="flex items-center justify-center py-16">
            <p className="text-muted-foreground">Loading contacts...</p>
          </CardContent>
        </Card>
      ) : contacts.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16">
            <Phone className="mb-4 h-16 w-16 text-muted-foreground/50" />
            <h3 className="mb-2 text-lg font-semibold">No contacts yet</h3>
            <p className="mb-4 max-w-sm text-center text-sm text-muted-foreground">
              Add contacts manually or they&apos;ll be created automatically from voice agent calls
            </p>
            <Button size="sm" onClick={openAddModal}>
              <Plus className="mr-2 h-4 w-4" />
              Add Your First Contact
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {contacts.map((contact) => (
            <Card
              key={contact.id}
              className="group cursor-pointer transition-all hover:border-primary/50"
              onClick={() => openViewModal(contact)}
            >
              <CardContent className="p-4">
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2.5 overflow-hidden">
                    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-primary/10">
                      <Phone className="h-4 w-4 text-primary" />
                    </div>
                    <div className="min-w-0">
                      <h3 className="truncate text-sm font-medium">
                        {contact.first_name} {contact.last_name}
                      </h3>
                      <p className="truncate text-xs text-muted-foreground">
                        {contact.phone_number}
                      </p>
                    </div>
                  </div>
                  <span
                    className={`inline-flex h-5 shrink-0 items-center rounded-full px-1.5 text-[10px] font-medium ${getStatusColor(contact.status)}`}
                  >
                    {contact.status}
                  </span>
                </div>

                <div className="mt-3 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                  {contact.email && (
                    <div className="flex items-center gap-1">
                      <Mail className="h-3 w-3" />
                      <span className="truncate">{contact.email}</span>
                    </div>
                  )}
                  {contact.company_name && (
                    <div className="flex items-center gap-1">
                      <Building2 className="h-3 w-3" />
                      <span className="truncate">{contact.company_name}</span>
                    </div>
                  )}
                </div>

                {contact.tags && (
                  <div className="mt-2.5 flex items-center gap-1 border-t border-border/50 pt-2.5 text-xs text-muted-foreground">
                    <Tag className="h-3 w-3" />
                    <span className="truncate">{contact.tags}</span>
                  </div>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Contact Modal */}
      <Dialog open={isModalOpen} onOpenChange={setIsModalOpen}>
        <DialogContent className="sm:max-w-[500px]">
          <DialogHeader>
            <DialogTitle className="flex items-center justify-between">
              {modalMode === "add" && "Add New Contact"}
              {modalMode === "edit" && "Edit Contact"}
              {modalMode === "view" && "Contact Details"}
            </DialogTitle>
            <DialogDescription>
              {modalMode === "add" && "Fill in the contact information below."}
              {modalMode === "edit" && "Update the contact information."}
              {modalMode === "view" && "View and manage contact information."}
            </DialogDescription>
          </DialogHeader>

          <form onSubmit={handleSubmit}>
            <div className="grid gap-4 py-4">
              {/* Required fields note */}
              {modalMode !== "view" && (
                <p className="text-xs text-muted-foreground">
                  Fields marked with <span className="text-destructive">*</span> are required
                </p>
              )}

              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label
                    htmlFor="first_name"
                    className={fieldErrors.first_name ? "text-destructive" : ""}
                  >
                    First Name <span className="text-destructive">*</span>
                  </Label>
                  <Input
                    id="first_name"
                    value={formData.first_name}
                    onChange={(e) => {
                      setFormData({ ...formData, first_name: e.target.value });
                      if (fieldErrors.first_name) {
                        setFieldErrors({ ...fieldErrors, first_name: "" });
                      }
                    }}
                    disabled={modalMode === "view"}
                    className={fieldErrors.first_name ? "border-destructive" : ""}
                    placeholder="Required"
                  />
                  {fieldErrors.first_name && (
                    <p className="text-xs text-destructive">{fieldErrors.first_name}</p>
                  )}
                </div>
                <div className="space-y-2">
                  <Label htmlFor="last_name">Last Name</Label>
                  <Input
                    id="last_name"
                    value={formData.last_name}
                    onChange={(e) => setFormData({ ...formData, last_name: e.target.value })}
                    disabled={modalMode === "view"}
                    placeholder="Optional"
                  />
                </div>
              </div>

              <div className="space-y-2">
                <Label
                  htmlFor="phone_number"
                  className={fieldErrors.phone_number ? "text-destructive" : ""}
                >
                  Phone Number <span className="text-destructive">*</span>
                </Label>
                <Input
                  id="phone_number"
                  type="tel"
                  value={formData.phone_number}
                  onChange={(e) => {
                    setFormData({ ...formData, phone_number: e.target.value });
                    if (fieldErrors.phone_number) {
                      setFieldErrors({ ...fieldErrors, phone_number: "" });
                    }
                  }}
                  disabled={modalMode === "view"}
                  className={fieldErrors.phone_number ? "border-destructive" : ""}
                  placeholder="Required (7-20 digits)"
                />
                {fieldErrors.phone_number && (
                  <p className="text-xs text-destructive">{fieldErrors.phone_number}</p>
                )}
              </div>

              <div className="space-y-2">
                <Label htmlFor="email" className={fieldErrors.email ? "text-destructive" : ""}>
                  Email
                </Label>
                <Input
                  id="email"
                  type="email"
                  value={formData.email}
                  onChange={(e) => {
                    setFormData({ ...formData, email: e.target.value });
                    if (fieldErrors.email) {
                      setFieldErrors({ ...fieldErrors, email: "" });
                    }
                  }}
                  disabled={modalMode === "view"}
                  className={fieldErrors.email ? "border-destructive" : ""}
                  placeholder="Optional"
                />
                {fieldErrors.email && (
                  <p className="text-xs text-destructive">{fieldErrors.email}</p>
                )}
              </div>

              <div className="space-y-2">
                <Label htmlFor="company_name">Company</Label>
                <Input
                  id="company_name"
                  value={formData.company_name}
                  onChange={(e) => setFormData({ ...formData, company_name: e.target.value })}
                  disabled={modalMode === "view"}
                  placeholder="Optional"
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="status" className="flex items-center gap-1">
                  Status
                  <InfoTooltip content="Track where this contact is in your sales pipeline. New = first contact, Contacted = reached out, Qualified = good fit, Converted = became a customer, Lost = not interested." />
                </Label>
                <Select
                  value={formData.status}
                  onValueChange={(value) => setFormData({ ...formData, status: value })}
                  disabled={modalMode === "view"}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select status" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="new">New</SelectItem>
                    <SelectItem value="contacted">Contacted</SelectItem>
                    <SelectItem value="qualified">Qualified</SelectItem>
                    <SelectItem value="converted">Converted</SelectItem>
                    <SelectItem value="lost">Lost</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              {workspaces.length > 0 && (
                <div className="space-y-2">
                  <Label htmlFor="workspace">
                    <span className="flex items-center gap-2">
                      <FolderOpen className="h-4 w-4" />
                      Workspace
                      <InfoTooltip content="Assign this contact to a workspace. Workspaces help organize contacts, appointments, and agents for different businesses or projects." />
                    </span>
                  </Label>
                  <Select
                    value={formData.workspace_id}
                    onValueChange={(value) => setFormData({ ...formData, workspace_id: value })}
                    disabled={modalMode === "view"}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Select workspace" />
                    </SelectTrigger>
                    <SelectContent>
                      {workspaces.map((ws) => (
                        <SelectItem key={ws.id} value={ws.id}>
                          {ws.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              )}

              <div className="space-y-2">
                <Label htmlFor="tags" className="flex items-center gap-1">
                  Tags
                  <InfoTooltip content="Add comma-separated labels to categorize contacts. Use tags like VIP, Enterprise, or Lead to filter and organize your contacts." />
                </Label>
                <Input
                  id="tags"
                  value={formData.tags}
                  onChange={(e) => setFormData({ ...formData, tags: e.target.value })}
                  disabled={modalMode === "view"}
                  placeholder="e.g., VIP, Enterprise, Lead"
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="notes">Notes</Label>
                <Textarea
                  id="notes"
                  value={formData.notes}
                  onChange={(e) => setFormData({ ...formData, notes: e.target.value })}
                  disabled={modalMode === "view"}
                  rows={3}
                />
              </div>
            </div>

            <DialogFooter className="gap-2">
              {modalMode === "view" && (
                <>
                  <Button
                    type="button"
                    variant="destructive"
                    onClick={handleDelete}
                    disabled={deleteContactMutation.isPending}
                  >
                    {deleteContactMutation.isPending ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    ) : (
                      <X className="mr-2 h-4 w-4" />
                    )}
                    Delete
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={openCallModal}
                    disabled={agents.length === 0 || phoneNumbers.length === 0}
                  >
                    <PhoneOutgoing className="mr-2 h-4 w-4" />
                    Call
                  </Button>
                  <Button type="button" onClick={switchToEditMode}>
                    Edit Contact
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
                    {modalMode === "add" ? "Create Contact" : "Save Changes"}
                  </Button>
                </>
              )}
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <AlertDialog open={isDeleteDialogOpen} onOpenChange={setIsDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Contact</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete {selectedContact?.first_name}{" "}
              {selectedContact?.last_name}? This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={confirmDelete}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Call Modal */}
      <Dialog open={isCallModalOpen} onOpenChange={setIsCallModalOpen}>
        <DialogContent className="sm:max-w-[400px]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <PhoneOutgoing className="h-5 w-5" />
              Initiate Call
            </DialogTitle>
            <DialogDescription>
              Call {selectedContact?.first_name} {selectedContact?.last_name} at{" "}
              {selectedContact?.phone_number}
            </DialogDescription>
          </DialogHeader>

          <div className="grid gap-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="agent">Select Agent</Label>
              {agents.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No agents available.{" "}
                  <Link href="/dashboard/agents" className="text-primary hover:underline">
                    Create an agent
                  </Link>{" "}
                  first.
                </p>
              ) : (
                <Select value={selectedAgentId} onValueChange={setSelectedAgentId}>
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
              <Label htmlFor="fromNumber">Call From</Label>
              {phoneNumbers.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No phone numbers available.{" "}
                  <Link href="/dashboard/phone-numbers" className="text-primary hover:underline">
                    Add a phone number
                  </Link>{" "}
                  first.
                </p>
              ) : (
                <Select value={selectedFromNumber} onValueChange={setSelectedFromNumber}>
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
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setIsCallModalOpen(false)}>
              Cancel
            </Button>
            <Button
              type="button"
              onClick={handleInitiateCall}
              disabled={!selectedAgentId || !selectedFromNumber || initiateCallMutation.isPending}
            >
              {initiateCallMutation.isPending ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Phone className="mr-2 h-4 w-4" />
              )}
              Start Call
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
