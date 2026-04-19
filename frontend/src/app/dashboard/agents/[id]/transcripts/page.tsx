"use client";

import { use, useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  ArrowLeft,
  FileText,
  Loader2,
  AlertCircle,
  Clock,
  Music,
  Phone,
  PhoneIncoming,
  PhoneOutgoing,
  Download,
  ChevronLeft,
  ChevronRight,
  Calendar,
  User,
} from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { toast } from "sonner";
import { listCalls, downloadCallRecording, type CallRecord } from "@/lib/api/calls";
import { getAgent } from "@/lib/api/agents";

function formatDuration(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  if (mins === 0) return `${secs}s`;
  return `${mins}m ${secs}s`;
}

function formatPhoneNumber(number: string): string {
  if (number.startsWith("+1") && number.length === 12) {
    return `(${number.slice(2, 5)}) ${number.slice(5, 8)}-${number.slice(8)}`;
  }
  return number;
}

function formatDate(dateString: string): string {
  const date = new Date(dateString);
  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function formatTime(dateString: string): string {
  const date = new Date(dateString);
  return date.toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  });
}

function truncateTranscript(transcript: string, maxLength: number = 120): string {
  if (transcript.length <= maxLength) return transcript;
  return transcript.slice(0, maxLength).trim() + "...";
}

