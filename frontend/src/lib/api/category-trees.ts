/**
 * Category Trees API client.
 *
 * Covers: tree admin CRUD, structured import, AI discovery, node edits,
 * template download, and the categorize endpoint.
 */

import { api } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface TreeMeta {
  tree_name: string;
  workspace_id: string;
  agent_id: string | null;
  source_type: "structured_upload" | "ai_generated";
  status: "draft" | "active" | "archived";
  node_count: number;
  created_at: string;
}

export interface CategoryNodeMetadata {
  example_query?: string;
  urgency_level?: string;
  self_resolution?: boolean;
  requires_property_info?: boolean;
  can_report_fault?: boolean;
  requires_manual_support?: boolean;
  info_to_collect?: string;
  // Arbitrary additional fields from custom import columns
  [key: string]: unknown;
}

export interface CategoryNode {
  id: string;
  tree_name: string;
  workspace_id: string;
  agent_id: string | null;
  status: "draft" | "active" | "archived";
  code: string | null;
  label: string;
  parent_id: string | null;
  depth: number;
  position: number;
  metadata: CategoryNodeMetadata | null;
}

export interface NodeAddRequest {
  label: string;
  parent_id?: string | null;
  code?: string | null;
  position?: number;
}

export interface NodeUpdateRequest {
  label?: string;
  code?: string | null;
  parent_id?: string | null;
  position?: number;
  metadata?: CategoryNodeMetadata | null;
}

export interface DiscoverHints {
  label?: string;
  max_depth?: number | null; // null = AI decides
  approx_top_level?: string;
}

export interface DiscoverJobStatus {
  job_id: string;
  status: "pending" | "running" | "completed" | "failed";
  step?: string;
  node_count?: number;
  error?: string;
}

export interface ImportDataItem {
  code: string | null;
  path: string[];
  metadata?: CategoryNodeMetadata | null;
}

export interface StructuredImportPreview {
  valid: boolean;
  node_count: number;
  preview: ImportDataItem[];
  import_data: ImportDataItem[];
}

export interface ConfirmImportBody {
  import_data: ImportDataItem[];
  agent_id?: string | null;
}

export interface CategorizeResult {
  matched: boolean;
  code: string | null;
  label: string | null;
  path: string[];
  depth: number;
  confidence: number | null;
  result_id: string;
  resolution_layer?: string;
  // Well-known metadata fields (flat for easy access)
  urgency_level: string | null;
  self_resolution: boolean | null;
  can_report_fault: boolean | null;
  requires_manual_support: boolean | null;
  requires_property_info: boolean | null;
  info_to_collect: string | null;
  // Full metadata blob
  metadata: CategoryNodeMetadata | null;
}

// ---------------------------------------------------------------------------
// Tree list / meta
// ---------------------------------------------------------------------------

export async function listCategoryTrees(workspaceId: string): Promise<TreeMeta[]> {
  const res = await api.get<TreeMeta[]>("/api/v1/category-trees", {
    params: { workspace_id: workspaceId },
  });
  return res.data;
}

export async function getCategoryTreeNodes(
  workspaceId: string,
  treeName: string
): Promise<CategoryNode[]> {
  const res = await api.get<CategoryNode[]>(
    `/api/v1/category-trees/${workspaceId}/${encodeURIComponent(treeName)}/nodes`
  );
  return res.data;
}

// ---------------------------------------------------------------------------
// Structured upload (Option A)
// ---------------------------------------------------------------------------

