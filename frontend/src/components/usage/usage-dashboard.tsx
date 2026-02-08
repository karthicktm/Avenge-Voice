"use client";

import { useState } from "react";
import { AlertCircle, ArrowUpRight, BarChart3, RefreshCw, TrendingUp } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import { UsageMeter } from "./usage-meter";
import { UsageAlertBanner } from "./usage-alert-banner";
import { useUsageOverview, usePendingAlertsCount } from "@/hooks/use-usage";
import { getResourceDisplayName } from "@/lib/api/usage";

// Resource categories for organized display
const RESOURCE_CATEGORIES = {
  "Voice & Calls": ["voice_minutes", "concurrent_calls", "calls_per_day"],
  "AI & Generation": [
    "llm_tokens",
    "llm_input_tokens",
    "llm_output_tokens",
    "llm_requests",
    "realtime_session_minutes",
    "audio_processing_minutes",
    "image_generations",
    "video_minutes",
  ],
  Communication: ["sms_messages", "email_sends"],
  "Storage & Limits": ["storage_gb", "documents", "agents", "workspaces", "members", "contacts"],
};

interface UsageDashboardProps {
  onUpgradeClick?: () => void;
}

export function UsageDashboard({ onUpgradeClick }: UsageDashboardProps) {
  const { data: overview, isLoading, error, refetch } = useUsageOverview();
  const { data: alertsCount } = usePendingAlertsCount();

  const [selectedCategory, setSelectedCategory] = useState<string>("all");

  if (isLoading) {
    return <UsageDashboardSkeleton />;
  }

  if (error) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center py-12">
          <AlertCircle className="mb-4 h-12 w-12 text-destructive" />
          <p className="mb-4 text-center text-muted-foreground">Failed to load usage data</p>
          <Button variant="outline" onClick={() => void refetch()}>
            <RefreshCw className="mr-2 h-4 w-4" />
            Try Again
          </Button>
        </CardContent>
      </Card>
    );
  }

  if (!overview) {
    return null;
  }

  const hasAlerts = alertsCount && alertsCount.count > 0;

  // Get resources by category
  const getResourcesForCategory = (category: string) => {
    if (category === "all") {
      return Object.values(overview.resources);
    }
    const resourceTypes = RESOURCE_CATEGORIES[category as keyof typeof RESOURCE_CATEGORIES] || [];
    return resourceTypes
      .map((rt) => overview.resources[rt])
      .filter((r) => r && (r.limit !== 0 || r.unlimited));
  };

  const categories = ["all", ...Object.keys(RESOURCE_CATEGORIES)];

  return (
    <div className="space-y-6">
      {/* Alert Banner */}
      {hasAlerts && (
        <UsageAlertBanner alertCount={alertsCount.count} onUpgradeClick={onUpgradeClick} />
      )}

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">Usage Overview</h2>
          <p className="text-muted-foreground">Current billing period: {overview.period}</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => void refetch()}>
            <RefreshCw className="mr-2 h-4 w-4" />
            Refresh
          </Button>
          {onUpgradeClick && (
            <Button size="sm" onClick={onUpgradeClick}>
              <ArrowUpRight className="mr-2 h-4 w-4" />
              Upgrade Plan
            </Button>
          )}
        </div>
      </div>

      {/* Category Tabs */}
      <Tabs value={selectedCategory} onValueChange={setSelectedCategory}>
        <TabsList className="mb-4">
          {categories.map((cat) => (
            <TabsTrigger key={cat} value={cat} className="capitalize">
              {cat === "all" ? "All Resources" : cat}
            </TabsTrigger>
          ))}
        </TabsList>

        {categories.map((cat) => (
          <TabsContent key={cat} value={cat}>
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
              {getResourcesForCategory(cat)
                .filter((resource): resource is NonNullable<typeof resource> => !!resource)
                .map((resource) => (
                  <UsageMeter
                    key={resource.resource_type}
                    resourceType={resource.resource_type}
                    current={resource.current}
                    limit={resource.limit}
                    percentage={resource.percentage}
                    unlimited={resource.unlimited}
                  />
                ))}
            </div>
            {getResourcesForCategory(cat).length === 0 && (
              <div className="py-12 text-center text-muted-foreground">
                No resources to display in this category
              </div>
            )}
          </TabsContent>
        ))}
      </Tabs>

      {/* Quick Stats */}
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">Most Used</CardTitle>
            <TrendingUp className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            {(() => {
              const resources = Object.values(overview.resources)
                .filter((r) => !r.unlimited && r.limit && r.limit > 0)
                .sort((a, b) => b.percentage - a.percentage);
              const topResource = resources[0];
              if (!topResource) return <p className="text-muted-foreground">No usage yet</p>;
              return (
                <>
                  <p className="text-2xl font-bold">{topResource.percentage.toFixed(1)}%</p>
                  <p className="text-xs text-muted-foreground">
                    {getResourceDisplayName(topResource.resource_type)}
                  </p>
                </>
              );
            })()}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">Resources at Risk</CardTitle>
            <AlertCircle className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            {(() => {
              const atRisk = Object.values(overview.resources).filter(
                (r) => !r.unlimited && r.percentage >= 80
              );
              return (
                <>
                  <p className="text-2xl font-bold">{atRisk.length}</p>
                  <p className="text-xs text-muted-foreground">
                    {atRisk.length === 0 ? "All resources healthy" : "Above 80% usage"}
                  </p>
                </>
              );
            })()}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">Period Progress</CardTitle>
            <BarChart3 className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            {(() => {
              const start = new Date(overview.period_start);
              const end = new Date(overview.period_end);
              const now = new Date();
              const total = end.getTime() - start.getTime();
              const elapsed = now.getTime() - start.getTime();
              const progress = Math.min(Math.max((elapsed / total) * 100, 0), 100);
              return (
                <>
                  <p className="text-2xl font-bold">{progress.toFixed(0)}%</p>
                  <p className="text-xs text-muted-foreground">of billing period</p>
                </>
              );
            })()}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function UsageDashboardSkeleton() {
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <Skeleton className="mb-2 h-8 w-48" />
          <Skeleton className="h-4 w-32" />
        </div>
        <div className="flex gap-2">
          <Skeleton className="h-9 w-24" />
          <Skeleton className="h-9 w-32" />
        </div>
      </div>

      <Skeleton className="h-10 w-full max-w-xl" />

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <Card key={i}>
            <CardContent className="p-4">
              <Skeleton className="mb-3 h-4 w-24" />
              <Skeleton className="mb-2 h-8 w-32" />
              <Skeleton className="h-2 w-full" />
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
