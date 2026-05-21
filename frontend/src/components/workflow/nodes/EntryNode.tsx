"use client";

import { Play } from "lucide-react";
import { Handle, Position } from "@xyflow/react";

export function EntryNode() {
  return (
    <div className="relative flex items-center gap-2 rounded-full bg-emerald-500 px-5 py-2.5 shadow-md">
      <Play className="h-4 w-4 fill-white text-white" />
      <span className="text-sm font-bold text-white">Start</span>
      <Handle
        type="source"
        position={Position.Bottom}
        className="!h-3 !w-3 !rounded-full !border-2 !border-white !bg-emerald-700"
      />
    </div>
  );
}
