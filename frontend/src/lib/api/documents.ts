/**
 * Document API client for RAG knowledge base management.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

function getAuthHeaders(): HeadersInit {
  if (typeof window === "undefined") return {};
  const token = localStorage.getItem("access_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/**
 * Fetch with timeout to prevent hanging requests
 */
async function fetchWithTimeout(
  url: string,
  options: RequestInit = {},
  timeoutMs = 30000 // Longer timeout for file uploads
): Promise<Response> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  // Merge auth headers with any provided headers
  const headers = {
    ...getAuthHeaders(),
    ...(options.headers ?? {}),
  };

  try {
    const response = await fetch(url, {
      ...options,
      headers,
      signal: controller.signal,
    });
    return response;
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      throw new Error("Request timed out - please check if the backend is running");
    }
    throw error;
  } finally {
    clearTimeout(timeoutId);
  }
}

export interface Document {
  id: string;
  filename: string;
  file_type: string;
  file_size: number;
  status: "uploading" | "processing" | "ready" | "error";
  chunk_count: number;
  error_message?: string;
  created_at: string;
  updated_at: string;
}

export interface DocumentUploadResponse {
  documents: Array<{
    id: string;
    filename: string;
    file_type: string;
    file_size: number;
    status: string;
    created_at: string;
  }>;
  errors: Array<{
    filename: string;
    error: string;
  }>;
  total_uploaded: number;
  total_failed: number;
}

export interface DocumentListResponse {
  documents: Document[];
  total: number;
}

/**
 * Upload multiple documents to an agent's knowledge base.
 */
export async function uploadDocuments(
  agentId: string,
  files: File[]
): Promise<DocumentUploadResponse> {
  const formData = new FormData();

  // Add all files to FormData
  files.forEach((file) => {
    formData.append("files", file);
  });

  // Note: Don't set Content-Type header - browser will set it automatically with boundary
  const response = await fetchWithTimeout(
    `${API_BASE}/api/v1/agents/${agentId}/documents`,
    {
      method: "POST",
      body: formData,
    }
  );

  if (!response.ok) {
    throw new Error(`Upload failed: ${response.statusText}`);
  }

  return response.json();
}

/**
 * List all documents for an agent.
 */
export async function listDocuments(
  agentId: string
): Promise<DocumentListResponse> {
  const response = await fetchWithTimeout(
    `${API_BASE}/api/v1/agents/${agentId}/documents`
  );

  if (!response.ok) {
    throw new Error(`Failed to fetch documents: ${response.statusText}`);
  }

  return response.json();
}

/**
 * Delete a document from an agent's knowledge base.
 */
export async function deleteDocument(
  agentId: string,
  documentId: string
): Promise<void> {
  const response = await fetchWithTimeout(
    `${API_BASE}/api/v1/agents/${agentId}/documents/${documentId}`,
    {
      method: "DELETE",
    }
  );

  if (!response.ok) {
    throw new Error(`Failed to delete document: ${response.statusText}`);
  }
}

/**
 * Reindex a document (delete old chunks and re-embed).
 */
export async function reindexDocument(
  agentId: string,
  documentId: string
): Promise<{ message: string; document_id: string; status: string }> {
  const response = await fetchWithTimeout(
    `${API_BASE}/api/v1/agents/${agentId}/documents/${documentId}/reindex`,
    {
      method: "POST",
    }
  );

  if (!response.ok) {
    throw new Error(`Failed to reindex document: ${response.statusText}`);
  }

  return response.json();
}

/**
 * Format file size for display.
 */
export function formatFileSize(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`;
}

/**
 * Get file type icon based on extension.
 */
export function getFileTypeIcon(fileType: string): string {
  const icons: Record<string, string> = {
    pdf: "📄",
    docx: "📝",
    doc: "📝",
    txt: "📃",
    md: "📋",
    xlsx: "📊",
    xls: "📊",
  };
  return icons[fileType.toLowerCase()] ?? "📎";
}

/**
 * Validate file before upload.
 */
export function validateFile(file: File): { valid: boolean; error?: string } {
  const maxSize = 10 * 1024 * 1024; // 10MB
  const allowedTypes = ["pdf", "docx", "doc", "txt", "md", "xlsx", "xls"];
  const extension = file.name.split(".").pop()?.toLowerCase() ?? "";

  if (!allowedTypes.includes(extension)) {
    return {
      valid: false,
      error: `File type .${extension} not allowed. Allowed types: ${allowedTypes.join(", ")}`,
    };
  }

  if (file.size > maxSize) {
    return {
      valid: false,
      error: `File too large (${formatFileSize(file.size)}). Maximum size is 10MB.`,
    };
  }

  return { valid: true };
}