export default function TranscriptsPage({ params }: { params: Promise<{ id: string }> }) {
  const { id: agentId } = use(params);
  const router = useRouter();
  const [selectedCall, setSelectedCall] = useState<CallRecord | null>(null);
  const [page, setPage] = useState(1);
  const pageSize = 12;

  // Fetch agent details
  const {
    data: agent,
    isLoading: isLoadingAgent,
    error: agentError,
  } = useQuery({
    queryKey: ["agent", agentId],
    queryFn: () => getAgent(agentId),
  });

  // Fetch calls with transcripts for this agent
  const {
    data: callsData,
    isLoading: isLoadingCalls,
    error: callsError,
  } = useQuery({
    queryKey: ["agent-transcripts", agentId, page],
    queryFn: () =>
      listCalls({
        agent_id: agentId,
        page,
        page_size: pageSize,
      }),
  });

  // Filter to only calls with transcripts
  const callsWithTranscripts = useMemo(() => {
    return (callsData?.calls ?? []).filter((call) => call.transcript);
  }, [callsData?.calls]);

  const totalPages = callsData?.total_pages ?? 0;
  const isLoading = isLoadingAgent || isLoadingCalls;
  const error = agentError ?? callsError;

  const handleDownloadTranscript = (call: CallRecord) => {
    if (!call.transcript) return;

    const blob = new Blob([call.transcript], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `transcript-${call.id}-${formatDate(call.started_at)}.txt`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const handleDownloadRecording = async (call: CallRecord) => {
    if (!call.recording_url) return;
    try {
      await downloadCallRecording(call.id);
      toast.success("Recording download started");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to download recording");
    }
  };

  if (isLoading) {
    return (
      <div className="space-y-6">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="icon" asChild>
            <Link href="/dashboard/agents">
              <ArrowLeft className="h-4 w-4" />
            </Link>
          </Button>
          <div>
            <h1 className="text-xl font-semibold">Transcripts</h1>
            <p className="text-sm text-muted-foreground">Loading...</p>
          </div>
        </div>
        <Card>
          <CardContent className="flex items-center justify-center py-16">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          </CardContent>
        </Card>
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-6">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="icon" asChild>
            <Link href="/dashboard/agents">
              <ArrowLeft className="h-4 w-4" />
            </Link>
          </Button>
          <div>
            <h1 className="text-xl font-semibold">Transcripts</h1>
            <p className="text-sm text-muted-foreground">Error loading data</p>
          </div>
        </div>
        <Card className="border-destructive">
          <CardContent className="flex flex-col items-center justify-center py-16">
            <AlertCircle className="mb-4 h-16 w-16 text-destructive" />
            <h3 className="mb-2 text-lg font-semibold">Failed to load transcripts</h3>
            <p className="mb-4 text-center text-sm text-muted-foreground">
              {error instanceof Error ? error.message : "An unexpected error occurred"}
            </p>
            <Button variant="outline" onClick={() => router.back()}>
              Go Back
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="icon" asChild>
            <Link href="/dashboard/agents">
              <ArrowLeft className="h-4 w-4" />
            </Link>
          </Button>
          <div>
            <h1 className="text-xl font-semibold">Transcripts</h1>
            <p className="text-sm text-muted-foreground">
              {agent?.name} &middot;{" "}
              {callsWithTranscripts.length === 0
                ? "No transcripts yet"
                : `${callsData?.total ?? 0} calls, ${callsWithTranscripts.length} with transcripts`}
            </p>
          </div>
        </div>
      </div>

      {/* Content */}
      {callsWithTranscripts.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16">
            <FileText className="mb-4 h-16 w-16 text-muted-foreground/50" />
            <h3 className="mb-2 text-lg font-semibold">No transcripts yet</h3>
            <p className="mb-4 max-w-sm text-center text-sm text-muted-foreground">
              {agent?.enable_transcript
                ? "Transcripts will appear here once calls are made with this agent."
                : "Enable transcripts in agent settings to start recording conversations."}
            </p>
            <Button variant="outline" asChild>
              <Link href={`/dashboard/agents/${agentId}`}>
                {agent?.enable_transcript ? "View Agent" : "Enable Transcripts"}
              </Link>
            </Button>
          </CardContent>
        </Card>
      ) : (
        <>
          {/* Transcript Cards Grid */}
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {callsWithTranscripts.map((call) => (
              <Card
                key={call.id}
                className="group cursor-pointer transition-all hover:border-primary/50"
                onClick={() => setSelectedCall(call)}
              >
                <CardContent className="p-4">
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-center gap-2.5 overflow-hidden">
                      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-primary/10">
                        {call.direction === "inbound" ? (
                          <PhoneIncoming className="h-4 w-4 text-primary" />
                        ) : (
                          <PhoneOutgoing className="h-4 w-4 text-primary" />
                        )}
                      </div>
                      <div className="min-w-0">
                        <h3 className="truncate text-sm font-medium">
                          {call.contact_name ??
                            formatPhoneNumber(
                              call.direction === "inbound" ? call.from_number : call.to_number
                            )}
                        </h3>
                        <p className="text-xs text-muted-foreground">
                          {formatDate(call.started_at)} &middot; {formatTime(call.started_at)}
                        </p>
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-1.5">
                      <Badge
                        variant={call.direction === "inbound" ? "default" : "secondary"}
                        className="h-5 px-1.5 text-[10px]"
                      >
                        {call.direction}
                      </Badge>
                    </div>
                  </div>

                  {/* Transcript Preview */}
                  <p className="mt-2.5 line-clamp-3 min-h-[3lh] text-xs text-muted-foreground">
                    {truncateTranscript(call.transcript ?? "", 150)}
                  </p>

                  {/* Footer */}
                  <div className="mt-3 flex items-center justify-between border-t border-border/50 pt-3">
                    <div className="flex items-center gap-2 text-xs text-muted-foreground">
                      <Clock className="h-3 w-3" />
                      <span>{formatDuration(call.duration_seconds)}</span>
                    </div>
                    <div className="flex gap-1">
                      {call.recording_url && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-6 px-2 text-xs"
                          onClick={(e) => {
                            e.stopPropagation();
                            void handleDownloadRecording(call);
                          }}
                        >
                          <Music className="mr-1 h-3 w-3" />
                          Audio
                        </Button>
                      )}
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-6 px-2 text-xs"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDownloadTranscript(call);
                        }}
                      >
                        <Download className="mr-1 h-3 w-3" />
                        Download
                      </Button>
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between border-t pt-4">
              <p className="text-sm text-muted-foreground">
                Page {page} of {totalPages}
              </p>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page === 1}
                >
                  <ChevronLeft className="mr-1 h-4 w-4" />
                  Previous
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages}
                >
                  Next
                  <ChevronRight className="ml-1 h-4 w-4" />
                </Button>
              </div>
            </div>
          )}
        </>
      )}

      {/* Transcript Detail Dialog */}
      <Dialog open={!!selectedCall} onOpenChange={(open) => !open && setSelectedCall(null)}>
        <DialogContent className="max-h-[80vh] max-w-2xl overflow-hidden">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <FileText className="h-5 w-5" />
              Call Transcript
            </DialogTitle>
            <DialogDescription>
              {selectedCall && (
                <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <span className="flex items-center gap-1">
                    <Calendar className="h-3.5 w-3.5" />
                    {formatDate(selectedCall.started_at)} at {formatTime(selectedCall.started_at)}
                  </span>
                  <span className="flex items-center gap-1">
                    <Clock className="h-3.5 w-3.5" />
                    {formatDuration(selectedCall.duration_seconds)}
                  </span>
                  <span className="flex items-center gap-1">
                    <Phone className="h-3.5 w-3.5" />
                    {selectedCall.direction === "inbound"
                      ? formatPhoneNumber(selectedCall.from_number)
                      : formatPhoneNumber(selectedCall.to_number)}
                  </span>
                  {selectedCall.contact_name && (
                    <span className="flex items-center gap-1">
                      <User className="h-3.5 w-3.5" />
                      {selectedCall.contact_name}
                    </span>
                  )}
                </span>
              )}
            </DialogDescription>
          </DialogHeader>

          {/* Transcript Content */}
          <div className="max-h-[50vh] overflow-y-auto rounded-lg border bg-muted/30 p-4">
            <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed">
              {selectedCall?.transcript}
            </pre>
          </div>

          {/* Actions */}
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setSelectedCall(null)}>
              Close
            </Button>
            {selectedCall?.recording_url && (
              <Button variant="outline" onClick={() => void handleDownloadRecording(selectedCall)}>
                <Music className="mr-2 h-4 w-4" />
                Audio
              </Button>
            )}
            {selectedCall && (
              <Button onClick={() => handleDownloadTranscript(selectedCall)}>
                <Download className="mr-2 h-4 w-4" />
                Download
              </Button>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
