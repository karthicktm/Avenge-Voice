"use client";

import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { type GenerateWorkflowResponse } from "@/lib/api/workflows";

const TYPE_LABEL: Record<string, string> = {
  entry: "Entry",
  categorize: "Categorize",
  condition: "Condition",
  transfer: "Transfer",
  instruction: "Instruction",
  collect_email: "Collect Email",
  sms: "SMS",
  appointment: "Appointment",
  webhook: "Webhook",
  voicemail: "Voicemail",
  end_call: "End Call",
  subagent: "Sub-Agent",
  lookup_transfer: "Lookup & Transfer",
};

interface WorkflowPreviewModalProps {
  result: GenerateWorkflowResponse | null;
  onReplace: () => void;
  onAppend: () => void;
  onDiscard: () => void;
}

export function WorkflowPreviewModal({
  result,
  onReplace,
  onAppend,
  onDiscard,
}: WorkflowPreviewModalProps) {
  return (
    <Dialog open={!!result} onOpenChange={() => onDiscard()}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>
            {result?.intent === "workflow" ? "Generated Workflow" : "Generated Node"}
          </DialogTitle>
        </DialogHeader>

        <div className="max-h-60 space-y-1.5 overflow-y-auto">
          {result?.nodes.map((node) => (
            <div key={node.id} className="flex items-center gap-2 rounded border px-2.5 py-1.5">
              <Badge variant="secondary" className="shrink-0 text-xs">
                {TYPE_LABEL[node.type ?? ""] ?? node.type}
              </Badge>
              <span className="truncate text-sm">{node.label}</span>
            </div>
          ))}
        </div>

        {result && (
          <p className="text-xs text-muted-foreground">
            {result.nodes.length} node{result.nodes.length !== 1 ? "s" : ""}, {result.edges.length}{" "}
            connection{result.edges.length !== 1 ? "s" : ""}
            {result.agent_name && (
              <>
                {" "}
                — generated with <strong>{result.agent_name}</strong> context
              </>
            )}
          </p>
        )}

        <DialogFooter className="gap-2 sm:justify-start">
          <Button variant="ghost" size="sm" onClick={onDiscard}>
            Discard
          </Button>
          <Button variant="outline" size="sm" onClick={onAppend}>
            Append
          </Button>
          <Button size="sm" onClick={onReplace}>
            Replace Canvas
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
