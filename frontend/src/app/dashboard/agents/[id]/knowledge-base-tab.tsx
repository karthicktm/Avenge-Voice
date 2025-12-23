"use client";

import { useCallback, useEffect, useState } from "react";
import { useDropzone } from "react-dropzone";
import {
  AlertCircle,
  CheckCircle2,
  FileText,
  Loader2,
  RefreshCw,
  Trash2,
  Upload,
  X,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { toast } from "sonner";
import {
  deleteDocument,
  Document,
  formatFileSize,
  getFileTypeIcon,
  listDocuments,
  reindexDocument,
  uploadDocuments,
  validateFile,
} from "@/lib/api/documents";

interface KnowledgeBaseTabProps {
  agentId: string;
}

export function KnowledgeBaseTab({ agentId }: KnowledgeBaseTabProps) {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<Record<string, boolean>>({});

  // Auto-refresh when documents are processing
  const hasProcessing = documents.some((doc) => doc.status === "processing");

  // Fetch documents
  const fetchDocuments = useCallback(async () => {
    try {
      const data = await listDocuments(agentId);
      setDocuments(data.documents);
    } catch (error) {
      console.error("Failed to load documents:", error);
      toast.error("Failed to load documents");
    } finally {
      setLoading(false);
    }
  }, [agentId]);

  useEffect(() => {
    fetchDocuments();
  }, [fetchDocuments]);

  // Auto-refresh every 3 seconds when documents are processing
  useEffect(() => {
    if (!hasProcessing) return;

    const interval = setInterval(() => {
      fetchDocuments();
    }, 3000);

    return () => clearInterval(interval);
  }, [hasProcessing, fetchDocuments]);

  // Handle file drop
  const onDrop = useCallback(
    async (acceptedFiles: File[]) => {
      if (acceptedFiles.length === 0) return;

      // Validate all files first
      const validationResults = acceptedFiles.map((file) => ({
        file,
        validation: validateFile(file),
      }));

      const invalidFiles = validationResults.filter((r) => !r.validation.valid);
      if (invalidFiles.length > 0) {
        invalidFiles.forEach((r) => {
          toast.error(`${r.file.name}: ${r.validation.error}`);
        });
        return;
      }

      setUploading(true);
      const progressMap: Record<string, boolean> = {};
      acceptedFiles.forEach((file) => {
        progressMap[file.name] = true;
      });
      setUploadProgress(progressMap);

      try {
        const result = await uploadDocuments(agentId, acceptedFiles);

        // Show success for uploaded files
        if (result.total_uploaded > 0) {
          toast.success(`Successfully uploaded ${result.total_uploaded} file(s)`);
        }

        // Show errors for failed files
        result.errors.forEach((error) => {
          toast.error(`${error.filename}: ${error.error}`);
        });

        // Refresh document list
        await fetchDocuments();
      } catch (error) {
        console.error("Upload failed:", error);
        toast.error("Failed to upload documents");
      } finally {
        setUploading(false);
        setUploadProgress({});
      }
    },
    [agentId, fetchDocuments]
  );

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      "application/pdf": [".pdf"],
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [".docx"],
      "application/msword": [".doc"],
      "text/plain": [".txt"],
      "text/markdown": [".md"],
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"],
      "application/vnd.ms-excel": [".xls"],
    },
    multiple: true,
    disabled: uploading,
  });

  // Handle delete
  const handleDelete = async (documentId: string, filename: string) => {
    if (!confirm(`Are you sure you want to delete "${filename}"?`)) return;

    try {
      await deleteDocument(agentId, documentId);
      toast.success(`Deleted ${filename}`);
      await fetchDocuments();
    } catch (error) {
      console.error("Delete failed:", error);
      toast.error("Failed to delete document");
    }
  };

  // Handle reindex
  const handleReindex = async (documentId: string, filename: string) => {
    try {
      await reindexDocument(agentId, documentId);
      toast.success(`Reprocessing ${filename}`);
      await fetchDocuments();
    } catch (error) {
      console.error("Reindex failed:", error);
      toast.error("Failed to reindex document");
    }
  };

  return (
    <div className="space-y-6">
      {/* Info Card */}
      <Card>
        <CardHeader>
          <CardTitle>Knowledge Base</CardTitle>
          <CardDescription>
            Upload documents to create a custom knowledge base for your voice agent. The agent can
            search these documents during conversations to provide accurate answers.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="rounded-lg bg-muted p-4 text-sm">
            <p className="font-medium mb-2">How it works:</p>
            <ul className="list-disc list-inside space-y-1 text-muted-foreground">
              <li>Upload PDFs, Word docs, spreadsheets, or text files</li>
              <li>Documents are automatically chunked and indexed using AI embeddings</li>
              <li>The voice agent searches documents to answer customer questions</li>
              <li>Perfect for product info, policies, FAQs, and documentation</li>
            </ul>
          </div>
        </CardContent>
      </Card>

      {/* Upload Dropzone */}
      <Card>
        <CardHeader>
          <CardTitle>Upload Documents</CardTitle>
          <CardDescription>
            Drag and drop files or click to browse. Maximum 10MB per file.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div
            {...getRootProps()}
            className={`
              border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors
              ${isDragActive ? "border-primary bg-primary/5" : "border-border hover:border-primary/50"}
              ${uploading ? "opacity-50 cursor-not-allowed" : ""}
            `}
          >
            <input {...getInputProps()} />
            <Upload className="mx-auto h-12 w-12 text-muted-foreground mb-4" />
            {isDragActive ? (
              <p className="text-lg font-medium">Drop files here...</p>
            ) : uploading ? (
              <div className="space-y-2">
                <Loader2 className="mx-auto h-6 w-6 animate-spin text-primary" />
                <p className="text-lg font-medium">Uploading...</p>
                <div className="space-y-1">
                  {Object.keys(uploadProgress).map((filename) => (
                    <p key={filename} className="text-sm text-muted-foreground">
                      {filename}
                    </p>
                  ))}
                </div>
              </div>
            ) : (
              <div>
                <p className="text-lg font-medium mb-2">
                  Drag & drop files here, or click to select
                </p>
                <p className="text-sm text-muted-foreground">
                  Supported: PDF, DOCX, DOC, TXT, MD, XLSX, XLS (max 10MB each)
                </p>
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Documents Table */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>Uploaded Documents ({documents.length})</span>
            {hasProcessing && (
              <span className="text-sm font-normal text-muted-foreground flex items-center gap-2">
                <Loader2 className="h-4 w-4 animate-spin" />
                Processing...
              </span>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : documents.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              <FileText className="mx-auto h-12 w-12 mb-2 opacity-50" />
              <p>No documents uploaded yet</p>
              <p className="text-sm">Upload your first document to get started</p>
            </div>
          ) : (
            <div className="space-y-2">
              {documents.map((doc) => (
                <div
                  key={doc.id}
                  className="flex items-center justify-between p-4 border rounded-lg hover:bg-muted/50 transition-colors"
                >
                  <div className="flex items-center gap-3 flex-1 min-w-0">
                    <div className="text-2xl">{getFileTypeIcon(doc.file_type)}</div>
                    <div className="flex-1 min-w-0">
                      <p className="font-medium truncate">{doc.filename}</p>
                      <div className="flex items-center gap-4 text-sm text-muted-foreground">
                        <span>{formatFileSize(doc.file_size)}</span>
                        <span>{doc.file_type.toUpperCase()}</span>
                        {doc.status === "ready" && (
                          <span>{doc.chunk_count} chunks</span>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    {/* Status Badge */}
                    {doc.status === "ready" && (
                      <div className="flex items-center gap-1 text-green-600 bg-green-50 px-2 py-1 rounded text-sm">
                        <CheckCircle2 className="h-4 w-4" />
                        Ready
                      </div>
                    )}
                    {doc.status === "processing" && (
                      <div className="flex items-center gap-1 text-blue-600 bg-blue-50 px-2 py-1 rounded text-sm">
                        <Loader2 className="h-4 w-4 animate-spin" />
                        Processing
                      </div>
                    )}
                    {doc.status === "error" && (
                      <div
                        className="flex items-center gap-1 text-red-600 bg-red-50 px-2 py-1 rounded text-sm cursor-help"
                        title={doc.error_message}
                      >
                        <AlertCircle className="h-4 w-4" />
                        Error
                      </div>
                    )}

                    {/* Actions */}
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => handleReindex(doc.id, doc.filename)}
                      disabled={doc.status === "processing"}
                      title="Reprocess document"
                    >
                      <RefreshCw className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => handleDelete(doc.id, doc.filename)}
                      disabled={doc.status === "processing"}
                      title="Delete document"
                    >
                      <Trash2 className="h-4 w-4 text-red-600" />
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
