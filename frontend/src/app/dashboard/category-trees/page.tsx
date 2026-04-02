"use client";

import { useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  Network,
  Plus,
  Upload,
  Sparkles,
  ChevronRight,
  Loader2,
  Trash2,
  CheckCircle,
  XCircle,
  Clock,
  RefreshCw,
  Download,
  Edit2,
  FolderTree,
  ChevronDown,
  ChevronRight as ChevronRightIcon,
  Info,
} from "lucide-react";
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
import { api } from "@/lib/api";
import {
  listCategoryTrees,
  getCategoryTreeNodes,
  validateStructuredUpload,
  confirmStructuredImport,
  startAiDiscovery,
  pollDiscoveryJob,
  approveDraftTree,
  discardDraftTree,
  archiveCategoryTree,
  updateCategoryNode,
  deleteCategoryNode,
  downloadTemplate,
  exportCategoryTree,
  enrichExamples,
  categorizeText,
  type TreeMeta,
  type CategoryNode,
  type CategoryNodeMetadata,
  type DiscoverJobStatus,
  type StructuredImportPreview,
} from "@/lib/api/category-trees";

// ---------------------------------------------------------------------------
// Workspace selector helper
// ---------------------------------------------------------------------------

interface WorkspaceOption {
  id: string;
  name: string;
}

