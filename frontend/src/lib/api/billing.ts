/**
 * Billing API client for subscription and payment management
 */

import { api } from "../api";

// =============================================================================
// Types
// =============================================================================

export interface Subscription {
  plan_type: string;
  status: string;
  stripe_customer_id: string | null;
  stripe_subscription_id: string | null;
  stripe_price_id: string | null;
  subscription_started_at: string | null;
  subscription_ends_at: string | null;
  next_billing_date: string | null;
  cancel_at_period_end: boolean;
}

export interface CheckoutRequest {
  price_id: string;
  success_url: string;
  cancel_url: string;
}

export interface CheckoutResponse {
  checkout_url: string;
}

export interface PaymentMethod {
  id: string;
  type: string;
  is_default: boolean;
  card_brand: string | null;
  card_last4: string | null;
  card_exp_month: number | null;
  card_exp_year: number | null;
  bank_name: string | null;
  bank_last4: string | null;
}

export interface Invoice {
  id: string;
  stripe_invoice_id: string;
  status: string;
  currency: string;
  amount_due: number;
  amount_paid: number;
  total: number;
  invoice_pdf_url: string | null;
  hosted_invoice_url: string | null;
  period_start: string | null;
  period_end: string | null;
  created_at: string;
}

export interface UpcomingInvoice {
  amount_due: number;
  currency: string;
  period_start: string | null;
  period_end: string | null;
  next_payment_attempt: string | null;
  lines: {
    description: string;
    amount: number;
    quantity: number;
  }[];
}

export interface PlanInfo {
  plan_type: string;
  name: string;
  limits: Record<string, number>;
}

export interface PortalSession {
  portal_url: string;
}

// =============================================================================
// API Functions
// =============================================================================

export const billingApi = {
  // Subscription
  getSubscription: async (): Promise<Subscription> => {
    const response = await api.get<Subscription>("/api/v1/billing/subscription");
    return response.data;
  },

  createCheckout: async (request: CheckoutRequest): Promise<CheckoutResponse> => {
    const response = await api.post<CheckoutResponse>("/api/v1/billing/checkout", request);
    return response.data;
  },

  cancelSubscription: async (cancelImmediately = false): Promise<{ message: string }> => {
    const response = await api.post<{ message: string }>(
      `/api/v1/billing/subscription/cancel?cancel_immediately=${cancelImmediately}`
    );
    return response.data;
  },

  reactivateSubscription: async (): Promise<{ message: string }> => {
    const response = await api.post<{ message: string }>("/api/v1/billing/subscription/reactivate");
    return response.data;
  },

  changePlan: async (newPriceId: string): Promise<{ message: string }> => {
    const response = await api.post<{ message: string }>(
      "/api/v1/billing/subscription/change-plan",
      {
        new_price_id: newPriceId,
      }
    );
    return response.data;
  },

  // Payment Methods
  listPaymentMethods: async (): Promise<PaymentMethod[]> => {
    const response = await api.get<PaymentMethod[]>("/api/v1/billing/payment-methods");
    return response.data;
  },

  attachPaymentMethod: async (
    paymentMethodId: string,
    setAsDefault = true
  ): Promise<PaymentMethod> => {
    const response = await api.post<PaymentMethod>("/api/v1/billing/payment-methods/attach", {
      payment_method_id: paymentMethodId,
      set_as_default: setAsDefault,
    });
    return response.data;
  },

  detachPaymentMethod: async (paymentMethodId: string): Promise<void> => {
    await api.delete(`/api/v1/billing/payment-methods/${paymentMethodId}`);
  },

  // Invoices
  listInvoices: async (limit = 20, offset = 0): Promise<Invoice[]> => {
    const response = await api.get<Invoice[]>("/api/v1/billing/invoices", {
      params: { limit, offset },
    });
    return response.data;
  },

  getUpcomingInvoice: async (): Promise<UpcomingInvoice> => {
    const response = await api.get<UpcomingInvoice>("/api/v1/billing/invoices/upcoming");
    return response.data;
  },

  // Portal
  createPortalSession: async (returnUrl?: string): Promise<PortalSession> => {
    const response = await api.post<PortalSession>("/api/v1/billing/portal-session", null, {
      params: returnUrl ? { return_url: returnUrl } : undefined,
    });
    return response.data;
  },

  // Plans
  listPlans: async (): Promise<PlanInfo[]> => {
    const response = await api.get<PlanInfo[]>("/api/v1/billing/plans");
    return response.data;
  },
};

// =============================================================================
// Utility Functions
// =============================================================================

export function formatCurrency(cents: number, currency = "usd"): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: currency.toUpperCase(),
  }).format(cents / 100);
}

export function getStatusColor(status: string): string {
  switch (status) {
    case "active":
      return "green";
    case "trialing":
    case "trial":
      return "blue";
    case "past_due":
      return "yellow";
    case "cancelled":
    case "canceled":
      return "red";
    default:
      return "gray";
  }
}

export function getPlanDisplayName(planType: string): string {
  const names: Record<string, string> = {
    free: "Free",
    starter: "Starter",
    professional: "Professional",
    enterprise: "Enterprise",
  };
  return names[planType] ?? planType.charAt(0).toUpperCase() + planType.slice(1);
}
