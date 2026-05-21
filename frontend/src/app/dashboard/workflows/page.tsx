"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { GitBranch, Plus, Trash2, Pencil } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
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
import { api } from "@/lib/api";
import { type Workflow, listWorkflows, createWorkflow, deleteWorkflow } from "@/lib/api/workflows";
import { WorkflowCanvas } from "./WorkflowCanvas";

interface WorkspaceOption {
  id: string;
  name: string;
}

export default function WorkflowsPage() {
  const qc = useQueryClient();
  const [workspaceId, setWorkspaceId] = useState("");
  const [selectedWorkflow, setSelectedWorkflow] = useState<Workflow | null>(null);
  const [newName, setNewName] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Workflow | null>(null);

  const { data: workspaces = [] } = useQuery<WorkspaceOption[]>({
    queryKey: ["workspaces-list"],
    queryFn: async () => {
      const res = await api.get<WorkspaceOption[]>("/api/v1/workspaces");
      return res.data;
    },
  });

  if (workspaces.length > 0 && !workspaceId && workspaces[0]) {
    setWorkspaceId(workspaces[0].id);
  }

  const { data: workflows = [] } = useQuery<Workflow[]>({
    queryKey: ["workflows", workspaceId],
    queryFn: () => listWorkflows(workspaceId),
    enabled: !!workspaceId,
  });

  const createMutation = useMutation({
    mutationFn: () => createWorkflow({ workspace_id: workspaceId, name: newName }),
    onSuccess: (wf) => {
      void qc.invalidateQueries({ queryKey: ["workflows", workspaceId] });
      setCreateOpen(false);
      setNewName("");
      setSelectedWorkflow(wf);
      toast.success("Workflow created");
    },
    onError: () => toast.error("Failed to create workflow"),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteWorkflow(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["workflows", workspaceId] });
      if (selectedWorkflow?.id === deleteTarget?.id) setSelectedWorkflow(null);
      setDeleteTarget(null);
      toast.success("Workflow deleted");
    },
    onError: () => toast.error("Failed to delete workflow"),
  });

  if (selectedWorkflow) {
    return (
      <WorkflowCanvas
        workflow={selectedWorkflow}
        onBack={() => setSelectedWorkflow(null)}
        onSaved={(updated) => {
          setSelectedWorkflow(updated);
          void qc.invalidateQueries({ queryKey: ["workflows", workspaceId] });
        }}
      />
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b px-6 py-4">
        <div className="flex items-center gap-2">
          <GitBranch className="h-5 w-5 text-indigo-500" />
          <h1 className="text-lg font-semibold">Workflows</h1>
        </div>
        <Button onClick={() => setCreateOpen(true)} disabled={!workspaceId}>
          <Plus className="mr-2 h-4 w-4" />
          New Workflow
        </Button>
      </div>

      {/* Workspace selector */}
      {workspaces.length > 1 && (
        <div className="border-b px-6 py-3">
          <select
            className="rounded border px-3 py-1 text-sm"
            value={workspaceId}
            onChange={(e) => setWorkspaceId(e.target.value)}
          >
            {workspaces.map((ws) => (
              <option key={ws.id} value={ws.id}>
                {ws.name}
              </option>
            ))}
          </select>
        </div>
      )}

      <div className="flex-1 overflow-y-auto p-6">
        {workflows.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-3 py-24 text-center text-gray-500">
            <GitBranch className="h-12 w-12 opacity-30" />
            <p className="text-sm">No workflows yet. Create one to get started.</p>
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {workflows.map((wf) => (
              <div
                key={wf.id}
                className="flex cursor-pointer items-start justify-between rounded-lg border bg-white p-4 shadow-sm hover:border-indigo-300 hover:shadow-md"
                onClick={() => setSelectedWorkflow(wf)}
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <GitBranch className="h-4 w-4 shrink-0 text-indigo-400" />
                    <span className="truncate font-medium">{wf.name}</span>
                  </div>
                  <div className="mt-1 text-xs text-gray-400">
                    {wf.nodes.length} nodes · {wf.edges.length} edges
                  </div>
                </div>
                <div className="ml-2 flex shrink-0 gap-1">
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7"
                    onClick={(e) => {
                      e.stopPropagation();
                      setSelectedWorkflow(wf);
                    }}
                  >
                    <Pencil className="h-3.5 w-3.5" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 text-red-400 hover:text-red-600"
                    onClick={(e) => {
                      e.stopPropagation();
                      setDeleteTarget(wf);
                    }}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Create dialog */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create Workflow</DialogTitle>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <Label>Name</Label>
            <Input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="e.g. AMEDTEC Service Workflow"
              onKeyDown={(e) => {
                if (e.key === "Enter" && newName.trim()) createMutation.mutate();
              }}
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => createMutation.mutate()}
              disabled={!newName.trim() || createMutation.isPending}
            >
              Create
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete dialog */}
      <AlertDialog open={!!deleteTarget} onOpenChange={() => setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete workflow?</AlertDialogTitle>
            <AlertDialogDescription>
              This will permanently delete <strong>{deleteTarget?.name}</strong>. Agents using this
              workflow will need to be reassigned.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-red-600 hover:bg-red-700"
              onClick={() => deleteTarget && deleteMutation.mutate(deleteTarget.id)}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
