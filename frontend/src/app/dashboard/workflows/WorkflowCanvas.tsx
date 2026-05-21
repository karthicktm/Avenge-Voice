"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  addEdge,
  useNodesState,
  useEdgesState,
  type Connection,
  type Edge,
  type Node,
  MarkerType,
  BackgroundVariant,
  Panel,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  ArrowLeft,
  Save,
  Play,
  PhoneOff,
  Tags,
  GitBranch,
  PhoneForwarded,
  Mail,
  MessageSquare,
  BookUser,
  Webhook,
  MessageCircle,
  CalendarPlus,
  Voicemail,
  Bot,
  ChevronRight,
  AlertCircle,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { NodeConfigPanel } from "@/components/workflow/NodeConfigPanel";
import { EntryNode } from "@/components/workflow/nodes/EntryNode";
import { CategorizeNode } from "@/components/workflow/nodes/CategorizeNode";
import { ConditionNode } from "@/components/workflow/nodes/ConditionNode";
import { TransferNode } from "@/components/workflow/nodes/TransferNode";
import { CollectEmailNode } from "@/components/workflow/nodes/CollectEmailNode";
import { InstructionNode } from "@/components/workflow/nodes/InstructionNode";
import { LookupTransferNode } from "@/components/workflow/nodes/LookupTransferNode";
import { WebhookNode } from "@/components/workflow/nodes/WebhookNode";
import { SmsNode } from "@/components/workflow/nodes/SmsNode";
import { AppointmentNode } from "@/components/workflow/nodes/AppointmentNode";
import { VoicemailNode } from "@/components/workflow/nodes/VoicemailNode";
import { SubagentNode } from "@/components/workflow/nodes/SubagentNode";
import { EndCallNode } from "@/components/workflow/nodes/EndCallNode";
import {
  updateWorkflow,
  type Workflow,
  type WorkflowNode,
  type WorkflowEdge,
  type WorkflowNodeType,
} from "@/lib/api/workflows";
import { listCategoryTrees } from "@/lib/api/category-trees";

// ── ReactFlow node type registry ─────────────────────────────────────────────

const nodeTypes = {
  entry: EntryNode,
  categorize: CategorizeNode,
  condition: ConditionNode,
  transfer: TransferNode,
  collect_email: CollectEmailNode,
  instruction: InstructionNode,
  lookup_transfer: LookupTransferNode,
  webhook: WebhookNode,
  sms: SmsNode,
  appointment: AppointmentNode,
  voicemail: VoicemailNode,
  subagent: SubagentNode,
  end_call: EndCallNode,
};

// ── Node palette definition ───────────────────────────────────────────────────

interface PaletteItem {
  type: WorkflowNodeType;
  label: string;
  description: string;
  icon: React.ReactNode;
  color: string;
  defaultLabel: string;
  defaultConfig: Record<string, string>;
}

