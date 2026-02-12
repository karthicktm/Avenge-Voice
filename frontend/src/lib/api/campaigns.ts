/**
 * API client for campaign management
 */

import { api } from "@/lib/api";

export interface Campaign {
  id: string;
  workspace_id: string;
  agent_id: string;
  agent_name: string | null;
  name: string;
  description: string | null;
  script: string | null;
  campaign_greeting: string | null;
  status: CampaignStatus;
  from_phone_number: string;
  scheduled_start: string | null;
  scheduled_end: string | null;
  // Scheduler fields
  calling_hours_start: string | null; // Time as HH:MM string
  calling_hours_end: string | null; // Time as HH:MM string
  calling_days: number[] | null; // 0=Mon, 6=Sun
  timezone: string | null;
  // Call settings
  calls_per_minute: number;
  max_concurrent_calls: number;
  max_attempts_per_contact: number;
  retry_delay_minutes: number;
  total_contacts: number;
  contacts_called: number;
  contacts_completed: number;
  contacts_failed: number;
  total_call_duration_seconds: number;
  // Error tracking
  last_error: string | null;
  error_count: number;
  last_error_at: string | null;
  // Timestamps
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

export type CampaignStatus =
  | "draft"
  | "scheduled"
  | "running"
  | "paused"
  | "completed"
  | "canceled";

export interface CampaignContact {
  id: string;
  contact_id: number;
  status: string;
  attempts: number;
  last_attempt_at: string | null;
  next_attempt_at: string | null;
  last_call_duration_seconds: number;
  last_call_outcome: string | null;
  priority: number;
  // Disposition fields
  disposition: string | null;
  disposition_notes: string | null;
  callback_requested_at: string | null;
  // Contact details
  contact_name: string | null;
  contact_phone: string | null;
}

export interface CampaignStats {
  total_contacts: number;
  contacts_pending: number;
  contacts_calling: number;
  contacts_completed: number;
  contacts_failed: number;
  contacts_no_answer: number;
  contacts_busy: number;
  contacts_skipped: number;
  total_calls_made: number;
  total_call_duration_seconds: number;
  average_call_duration_seconds: number;
  completion_rate: number;
}

export interface CreateCampaignRequest {
  workspace_id: string;
  agent_id: string;
  name: string;
  description?: string;
  script?: string;
  campaign_greeting?: string;
  from_phone_number: string;
  scheduled_start?: string;
  scheduled_end?: string;
  // Scheduler fields
  calling_hours_start?: string; // Time as HH:MM string
  calling_hours_end?: string; // Time as HH:MM string
  calling_days?: number[]; // 0=Mon, 6=Sun
  timezone?: string;
  // Call settings
  calls_per_minute?: number;
  max_concurrent_calls?: number;
  max_attempts_per_contact?: number;
  retry_delay_minutes?: number;
  contact_ids?: number[];
}

export interface UpdateCampaignRequest {
  name?: string;
  description?: string;
  script?: string;
  campaign_greeting?: string;
  from_phone_number?: string;
  scheduled_start?: string;
  scheduled_end?: string;
  // Scheduler fields
  calling_hours_start?: string;
  calling_hours_end?: string;
  calling_days?: number[];
  timezone?: string;
  // Call settings
  calls_per_minute?: number;
  max_concurrent_calls?: number;
  max_attempts_per_contact?: number;
  retry_delay_minutes?: number;
}

export interface DispositionStats {
  total: number;
  by_disposition: Record<string, number>;
  callbacks_pending: number;
}

export interface UpdateDispositionRequest {
  disposition: string;
  disposition_notes?: string;
  callback_requested_at?: string;
}

export interface DispositionOption {
  value: string;
  label: string;
}

export interface DispositionOptions {
  positive: DispositionOption[];
  neutral: DispositionOption[];
  negative: DispositionOption[];
  technical: DispositionOption[];
}

/**
 * List all campaigns
 */
export async function listCampaigns(params?: {
  workspace_id?: string;
  status?: CampaignStatus;
}): Promise<Campaign[]> {
  const searchParams = new URLSearchParams();
  if (params?.workspace_id) searchParams.set("workspace_id", params.workspace_id);
  if (params?.status) searchParams.set("status", params.status);

  const query = searchParams.toString();
  const response = await api.get(`/api/v1/campaigns${query ? `?${query}` : ""}`);
  return response.data;
}

/**
 * Get a specific campaign
 */
export async function getCampaign(campaignId: string): Promise<Campaign> {
  const response = await api.get(`/api/v1/campaigns/${campaignId}`);
  return response.data;
}

/**
 * Create a new campaign
 */
export async function createCampaign(data: CreateCampaignRequest): Promise<Campaign> {
  const response = await api.post("/api/v1/campaigns", data);
  return response.data;
}

/**
 * Update a campaign
 */
export async function updateCampaign(
  campaignId: string,
  data: UpdateCampaignRequest
): Promise<Campaign> {
  const response = await api.put(`/api/v1/campaigns/${campaignId}`, data);
  return response.data;
}

/**
 * Delete a campaign
 */
export async function deleteCampaign(campaignId: string): Promise<void> {
  await api.delete(`/api/v1/campaigns/${campaignId}`);
}

/**
 * Get campaign contacts
 */
export async function getCampaignContacts(
  campaignId: string,
  params?: { status?: string; limit?: number; offset?: number }
): Promise<CampaignContact[]> {
  const searchParams = new URLSearchParams();
  if (params?.status) searchParams.set("status", params.status);
  if (params?.limit) searchParams.set("limit", params.limit.toString());
  if (params?.offset) searchParams.set("offset", params.offset.toString());

  const query = searchParams.toString();
  const response = await api.get(
    `/api/v1/campaigns/${campaignId}/contacts${query ? `?${query}` : ""}`
  );
  return response.data;
}

/**
 * Add contacts to a campaign
 */
export async function addContactsToCampaign(
  campaignId: string,
  contactIds: number[]
): Promise<{ added: number }> {
  const response = await api.post(`/api/v1/campaigns/${campaignId}/contacts`, {
    contact_ids: contactIds,
  });
  return response.data;
}

/**
 * Remove a contact from a campaign
 */
export async function removeContactFromCampaign(
  campaignId: string,
  contactId: number
): Promise<void> {
  await api.delete(`/api/v1/campaigns/${campaignId}/contacts/${contactId}`);
}

/**
 * Start a campaign
 */
export async function startCampaign(campaignId: string): Promise<Campaign> {
  const response = await api.post(`/api/v1/campaigns/${campaignId}/start`);
  return response.data;
}

/**
 * Pause a campaign
 */
export async function pauseCampaign(campaignId: string): Promise<Campaign> {
  const response = await api.post(`/api/v1/campaigns/${campaignId}/pause`);
  return response.data;
}

/**
 * Stop a campaign
 */
export async function stopCampaign(campaignId: string): Promise<Campaign> {
  const response = await api.post(`/api/v1/campaigns/${campaignId}/stop`);
  return response.data;
}

/**
 * Restart a completed or canceled campaign
 */
export async function restartCampaign(campaignId: string): Promise<Campaign> {
  const response = await api.post(`/api/v1/campaigns/${campaignId}/restart`);
  return response.data;
}

/**
 * Get campaign statistics
 */
export async function getCampaignStats(campaignId: string): Promise<CampaignStats> {
  const response = await api.get(`/api/v1/campaigns/${campaignId}/stats`);
  return response.data;
}

/**
 * Get disposition statistics for a campaign
 */
export async function getDispositionStats(campaignId: string): Promise<DispositionStats> {
  const response = await api.get(`/api/v1/campaigns/${campaignId}/dispositions`);
  return response.data;
}

/**
 * Update contact disposition
 */
export async function updateContactDisposition(
  campaignId: string,
  contactId: number,
  data: UpdateDispositionRequest
): Promise<CampaignContact> {
  const response = await api.put(
    `/api/v1/campaigns/${campaignId}/contacts/${contactId}/disposition`,
    data
  );
  return response.data;
}

/**
 * Get available disposition options
 */
export async function getDispositionOptions(): Promise<DispositionOptions> {
  const response = await api.get("/api/v1/campaigns/dispositions/options");
  return response.data;
}

// Contact Filter Types
export interface AddContactsByFilterRequest {
  status?: string[];
  tags?: string[];
  exclude_existing?: boolean;
}

export interface FilteredContactsResponse {
  total_matching: number;
  already_in_campaign: number;
  will_be_added: number;
}

export interface AddContactsByFilterResponse {
  added: number;
  total_matching: number;
}

/**
 * Preview contacts matching filter criteria before adding to campaign
 */
export async function previewContactsByFilter(
  campaignId: string,
  data: AddContactsByFilterRequest
): Promise<FilteredContactsResponse> {
  const response = await api.post(`/api/v1/campaigns/${campaignId}/contacts/filter/preview`, data);
  return response.data;
}

/**
 * Add contacts to campaign by filter criteria
 */
export async function addContactsByFilter(
  campaignId: string,
  data: AddContactsByFilterRequest
): Promise<AddContactsByFilterResponse> {
  const response = await api.post(`/api/v1/campaigns/${campaignId}/contacts/filter`, data);
  return response.data;
}
