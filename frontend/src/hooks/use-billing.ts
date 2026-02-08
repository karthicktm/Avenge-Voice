"use client";

/**
 * React hooks for billing operations
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  billingApi,
  type Subscription,
  type PaymentMethod,
  type Invoice,
  type PlanInfo,
} from "@/lib/api/billing";

// =============================================================================
// Query Keys
// =============================================================================

export const billingKeys = {
  all: ["billing"] as const,
  subscription: () => [...billingKeys.all, "subscription"] as const,
  paymentMethods: () => [...billingKeys.all, "payment-methods"] as const,
  invoices: () => [...billingKeys.all, "invoices"] as const,
  upcomingInvoice: () => [...billingKeys.all, "upcoming-invoice"] as const,
  plans: () => [...billingKeys.all, "plans"] as const,
};

// =============================================================================
// Hooks
// =============================================================================

export function useSubscription() {
  return useQuery<Subscription>({
    queryKey: billingKeys.subscription(),
    queryFn: billingApi.getSubscription,
  });
}

export function usePaymentMethods() {
  return useQuery<PaymentMethod[]>({
    queryKey: billingKeys.paymentMethods(),
    queryFn: billingApi.listPaymentMethods,
  });
}

export function useInvoices(limit = 20, offset = 0) {
  return useQuery<Invoice[]>({
    queryKey: [...billingKeys.invoices(), limit, offset],
    queryFn: () => billingApi.listInvoices(limit, offset),
  });
}

export function useUpcomingInvoice() {
  return useQuery({
    queryKey: billingKeys.upcomingInvoice(),
    queryFn: billingApi.getUpcomingInvoice,
  });
}

export function usePlans() {
  return useQuery<PlanInfo[]>({
    queryKey: billingKeys.plans(),
    queryFn: billingApi.listPlans,
    staleTime: 1000 * 60 * 60, // Plans rarely change, cache for 1 hour
  });
}

// =============================================================================
// Mutations
// =============================================================================

export function useCreateCheckout() {
  return useMutation({
    mutationFn: billingApi.createCheckout,
    onSuccess: (data) => {
      // Redirect to Stripe Checkout
      window.location.href = data.checkout_url;
    },
  });
}

export function useCancelSubscription() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (cancelImmediately?: boolean) => billingApi.cancelSubscription(cancelImmediately),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: billingKeys.subscription() });
    },
  });
}

export function useReactivateSubscription() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: billingApi.reactivateSubscription,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: billingKeys.subscription() });
    },
  });
}

export function useChangePlan() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (newPriceId: string) => billingApi.changePlan(newPriceId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: billingKeys.subscription() });
      void queryClient.invalidateQueries({ queryKey: billingKeys.upcomingInvoice() });
    },
  });
}

export function useAttachPaymentMethod() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      paymentMethodId,
      setAsDefault = true,
    }: {
      paymentMethodId: string;
      setAsDefault?: boolean;
    }) => billingApi.attachPaymentMethod(paymentMethodId, setAsDefault),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: billingKeys.paymentMethods() });
    },
  });
}

export function useDetachPaymentMethod() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: billingApi.detachPaymentMethod,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: billingKeys.paymentMethods() });
    },
  });
}

export function useCreatePortalSession() {
  return useMutation({
    mutationFn: (returnUrl?: string) => billingApi.createPortalSession(returnUrl),
    onSuccess: (data) => {
      // Redirect to Stripe billing portal
      window.location.href = data.portal_url;
    },
  });
}
