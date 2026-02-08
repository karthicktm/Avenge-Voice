"use client";

import { cn } from "@/lib/utils";
import { Progress } from "@/components/ui/progress";
import { formatResourceValue, getResourceDisplayName, getUsageColor } from "@/lib/api/usage";

interface UsageMeterProps {
  resourceType: string;
  current: number;
  limit: number | null;
  percentage: number;
  unlimited?: boolean;
  className?: string;
  showLabel?: boolean;
  compact?: boolean;
}

export function UsageMeter({
  resourceType,
  current,
  limit,
  percentage,
  unlimited = false,
  className,
  showLabel = true,
  compact = false,
}: UsageMeterProps) {
  const color = getUsageColor(percentage);
  const displayName = getResourceDisplayName(resourceType);

  const colorClasses = {
    green: "bg-green-500",
    yellow: "bg-yellow-500",
    orange: "bg-orange-500",
    red: "bg-red-500",
  };

  const indicatorClass = colorClasses[color as keyof typeof colorClasses] || colorClasses.green;

  if (compact) {
    return (
      <div className={cn("space-y-1", className)}>
        <div className="flex items-center justify-between text-sm">
          <span className="text-muted-foreground">{displayName}</span>
          <span className="font-medium">
            {unlimited ? (
              <span className="text-muted-foreground">Unlimited</span>
            ) : (
              <>
                {formatResourceValue(current, resourceType)}
                {limit && (
                  <span className="text-muted-foreground">
                    {" "}
                    / {formatResourceValue(limit, resourceType)}
                  </span>
                )}
              </>
            )}
          </span>
        </div>
        {!unlimited && (
          <Progress value={percentage} className="h-1.5" indicatorClassName={indicatorClass} />
        )}
      </div>
    );
  }

  return (
    <div className={cn("rounded-lg border bg-card p-4", className)}>
      {showLabel && <h4 className="mb-3 text-sm font-medium">{displayName}</h4>}

      <div className="space-y-3">
        <div className="flex items-baseline justify-between">
          <span className="text-2xl font-bold">{formatResourceValue(current, resourceType)}</span>
          {unlimited ? (
            <span className="text-sm text-muted-foreground">Unlimited</span>
          ) : (
            limit && (
              <span className="text-sm text-muted-foreground">
                of {formatResourceValue(limit, resourceType)}
              </span>
            )
          )}
        </div>

        {!unlimited && (
          <>
            <Progress
              value={Math.min(percentage, 100)}
              className="h-2"
              indicatorClassName={indicatorClass}
            />
            <div className="flex items-center justify-between text-xs text-muted-foreground">
              <span>{percentage.toFixed(1)}% used</span>
              {limit && (
                <span>
                  {formatResourceValue(Math.max(limit - current, 0), resourceType)} remaining
                </span>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
