"use client";

import { Check, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { usePlans } from "@/hooks/use-billing";
import { cn } from "@/lib/utils";

interface PlanSelectorProps {
  currentPlan?: string;
  onSelectPlan: (planType: string, priceId: string) => void;
  isLoading?: boolean;
  priceIds?: Record<string, string>;
}

// Feature highlights for each plan
const PLAN_FEATURES: Record<string, string[]> = {
  free: ["1 Agent", "1 Workspace", "10 Voice Minutes/mo", "Basic Support"],
  starter: [
    "5 Agents",
    "3 Workspaces",
    "500 Voice Minutes/mo",
    "10K LLM Requests/mo",
    "Email Support",
  ],
  professional: [
    "20 Agents",
    "10 Workspaces",
    "2,000 Voice Minutes/mo",
    "50K LLM Requests/mo",
    "Priority Support",
    "Advanced Analytics",
  ],
  enterprise: [
    "Unlimited Agents",
    "Unlimited Workspaces",
    "Unlimited Voice Minutes",
    "Unlimited LLM Requests",
    "24/7 Dedicated Support",
    "Custom Integrations",
    "SLA Guarantee",
  ],
};

const PLAN_PRICES: Record<string, number> = {
  free: 0,
  starter: 49,
  professional: 199,
  enterprise: -1, // Contact sales
};

export function PlanSelector({
  currentPlan = "free",
  onSelectPlan,
  isLoading = false,
  priceIds = {},
}: PlanSelectorProps) {
  const { isLoading: plansLoading } = usePlans();

  if (plansLoading) {
    return <PlanSelectorSkeleton />;
  }

  const planTypes = ["free", "starter", "professional", "enterprise"];

  return (
    <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-4">
      {planTypes.map((planType) => {
        const features = PLAN_FEATURES[planType] ?? [];
        const price = PLAN_PRICES[planType];
        const isCurrent = currentPlan === planType;
        const isPopular = planType === "professional";
        const priceId = priceIds[planType];

        return (
          <Card
            key={planType}
            className={cn(
              "relative flex flex-col",
              isPopular && "border-primary shadow-lg",
              isCurrent && "bg-muted/50"
            )}
          >
            {isPopular && (
              <div className="absolute -top-3 left-1/2 -translate-x-1/2">
                <Badge className="bg-primary">
                  <Sparkles className="mr-1 h-3 w-3" />
                  Most Popular
                </Badge>
              </div>
            )}

            <CardHeader className="pb-4">
              <CardTitle className="flex items-center justify-between">
                <span className="capitalize">{planType}</span>
                {isCurrent && <Badge variant="outline">Current</Badge>}
              </CardTitle>
              <CardDescription>
                {price === -1 ? (
                  <span className="text-2xl font-bold">Custom</span>
                ) : (
                  <>
                    <span className="text-3xl font-bold">${price}</span>
                    <span className="text-muted-foreground">/month</span>
                  </>
                )}
              </CardDescription>
            </CardHeader>

            <CardContent className="flex-1">
              <ul className="space-y-2">
                {features.map((feature, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm">
                    <Check className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                    <span>{feature}</span>
                  </li>
                ))}
              </ul>
            </CardContent>

            <CardFooter>
              {planType === "enterprise" ? (
                <Button variant="outline" className="w-full" asChild>
                  <a href="mailto:sales@avengeai.com">Contact Sales</a>
                </Button>
              ) : isCurrent ? (
                <Button variant="outline" className="w-full" disabled>
                  Current Plan
                </Button>
              ) : (
                <Button
                  className="w-full"
                  variant={isPopular ? "default" : "outline"}
                  onClick={() => priceId && onSelectPlan(planType, priceId)}
                  disabled={isLoading || !priceId}
                >
                  {isLoading ? "Processing..." : planType === "free" ? "Downgrade" : "Upgrade"}
                </Button>
              )}
            </CardFooter>
          </Card>
        );
      })}
    </div>
  );
}

function PlanSelectorSkeleton() {
  return (
    <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-4">
      {[1, 2, 3, 4].map((i) => (
        <Card key={i} className="flex flex-col">
          <CardHeader className="pb-4">
            <Skeleton className="h-6 w-24" />
            <Skeleton className="h-8 w-32" />
          </CardHeader>
          <CardContent className="flex-1">
            <div className="space-y-2">
              {[1, 2, 3, 4].map((j) => (
                <div key={j} className="flex items-center gap-2">
                  <Skeleton className="h-4 w-4" />
                  <Skeleton className="h-4 w-32" />
                </div>
              ))}
            </div>
          </CardContent>
          <CardFooter>
            <Skeleton className="h-10 w-full" />
          </CardFooter>
        </Card>
      ))}
    </div>
  );
}
