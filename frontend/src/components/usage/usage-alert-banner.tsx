"use client";

import { AlertTriangle, ArrowUpRight, X } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface UsageAlertBannerProps {
  alertCount: number;
  onUpgradeClick?: () => void;
  className?: string;
}

export function UsageAlertBanner({ alertCount, onUpgradeClick, className }: UsageAlertBannerProps) {
  const [dismissed, setDismissed] = useState(false);

  if (dismissed || alertCount === 0) {
    return null;
  }

  return (
    <div
      className={cn(
        "relative flex items-center justify-between rounded-lg border border-yellow-500/50 bg-yellow-500/10 px-4 py-3",
        className
      )}
    >
      <div className="flex items-center gap-3">
        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-yellow-500/20">
          <AlertTriangle className="h-4 w-4 text-yellow-600 dark:text-yellow-400" />
        </div>
        <div>
          <p className="font-medium text-yellow-900 dark:text-yellow-100">
            {alertCount === 1
              ? "1 usage alert requires your attention"
              : `${alertCount} usage alerts require your attention`}
          </p>
          <p className="text-sm text-yellow-800/80 dark:text-yellow-200/80">
            You&apos;re approaching or have exceeded resource limits
          </p>
        </div>
      </div>
      <div className="flex items-center gap-2">
        {onUpgradeClick && (
          <Button
            size="sm"
            variant="outline"
            onClick={onUpgradeClick}
            className="border-yellow-500/50 bg-yellow-500/10 text-yellow-900 hover:bg-yellow-500/20 dark:text-yellow-100"
          >
            <ArrowUpRight className="mr-1 h-4 w-4" />
            Upgrade
          </Button>
        )}
        <Button
          size="icon"
          variant="ghost"
          onClick={() => setDismissed(true)}
          className="h-7 w-7 text-yellow-900/60 hover:text-yellow-900 dark:text-yellow-100/60 dark:hover:text-yellow-100"
        >
          <X className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
