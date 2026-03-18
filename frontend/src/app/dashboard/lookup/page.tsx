"use client";

import { useRef, useState } from "react";
import { useAuth } from "@/hooks/use-auth";
import { api } from "@/lib/api";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Database,
  Plus,
  Upload,
  Download,
  Trash2,
  Edit2,
  Search,
  ChevronRight,
  Loader2,
  AlertCircle,
  ToggleLeft,
  ToggleRight,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
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
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  listCollections,
  createCollection,
  updateCollection,
  deleteCollection,
  listRecords,
  createRecord,
  updateRecord,
  deleteRecord,
  importRecords,
  exportUrl,
  getLookupStats,
  type LookupCollection,
  type LookupRecord,
  type CollectionCreate,
  type RecordCreate,
} from "@/lib/api/lookup";

// ---------------------------------------------------------------------------
// Domain colour mapping
// ---------------------------------------------------------------------------

const DOMAIN_COLORS: Record<string, string> = {
  property: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  faq: "bg-amber-500/20 text-amber-400 border-amber-500/30",
  product: "bg-violet-500/20 text-violet-400 border-violet-500/30",
  staff: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
  custom: "bg-slate-500/20 text-slate-400 border-slate-500/30",
};

function domainColor(domain: string): string {
  const key = domain.startsWith("custom") ? "custom" : domain;
  return DOMAIN_COLORS[key] ?? DOMAIN_COLORS.custom ?? "";
}

// ---------------------------------------------------------------------------
// Empty state
// ---------------------------------------------------------------------------

