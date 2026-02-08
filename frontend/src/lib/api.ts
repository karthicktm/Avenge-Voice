import axios from "axios";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const api = axios.create({
  baseURL: API_URL,
  headers: {
    "Content-Type": "application/json",
  },
  withCredentials: true,
});

// Safely get/set localStorage with error handling
function safeGetItem(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch (error) {
    console.warn(`Failed to access localStorage for key "${key}":`, error);
    return null;
  }
}

function safeRemoveItem(key: string): void {
  try {
    localStorage.removeItem(key);
  } catch (error) {
    console.warn(`Failed to remove localStorage key "${key}":`, error);
  }
}

// Logout function - clears auth token and redirects to login
export function logout(): void {
  safeRemoveItem("access_token");
  try {
    window.location.href = "/login";
  } catch (navError) {
    console.error("Failed to redirect to login:", navError);
  }
}

// Request interceptor for adding auth token
api.interceptors.request.use(
  (config) => {
    const token = safeGetItem("access_token");
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Response interceptor for handling errors
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    // Log authentication failures
    if (error.response?.status === 401) {
      console.error("Authentication failed - redirecting to login", {
        endpoint: error.config?.url,
        status: error.response.status,
      });
      safeRemoveItem("access_token");
      // Safely navigate to login
      try {
        window.location.href = "/login";
      } catch (navError) {
        console.error("Failed to redirect to login:", navError);
      }
    } else if (error.response) {
      // Log API errors with details
      console.error("API error:", {
        endpoint: error.config?.url,
        method: error.config?.method?.toUpperCase(),
        status: error.response.status,
        message: error.response.data?.message ?? error.message,
      });
    } else if (error.request) {
      // Log network errors
      console.error("Network error - no response received:", {
        endpoint: error.config?.url,
        method: error.config?.method?.toUpperCase(),
      });
    } else {
      // Log request setup errors
      console.error("Request error:", error.message);
    }
    return Promise.reject(error);
  }
);

// Integration types
export interface IntegrationResponse {
  id: string;
  integration_id: string;
  integration_name: string;
  workspace_id: string | null;
  is_active: boolean;
  is_connected: boolean;
  connected_at: string | null;
  last_used_at: string | null;
  has_credentials: boolean;
  credential_fields: string[];
}

export interface IntegrationListResponse {
  integrations: IntegrationResponse[];
  total: number;
}

export interface ConnectIntegrationRequest {
  integration_id: string;
  integration_name: string;
  workspace_id?: string | null;
  credentials: Record<string, string>;
  metadata?: Record<string, unknown>;
}

export interface UpdateIntegrationRequest {
  credentials?: Record<string, string>;
  metadata?: Record<string, unknown>;
  is_active?: boolean;
}

// Integration API functions
export const integrationsApi = {
  // List all connected integrations for the user (optionally filtered by workspace)
  list: async (workspaceId?: string): Promise<IntegrationListResponse> => {
    const params = workspaceId ? { workspace_id: workspaceId } : {};
    const response = await api.get<IntegrationListResponse>("/api/v1/integrations", { params });
    return response.data;
  },

  // Get a specific integration's connection status
  get: async (integrationId: string, workspaceId?: string): Promise<IntegrationResponse> => {
    const params = workspaceId ? { workspace_id: workspaceId } : {};
    const response = await api.get<IntegrationResponse>(`/api/v1/integrations/${integrationId}`, {
      params,
    });
    return response.data;
  },

  // Connect a new integration
  connect: async (request: ConnectIntegrationRequest): Promise<IntegrationResponse> => {
    const response = await api.post<IntegrationResponse>("/api/v1/integrations", request);
    return response.data;
  },

  // Update an integration's credentials or settings
  update: async (
    integrationId: string,
    request: UpdateIntegrationRequest,
    workspaceId?: string
  ): Promise<IntegrationResponse> => {
    const params = workspaceId ? { workspace_id: workspaceId } : {};
    const response = await api.put<IntegrationResponse>(
      `/api/v1/integrations/${integrationId}`,
      request,
      { params }
    );
    return response.data;
  },

  // Disconnect an integration
  disconnect: async (integrationId: string, workspaceId?: string): Promise<void> => {
    const params = workspaceId ? { workspace_id: workspaceId } : {};
    await api.delete(`/api/v1/integrations/${integrationId}`, { params });
  },
};

// Email Verification API functions
export interface SendVerificationCodeRequest {
  email: string;
}

export interface VerifyEmailCodeRequest {
  email: string;
  code: string;
}

export interface VerificationCodeResponse {
  message: string;
  expires_in_minutes: number;
}

export interface TokenResponse {
  access_token: string;
}

export const emailVerificationApi = {
  // Send verification code to email
  sendCode: async (email: string): Promise<VerificationCodeResponse> => {
    const response = await api.post<VerificationCodeResponse>(
      "/api/v1/auth/send-verification-code",
      {
        email,
      }
    );
    return response.data;
  },

  // Verify email with code
  verifyCode: async (email: string, code: string): Promise<TokenResponse> => {
    const response = await api.post<TokenResponse>("/api/v1/auth/verify-email-code", {
      email,
      code,
    });
    return response.data;
  },
};

export default api;