const PALETTE_GROUPS: Array<{ group: string; items: PaletteItem[] }> = [
  {
    group: "Flow",
    items: [
      {
        type: "entry",
        label: "Start",
        description: "Entry point of the workflow",
        icon: <Play className="h-4 w-4" />,
        color: "bg-emerald-100 text-emerald-700",
        defaultLabel: "Start",
        defaultConfig: {},
      },
      {
        type: "condition",
        label: "Condition",
        description: "Branch based on a condition",
        icon: <GitBranch className="h-4 w-4" />,
        color: "bg-orange-100 text-orange-700",
        defaultLabel: "Branch",
        defaultConfig: { condition: "action_type == transfer" },
      },
      {
        type: "end_call",
        label: "End Call",
        description: "Hang up the call",
        icon: <PhoneOff className="h-4 w-4" />,
        color: "bg-red-100 text-red-700",
        defaultLabel: "End Call",
        defaultConfig: {},
      },
    ],
  },
  {
    group: "AI",
    items: [
      {
        type: "categorize",
        label: "Categorize",
        description: "Classify caller intent using a category tree",
        icon: <Tags className="h-4 w-4" />,
        color: "bg-blue-100 text-blue-700",
        defaultLabel: "Classify caller",
        defaultConfig: { llm_provider: "openai", llm_model: "gpt-4o-mini" },
      },
      {
        type: "subagent",
        label: "Subagent",
        description: "Override agent prompt/model/voice for this step",
        icon: <Bot className="h-4 w-4" />,
        color: "bg-purple-100 text-purple-700",
        defaultLabel: "Specialist agent",
        defaultConfig: {},
      },
    ],
  },
  {
    group: "Communication",
    items: [
      {
        type: "transfer",
        label: "Transfer",
        description: "Transfer call to a number",
        icon: <PhoneForwarded className="h-4 w-4" />,
        color: "bg-orange-100 text-orange-700",
        defaultLabel: "Transfer call",
        defaultConfig: {},
      },
      {
        type: "sms",
        label: "Send SMS",
        description: "Send an SMS to the caller",
        icon: <MessageCircle className="h-4 w-4" />,
        color: "bg-pink-100 text-pink-700",
        defaultLabel: "Send SMS",
        defaultConfig: { to: "{{caller_number}}" },
      },
      {
        type: "instruction",
        label: "Instruction",
        description: "Read a script or give information",
        icon: <MessageSquare className="h-4 w-4" />,
        color: "bg-amber-100 text-amber-700",
        defaultLabel: "Read script",
        defaultConfig: {},
      },
      {
        type: "lookup_transfer",
        label: "Lookup + Transfer",
        description: "Phonebook lookup, then transfer",
        icon: <BookUser className="h-4 w-4" />,
        color: "bg-teal-100 text-teal-700",
        defaultLabel: "Phonebook lookup → transfer",
        defaultConfig: {},
      },
    ],
  },
  {
    group: "Collect",
    items: [
      {
        type: "collect_email",
        label: "Collect + Email",
        description: "Gather info from caller, send email report",
        icon: <Mail className="h-4 w-4" />,
        color: "bg-violet-100 text-violet-700",
        defaultLabel: "Collect info & email",
        defaultConfig: {},
      },
      {
        type: "appointment",
        label: "Appointment",
        description: "Book an appointment",
        icon: <CalendarPlus className="h-4 w-4" />,
        color: "bg-indigo-100 text-indigo-700",
        defaultLabel: "Book appointment",
        defaultConfig: {},
      },
      {
        type: "voicemail",
        label: "Voicemail",
        description: "Record a caller message",
        icon: <Voicemail className="h-4 w-4" />,
        color: "bg-rose-100 text-rose-700",
        defaultLabel: "Record voicemail",
        defaultConfig: { max_seconds: "60" },
      },
    ],
  },
  {
    group: "Integration",
    items: [
      {
        type: "webhook",
        label: "Webhook",
        description: "HTTP request to an external URL",
        icon: <Webhook className="h-4 w-4" />,
        color: "bg-cyan-100 text-cyan-700",
        defaultLabel: "HTTP request",
        defaultConfig: { method: "POST" },
      },
    ],
  },
];

// ── Converters ────────────────────────────────────────────────────────────────

function wfNodesToFlow(nodes: WorkflowNode[]): Node[] {
  return nodes.map((n, i) => ({
    id: n.id,
    type: n.type,
    position: n.position ?? { x: 200 + i * 240, y: 100 + (i % 3) * 140 },
    data: { ...n },
  }));
}

function wfEdgesToFlow(edges: WorkflowEdge[]): Edge[] {
  return edges.map((e) => {
    const isNo = e.sourceHandle === "no";
    const isYes = e.sourceHandle === "yes";
    return {
      id: e.id,
      source: e.from,
      target: e.to,
      sourceHandle: e.sourceHandle,
      label: e.label ?? e.condition ?? undefined,
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color: isNo ? "#ef4444" : isYes ? "#22c55e" : "#6366f1",
      },
      style: { stroke: isNo ? "#ef4444" : isYes ? "#22c55e" : "#6366f1", strokeWidth: 2 },
      labelStyle: { fontSize: 11, fontWeight: 500 },
      labelBgStyle: { fill: "#fff", fillOpacity: 0.85 },
    };
  });
}

function flowToWfNodes(nodes: Node[]): WorkflowNode[] {
  return nodes.map((n) => {
    const d = n.data as unknown as WorkflowNode;
    return {
      id: n.id,
      type: n.type as WorkflowNodeType,
      label: d.label,
      config: d.config,
      position: n.position,
    };
  });
}

function flowToWfEdges(edges: Edge[]): WorkflowEdge[] {
  return edges.map((e) => ({
    id: e.id,
    from: e.source,
    to: e.target,
    sourceHandle: e.sourceHandle ?? undefined,
    condition: typeof e.label === "string" ? e.label : undefined,
  }));
}

