/**
 * Documents API client for Knowledge Base / RAG functionality.
 */

import { api } from "@/lib/api";

export interface Document {
  id: string;
  agent_id: string;
  filename: string;
  file_type: string;
  file_size: number;
  status: "pending" | "processing" | "ready" | "failed";
  error_message: string | null;
  chunk_count: number;
  created_at: string;
  updated_at: string;
  processed_at: string | null;
  source_type?: string;
  source_url?: string | null;
}

export interface DocumentListResponse {
  documents: Document[];
  total: number;
}

/**
 * Upload a document to an agent's knowledge base.
 */
export async function uploadDocument(agentId: string, file: File): Promise<Document> {
  const formData = new FormData();
  formData.append("file", file);

  const response = await api.post<Document>(`/api/v1/agents/${agentId}/documents`, formData, {
    headers: {
      "Content-Type": "multipart/form-data",
    },
  });
  return response.data;
}

/**
 * Upload multiple documents to an agent's knowledge base.
 */
export async function uploadDocuments(agentId: string, files: File[]): Promise<Document[]> {
  const results: Document[] = [];
  for (const file of files) {
    const doc = await uploadDocument(agentId, file);
    results.push(doc);
  }
  return results;
}

/**
 * List all documents in an agent's knowledge base.
 */
export async function listDocuments(agentId: string): Promise<DocumentListResponse> {
  const response = await api.get<DocumentListResponse>(`/api/v1/agents/${agentId}/documents`);
  return response.data;
}

/**
 * Get a specific document.
 */
export async function getDocument(agentId: string, documentId: string): Promise<Document> {
  const response = await api.get<Document>(`/api/v1/agents/${agentId}/documents/${documentId}`);
  return response.data;
}

/**
 * Delete a document from the knowledge base.
 */
export async function deleteDocument(agentId: string, documentId: string): Promise<void> {
  await api.delete(`/api/v1/agents/${agentId}/documents/${documentId}`);
}

/**
 * Reindex a document (reprocess with updated settings).
 */
export async function reindexDocument(agentId: string, documentId: string): Promise<Document> {
  const response = await api.post<Document>(
    `/api/v1/agents/${agentId}/documents/${documentId}/reindex`
  );
  return response.data;
}

export interface CrawlResponse {
  status: string;
  message: string;
}

/**
 * Trigger a site crawl for knowledge base indexing.
 */
export async function crawlSite(
  agentId: string,
  siteUrl: string,
  maxPages: number = 50
): Promise<CrawlResponse> {
  const response = await api.post<CrawlResponse>(`/api/v1/agents/${agentId}/crawl`, {
    site_url: siteUrl,
    max_pages: maxPages,
  });
  return response.data;
}

/**
 * Format file size for display.
 */
export function formatFileSize(bytes: number): string {
  if (bytes === 0) return "0 Bytes";
  const k = 1024;
  const sizes = ["Bytes", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
}

/**
 * Get status badge color for document status.
 */
export function getStatusColor(
  status: Document["status"]
): "default" | "secondary" | "destructive" | "outline" {
  switch (status) {
    case "ready":
      return "default";
    case "processing":
    case "pending":
      return "secondary";
    case "failed":
      return "destructive";
    default:
      return "outline";
  }
}
