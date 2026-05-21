"use client";

import { PhoneOff } from "lucide-react";
import { Handle, Position } from "@xyflow/react";

export function EndCallNode() {
  return (
    <div className="relative flex items-center gap-2 rounded-full bg-red-500 px-5 py-2.5 shadow-md">
      <Handle
        type="target"
        position={Position.Top}
        className="!h-3 !w-3 !rounded-full !border-2 !border-white !bg-red-700"
      />
      <PhoneOff className="h-4 w-4 text-white" />
      <span className="text-sm font-bold text-white">End Call</span>
    </div>
  );
}