export async function downloadTemplate(fmt: "csv" | "json" | "xlsx"): Promise<void> {
  const token = typeof window !== "undefined" ? localStorage.getItem("access_token") : null;
  const url = `${process.env.NEXT_PUBLIC_API_URL ?? ""}/api/v1/category-trees/templates/${fmt}`;
  const res = await fetch(url, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw new Error("Download failed");
  const blob = await res.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `category_template.${fmt}`;
  a.click();
}

export async function validateStructuredUpload(
  workspaceId: string,
  treeName: string,
  file: File
): Promise<StructuredImportPreview> {
  const form = new FormData();
  form.append("file", file);
  const res = await api.post<StructuredImportPreview>(
    `/api/v1/category-trees/${workspaceId}/${encodeURIComponent(treeName)}/import/structured`,
    form,
    { headers: { "Content-Type": undefined } }
  );
  return res.data;
}

export async function confirmStructuredImport(
  workspaceId: string,
  treeName: string,
  body: ConfirmImportBody
): Promise<{ imported: number; tree_name: string; status: string }> {
  const res = await api.post(
    `/api/v1/category-trees/${workspaceId}/${encodeURIComponent(treeName)}/import/confirm`,
    body
  );
  return res.data as { imported: number; tree_name: string; status: string };
}

// ---------------------------------------------------------------------------
// AI discovery (Option B)
// ---------------------------------------------------------------------------

export async function startAiDiscovery(
  workspaceId: string,
  treeName: string,
  hints: DiscoverHints,
  file?: File
): Promise<{ job_id: string; status: string }> {
  // Hints go in the query string; file (if any) is multipart body.
  // This avoids any Content-Type mixing issues with the axios instance defaults.
  const params = new URLSearchParams();
  if (hints.label) params.set("label", hints.label);
  params.set("max_depth", String(hints.max_depth ?? 3));
  params.set("approx_top_level", hints.approx_top_level ?? "ai_decides");

  const url = `/api/v1/category-trees/${workspaceId}/${encodeURIComponent(treeName)}/discover?${params}`;

  let body: FormData | undefined;
  if (file) {
    body = new FormData();
    body.append("file", file);
  }

  const res = await api.post(url, body);
  return res.data as { job_id: string; status: string };
}

export async function pollDiscoveryJob(jobId: string): Promise<DiscoverJobStatus> {
  const res = await api.get<DiscoverJobStatus>(`/api/v1/category-trees/jobs/${jobId}`);
  return res.data;
}

export async function approveDraftTree(
  workspaceId: string,
  treeName: string
): Promise<{ activated: number }> {
  const res = await api.post(
    `/api/v1/category-trees/${workspaceId}/${encodeURIComponent(treeName)}/approve`
  );
  return res.data as { activated: number };
}

export async function discardDraftTree(workspaceId: string, treeName: string): Promise<void> {
  await api.delete(`/api/v1/category-trees/${workspaceId}/${encodeURIComponent(treeName)}/draft`);
}

// ---------------------------------------------------------------------------
// Archive tree
// ---------------------------------------------------------------------------

export async function archiveCategoryTree(workspaceId: string, treeName: string): Promise<void> {
  await api.delete(`/api/v1/category-trees/${workspaceId}/${encodeURIComponent(treeName)}`);
}

// ---------------------------------------------------------------------------
// Node CRUD
// ---------------------------------------------------------------------------

export async function addCategoryNode(
  workspaceId: string,
  treeName: string,
  body: NodeAddRequest
): Promise<CategoryNode> {
  const res = await api.post<CategoryNode>(
    `/api/v1/category-trees/${workspaceId}/${encodeURIComponent(treeName)}/nodes`,
    body
  );
  return res.data;
}

export async function updateCategoryNode(
  workspaceId: string,
  treeName: string,
  nodeId: string,
  body: NodeUpdateRequest
): Promise<CategoryNode> {
  const res = await api.put<CategoryNode>(
    `/api/v1/category-trees/${workspaceId}/${encodeURIComponent(treeName)}/nodes/${nodeId}`,
    body
  );
  return res.data;
}

export async function deleteCategoryNode(
  workspaceId: string,
  treeName: string,
  nodeId: string,
  cascade = false
): Promise<void> {
  await api.delete(
    `/api/v1/category-trees/${workspaceId}/${encodeURIComponent(treeName)}/nodes/${nodeId}`,
    { params: { cascade } }
  );
}

// ---------------------------------------------------------------------------
// Categorize (direct call — for testing)
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Export tree data
// ---------------------------------------------------------------------------

export async function exportCategoryTree(
  workspaceId: string,
  treeName: string,
  fmt: "csv" | "json"
): Promise<void> {
  const token = typeof window !== "undefined" ? localStorage.getItem("access_token") : null;
  const url = `${process.env.NEXT_PUBLIC_API_URL ?? ""}/api/v1/category-trees/${workspaceId}/${encodeURIComponent(treeName)}/export/${fmt}`;
  const res = await fetch(url, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw new Error("Export failed");
  const blob = await res.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `${treeName}_export.${fmt}`;
  a.click();
}

// ---------------------------------------------------------------------------
// LLM enrichment
// ---------------------------------------------------------------------------

export async function enrichExamples(
  workspaceId: string,
  treeName: string,
  overwrite = false
): Promise<{ status: string; tree_name: string }> {
  const res = await api.post<{ status: string; tree_name: string }>(
    `/api/v1/category-trees/${workspaceId}/${encodeURIComponent(treeName)}/enrich-examples`,
    null,
    { params: { overwrite } }
  );
  return res.data;
}

// ---------------------------------------------------------------------------
// Categorize (direct call — for testing)
// ---------------------------------------------------------------------------

export async function categorizeText(
  workspaceId: string,
  treeName: string,
  text: string
): Promise<CategorizeResult> {
  const res = await api.post<CategorizeResult>("/api/v1/category-trees/categorize", {
    workspace_id: workspaceId,
    tree_name: treeName,
    text,
  });
  return res.data;
}
