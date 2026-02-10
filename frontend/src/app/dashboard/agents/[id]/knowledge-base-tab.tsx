"use client";

import { useCallback, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  AlertCircle,
  CheckCircle2,
  Clock,
  FileText,
  Globe,
  Loader2,
  RefreshCw,
  Trash2,
  Upload,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  crawlSite,
  listDocuments,
  uploadDocuments,
  deleteDocument,
  reindexDocument,
  formatFileSize,
  type Document,
} from "@/lib/api/documents";

interface KnowledgeBaseTabProps {
  agentId: string;
  siteUrl?: string;
  lastCrawlAt?: string;
  crawlScheduleHours?: number;
}

const SUPPORTED_TYPES = ["pdf", "docx", "txt", "md"];
const MAX_FILE_SIZE = 50 * 1024 * 1024; // 50MB

const SCHEDULE_LABELS: Record<number, string> = {
  6: "Every 6 hours",
  12: "Every 12 hours",
  24: "Every 24 hours",
  48: "Every 2 days",
  168: "Weekly",
};

export function KnowledgeBaseTab({
  agentId,
  siteUrl,
  lastCrawlAt,
  crawlScheduleHours,
}: KnowledgeBaseTabProps) {
  const queryClient = useQueryClient();
  const [isDragging, setIsDragging] = useState(false);
  const [crawlUrl, setCrawlUrl] = useState(siteUrl ?? "");

  // Fetch documents
  const {
    data: documentsData,
    isLoading,
    refetch,
  } = useQuery({
    queryKey: ["documents", agentId],
    queryFn: () => listDocuments(agentId),
    refetchInterval: (query) => {
      // Auto-refresh while documents are processing
      const docs = query.state.data?.documents ?? [];
      const hasProcessing = docs.some((d) => d.status === "pending" || d.status === "processing");
      return hasProcessing ? 3000 : false;
    },
  });

  const documents = documentsData?.documents ?? [];

  // Upload mutation
  const uploadMutation = useMutation({
    mutationFn: (files: File[]) => uploadDocuments(agentId, files),
    onSuccess: (uploaded) => {
      toast.success(`Uploaded ${uploaded.length} document${uploaded.length > 1 ? "s" : ""}`);
      void queryClient.invalidateQueries({ queryKey: ["documents", agentId] });
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to upload documents");
    },
  });

  // Delete mutation
  const deleteMutation = useMutation({
    mutationFn: (documentId: string) => deleteDocument(agentId, documentId),
    onSuccess: () => {
      toast.success("Document deleted");
      void queryClient.invalidateQueries({ queryKey: ["documents", agentId] });
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to delete document");
    },
  });

  // Reindex mutation
  const reindexMutation = useMutation({
    mutationFn: (documentId: string) => reindexDocument(agentId, documentId),
    onSuccess: () => {
      toast.success("Reindexing started");
      void queryClient.invalidateQueries({ queryKey: ["documents", agentId] });
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to reindex document");
    },
  });

  // Crawl mutation
  const crawlMutation = useMutation({
    mutationFn: (url: string) => crawlSite(agentId, url),
    onSuccess: (result) => {
      toast.success(result.message);
      void queryClient.invalidateQueries({ queryKey: ["documents", agentId] });
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to start crawl");
    },
  });

  // Validate and upload files
  const handleFiles = useCallback(
    (files: FileList | File[]) => {
      const fileArray = Array.from(files);
      const validFiles: File[] = [];
      const errors: string[] = [];

      for (const file of fileArray) {
        const ext = file.name.split(".").pop()?.toLowerCase();
        if (!ext || !SUPPORTED_TYPES.includes(ext)) {
          errors.push(`${file.name}: Unsupported file type`);
          continue;
        }
        if (file.size > MAX_FILE_SIZE) {
          errors.push(`${file.name}: File too large (max 50MB)`);
          continue;
        }
        validFiles.push(file);
      }

      if (errors.length > 0) {
        errors.forEach((err) => toast.error(err));
      }

      if (validFiles.length > 0) {
        uploadMutation.mutate(validFiles);
      }
    },
    [uploadMutation]
  );

  // Drag and drop handlers
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      if (e.dataTransfer.files.length > 0) {
        handleFiles(e.dataTransfer.files);
      }
    },
    [handleFiles]
  );

  // File input handler
  const handleFileInput = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      if (e.target.files && e.target.files.length > 0) {
        handleFiles(e.target.files);
        e.target.value = ""; // Reset input
      }
    },
    [handleFiles]
  );

  // Get status icon and color
  const getStatusDisplay = (status: Document["status"]) => {
    switch (status) {
      case "ready":
        return {
          icon: <CheckCircle2 className="h-4 w-4" />,
          variant: "default" as const,
          label: "Ready",
        };
      case "processing":
        return {
          icon: <Loader2 className="h-4 w-4 animate-spin" />,
          variant: "secondary" as const,
          label: "Processing",
        };
      case "pending":
        return {
          icon: <Clock className="h-4 w-4" />,
          variant: "secondary" as const,
          label: "Pending",
        };
      case "failed":
        return {
          icon: <AlertCircle className="h-4 w-4" />,
          variant: "destructive" as const,
          label: "Failed",
        };
    }
  };

  const handleCrawl = () => {
    if (!crawlUrl.trim()) {
      toast.error("Please enter a website URL");
      return;
    }
    crawlMutation.mutate(crawlUrl.trim());
  };

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-sm font-medium">Knowledge Base</CardTitle>
            <CardDescription>
              Upload documents or crawl websites to create a searchable knowledge base
            </CardDescription>
          </div>
          <Button variant="outline" size="sm" onClick={() => void refetch()}>
            <RefreshCw className="mr-1.5 h-3.5 w-3.5" />
            Refresh
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Upload area */}
        <div
          className={`relative rounded-lg border-2 border-dashed p-6 text-center transition-colors ${
            isDragging
              ? "border-primary bg-primary/5"
              : "border-muted-foreground/25 hover:border-muted-foreground/50"
          }`}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
        >
          <input
            type="file"
            multiple
            accept=".pdf,.docx,.txt,.md"
            className="absolute inset-0 cursor-pointer opacity-0"
            onChange={handleFileInput}
            disabled={uploadMutation.isPending}
          />
          <div className="flex flex-col items-center gap-2">
            {uploadMutation.isPending ? (
              <>
                <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
                <p className="text-sm text-muted-foreground">Uploading...</p>
              </>
            ) : (
              <>
                <Upload className="h-8 w-8 text-muted-foreground" />
                <p className="text-sm font-medium">Drag and drop files here, or click to browse</p>
                <p className="text-xs text-muted-foreground">
                  Supported: PDF, DOCX, TXT, MD (max 50MB each)
                </p>
              </>
            )}
          </div>
        </div>

        {/* Crawl Website section */}
        <div className="space-y-3 rounded-lg border bg-muted/30 p-4">
          <div className="flex items-center gap-2">
            <Globe className="h-4 w-4 text-muted-foreground" />
            <h4 className="text-sm font-medium">Crawl Website</h4>
          </div>
          <p className="text-xs text-muted-foreground">
            Automatically crawl a website and index its pages into the knowledge base.
          </p>
          {(!!crawlScheduleHours || lastCrawlAt) && (
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
              {!!crawlScheduleHours && SCHEDULE_LABELS[crawlScheduleHours] && (
                <span className="flex items-center gap-1">
                  <Clock className="h-3 w-3" />
                  Auto-crawl: {SCHEDULE_LABELS[crawlScheduleHours]}
                </span>
              )}
              {lastCrawlAt && (
                <span className="flex items-center gap-1">
                  <CheckCircle2 className="h-3 w-3" />
                  Last crawl: {new Date(lastCrawlAt).toLocaleString()}
                </span>
              )}
            </div>
          )}
          <div className="flex gap-2">
            <Input
              type="url"
              placeholder="https://www.example.com"
              className="h-8"
              value={crawlUrl}
              onChange={(e) => setCrawlUrl(e.target.value)}
              disabled={crawlMutation.isPending}
            />
            <Button
              size="sm"
              variant="outline"
              onClick={handleCrawl}
              disabled={crawlMutation.isPending || !crawlUrl.trim()}
            >
              {crawlMutation.isPending ? (
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
              ) : (
                <Globe className="mr-1.5 h-3.5 w-3.5" />
              )}
              Crawl Now
            </Button>
          </div>
        </div>

        {/* Documents list */}
        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : documents.length === 0 ? (
          <div className="rounded-lg border border-dashed p-8 text-center">
            <FileText className="mx-auto h-12 w-12 text-muted-foreground/50" />
            <p className="mt-2 text-sm font-medium text-muted-foreground">No documents uploaded</p>
            <p className="text-xs text-muted-foreground">
              Upload documents or crawl a website to enable knowledge base search
            </p>
          </div>
        ) : (
          <div className="rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Document</TableHead>
                  <TableHead>Size</TableHead>
                  <TableHead>Chunks</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="w-[100px]">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {documents.map((doc) => {
                  const statusDisplay = getStatusDisplay(doc.status);
                  const isWebCrawl = doc.source_type === "web_crawl";
                  return (
                    <TableRow key={doc.id}>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          {isWebCrawl ? (
                            <Globe className="h-4 w-4 text-muted-foreground" />
                          ) : (
                            <FileText className="h-4 w-4 text-muted-foreground" />
                          )}
                          <div>
                            <p className="text-sm font-medium">{doc.filename}</p>
                            <div className="flex items-center gap-1.5">
                              <p className="text-xs uppercase text-muted-foreground">
                                {doc.file_type}
                              </p>
                              {isWebCrawl && (
                                <Badge variant="outline" className="px-1 py-0 text-[10px]">
                                  Web Crawl
                                </Badge>
                              )}
                            </div>
                            {isWebCrawl && doc.source_url && (
                              <p
                                className="max-w-[200px] truncate text-[10px] text-muted-foreground"
                                title={doc.source_url}
                              >
                                {doc.source_url}
                              </p>
                            )}
                          </div>
                        </div>
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {formatFileSize(doc.file_size)}
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {doc.chunk_count > 0 ? doc.chunk_count : "-"}
                      </TableCell>
                      <TableCell>
                        <Badge variant={statusDisplay.variant} className="gap-1">
                          {statusDisplay.icon}
                          {statusDisplay.label}
                        </Badge>
                        {doc.error_message && (
                          <p className="mt-1 text-xs text-destructive">{doc.error_message}</p>
                        )}
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-1">
                          {doc.status === "failed" && (
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-8 w-8"
                              onClick={() => reindexMutation.mutate(doc.id)}
                              disabled={reindexMutation.isPending}
                              title="Retry processing"
                            >
                              <RefreshCw className="h-4 w-4" />
                            </Button>
                          )}
                          <AlertDialog>
                            <AlertDialogTrigger asChild>
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-8 w-8 text-destructive hover:text-destructive"
                                disabled={deleteMutation.isPending}
                              >
                                <Trash2 className="h-4 w-4" />
                              </Button>
                            </AlertDialogTrigger>
                            <AlertDialogContent>
                              <AlertDialogHeader>
                                <AlertDialogTitle>Delete document?</AlertDialogTitle>
                                <AlertDialogDescription>
                                  This will permanently delete &ldquo;{doc.filename}&rdquo; and
                                  remove it from the knowledge base. This action cannot be undone.
                                </AlertDialogDescription>
                              </AlertDialogHeader>
                              <AlertDialogFooter>
                                <AlertDialogCancel>Cancel</AlertDialogCancel>
                                <AlertDialogAction
                                  onClick={() => deleteMutation.mutate(doc.id)}
                                  className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                                >
                                  Delete
                                </AlertDialogAction>
                              </AlertDialogFooter>
                            </AlertDialogContent>
                          </AlertDialog>
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        )}

        {/* Info text */}
        <p className="text-xs text-muted-foreground">
          Documents are processed and split into searchable chunks. Your agent can search this
          knowledge base during calls to answer questions from your documentation.
        </p>
      </CardContent>
    </Card>
  );
}