function EmptyState({ onNew }: { onNew: () => void }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-4 py-24 text-center">
      <Database className="h-12 w-12 text-muted-foreground/40" />
      <div>
        <p className="text-lg font-medium text-foreground">No collections yet</p>
        <p className="text-sm text-muted-foreground">
          Create a collection to start querying structured data during calls.
        </p>
      </div>
      <Button onClick={onNew} className="gap-2">
        <Plus className="h-4 w-4" />
        New Collection
      </Button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Collection Modal
// ---------------------------------------------------------------------------

interface WorkspaceOption {
  id: string;
  name: string;
}

interface CollectionFormData {
  name: string;
  domain: string;
  use_case_tag: string;
  source_type: string;
  workspace_id: string;
}

function CollectionModal({
  open,
  collection,
  onClose,
  onSaved,
}: {
  open: boolean;
  collection: LookupCollection | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const isEdit = collection !== null;
  const [form, setForm] = useState<CollectionFormData>(() => ({
    name: collection?.name ?? "",
    domain: collection?.domain ?? "custom",
    use_case_tag: collection?.use_case_tag ?? "",
    source_type: collection?.source_type ?? "manual",
    workspace_id: collection?.workspace_id ?? "",
  }));
  const [saving, setSaving] = useState(false);

  const { data: workspaces = [] } = useQuery<WorkspaceOption[]>({
    queryKey: ["workspaces-list"],
    queryFn: async () => {
      const res = await api.get<WorkspaceOption[]>("/api/v1/workspaces");
      return res.data;
    },
    enabled: open,
  });

  // Reset when dialog opens for a different collection
  const prevId = useRef(collection?.id);
  if (prevId.current !== collection?.id) {
    prevId.current = collection?.id;
    setForm({
      name: collection?.name ?? "",
      domain: collection?.domain ?? "custom",
      use_case_tag: collection?.use_case_tag ?? "",
      source_type: collection?.source_type ?? "manual",
      workspace_id: collection?.workspace_id ?? "",
    });
  }

  async function handleSave() {
    if (!form.name.trim()) {
      toast.error("Name is required");
      return;
    }
    setSaving(true);
    try {
      if (isEdit && collection) {
        await updateCollection(collection.id, {
          name: form.name,
          domain: form.domain,
          use_case_tag: form.use_case_tag || undefined,
          source_type: form.source_type,
        });
        toast.success("Collection updated");
      } else {
        const body: CollectionCreate = {
          name: form.name,
          domain: form.domain,
          use_case_tag: form.use_case_tag || undefined,
          source_type: form.source_type,
          workspace_id: form.workspace_id || undefined,
        };
        await createCollection(body);
        toast.success("Collection created");
      }
      onSaved();
      onClose();
    } catch {
      toast.error("Failed to save collection");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{isEdit ? "Edit Collection" : "New Collection"}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div className="space-y-1">
            <Label>Name</Label>
            <Input
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              placeholder="e.g. Property Overview 2026"
            />
          </div>
          <div className="space-y-1">
            <Label>Domain</Label>
            <Select
              value={form.domain}
              onValueChange={(v) => setForm((f) => ({ ...f, domain: v }))}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="property">Property</SelectItem>
                <SelectItem value="faq">FAQ</SelectItem>
                <SelectItem value="product">Product</SelectItem>
                <SelectItem value="staff">Staff</SelectItem>
                <SelectItem value="custom">Custom</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <Label>Use Case Tag (optional)</Label>
            <Input
              value={form.use_case_tag}
              onChange={(e) => setForm((f) => ({ ...f, use_case_tag: e.target.value }))}
              placeholder="e.g. north-region"
            />
          </div>
          <div className="space-y-1">
            <Label>Source Type</Label>
            <Select
              value={form.source_type}
              onValueChange={(v) => setForm((f) => ({ ...f, source_type: v }))}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="manual">Manual</SelectItem>
                <SelectItem value="csv">CSV</SelectItem>
                <SelectItem value="excel">Excel</SelectItem>
                <SelectItem value="json">JSON</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <Label>Workspace (optional)</Label>
            <Select
              value={form.workspace_id}
              onValueChange={(v) => setForm((f) => ({ ...f, workspace_id: v === "__none__" ? "" : v }))}
            >
              <SelectTrigger>
                <SelectValue placeholder="No workspace (personal)" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__none__">No workspace (personal)</SelectItem>
                {workspaces.map((ws) => (
                  <SelectItem key={ws.id} value={ws.id}>
                    {ws.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              Agents in this workspace will be able to search this collection.
            </p>
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={() => void handleSave()} disabled={saving} className="gap-2">
            {saving && <Loader2 className="h-4 w-4 animate-spin" />}
            {isEdit ? "Save" : "Create"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Record Modal
// ---------------------------------------------------------------------------

function RecordModal({
  open,
  record,
  onClose,
  onSaved,
  collectionId,
}: {
  open: boolean;
  record: LookupRecord | null;
  onClose: () => void;
  onSaved: () => void;
  collectionId: string;
}) {
  const isEdit = record !== null;
  const [title, setTitle] = useState(record?.title ?? "");
  const [jsonText, setJsonText] = useState(
    record ? JSON.stringify(record.data, null, 2) : "{}",
  );
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const prevId = useRef(record?.id);
  if (prevId.current !== record?.id) {
    prevId.current = record?.id;
    setTitle(record?.title ?? "");
    setJsonText(record ? JSON.stringify(record.data, null, 2) : "{}");
    setJsonError(null);
  }

  function handleJsonChange(val: string) {
    setJsonText(val);
    try {
      JSON.parse(val);
      setJsonError(null);
    } catch {
      setJsonError("Invalid JSON");
    }
  }

  async function handleSave() {
    if (!title.trim()) {
      toast.error("Title is required");
      return;
    }
    let data: Record<string, unknown> = {};
    try {
      data = JSON.parse(jsonText) as Record<string, unknown>;
    } catch {
      toast.error("Fix JSON errors before saving");
      return;
    }
    setSaving(true);
    try {
      if (isEdit && record) {
        await updateRecord(record.id, { title, data });
        toast.success("Record updated");
      } else {
        const body: RecordCreate = { title, data };
        await createRecord(collectionId, body);
        toast.success("Record created");
      }
      onSaved();
      onClose();
    } catch {
      toast.error("Failed to save record");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{isEdit ? "Edit Record" : "New Record"}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div className="space-y-1">
            <Label>Title</Label>
            <Input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. 42 Main Street"
            />
          </div>
          <div className="space-y-1">
            <Label>Data (JSON)</Label>
            <textarea
              value={jsonText}
              onChange={(e) => handleJsonChange(e.target.value)}
              rows={10}
              className="w-full rounded-md border bg-background px-3 py-2 font-mono text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
            />
            {jsonError && (
              <p className="flex items-center gap-1 text-xs text-destructive">
                <AlertCircle className="h-3 w-3" />
                {jsonError}
              </p>
            )}
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={() => void handleSave()} disabled={saving || !!jsonError} className="gap-2">
            {saving && <Loader2 className="h-4 w-4 animate-spin" />}
            {isEdit ? "Save" : "Create"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export default function LookupPage() {
  const { user } = useAuth();
  const qc = useQueryClient();

  // Selected collection
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // Collection modal
  const [collectionModal, setCollectionModal] = useState<{
    open: boolean;
    collection: LookupCollection | null;
  }>({ open: false, collection: null });

  // Record modal
  const [recordModal, setRecordModal] = useState<{
    open: boolean;
    record: LookupRecord | null;
  }>({ open: false, record: null });

  // Delete dialogs
  const [deleteColId, setDeleteColId] = useState<string | null>(null);
  const [deleteRecId, setDeleteRecId] = useState<string | null>(null);

  // Records search + pagination
  const [search, setSearch] = useState("");
  const [skip, setSkip] = useState(0);
  const LIMIT = 50;

  // File input ref for import
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [importingId, setImportingId] = useState<string | null>(null);

  // ---------------------------------------------------------------------------
  // Data fetching
  // ---------------------------------------------------------------------------

  const { data: stats } = useQuery({
    queryKey: ["lookup-stats"],
    queryFn: () => getLookupStats(),
    enabled: !!user,
  });

  const { data: collections = [], isLoading: loadingCols } = useQuery({
    queryKey: ["lookup-collections"],
    queryFn: () => listCollections(),
    enabled: !!user,
  });

  const selectedCollection = collections.find((c) => c.id === selectedId) ?? null;

  const { data: recordsPage, isLoading: loadingRecords } = useQuery({
    queryKey: ["lookup-records", selectedId, search, skip],
    queryFn: () =>
      selectedId
        ? listRecords(selectedId, { search: search || undefined, limit: LIMIT, skip })
        : Promise.resolve({ records: [], total: 0, limit: LIMIT, skip: 0 }),
    enabled: !!selectedId,
  });

  // ---------------------------------------------------------------------------
  // Mutations
  // ---------------------------------------------------------------------------

  const toggleActiveMutation = useMutation({
    mutationFn: ({ id, is_active }: { id: string; is_active: boolean }) =>
      updateCollection(id, { is_active }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["lookup-collections"] });
      void qc.invalidateQueries({ queryKey: ["lookup-stats"] });
    },
    onError: () => toast.error("Failed to update collection"),
  });

  const deleteColMutation = useMutation({
    mutationFn: (id: string) => deleteCollection(id),
    onSuccess: () => {
      toast.success("Collection deleted");
      if (selectedId === deleteColId) setSelectedId(null);
      void qc.invalidateQueries({ queryKey: ["lookup-collections"] });
      void qc.invalidateQueries({ queryKey: ["lookup-stats"] });
    },
    onError: () => toast.error("Failed to delete collection"),
  });

  const deleteRecMutation = useMutation({
    mutationFn: (id: string) => deleteRecord(id),
    onSuccess: () => {
      toast.success("Record deleted");
      void qc.invalidateQueries({ queryKey: ["lookup-records", selectedId] });
      void qc.invalidateQueries({ queryKey: ["lookup-collections"] });
      void qc.invalidateQueries({ queryKey: ["lookup-stats"] });
    },
    onError: () => toast.error("Failed to delete record"),
  });

  // ---------------------------------------------------------------------------
  // Import handler
  // ---------------------------------------------------------------------------

  async function handleImport(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file || !importingId) return;
    try {
      const result = await importRecords(importingId, file);
      toast.success(`Imported ${result.imported} records (${result.skipped} skipped)`);
      void qc.invalidateQueries({ queryKey: ["lookup-records", importingId] });
      void qc.invalidateQueries({ queryKey: ["lookup-collections"] });
      void qc.invalidateQueries({ queryKey: ["lookup-stats"] });
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data
        ?.detail;
      const msg =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((d) => (typeof d === "object" && d !== null && "msg" in d ? String((d as { msg: unknown }).msg) : String(d))).join("; ")
            : "Import failed";
      toast.error(msg);
    } finally {
      setImportingId(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  function triggerImport(collectionId: string) {
    setImportingId(collectionId);
    fileInputRef.current?.click();
  }

  // ---------------------------------------------------------------------------
  // Export handler
  // ---------------------------------------------------------------------------

  async function handleExport(collectionId: string, format: "csv" | "json") {
    const token =
      typeof window !== "undefined" ? localStorage.getItem("access_token") : null;
    const url = exportUrl(collectionId, format);
    try {
      const res = await fetch(url, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) throw new Error("Export failed");
      const blob = await res.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `lookup-export.${format}`;
      a.click();
    } catch {
      toast.error("Export failed");
    }
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="flex h-full flex-col">
      {/* Hidden file input */}
      <input
        ref={fileInputRef}
        type="file"
        accept=".csv,.xlsx,.json"
        className="hidden"
        onChange={(e) => void handleImport(e)}
      />

      {/* Top bar */}
      <div className="flex items-center justify-between border-b border-border px-6 py-4">
        <div className="flex items-center gap-3">
          <Database className="h-5 w-5 text-teal-400" />
          <h1 className="text-lg font-semibold">Lookup</h1>
          {stats && (
            <div className="flex gap-2 text-xs text-muted-foreground">
              <span className="rounded-full bg-muted px-2 py-0.5">
                {stats.total_collections} collections
              </span>
              <span className="rounded-full bg-muted px-2 py-0.5">
                {stats.total_records} records
              </span>
            </div>
          )}
        </div>
        <Button
          size="sm"
          className="gap-2"
          onClick={() => setCollectionModal({ open: true, collection: null })}
        >
          <Plus className="h-4 w-4" />
          New Collection
        </Button>
      </div>

      {/* Main layout */}
      <div className="flex flex-1 overflow-hidden">
        {/* Collections sidebar */}
        <aside className="flex w-72 shrink-0 flex-col border-r border-border">
          <div className="p-3 text-xs font-medium uppercase tracking-wider text-muted-foreground">
            Collections
          </div>
          <div className="flex-1 overflow-y-auto">
            {loadingCols ? (
              <div className="flex items-center justify-center py-12">
                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
              </div>
            ) : collections.length === 0 ? (
              <EmptyState onNew={() => setCollectionModal({ open: true, collection: null })} />
            ) : (
              <div className="space-y-0.5 px-2 pb-4">
                {collections.map((col) => (
                  <div
                    key={col.id}
                    onClick={() => {
                      setSelectedId(col.id);
                      setSearch("");
                      setSkip(0);
                    }}
                    className={`group flex cursor-pointer items-start justify-between rounded-md px-3 py-2.5 transition-colors ${
                      selectedId === col.id
                        ? "bg-accent text-accent-foreground"
                        : "text-muted-foreground hover:bg-accent/50 hover:text-foreground"
                    }`}
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="truncate text-sm font-medium">{col.name}</span>
                        {!col.is_active && (
                          <span className="shrink-0 rounded bg-muted px-1 text-[10px] text-muted-foreground">
                            off
                          </span>
                        )}
                      </div>
                      <div className="mt-1 flex items-center gap-1.5">
                        <span
                          className={`rounded-full border px-1.5 py-px text-[10px] ${domainColor(col.domain)}`}
                        >
                          {col.domain}
                        </span>
                        <span className="text-[11px] text-muted-foreground">
                          {col.record_count} records
                        </span>
                      </div>
                    </div>
                    <div className="ml-2 flex shrink-0 items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          setCollectionModal({ open: true, collection: col });
                        }}
                        className="rounded p-1 hover:bg-muted"
                        title="Edit"
                      >
                        <Edit2 className="h-3 w-3" />
                      </button>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          toggleActiveMutation.mutate({ id: col.id, is_active: !col.is_active });
                        }}
                        className="rounded p-1 hover:bg-muted"
                        title={col.is_active ? "Deactivate" : "Activate"}
                      >
                        {col.is_active ? (
                          <ToggleRight className="h-3 w-3 text-teal-400" />
                        ) : (
                          <ToggleLeft className="h-3 w-3" />
                        )}
                      </button>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          setDeleteColId(col.id);
                        }}
                        className="rounded p-1 hover:bg-muted"
                        title="Delete"
                      >
                        <Trash2 className="h-3 w-3 text-destructive" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </aside>

        {/* Records panel */}
        <main className="flex flex-1 flex-col overflow-hidden">
          {!selectedCollection ? (
            <div className="flex flex-1 items-center justify-center text-muted-foreground">
              <div className="text-center">
                <ChevronRight className="mx-auto mb-2 h-8 w-8 opacity-30" />
                <p className="text-sm">Select a collection to view records</p>
              </div>
            </div>
          ) : (
            <>
              {/* Records toolbar */}
              <div className="flex items-center gap-3 border-b border-border px-4 py-3">
                <div className="relative flex-1">
                  <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    value={search}
                    onChange={(e) => {
                      setSearch(e.target.value);
                      setSkip(0);
                    }}
                    placeholder="Search by title…"
                    className="pl-9"
                  />
                  {search && (
                    <button
                      onClick={() => setSearch("")}
                      className="absolute right-3 top-1/2 -translate-y-1/2"
                    >
                      <X className="h-4 w-4 text-muted-foreground" />
                    </button>
                  )}
                </div>

                {/* Import */}
                <Button
                  variant="outline"
                  size="sm"
                  className="gap-2"
                  onClick={() => triggerImport(selectedCollection.id)}
                >
                  <Upload className="h-4 w-4" />
                  Import
                </Button>

                {/* Export */}
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button variant="outline" size="sm" className="gap-2">
                      <Download className="h-4 w-4" />
                      Export
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent>
                    <DropdownMenuItem
                      onClick={() => void handleExport(selectedCollection.id, "csv")}
                    >
                      Export as CSV
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      onClick={() => void handleExport(selectedCollection.id, "json")}
                    >
                      Export as JSON
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>

                <Button
                  size="sm"
                  className="gap-2"
                  onClick={() => setRecordModal({ open: true, record: null })}
                >
                  <Plus className="h-4 w-4" />
                  Add Record
                </Button>
              </div>

              {/* Records table */}
              <div className="flex-1 overflow-auto">
                {loadingRecords ? (
                  <div className="flex items-center justify-center py-16">
                    <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                  </div>
                ) : !recordsPage || recordsPage.records.length === 0 ? (
                  <div className="flex flex-col items-center justify-center gap-3 py-16 text-center text-muted-foreground">
                    <Database className="h-8 w-8 opacity-30" />
                    <div>
                      <p className="text-sm font-medium">No records</p>
                      <p className="text-xs">
                        Add records manually or import a CSV/Excel/JSON file.
                      </p>
                    </div>
                  </div>
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Title</TableHead>
                        <TableHead>Data preview</TableHead>
                        <TableHead className="w-20 text-right">Actions</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {recordsPage.records.map((rec) => (
                        <TableRow key={rec.id}>
                          <TableCell className="max-w-[200px] truncate font-medium">
                            {rec.title}
                          </TableCell>
                          <TableCell className="max-w-[400px] truncate text-xs text-muted-foreground">
                            {JSON.stringify(rec.data)}
                          </TableCell>
                          <TableCell className="text-right">
                            <div className="flex items-center justify-end gap-1">
                              <button
                                onClick={() => setRecordModal({ open: true, record: rec })}
                                className="rounded p-1 hover:bg-muted"
                                title="Edit"
                              >
                                <Edit2 className="h-3.5 w-3.5" />
                              </button>
                              <button
                                onClick={() => setDeleteRecId(rec.id)}
                                className="rounded p-1 hover:bg-muted"
                                title="Delete"
                              >
                                <Trash2 className="h-3.5 w-3.5 text-destructive" />
                              </button>
                            </div>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </div>

              {/* Pagination */}
              {recordsPage && recordsPage.total > LIMIT && (
                <div className="flex items-center justify-between border-t border-border px-4 py-3 text-sm">
                  <span className="text-muted-foreground">
                    {skip + 1}–{Math.min(skip + LIMIT, recordsPage.total)} of{" "}
                    {recordsPage.total}
                  </span>
                  <div className="flex gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={skip === 0}
                      onClick={() => setSkip((s) => Math.max(0, s - LIMIT))}
                    >
                      Previous
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={skip + LIMIT >= recordsPage.total}
                      onClick={() => setSkip((s) => s + LIMIT)}
                    >
                      Next
                    </Button>
                  </div>
                </div>
              )}
            </>
          )}
        </main>
      </div>

      {/* Modals */}
      <CollectionModal
        open={collectionModal.open}
        collection={collectionModal.collection}
        onClose={() => setCollectionModal({ open: false, collection: null })}
        onSaved={() => {
          void qc.invalidateQueries({ queryKey: ["lookup-collections"] });
          void qc.invalidateQueries({ queryKey: ["lookup-stats"] });
        }}
      />

      {selectedId && (
        <RecordModal
          open={recordModal.open}
          record={recordModal.record}
          collectionId={selectedId}
          onClose={() => setRecordModal({ open: false, record: null })}
          onSaved={() => {
            void qc.invalidateQueries({ queryKey: ["lookup-records", selectedId] });
            void qc.invalidateQueries({ queryKey: ["lookup-collections"] });
            void qc.invalidateQueries({ queryKey: ["lookup-stats"] });
          }}
        />
      )}

      {/* Delete collection dialog */}
      <AlertDialog open={!!deleteColId} onOpenChange={(o) => !o && setDeleteColId(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Collection?</AlertDialogTitle>
            <AlertDialogDescription>
              This will permanently delete the collection and all its records. This action cannot be
              undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => {
                if (deleteColId) deleteColMutation.mutate(deleteColId);
                setDeleteColId(null);
              }}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Delete record dialog */}
      <AlertDialog open={!!deleteRecId} onOpenChange={(o) => !o && setDeleteRecId(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Record?</AlertDialogTitle>
            <AlertDialogDescription>
              This record will be permanently deleted.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => {
                if (deleteRecId) deleteRecMutation.mutate(deleteRecId);
                setDeleteRecId(null);
              }}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
