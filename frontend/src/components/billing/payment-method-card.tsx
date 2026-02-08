"use client";

import { CreditCard, Building, Trash2, Star, AlertCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { usePaymentMethods, useDetachPaymentMethod } from "@/hooks/use-billing";
import type { PaymentMethod } from "@/lib/api/billing";

// Card brand icons (simplified - could use actual brand SVGs)
const CARD_BRAND_COLORS: Record<string, string> = {
  visa: "text-blue-600",
  mastercard: "text-orange-500",
  amex: "text-blue-500",
  discover: "text-orange-600",
  default: "text-muted-foreground",
};

interface PaymentMethodCardProps {
  onAddPaymentMethod?: () => void;
}

export function PaymentMethodCard({ onAddPaymentMethod }: PaymentMethodCardProps) {
  const { data: paymentMethods, isLoading, error } = usePaymentMethods();
  const detachMutation = useDetachPaymentMethod();

  if (isLoading) {
    return <PaymentMethodCardSkeleton />;
  }

  if (error) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center py-12">
          <AlertCircle className="mb-4 h-12 w-12 text-destructive" />
          <p className="text-center text-muted-foreground">Failed to load payment methods</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between">
          <div>
            <CardTitle>Payment Methods</CardTitle>
            <CardDescription>Manage your payment methods for billing</CardDescription>
          </div>
          {onAddPaymentMethod && (
            <Button size="sm" onClick={onAddPaymentMethod}>
              Add Payment Method
            </Button>
          )}
        </div>
      </CardHeader>

      <CardContent>
        {!paymentMethods || paymentMethods.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 text-center">
            <CreditCard className="mb-4 h-12 w-12 text-muted-foreground" />
            <p className="mb-2 font-medium">No payment methods</p>
            <p className="mb-4 text-sm text-muted-foreground">
              Add a payment method to manage your subscription
            </p>
            {onAddPaymentMethod && (
              <Button variant="outline" onClick={onAddPaymentMethod}>
                Add Payment Method
              </Button>
            )}
          </div>
        ) : (
          <div className="space-y-3">
            {paymentMethods.map((pm) => (
              <PaymentMethodItem
                key={pm.id}
                paymentMethod={pm}
                onDelete={() => {
                  if (confirm("Are you sure you want to remove this payment method?")) {
                    detachMutation.mutate(pm.id);
                  }
                }}
                isDeleting={detachMutation.isPending}
              />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

interface PaymentMethodItemProps {
  paymentMethod: PaymentMethod;
  onDelete: () => void;
  isDeleting: boolean;
}

function PaymentMethodItem({ paymentMethod, onDelete, isDeleting }: PaymentMethodItemProps) {
  const isCard = paymentMethod.type === "card";
  const brandColor =
    CARD_BRAND_COLORS[paymentMethod.card_brand?.toLowerCase() ?? "default"] ??
    CARD_BRAND_COLORS.default;

  return (
    <div className="flex items-center justify-between rounded-lg border p-4">
      <div className="flex items-center gap-3">
        <div
          className={`flex h-10 w-10 items-center justify-center rounded-lg bg-muted ${brandColor}`}
        >
          {isCard ? <CreditCard className="h-5 w-5" /> : <Building className="h-5 w-5" />}
        </div>
        <div>
          <div className="flex items-center gap-2">
            <p className="font-medium">
              {isCard ? (
                <>
                  {paymentMethod.card_brand?.charAt(0).toUpperCase()}
                  {paymentMethod.card_brand?.slice(1)} ending in {paymentMethod.card_last4}
                </>
              ) : (
                <>
                  {paymentMethod.bank_name} ending in {paymentMethod.bank_last4}
                </>
              )}
            </p>
            {paymentMethod.is_default && (
              <Badge variant="secondary" className="text-xs">
                <Star className="mr-1 h-3 w-3" />
                Default
              </Badge>
            )}
          </div>
          {isCard && paymentMethod.card_exp_month && paymentMethod.card_exp_year && (
            <p className="text-sm text-muted-foreground">
              Expires {paymentMethod.card_exp_month.toString().padStart(2, "0")}/
              {paymentMethod.card_exp_year}
            </p>
          )}
        </div>
      </div>

      <Button
        variant="ghost"
        size="icon"
        onClick={onDelete}
        disabled={isDeleting || paymentMethod.is_default}
        className="text-muted-foreground hover:text-destructive"
      >
        <Trash2 className="h-4 w-4" />
      </Button>
    </div>
  );
}

function PaymentMethodCardSkeleton() {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between">
          <div>
            <Skeleton className="h-6 w-40" />
            <Skeleton className="mt-1 h-4 w-60" />
          </div>
          <Skeleton className="h-9 w-36" />
        </div>
      </CardHeader>
      <CardContent>
        <div className="space-y-3">
          {[1, 2].map((i) => (
            <div key={i} className="flex items-center justify-between rounded-lg border p-4">
              <div className="flex items-center gap-3">
                <Skeleton className="h-10 w-10 rounded-lg" />
                <div>
                  <Skeleton className="mb-1 h-4 w-40" />
                  <Skeleton className="h-3 w-24" />
                </div>
              </div>
              <Skeleton className="h-8 w-8" />
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