// ── Props ─────────────────────────────────────────────────────────────────────

interface Props {
  workflow: Workflow;
  onBack: () => void;
  onSaved: (updated: Workflow) => void;
}

let _nodeCounter = 1;

// ── Component ─────────────────────────────────────────────────────────────────

export function WorkflowCanvas({ workflow, onBack, onSaved }: Props) {
  const [nodes, setNodes, onNodesChange] = useNodesState(wfNodesToFlow(workflow.nodes));
  const [edges, setEdges, onEdgesChange] = useEdgesState(wfEdgesToFlow(workflow.edges));
  const [selectedNode, setSelectedNode] = useState<Node | null>(null);
  const [dirty, setDirty] = useState(false);
  const reactFlowWrapper = useRef<HTMLDivElement>(null);

  const { data: trees = [] } = useQuery({
    queryKey: ["category-trees-names", workflow.workspace_id],
    queryFn: async () => {
      const result = await listCategoryTrees(workflow.workspace_id);
      return result.map((t: { tree_name: string }) => t.tree_name);
    },
  });

  const saveMutation = useMutation({
    mutationFn: () =>
      updateWorkflow(workflow.id, { nodes: flowToWfNodes(nodes), edges: flowToWfEdges(edges) }),
    onSuccess: (updated) => {
      onSaved(updated);
      setDirty(false);
      toast.success("Workflow saved");
    },
    onError: () => toast.error("Failed to save workflow"),
  });

  // Mark dirty whenever nodes/edges change after initial load
  const initialised = useRef(false);
  useEffect(() => {
    if (!initialised.current) {
      initialised.current = true;
      return;
    }
    setDirty(true);
  }, [nodes, edges]);

  // Keyboard shortcuts: Delete = remove selected; Cmd/Ctrl+S = save
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "s") {
        e.preventDefault();
        saveMutation.mutate();
      }
      if ((e.key === "Delete" || e.key === "Backspace") && selectedNode) {
        const tag = (e.target as HTMLElement).tagName;
        if (tag === "INPUT" || tag === "TEXTAREA") return;
        deleteNode(selectedNode.id);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const onConnect = useCallback(
    (connection: Connection) => {
      const isYes = connection.sourceHandle === "yes";
      const isNo = connection.sourceHandle === "no";
      setEdges((eds) =>
        addEdge(
          {
            ...connection,
            label: isYes ? "Yes" : isNo ? "No" : undefined,
            markerEnd: {
              type: MarkerType.ArrowClosed,
              color: isNo ? "#ef4444" : isYes ? "#22c55e" : "#6366f1",
            },
            style: { stroke: isNo ? "#ef4444" : isYes ? "#22c55e" : "#6366f1", strokeWidth: 2 },
            labelStyle: { fontSize: 11, fontWeight: 500 },
            labelBgStyle: { fill: "#fff", fillOpacity: 0.85 },
          },
          eds
        )
      );
    },
    [setEdges]
  );

  function addNode(item: PaletteItem) {
    const id = `n${Date.now()}_${_nodeCounter++}`;
    setNodes((ns) => [
      ...ns,
      {
        id,
        type: item.type,
        position: { x: 300, y: 80 + ns.length * 140 },
        data: { id, type: item.type, label: item.defaultLabel, config: { ...item.defaultConfig } },
      },
    ]);
  }

  function deleteNode(nodeId: string) {
    setNodes((ns) => ns.filter((n) => n.id !== nodeId));
    setEdges((es) => es.filter((e) => e.source !== nodeId && e.target !== nodeId));
    setSelectedNode(null);
  }

  function updateNodeConfig(nodeId: string, config: WorkflowNode["config"]) {
    setNodes((ns) => ns.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, config } } : n)));
    setSelectedNode((prev) =>
      prev?.id === nodeId ? { ...prev, data: { ...prev.data, config } } : prev
    );
  }

  function updateNodeLabel(nodeId: string, label: string) {
    setNodes((ns) => ns.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, label } } : n)));
    setSelectedNode((prev) =>
      prev?.id === nodeId ? { ...prev, data: { ...prev.data, label } } : prev
    );
  }

  return (
    <div className="flex h-full flex-col bg-gray-50">
      {/* ── Toolbar ── */}
      <div className="flex items-center gap-3 border-b bg-white px-4 py-2.5 shadow-sm">
        <Button variant="ghost" size="icon" onClick={onBack} title="Back to workflows">
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <span className="font-semibold text-gray-800">{workflow.name}</span>

        {dirty && (
          <span className="flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-600">
            <AlertCircle className="h-3 w-3" />
            Unsaved changes
          </span>
        )}

        <div className="flex-1" />

        <span className="text-xs text-gray-400">⌘S to save · Delete to remove node</span>

        <Button
          size="sm"
          onClick={() => saveMutation.mutate()}
          disabled={saveMutation.isPending || !dirty}
          className="gap-1.5"
        >
          <Save className="h-3.5 w-3.5" />
          {saveMutation.isPending ? "Saving…" : "Save"}
        </Button>
      </div>

      {/* ── Main area ── */}
      <div className="flex flex-1 overflow-hidden">
        {/* ── Node Palette ── */}
        <aside className="flex w-56 shrink-0 flex-col border-r bg-white">
          <div className="border-b px-3 py-2.5">
            <p className="text-xs font-semibold uppercase tracking-wider text-gray-500">Nodes</p>
          </div>
          <div className="flex-1 overflow-y-auto py-2">
            {PALETTE_GROUPS.map((group) => (
              <div key={group.group} className="mb-1">
                <p className="px-3 py-1 text-[10px] font-semibold uppercase tracking-widest text-gray-400">
                  {group.group}
                </p>
                {group.items.map((item) => (
                  <button
                    key={item.type}
                    type="button"
                    className="group flex w-full items-center gap-2.5 px-3 py-2 text-left transition-colors hover:bg-gray-50 active:bg-gray-100"
                    onClick={() => addNode(item)}
                    title={item.description}
                  >
                    <span
                      className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${item.color}`}
                    >
                      {item.icon}
                    </span>
                    <div className="min-w-0">
                      <p className="text-xs font-medium text-gray-800">{item.label}</p>
                      <p className="truncate text-[10px] text-gray-400">{item.description}</p>
                    </div>
                    <ChevronRight className="ml-auto h-3 w-3 shrink-0 text-gray-300 opacity-0 transition-opacity group-hover:opacity-100" />
                  </button>
                ))}
              </div>
            ))}
          </div>
        </aside>

        {/* ── Canvas ── */}
        <div ref={reactFlowWrapper} className="relative flex-1">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeClick={(_, node) => setSelectedNode(node)}
            onPaneClick={() => setSelectedNode(null)}
            deleteKeyCode={null}
            fitView
            fitViewOptions={{ padding: 0.2 }}
            proOptions={{ hideAttribution: true }}
          >
            <Background variant={BackgroundVariant.Dots} gap={16} size={1} color="#d1d5db" />
            <Controls className="rounded-lg border bg-white shadow-sm" />
            <MiniMap
              className="rounded-lg border bg-white shadow-sm"
              nodeColor={(n) => {
                const map: Record<string, string> = {
                  entry: "#22c55e",
                  end_call: "#ef4444",
                  categorize: "#3b82f6",
                  condition: "#f97316",
                  transfer: "#f97316",
                  collect_email: "#8b5cf6",
                  instruction: "#f59e0b",
                  lookup_transfer: "#14b8a6",
                  webhook: "#0891b2",
                  sms: "#ec4899",
                  appointment: "#6366f1",
                  voicemail: "#f43f5e",
                  subagent: "#9333ea",
                };
                return map[n.type ?? ""] ?? "#9ca3af";
              }}
            />

            {/* Empty state */}
            {nodes.length === 0 && (
              <Panel position="top-center" className="pointer-events-none select-none">
                <div className="mt-32 flex flex-col items-center gap-2 text-gray-400">
                  <GitBranch className="h-10 w-10 opacity-30" />
                  <p className="text-sm font-medium">Click a node in the sidebar to add it</p>
                </div>
              </Panel>
            )}
          </ReactFlow>
        </div>

        {/* ── Config Panel ── */}
        {selectedNode && (
          <div className="w-72 shrink-0 border-l bg-white shadow-sm">
            <NodeConfigPanel
              node={selectedNode}
              availableTrees={trees}
              onChange={updateNodeConfig}
              onLabelChange={updateNodeLabel}
              onDelete={deleteNode}
              onClose={() => setSelectedNode(null)}
            />
          </div>
        )}
      </div>
    </div>
  );
}
