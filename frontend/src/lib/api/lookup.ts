/**
 * Lookup API client — collections and records for structured data queries.
 */

import { api } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface LookupCollection {
  id: string;
  workspace_id: string | null;
  user_id: number;
  name: string;
  domain: string;
  use_case_tag: string | null;
  source_type: string;
  field_schema: Record<
    string,
    { label: string; description?: string; searchable?: boolean }
  > | null;
  is_active: boolean;
  record_count: number;
}

export interface LookupRecord {
  id: string;
  collection_id: string;
  workspace_id: string | null;
  user_id: number;
  title: string;
  data: Record<string, unknown>;
  tags: string[] | null;
}

export interface PaginatedRecords {
  records: LookupRecord[];
  total: number;
  limit: number;
  skip: number;
}

export interface LookupStats {
  total_collections: number;
  total_records: number;
}

export interface ImportResult {
  imported: number;
  skipped: number;
  total: number;
}

export interface CollectionCreate {
  name: string;
  domain?: string;
  use_case_tag?: string;
  source_type?: string;
  field_schema?: Record<string, unknown> | null;
  workspace_id?: string | null;
}

export interface CollectionUpdate {
  name?: string;
  domain?: string;
  use_case_tag?: string;
  source_type?: string;
  field_schema?: Record<string, unknown> | null;
  is_active?: boolean;
}

export interface RecordCreate {
  title: string;
  data?: Record<string, unknown>;
  tags?: string[];
}

export interface RecordUpdate {
  title?: string;
  data?: Record<string, unknown>;
  tags?: string[];
}

// ---------------------------------------------------------------------------
// Collections
// ---------------------------------------------------------------------------

export async function listCollections(workspaceId?: string): Promise<LookupCollection[]> {
  const params = workspaceId ? { workspace_id: workspaceId } : {};
  const res = await api.get<LookupCollection[]>("/api/v1/lookup/collections", { params });
  return res.data;
}

export async function createCollection(body: CollectionCreate): Promise<LookupCollection> {
  const res = await api.post<LookupCollection>("/api/v1/lookup/collections", body);
  return res.data;
}

export async function getCollection(id: string): Promise<LookupCollection> {
  const res = await api.get<LookupCollection>(`/api/v1/lookup/collections/${id}`);
  return res.data;
}

export async function updateCollection(
  id: string,
  body: CollectionUpdate
): Promise<LookupCollection> {
  const res = await api.put<LookupCollection>(`/api/v1/lookup/collections/${id}`, body);
  return res.data;
}

export async function deleteCollection(id: string): Promise<void> {
  await api.delete(`/api/v1/lookup/collections/${id}`);
}

// ---------------------------------------------------------------------------
// Records
// ---------------------------------------------------------------------------

export async function listRecords(
  collectionId: string,
  params?: { search?: string; limit?: number; skip?: number }
): Promise<PaginatedRecords> {
  const res = await api.get<PaginatedRecords>(
    `/api/v1/lookup/collections/${collectionId}/records`,
    { params }
  );
  return res.data;
}

export async function createRecord(
  collectionId: string,
  body: RecordCreate
): Promise<LookupRecord> {
  const res = await api.post<LookupRecord>(
    `/api/v1/lookup/collections/${collectionId}/records`,
    body
  );
  return res.data;
}

export async function updateRecord(id: string, body: RecordUpdate): Promise<LookupRecord> {
  const res = await api.put<LookupRecord>(`/api/v1/lookup/records/${id}`, body);
  return res.data;
}

export async function deleteRecord(id: string): Promise<void> {
  await api.delete(`/api/v1/lookup/records/${id}`);
}

// ---------------------------------------------------------------------------
// Import / Export
// ---------------------------------------------------------------------------

export async function importRecords(collectionId: string, file: File): Promise<ImportResult> {
  const formData = new FormData();
  formData.append("file", file);
  const res = await api.post<ImportResult>(
    `/api/v1/lookup/collections/${collectionId}/import`,
    formData,
    { headers: { "Content-Type": undefined } }
  );
  return res.data;
}

export function exportUrl(collectionId: string, format: "csv" | "json"): string {
  const base = process.env.NEXT_PUBLIC_API_URL ?? "";
  return `${base}/api/v1/lookup/collections/${collectionId}/export?format=${format}`;
}

// ---------------------------------------------------------------------------
// Stats
// ---------------------------------------------------------------------------

export async function getLookupStats(workspaceId?: string): Promise<LookupStats> {
  const params = workspaceId ? { workspace_id: workspaceId } : {};
  const res = await api.get<LookupStats>("/api/v1/lookup/stats", { params });
  return res.data;
}
