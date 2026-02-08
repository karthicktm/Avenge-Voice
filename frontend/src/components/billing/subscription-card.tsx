"use client";

import { Calendar, CreditCard, CheckCircle, XCircle, Clock, AlertCircle } from "lucide-react";

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
import {
  useSubscription,
  useCancelSubscription,
  useReactivateSubscription,
  useCreatePortalSession,
} from "@/hooks/use-billing";
import { getPlanDisplayName, getStatusColor } from "@/lib/api/billing";

interface SubscriptionCardProps {
  onChangePlan?: () => void;
}

export function SubscriptionCard({ onChangePlan }: SubscriptionCardProps) {
  const { data: subscription, isLoading, error } = useSubscription();
  const cancelMutation = useCancelSubscription();
  const reactivateMutation = useReactivateSubscription();
  const portalMutation = useCreatePortalSession();

  if (isLoading) {
    return <SubscriptionCardSkeleton />;
  }

  if (error || !subscription) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center py-12">
          <AlertCircle className="mb-4 h-12 w-12 text-destructive" />
          <p className="text-center text-muted-foreground">Failed to load subscription</p>
        </CardContent>
      </Card>
    );
  }

  const statusColor = getStatusColor(subscription.status);
  const planName = getPlanDisplayName(subscription.plan_type);
  const isCancelling = subscription.cancel_at_period_end;
  const isActive = subscription.status === "active" || subscription.status === "trialing";

  const StatusIcon =
    {
      active: CheckCircle,
      trialing: Clock,
      past_due: AlertCircle,
      cancelled: XCircle,
      trial: Clock,
    }[subscription.status] ?? CheckCircle;

  const badgeVariant = {
    green: "default",
    blue: "secondary",
    yellow: "outline",
    red: "destructive",
  }[statusColor] as "default" | "secondary" | "outline" | "destructive";

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between">
          <div>
            <CardTitle className="flex items-center gap-2">
              {planName} Plan
              <Badge variant={badgeVariant} className="ml-2">
                <StatusIcon className="mr-1 h-3 w-3" />
                {subscription.status.replace("_", " ").charAt(0).toUpperCase() +
                  subscription.status.slice(1).replace("_", " ")}
              </Badge>
            </CardTitle>
            <CardDescription>
              {isCancelling
                ? "Your subscription will end at the end of the billing period"
                : isActive
                  ? "Your subscription is active"
                  : "Manage your subscription"}
            </CardDescription>
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Billing dates */}
        <div className="grid gap-4 sm:grid-cols-2">
          {subscription.subscription_started_at && (
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-muted">
                <Calendar className="h-5 w-5 text-muted-foreground" />
              </div>
              <div>
                <p className="text-sm font-medium">Started</p>
                <p className="text-sm text-muted-foreground">
                  {new Date(subscription.subscription_started_at).toLocaleDateString()}
                </p>
              </div>
            </div>
          )}

          {subscription.next_billing_date && !isCancelling && (
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-muted">
                <CreditCard className="h-5 w-5 text-muted-foreground" />
              </div>
              <div>
                <p className="text-sm font-medium">Next billing</p>
                <p className="text-sm text-muted-foreground">
                  {new Date(subscription.next_billing_date).toLocaleDateString()}
                </p>
              </div>
            </div>
          )}

          {subscription.subscription_ends_at && (
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-destructive/10">
                <XCircle className="h-5 w-5 text-destructive" />
              </div>
              <div>
                <p className="text-sm font-medium">Ends on</p>
                <p className="text-sm text-muted-foreground">
                  {new Date(subscription.subscription_ends_at).toLocaleDateString()}
                </p>
              </div>
            </div>
          )}
        </div>

        {/* Cancellation warning */}
        {isCancelling && (
          <div className="rounded-lg border border-yellow-500/50 bg-yellow-500/10 p-4">
            <p className="text-sm text-yellow-900 dark:text-yellow-100">
              Your subscription is set to cancel on{" "}
              {subscription.subscription_ends_at
                ? new Date(subscription.subscription_ends_at).toLocaleDateString()
                : "the end of the billing period"}
              . You can reactivate anytime before then.
            </p>
          </div>
        )}
      </CardContent>

      <CardFooter className="flex flex-wrap gap-2">
        {onChangePlan && isActive && !isCancelling && (
          <Button variant="outline" onClick={onChangePlan}>
            Change Plan
          </Button>
        )}

        {subscription.stripe_customer_id && (
          <Button
            variant="outline"
            onClick={() => portalMutation.mutate(window.location.href)}
            disabled={portalMutation.isPending}
          >
            {portalMutation.isPending ? "Loading..." : "Manage in Stripe"}
          </Button>
        )}

        {isActive && !isCancelling && subscription.stripe_subscription_id && (
          <Button
            variant="ghost"
            className="text-destructive hover:text-destructive"
            onClick={() => {
              if (confirm("Are you sure you want to cancel your subscription?")) {
                cancelMutation.mutate(false);
              }
            }}
            disabled={cancelMutation.isPending}
          >
            {cancelMutation.isPending ? "Cancelling..." : "Cancel Subscription"}
          </Button>
        )}

        {isCancelling && (
          <Button
            onClick={() => reactivateMutation.mutate()}
            disabled={reactivateMutation.isPending}
          >
            {reactivateMutation.isPending ? "Reactivating..." : "Reactivate Subscription"}
          </Button>
        )}
      </CardFooter>
    </Card>
  );
}

function SubscriptionCardSkeleton() {
  return (
    <Card>
      <CardHeader>
        <Skeleton className="h-6 w-40" />
        <Skeleton className="h-4 w-60" />
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="flex items-center gap-3">
            <Skeleton className="h-10 w-10 rounded-lg" />
            <div>
              <Skeleton className="mb-1 h-4 w-16" />
              <Skeleton className="h-4 w-24" />
            </div>
          </div>
          <div className="flex items-center gap-3">
            <Skeleton className="h-10 w-10 rounded-lg" />
            <div>
              <Skeleton className="mb-1 h-4 w-16" />
              <Skeleton className="h-4 w-24" />
            </div>
          </div>
        </div>
      </CardContent>
      <CardFooter className="gap-2">
        <Skeleton className="h-9 w-24" />
        <Skeleton className="h-9 w-32" />
      </CardFooter>
    </Card>
  );
}
