"use client";

import { useState } from "react";
import { CreditCard, BarChart3, FileText, Settings } from "lucide-react";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  SubscriptionCard,
  PaymentMethodCard,
  InvoiceList,
  PlanSelector,
} from "@/components/billing";
import { UsageDashboard } from "@/components/usage";
import { useSubscription, useCreateCheckout } from "@/hooks/use-billing";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

export default function BillingPage() {
  const { data: subscription } = useSubscription();
  const checkoutMutation = useCreateCheckout();
  const [showUpgradeDialog, setShowUpgradeDialog] = useState(false);

  // Price IDs should come from system settings in production
  // For now, these are placeholders
  const priceIds: Record<string, string> = {
    free: "",
    starter: process.env.NEXT_PUBLIC_STRIPE_PRICE_STARTER ?? "",
    professional: process.env.NEXT_PUBLIC_STRIPE_PRICE_PROFESSIONAL ?? "",
    enterprise: "",
  };

  const handleUpgrade = (planType: string, priceId: string) => {
    if (!priceId) {
      console.error("Price ID not configured for", planType);
      return;
    }

    checkoutMutation.mutate({
      price_id: priceId,
      success_url: `${window.location.origin}/dashboard/billing?success=true`,
      cancel_url: `${window.location.origin}/dashboard/billing?canceled=true`,
    });
  };

  return (
    <div className="container mx-auto max-w-7xl space-y-8 p-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Billing & Usage</h1>
        <p className="text-muted-foreground">
          Manage your subscription, payment methods, and monitor resource usage
        </p>
      </div>

      {/* Tabs */}
      <Tabs defaultValue="overview" className="space-y-6">
        <TabsList>
          <TabsTrigger value="overview" className="gap-2">
            <BarChart3 className="h-4 w-4" />
            Overview
          </TabsTrigger>
          <TabsTrigger value="subscription" className="gap-2">
            <CreditCard className="h-4 w-4" />
            Subscription
          </TabsTrigger>
          <TabsTrigger value="invoices" className="gap-2">
            <FileText className="h-4 w-4" />
            Invoices
          </TabsTrigger>
          <TabsTrigger value="plans" className="gap-2">
            <Settings className="h-4 w-4" />
            Plans
          </TabsTrigger>
        </TabsList>

        {/* Overview Tab */}
        <TabsContent value="overview" className="space-y-6">
          <UsageDashboard onUpgradeClick={() => setShowUpgradeDialog(true)} />
        </TabsContent>

        {/* Subscription Tab */}
        <TabsContent value="subscription" className="space-y-6">
          <div className="grid gap-6 lg:grid-cols-2">
            <SubscriptionCard onChangePlan={() => setShowUpgradeDialog(true)} />
            <PaymentMethodCard />
          </div>
        </TabsContent>

        {/* Invoices Tab */}
        <TabsContent value="invoices">
          <InvoiceList limit={20} />
        </TabsContent>

        {/* Plans Tab */}
        <TabsContent value="plans">
          <div className="space-y-6">
            <div>
              <h2 className="text-xl font-semibold">Choose Your Plan</h2>
              <p className="text-muted-foreground">
                Select the plan that best fits your needs. You can upgrade or downgrade anytime.
              </p>
            </div>
            <PlanSelector
              currentPlan={subscription?.plan_type}
              onSelectPlan={handleUpgrade}
              isLoading={checkoutMutation.isPending}
              priceIds={priceIds}
            />
          </div>
        </TabsContent>
      </Tabs>

      {/* Upgrade Dialog */}
      <Dialog open={showUpgradeDialog} onOpenChange={setShowUpgradeDialog}>
        <DialogContent className="max-w-5xl">
          <DialogHeader>
            <DialogTitle>Upgrade Your Plan</DialogTitle>
            <DialogDescription>
              Choose a plan to unlock more features and resources
            </DialogDescription>
          </DialogHeader>
          <PlanSelector
            currentPlan={subscription?.plan_type}
            onSelectPlan={(planType, priceId) => {
              handleUpgrade(planType, priceId);
              setShowUpgradeDialog(false);
            }}
            isLoading={checkoutMutation.isPending}
            priceIds={priceIds}
          />
        </DialogContent>
      </Dialog>
    </div>
  );
}
