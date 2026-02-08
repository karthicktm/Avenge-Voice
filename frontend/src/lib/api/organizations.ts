import { api } from "@/lib/api";

export interface PlanInfo {
  plan_type: string;
  max_users: number;
  max_agents: number;
  max_workspaces: number;
  max_call_minutes_per_month: number;
  max_storage_gb: number;
  features_enabled: string[];
}

export interface OrganizationResponse {
  id: string;
  name: string;
  slug: string;
  plan_type: string;
  subscription_status: string;
  trial_ends_at: string | null;
  max_users: number;
  max_agents: number;
  max_workspaces: number;
  max_call_minutes_per_month: number;
  max_storage_gb: number;
  current_users_count: number;
  current_agents_count: number;
  current_workspaces_count: number;
  current_month_call_minutes: number;
  current_month_storage_gb: number;
  features_enabled: string[];
}

export interface ChangePlanResponse {
  message: string;
  new_plan: string;
  limits: PlanInfo;
}

export async function fetchCurrentOrganization(): Promise<OrganizationResponse> {
  const response = await api.get("/api/v1/organizations/me");
  return response.data;
}

export async function fetchAvailablePlans(): Promise<PlanInfo[]> {
  const response = await api.get("/api/v1/organizations/plans");
  return response.data;
}

export async function changePlan(planType: string): Promise<ChangePlanResponse> {
  const response = await api.post("/api/v1/organizations/change-plan", {
    plan_type: planType,
  });
  return response.data;
}

// Plan display info
export const PLAN_DISPLAY_INFO: Record<
  string,
  { name: string; description: string; price: string; popular?: boolean }
> = {
  free: {
    name: "Free",
    description: "Get started with basic voice agents",
    price: "$0",
  },
  starter: {
    name: "Starter",
    description: "Perfect for small teams and growing businesses",
    price: "$29/mo",
  },
  professional: {
    name: "Professional",
    description: "Advanced features for scaling your voice operations",
    price: "$99/mo",
    popular: true,
  },
  enterprise: {
    name: "Enterprise",
    description: "Full suite of features with dedicated support",
    price: "Custom",
  },
};