// ---------------------------------------------------------------------------
// Status badge
// ---------------------------------------------------------------------------

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    active: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
    draft: "bg-amber-500/20 text-amber-400 border-amber-500/30",
    archived: "bg-slate-500/20 text-slate-400 border-slate-500/30",
  };
  return (
    <span
      className={`rounded-full border px-2 py-0.5 text-[10px] font-medium ${map[status] ?? map.archived}`}
    >
      {status}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Node tree view (collapsible)
// ---------------------------------------------------------------------------

function NodeTree({
  nodes,
  parentId,
  onEdit,
  onDelete,
}: {
  nodes: CategoryNode[];
  parentId: string | null;
  onEdit: (node: CategoryNode) => void;
  onDelete: (node: CategoryNode) => void;
}) {
  const children = nodes.filter((n) => n.parent_id === parentId);
  if (children.length === 0) return null;

  return (
    <ul className="space-y-0.5">
      {children.map((node) => (
        <NodeRow key={node.id} node={node} nodes={nodes} onEdit={onEdit} onDelete={onDelete} />
      ))}
    </ul>
  );
}

function NodeRow({
  node,
  nodes,
  onEdit,
  onDelete,
}: {
  node: CategoryNode;
  nodes: CategoryNode[];
  onEdit: (node: CategoryNode) => void;
  onDelete: (node: CategoryNode) => void;
}) {
  const [open, setOpen] = useState(node.depth < 1);
  const [metaOpen, setMetaOpen] = useState(false);
  const hasChildren = nodes.some((n) => n.parent_id === node.id);
  const hasMetadata = !!node.metadata && Object.keys(node.metadata).length > 0;

  return (
    <li>
      <div
        className="group flex items-center gap-1 rounded px-2 py-1 hover:bg-accent/50"
        style={{ paddingLeft: `${(node.depth + 1) * 16}px` }}
      >
        <button
          onClick={() => setOpen((o) => !o)}
          className="shrink-0 text-muted-foreground"
          aria-label={open ? "Collapse" : "Expand"}
        >
          {hasChildren ? (
            open ? (
              <ChevronDown className="h-3 w-3" />
            ) : (
              <ChevronRightIcon className="h-3 w-3" />
            )
          ) : (
            <span className="inline-block w-3" />
          )}
        </button>

        <span className="flex-1 truncate text-sm">
          {node.label}
          {node.code && (
            <span className="ml-2 text-[10px] text-muted-foreground">[{node.code}]</span>
          )}
        </span>

        <div className="flex shrink-0 items-center gap-1">
          {hasMetadata && (
            <button
              onClick={() => setMetaOpen((o) => !o)}
              className={`rounded p-1 transition-colors ${metaOpen ? "text-blue-400 hover:bg-blue-500/10" : "text-muted-foreground/50 hover:bg-muted hover:text-muted-foreground"}`}
              title={metaOpen ? "Hide details" : "Show details"}
            >
              <Info className="h-3 w-3" />
            </button>
          )}
          <div className="flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
            <button
              onClick={() => onEdit(node)}
              className="rounded p-1 hover:bg-muted"
              title="Rename"
            >
              <Edit2 className="h-3 w-3" />
            </button>
            <button
              onClick={() => onDelete(node)}
              className="rounded p-1 hover:bg-muted"
              title="Delete"
            >
              <Trash2 className="h-3 w-3 text-destructive" />
            </button>
          </div>
        </div>
      </div>

      {metaOpen && hasMetadata && node.metadata && (
        <div style={{ paddingLeft: `${(node.depth + 2) * 16}px` }} className="pb-1 pr-2">
          <NodeMetadataPanel metadata={node.metadata} />
        </div>
      )}

      {open && hasChildren && (
        <NodeTree nodes={nodes} parentId={node.id} onEdit={onEdit} onDelete={onDelete} />
      )}
    </li>
  );
}

// ---------------------------------------------------------------------------
// Import modal (structured upload)
// ---------------------------------------------------------------------------

function StructuredImportModal({
  open,
  workspaceId,
  treeName,
  onClose,
  onImported,
}: {
  open: boolean;
  workspaceId: string;
  treeName: string;
  onClose: () => void;
  onImported: () => void;
}) {
  const [step, setStep] = useState<"upload" | "preview">("upload");
  const [preview, setPreview] = useState<StructuredImportPreview | null>(null);
  const [loading, setLoading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  async function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setLoading(true);
    try {
      const result = await validateStructuredUpload(workspaceId, treeName, file);
      setPreview(result);
      setStep("preview");
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data
        ?.detail;
      if (detail && typeof detail === "object" && "errors" in detail) {
        const errors = (detail as { errors: string[] }).errors;
        toast.error(errors.slice(0, 3).join("; "));
      } else {
        toast.error(typeof detail === "string" ? detail : "Validation failed");
      }
    } finally {
      setLoading(false);
    }
  }

  async function handleConfirm() {
    if (!preview) return;
    setLoading(true);
    try {
      const result = await confirmStructuredImport(workspaceId, treeName, {
        import_data: preview.import_data,
      });
      toast.success(`Imported ${result.imported} nodes`);
      onImported();
      onClose();
    } catch {
      toast.error("Import failed");
    } finally {
      setLoading(false);
    }
  }

  function reset() {
    setStep("upload");
    setPreview(null);
    if (fileRef.current) fileRef.current.value = "";
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) {
          onClose();
          reset();
        }
      }}
    >
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Structured Upload — {treeName}</DialogTitle>
        </DialogHeader>

        {step === "upload" ? (
          <div className="space-y-4 py-2">
            <p className="text-sm text-muted-foreground">
              Upload a .csv, .xlsx, or .json file with columns: code, level_1, level_2, level_3,
              level_4
            </p>
            <div className="flex gap-2">
              {(["csv", "json"] as const).map((fmt) => (
                <Button
                  key={fmt}
                  variant="outline"
                  size="sm"
                  className="gap-1"
                  onClick={() => void downloadTemplate(fmt)}
                >
                  <Download className="h-3 w-3" />
                  {fmt.toUpperCase()} template
                </Button>
              ))}
            </div>
            <input
              ref={fileRef}
              type="file"
              accept=".csv,.xlsx,.json"
              className="hidden"
              onChange={(e) => void handleFile(e)}
            />
            <Button
              className="w-full gap-2"
              onClick={() => fileRef.current?.click()}
              disabled={loading}
            >
              {loading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Upload className="h-4 w-4" />
              )}
              Choose file…
            </Button>
          </div>
        ) : (
          <div className="space-y-4 py-2">
            <div className="flex items-center gap-2 rounded-md bg-emerald-500/10 px-3 py-2">
              <CheckCircle className="h-4 w-4 text-emerald-400" />
              <span className="text-sm font-medium">
                {preview?.node_count} nodes validated — ready to import
              </span>
            </div>
            <div className="max-h-56 overflow-y-auto rounded-md border bg-muted/30 p-3">
              <p className="mb-2 text-xs font-medium text-muted-foreground">
                Preview (first 50 nodes)
              </p>
              {preview?.preview.map((item, i) => (
                <div key={i} className="py-0.5 text-xs">
                  {item.path.join(" › ")}
                  {item.code && <span className="ml-2 text-muted-foreground">[{item.code}]</span>}
                </div>
              ))}
            </div>
            <p className="text-xs text-muted-foreground">
              Cannot edit here — fix the source file and re-upload if needed.
            </p>
          </div>
        )}

        <DialogFooter>
          <Button
            variant="ghost"
            onClick={() => {
              onClose();
              reset();
            }}
            disabled={loading}
          >
            Cancel
          </Button>
          {step === "preview" && (
            <>
              <Button variant="outline" onClick={reset} disabled={loading}>
                Re-upload
              </Button>
              <Button onClick={() => void handleConfirm()} disabled={loading} className="gap-2">
                {loading && <Loader2 className="h-4 w-4 animate-spin" />}
                Confirm Import
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// AI Discovery modal
// ---------------------------------------------------------------------------

function AiDiscoveryModal({
  open,
  workspaceId,
  treeName,
  onClose,
  onStarted,
}: {
  open: boolean;
  workspaceId: string;
  treeName: string;
  onClose: () => void;
  onStarted: (jobId: string) => void;
}) {
  const [label, setLabel] = useState("");
  // null = "AI decides", number = user-specified
  const [maxDepth, setMaxDepth] = useState<number | null>(null);
  const [depthInput, setDepthInput] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  function reset() {
    setLabel("");
    setMaxDepth(null);
    setDepthInput("");
    setFile(null);
    if (fileRef.current) fileRef.current.value = "";
  }

  function handleDepthChange(val: string) {
    setDepthInput(val);
    const n = parseInt(val, 10);
    setMaxDepth(!val || isNaN(n) ? null : Math.max(2, Math.min(n, 10)));
  }

  async function handleStart() {
    setLoading(true);
    try {
      const result = await startAiDiscovery(
        workspaceId,
        treeName,
        {
          label: label.trim() || undefined,
          max_depth: maxDepth ?? 3,
          approx_top_level: "ai_decides",
        },
        file ?? undefined
      );
      onStarted(result.job_id);
      onClose();
      reset();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data
        ?.detail;
      toast.error(typeof detail === "string" ? detail : "Failed to start AI discovery");
    } finally {
      setLoading(false);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) {
          onClose();
          reset();
        }
      }}
    >
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>AI Discovery — {treeName}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <p className="text-sm text-muted-foreground">
            Describe what to categorize and optionally upload sample data. The AI builds a draft
            tree you can review and edit before activating.
          </p>

          {/* Context hint */}
          <div className="space-y-1">
            <Label>Context hint (optional)</Label>
            <Input
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="e.g. Property maintenance issues reported by tenants"
            />
          </div>

          {/* Max depth — free input or AI decides */}
          <div className="space-y-1">
            <Label>Max tree depth</Label>
            <div className="flex items-center gap-2">
              <Input
                type="number"
                min={2}
                max={10}
                value={depthInput}
                onChange={(e) => handleDepthChange(e.target.value)}
                placeholder="e.g. 3"
                className="w-24"
              />
              <span className="text-sm text-muted-foreground">
                levels (leave blank = AI decides)
              </span>
            </div>
            {maxDepth !== null && (
              <p className="text-xs text-muted-foreground">
                Tree will have at most {maxDepth} levels deep.
              </p>
            )}
          </div>

          {/* Optional raw data file */}
          <div className="space-y-1">
            <Label>Sample data file (optional)</Label>
            <input
              ref={fileRef}
              type="file"
              accept=".txt,.csv,.xlsx,.json"
              className="hidden"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                className="gap-2"
                onClick={() => fileRef.current?.click()}
              >
                <Upload className="h-4 w-4" />
                {file ? file.name : "Choose file…"}
              </Button>
              {file && (
                <button
                  onClick={() => {
                    setFile(null);
                    if (fileRef.current) fileRef.current.value = "";
                  }}
                  className="text-xs text-muted-foreground hover:text-foreground"
                >
                  Remove
                </button>
              )}
            </div>
            <p className="text-xs text-muted-foreground">
              .txt / .csv / .xlsx / .json — max 10 MB. The AI samples up to 500 items.
            </p>
          </div>
        </div>

        <DialogFooter>
          <Button
            variant="ghost"
            onClick={() => {
              onClose();
              reset();
            }}
            disabled={loading}
          >
            Cancel
          </Button>
          <Button onClick={() => void handleStart()} disabled={loading} className="gap-2">
            {loading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Sparkles className="h-4 w-4" />
            )}
            Generate Draft
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Node metadata panel (read-only display of imported metadata)
// ---------------------------------------------------------------------------

const URGENCY_COLORS: Record<string, string> = {
  "prio 1": "bg-red-500/20 text-red-400 border-red-500/30",
  "prio 2": "bg-orange-500/20 text-orange-400 border-orange-500/30",
  "prio 3": "bg-yellow-500/20 text-yellow-400 border-yellow-500/30",
  blandat: "bg-slate-500/20 text-slate-400 border-slate-500/30",
};

function UrgencyChip({ value }: { value: string }) {
  const key = value.toLowerCase();
  const colorKey = Object.keys(URGENCY_COLORS).find((k) => key.includes(k));
  const cls = colorKey ? URGENCY_COLORS[colorKey] : "bg-muted text-muted-foreground border-border";
  return (
    <span className={`rounded-full border px-2 py-0.5 text-[10px] font-medium ${cls}`}>
      {value}
    </span>
  );
}

function BoolBadge({ label, value }: { label: string; value: boolean }) {
  return (
    <span
      className={`rounded border px-1.5 py-0.5 text-[10px] font-medium ${value ? "border-emerald-500/30 bg-emerald-500/20 text-emerald-400" : "border-border bg-slate-500/10 text-muted-foreground"}`}
    >
      {label}: {value ? "Yes" : "No"}
    </span>
  );
}

const KNOWN_KEYS = new Set([
  "urgency_level",
  "self_resolution",
  "requires_property_info",
  "can_report_fault",
  "requires_manual_support",
  "info_to_collect",
  "example_query",
]);

function NodeMetadataPanel({ metadata }: { metadata: CategoryNodeMetadata }) {
  const extraKeys = Object.keys(metadata).filter((k) => !KNOWN_KEYS.has(k));

  return (
    <div className="space-y-2 rounded-md border border-border/60 bg-muted/20 p-3">
      <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        Metadata
      </p>

      {metadata.example_query && (
        <p className="text-xs italic text-muted-foreground">
          e.g. &ldquo;{metadata.example_query}&rdquo;
        </p>
      )}

      {metadata.urgency_level && (
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-muted-foreground">Urgency:</span>
          <UrgencyChip value={metadata.urgency_level} />
        </div>
      )}

      <div className="flex flex-wrap gap-1.5">
        {metadata.self_resolution !== undefined && (
          <BoolBadge label="Self-resolve" value={metadata.self_resolution} />
        )}
        {metadata.can_report_fault !== undefined && (
          <BoolBadge label="Can report fault" value={metadata.can_report_fault} />
        )}
        {metadata.requires_manual_support !== undefined && (
          <BoolBadge label="Manual support" value={metadata.requires_manual_support} />
        )}
        {metadata.requires_property_info !== undefined && (
          <BoolBadge label="Property info needed" value={metadata.requires_property_info} />
        )}
      </div>

      {metadata.info_to_collect && (
        <div className="space-y-0.5">
          <p className="text-[10px] font-medium text-muted-foreground">Questions to ask caller:</p>
          <p className="text-xs leading-relaxed text-foreground/80">{metadata.info_to_collect}</p>
        </div>
      )}

      {extraKeys.length > 0 && (
        <div className="space-y-0.5 border-t border-border/40 pt-2">
          {extraKeys.map((k) => (
            <p key={k} className="text-xs text-muted-foreground">
              <span className="font-medium">{k}:</span> {String(metadata[k])}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Node edit modal
// ---------------------------------------------------------------------------

const URGENCY_OPTIONS = ["Prio 1", "Prio 2", "Prio 3", "Blandat"];

function NodeEditModal({
  open,
  node,
  workspaceId,
  onClose,
  onSaved,
}: {
  open: boolean;
  node: CategoryNode | null;
  workspaceId: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [label, setLabel] = useState(node?.label ?? "");
  const [code, setCode] = useState(node?.code ?? "");
  const [exampleQuery, setExampleQuery] = useState(node?.metadata?.example_query ?? "");
  const [urgencyLevel, setUrgencyLevel] = useState(node?.metadata?.urgency_level ?? "");
  const [selfResolution, setSelfResolution] = useState(node?.metadata?.self_resolution ?? false);
  const [canReportFault, setCanReportFault] = useState(node?.metadata?.can_report_fault ?? false);
  const [requiresManualSupport, setRequiresManualSupport] = useState(
    node?.metadata?.requires_manual_support ?? false
  );
  const [requiresPropertyInfo, setRequiresPropertyInfo] = useState(
    node?.metadata?.requires_property_info ?? false
  );
  const [infoToCollect, setInfoToCollect] = useState(node?.metadata?.info_to_collect ?? "");
  const [saving, setSaving] = useState(false);

  // Reset when node changes
  const prevId = useRef(node?.id);
  if (prevId.current !== node?.id) {
    prevId.current = node?.id;
    setLabel(node?.label ?? "");
    setCode(node?.code ?? "");
    setExampleQuery(node?.metadata?.example_query ?? "");
    setUrgencyLevel(node?.metadata?.urgency_level ?? "");
    setSelfResolution(node?.metadata?.self_resolution ?? false);
    setCanReportFault(node?.metadata?.can_report_fault ?? false);
    setRequiresManualSupport(node?.metadata?.requires_manual_support ?? false);
    setRequiresPropertyInfo(node?.metadata?.requires_property_info ?? false);
    setInfoToCollect(node?.metadata?.info_to_collect ?? "");
  }

  async function handleSave() {
    if (!node || !label.trim()) {
      toast.error("Label is required");
      return;
    }
    setSaving(true);
    try {
      await updateCategoryNode(workspaceId, node.tree_name, node.id, {
        label: label.trim(),
        code: code.trim() || null,
        metadata: {
          ...(exampleQuery.trim() ? { example_query: exampleQuery.trim() } : {}),
          ...(urgencyLevel ? { urgency_level: urgencyLevel } : {}),
          self_resolution: selfResolution,
          can_report_fault: canReportFault,
          requires_manual_support: requiresManualSupport,
          requires_property_info: requiresPropertyInfo,
          ...(infoToCollect.trim() ? { info_to_collect: infoToCollect.trim() } : {}),
        },
      });
      toast.success("Node updated");
      onSaved();
      onClose();
    } catch {
      toast.error("Failed to update node");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[90vh] max-w-md overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Edit Node</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div className="space-y-1">
            <Label>Label</Label>
            <Input
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="Category label"
            />
          </div>
          <div className="space-y-1">
            <Label>Code (optional)</Label>
            <Input value={code} onChange={(e) => setCode(e.target.value)} placeholder="e.g. W001" />
          </div>

          <div className="space-y-3 rounded-md border border-border/60 bg-muted/20 p-3">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              Metadata
            </p>

            <div className="space-y-1">
              <Label className="text-xs">Example query</Label>
              <Input
                value={exampleQuery}
                onChange={(e) => setExampleQuery(e.target.value)}
                placeholder='e.g. "My heating is broken"'
                className="text-sm"
              />
            </div>

            <div className="space-y-1">
              <Label className="text-xs">Urgency level</Label>
              <select
                value={urgencyLevel}
                onChange={(e) => setUrgencyLevel(e.target.value)}
                className="w-full rounded-md border border-input bg-background px-3 py-1.5 text-sm"
              >
                <option value="">— not set —</option>
                {URGENCY_OPTIONS.map((o) => (
                  <option key={o} value={o}>
                    {o}
                  </option>
                ))}
              </select>
            </div>

            <div className="space-y-1">
              <Label className="text-xs">Info to collect from caller</Label>
              <textarea
                value={infoToCollect}
                onChange={(e) => setInfoToCollect(e.target.value)}
                placeholder="Questions the agent should ask..."
                rows={2}
                className="w-full resize-none rounded-md border border-input bg-background px-3 py-1.5 text-sm"
              />
            </div>

            <div className="grid grid-cols-2 gap-2">
              {(
                [
                  ["Self-resolution possible", selfResolution, setSelfResolution],
                  ["Can report fault", canReportFault, setCanReportFault],
                  ["Requires manual support", requiresManualSupport, setRequiresManualSupport],
                  ["Property info needed", requiresPropertyInfo, setRequiresPropertyInfo],
                ] as [string, boolean, (v: boolean) => void][]
              ).map(([lbl, val, setter]) => (
                <label key={lbl} className="flex cursor-pointer items-center gap-2">
                  <input
                    type="checkbox"
                    checked={val}
                    onChange={(e) => setter(e.target.checked)}
                    className="h-3.5 w-3.5 rounded"
                  />
                  <span className="text-xs text-muted-foreground">{lbl}</span>
                </label>
              ))}
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button
            onClick={() => void handleSave()}
            disabled={saving || !label.trim()}
            className="gap-2"
          >
            {saving && <Loader2 className="h-4 w-4 animate-spin" />}
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Test categorize panel
// ---------------------------------------------------------------------------

function TestPanel({ workspaceId, treeName }: { workspaceId: string; treeName: string }) {
  const [text, setText] = useState("");
  const [result, setResult] = useState<import("@/lib/api/category-trees").CategorizeResult | null>(
    null
  );
  const [loading, setLoading] = useState(false);

  async function handleTest() {
    if (!text.trim()) return;
    setLoading(true);
    try {
      const res = await categorizeText(workspaceId, treeName, text.trim());
      setResult(res);
    } catch {
      toast.error("Categorization failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="rounded-md border bg-muted/20 p-4">
      <p className="mb-3 text-xs font-medium uppercase tracking-wider text-muted-foreground">
        Test Categorization
      </p>
      <div className="flex gap-2">
        <Input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Enter caller input to test…"
          onKeyDown={(e) => e.key === "Enter" && void handleTest()}
        />
        <Button size="sm" onClick={() => void handleTest()} disabled={loading || !text.trim()}>
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : "Test"}
        </Button>
      </div>
      {result && (
        <div className="mt-3 rounded-md bg-muted/40 p-3 text-sm">
          {result.matched ? (
            <>
              <div className="flex items-center gap-2 text-emerald-400">
                <CheckCircle className="h-4 w-4" />
                <span className="font-medium">Matched: {result.label}</span>
                {result.code && <span className="text-muted-foreground">[{result.code}]</span>}
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                Path: {result.path.join(" › ")}
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                Layer: {result.resolution_layer} · Confidence:{" "}
                {result.confidence != null ? result.confidence.toFixed(3) : "—"}
              </div>
              {result.metadata && (
                <div className="mt-2">
                  <NodeMetadataPanel metadata={result.metadata} />
                </div>
              )}
            </>
          ) : (
            <div className="flex items-center gap-2 text-muted-foreground">
              <XCircle className="h-4 w-4" />
              <span>No match found</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function CategoryTreesPage() {
  const qc = useQueryClient();

  const [workspaceId, setWorkspaceId] = useState<string>("");
  const [selectedTree, setSelectedTree] = useState<TreeMeta | null>(null);
  const [newTreeName, setNewTreeName] = useState("");
  const [showNewTreeInput, setShowNewTreeInput] = useState(false);

  const [enriching, setEnriching] = useState(false);

  // Modals
  const [structuredImportOpen, setStructuredImportOpen] = useState(false);
  const [aiDiscoveryOpen, setAiDiscoveryOpen] = useState(false);
  const [editNode, setEditNode] = useState<CategoryNode | null>(null);
  const [deleteNode, setDeleteNode] = useState<CategoryNode | null>(null);
  const [archiveTree, setArchiveTree] = useState<TreeMeta | null>(null);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);

  // Workspace list
  const { data: workspaces = [] } = useQuery<WorkspaceOption[]>({
    queryKey: ["workspaces-list"],
    queryFn: async () => {
      const res = await api.get<WorkspaceOption[]>("/api/v1/workspaces");
      return res.data;
    },
  });

  // Auto-select first workspace
  if (workspaces.length > 0 && !workspaceId && workspaces[0]) {
    setWorkspaceId(workspaces[0].id);
  }

  // Trees list
  const { data: trees = [], isLoading: loadingTrees } = useQuery({
    queryKey: ["category-trees", workspaceId],
    queryFn: () => listCategoryTrees(workspaceId),
    enabled: !!workspaceId,
  });

  // Nodes for selected tree
  const {
    data: nodes = [],
    isLoading: loadingNodes,
    isFetching: fetchingNodes,
  } = useQuery({
    queryKey: ["category-tree-nodes", workspaceId, selectedTree?.tree_name],
    queryFn: () =>
      selectedTree
        ? getCategoryTreeNodes(workspaceId, selectedTree.tree_name)
        : Promise.resolve([]),
    enabled: !!selectedTree && !!workspaceId,
  });

  // Poll active discovery job
  useQuery<DiscoverJobStatus>({
    queryKey: ["discovery-job", activeJobId],
    queryFn: () => pollDiscoveryJob(activeJobId ?? ""),
    enabled: !!activeJobId,
    refetchInterval: (data) => {
      const status = data?.state?.data?.status;
      if (status === "completed" || status === "failed") return false;
      return 2000;
    },
    select: (data) => {
      if (data.status === "completed") {
        toast.success("AI discovery complete — review the draft tree");
        void qc.invalidateQueries({ queryKey: ["category-trees", workspaceId] });
        setActiveJobId(null);
      } else if (data.status === "failed") {
        toast.error(`Discovery failed: ${data.error ?? "unknown error"}`);
        setActiveJobId(null);
      }
      return data;
    },
  });

  // Mutations
  const approveMutation = useMutation({
    mutationFn: () => approveDraftTree(workspaceId, selectedTree?.tree_name ?? ""),
    onSuccess: (data) => {
      toast.success(`Activated ${data.activated} nodes`);
      void qc.invalidateQueries({ queryKey: ["category-trees", workspaceId] });
      void qc.invalidateQueries({
        queryKey: ["category-tree-nodes", workspaceId, selectedTree?.tree_name],
      });
    },
    onError: () => toast.error("Approval failed"),
  });

  const discardMutation = useMutation({
    mutationFn: () => discardDraftTree(workspaceId, selectedTree?.tree_name ?? ""),
    onSuccess: () => {
      toast.success("Draft discarded");
      void qc.invalidateQueries({ queryKey: ["category-trees", workspaceId] });
      setSelectedTree(null);
    },
    onError: () => toast.error("Discard failed"),
  });

  const archiveMutation = useMutation({
    mutationFn: (tree: TreeMeta) => archiveCategoryTree(workspaceId, tree.tree_name),
    onSuccess: () => {
      toast.success("Tree archived");
      void qc.invalidateQueries({ queryKey: ["category-trees", workspaceId] });
      if (archiveTree?.tree_name === selectedTree?.tree_name) setSelectedTree(null);
      setArchiveTree(null);
    },
    onError: () => toast.error("Archive failed"),
  });

  const deleteNodeMutation = useMutation({
    mutationFn: (node: CategoryNode) =>
      deleteCategoryNode(workspaceId, node.tree_name, node.id, true),
    onSuccess: () => {
      toast.success("Node deleted");
      void qc.invalidateQueries({
        queryKey: ["category-tree-nodes", workspaceId, selectedTree?.tree_name],
      });
    },
    onError: () => toast.error("Delete failed"),
  });

  function handleTreeSelect(tree: TreeMeta) {
    setSelectedTree(tree);
  }

  function invalidateNodes() {
    void qc.invalidateQueries({
      queryKey: ["category-tree-nodes", workspaceId, selectedTree?.tree_name],
    });
    void qc.invalidateQueries({ queryKey: ["category-trees", workspaceId] });
  }

  const isDraft = selectedTree?.status === "draft";
  const isActive = selectedTree?.status === "active";

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-6 py-4">
        <div className="flex items-center gap-3">
          <Network className="h-5 w-5 text-purple-400" />
          <h1 className="text-lg font-semibold">Category Trees</h1>
          {trees.length > 0 && (
            <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
              {trees.length} tree{trees.length !== 1 ? "s" : ""}
            </span>
          )}
        </div>

        {/* Workspace selector */}
        <div className="flex items-center gap-3">
          <select
            value={workspaceId}
            onChange={(e) => {
              setWorkspaceId(e.target.value);
              setSelectedTree(null);
            }}
            className="rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
          >
            {workspaces.map((ws) => (
              <option key={ws.id} value={ws.id}>
                {ws.name}
              </option>
            ))}
          </select>

          {/* New tree button */}
          {!showNewTreeInput ? (
            <Button
              size="sm"
              className="gap-2"
              onClick={() => setShowNewTreeInput(true)}
              disabled={!workspaceId}
            >
              <Plus className="h-4 w-4" />
              New Tree
            </Button>
          ) : (
            <div className="flex items-center gap-2">
              <Input
                autoFocus
                value={newTreeName}
                onChange={(e) => setNewTreeName(e.target.value)}
                placeholder="tree_name (snake_case)"
                className="h-8 w-48 text-sm"
                onKeyDown={(e) => {
                  if (e.key === "Escape") {
                    setShowNewTreeInput(false);
                    setNewTreeName("");
                  }
                }}
              />
              <Button
                size="sm"
                disabled={!newTreeName.trim()}
                onClick={() => {
                  // Just select the new tree name as the context
                  const fakeMeta: TreeMeta = {
                    tree_name: newTreeName.trim(),
                    workspace_id: workspaceId,
                    agent_id: null,
                    source_type: "structured_upload",
                    status: "active",
                    node_count: 0,
                    created_at: new Date().toISOString(),
                  };
                  setSelectedTree(fakeMeta);
                  setShowNewTreeInput(false);
                  setNewTreeName("");
                  setStructuredImportOpen(true);
                }}
              >
                Create
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setShowNewTreeInput(false);
                  setNewTreeName("");
                }}
              >
                Cancel
              </Button>
            </div>
          )}
        </div>
      </div>

      {/* Body */}
      <div className="flex flex-1 overflow-hidden">
        {/* Tree list */}
        <aside className="flex w-64 shrink-0 flex-col border-r border-border">
          <div className="p-3 text-xs font-medium uppercase tracking-wider text-muted-foreground">
            Trees
          </div>
          <div className="flex-1 overflow-y-auto">
            {!workspaceId ? (
              <div className="py-8 text-center text-sm text-muted-foreground">
                Select a workspace
              </div>
            ) : loadingTrees ? (
              <div className="flex items-center justify-center py-12">
                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
              </div>
            ) : trees.length === 0 ? (
              <div className="flex flex-col items-center justify-center gap-3 px-4 py-12 text-center">
                <FolderTree className="h-8 w-8 text-muted-foreground/40" />
                <p className="text-sm text-muted-foreground">No trees yet</p>
                <Button
                  size="sm"
                  variant="outline"
                  className="gap-2"
                  onClick={() => setShowNewTreeInput(true)}
                >
                  <Plus className="h-3 w-3" />
                  New Tree
                </Button>
              </div>
            ) : (
              <div className="space-y-0.5 px-2 pb-4">
                {trees.map((tree) => (
                  <div
                    key={tree.tree_name}
                    onClick={() => handleTreeSelect(tree)}
                    className={`group flex cursor-pointer items-start justify-between rounded-md px-3 py-2.5 transition-colors ${
                      selectedTree?.tree_name === tree.tree_name
                        ? "bg-accent text-accent-foreground"
                        : "text-muted-foreground hover:bg-accent/50 hover:text-foreground"
                    }`}
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="truncate text-sm font-medium">{tree.tree_name}</span>
                        {selectedTree?.tree_name === tree.tree_name && fetchingNodes && (
                          <Loader2 className="h-3 w-3 shrink-0 animate-spin text-muted-foreground" />
                        )}
                      </div>
                      <div className="mt-1 flex items-center gap-1.5">
                        <StatusBadge status={tree.status} />
                        <span className="text-[11px] text-muted-foreground">
                          {tree.node_count} nodes
                        </span>
                      </div>
                    </div>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setArchiveTree(tree);
                      }}
                      className="ml-2 shrink-0 rounded p-1 opacity-0 transition-opacity hover:bg-muted group-hover:opacity-100"
                      title="Archive"
                    >
                      <Trash2 className="h-3 w-3 text-destructive" />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </aside>

        {/* Tree detail */}
        <main className="flex flex-1 flex-col overflow-hidden">
          {!selectedTree ? (
            <div className="flex flex-1 items-center justify-center text-muted-foreground">
              <div className="text-center">
                <ChevronRight className="mx-auto mb-2 h-8 w-8 opacity-30" />
                <p className="text-sm">Select a tree to view nodes</p>
              </div>
            </div>
          ) : (
            <>
              {/* Tree toolbar */}
              <div className="flex items-center gap-3 border-b border-border px-4 py-3">
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <h2 className="text-sm font-semibold">{selectedTree.tree_name}</h2>
                    <StatusBadge status={selectedTree.status} />
                    {activeJobId && (
                      <div className="flex items-center gap-1 text-xs text-amber-400">
                        <Clock className="h-3 w-3 animate-pulse" />
                        AI generating…
                      </div>
                    )}
                  </div>
                  <p className="text-xs text-muted-foreground">{nodes.length} nodes</p>
                </div>

                <div className="flex items-center gap-2">
                  {isDraft && (
                    <>
                      <Button
                        size="sm"
                        variant="outline"
                        className="gap-2 text-destructive"
                        onClick={() => discardMutation.mutate()}
                        disabled={discardMutation.isPending}
                      >
                        <XCircle className="h-4 w-4" />
                        Discard draft
                      </Button>
                      <Button
                        size="sm"
                        className="gap-2"
                        onClick={() => approveMutation.mutate()}
                        disabled={approveMutation.isPending}
                      >
                        <CheckCircle className="h-4 w-4" />
                        Approve &amp; Activate
                      </Button>
                    </>
                  )}

                  {!isDraft && (
                    <>
                      <Button
                        size="sm"
                        variant="outline"
                        className="gap-2"
                        onClick={() => setStructuredImportOpen(true)}
                      >
                        <Upload className="h-4 w-4" />
                        Import
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        className="gap-2"
                        onClick={() => setAiDiscoveryOpen(true)}
                      >
                        <Sparkles className="h-4 w-4" />
                        AI Discover
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        className="gap-2"
                        title="Export as CSV"
                        onClick={() =>
                          void exportCategoryTree(workspaceId, selectedTree.tree_name, "csv").catch(
                            () => toast.error("Export failed")
                          )
                        }
                      >
                        <Download className="h-4 w-4" />
                        CSV
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        className="gap-2"
                        title="Export as JSON"
                        onClick={() =>
                          void exportCategoryTree(
                            workspaceId,
                            selectedTree.tree_name,
                            "json"
                          ).catch(() => toast.error("Export failed"))
                        }
                      >
                        <Download className="h-4 w-4" />
                        JSON
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        className="gap-2"
                        title="Enrich nodes with AI-generated example queries"
                        disabled={enriching}
                        onClick={() => {
                          setEnriching(true);
                          void enrichExamples(workspaceId, selectedTree.tree_name)
                            .then(() => {
                              toast.success("AI enrichment started — nodes will update shortly");
                              void qc.invalidateQueries({ queryKey: ["category-tree-nodes"] });
                            })
                            .catch(() => toast.error("Enrichment failed"))
                            .finally(() => setEnriching(false));
                        }}
                      >
                        {enriching ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Sparkles className="h-4 w-4" />
                        )}
                        Enrich
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() =>
                          void qc.invalidateQueries({ queryKey: ["category-tree-nodes"] })
                        }
                      >
                        <RefreshCw className="h-4 w-4" />
                      </Button>
                    </>
                  )}
                </div>
              </div>

              {/* Nodes */}
              <div className="flex-1 overflow-auto p-4">
                {loadingNodes || fetchingNodes ? (
                  <div className="flex items-center justify-center py-16">
                    <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                  </div>
                ) : nodes.length === 0 ? (
                  <div className="flex flex-col items-center justify-center gap-3 py-16 text-center text-muted-foreground">
                    <FolderTree className="h-8 w-8 opacity-30" />
                    <div>
                      <p className="text-sm font-medium">No nodes yet</p>
                      <p className="text-xs">
                        Import a file or use AI Discovery to generate a tree.
                      </p>
                    </div>
                    <div className="flex gap-2">
                      <Button
                        size="sm"
                        variant="outline"
                        className="gap-2"
                        onClick={() => setStructuredImportOpen(true)}
                      >
                        <Upload className="h-4 w-4" />
                        Import
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        className="gap-2"
                        onClick={() => setAiDiscoveryOpen(true)}
                      >
                        <Sparkles className="h-4 w-4" />
                        AI Discover
                      </Button>
                    </div>
                  </div>
                ) : (
                  <div className="space-y-4">
                    <NodeTree
                      nodes={nodes}
                      parentId={null}
                      onEdit={(node) => setEditNode(node)}
                      onDelete={(node) => setDeleteNode(node)}
                    />

                    {/* Test panel — only for active trees */}
                    {isActive && (
                      <div className="mt-6">
                        <TestPanel workspaceId={workspaceId} treeName={selectedTree.tree_name} />
                      </div>
                    )}
                  </div>
                )}
              </div>
            </>
          )}
        </main>
      </div>

      {/* Modals */}
      {selectedTree && (
        <>
          <StructuredImportModal
            open={structuredImportOpen}
            workspaceId={workspaceId}
            treeName={selectedTree.tree_name}
            onClose={() => setStructuredImportOpen(false)}
            onImported={() => {
              invalidateNodes();
              // Re-select tree to get updated status
              void qc.invalidateQueries({ queryKey: ["category-trees", workspaceId] });
            }}
          />
          <AiDiscoveryModal
            open={aiDiscoveryOpen}
            workspaceId={workspaceId}
            treeName={selectedTree.tree_name}
            onClose={() => setAiDiscoveryOpen(false)}
            onStarted={(jobId) => {
              setActiveJobId(jobId);
              toast.info("AI is building your category tree…");
            }}
          />
        </>
      )}

      <NodeEditModal
        open={!!editNode}
        node={editNode}
        workspaceId={workspaceId}
        onClose={() => setEditNode(null)}
        onSaved={invalidateNodes}
      />

      {/* Delete node confirm */}
      <AlertDialog open={!!deleteNode} onOpenChange={(o) => !o && setDeleteNode(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete node?</AlertDialogTitle>
            <AlertDialogDescription>
              &quot;{deleteNode?.label}&quot; and all its children will be permanently deleted.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => {
                if (deleteNode) deleteNodeMutation.mutate(deleteNode);
                setDeleteNode(null);
              }}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Archive tree confirm */}
      <AlertDialog open={!!archiveTree} onOpenChange={(o) => !o && setArchiveTree(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Archive tree?</AlertDialogTitle>
            <AlertDialogDescription>
              &quot;{archiveTree?.tree_name}&quot; will be archived and invisible to agents.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => {
                if (archiveTree) archiveMutation.mutate(archiveTree);
              }}
            >
              Archive
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
