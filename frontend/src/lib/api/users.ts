/**
 * API client for user management (admin only)
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

function getAuthHeaders(): HeadersInit {
  if (typeof window === "undefined") return {};
  const token = localStorage.getItem("access_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/**
 * Fetch with timeout to prevent hanging requests
 */
async function fetchWithTimeout(
  url: string,
  options: RequestInit = {},
  timeoutMs = 10000
): Promise<Response> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  const headers = {
    ...getAuthHeaders(),
    ...(options.headers ?? {}),
  };

  try {
    const response = await fetch(url, {
      ...options,
      headers,
      signal: controller.signal,
    });
    return response;
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      throw new Error("Request timed out - please check if the backend is running");
    }
    throw error;
  } finally {
    clearTimeout(timeoutId);
  }
}

// =============================================================================
// Types
// =============================================================================

export type UserRole = "super_admin" | "admin" | "user";

export interface UserResponse {
  id: number;
  email: string;
  full_name: string | null;
  role: UserRole;
  is_active: boolean;
  email_verified: boolean;
  created_at: string;
  updated_at: string;
  organization_id: string | null;
  last_login_at: string | null;
}

export interface UserListResponse {
  users: UserResponse[];
  total: number;
  page: number;
  per_page: number;
}

export interface CreateUserRequest {
  email: string;
  password: string;
  full_name?: string;
  role?: UserRole;
}

export interface UpdateUserRequest {
  email?: string;
  full_name?: string;
  is_active?: boolean;
}

export interface ChangeRoleRequest {
  new_role: UserRole;
}

// =============================================================================
// API Functions
// =============================================================================

export async function fetchUsers(
  page = 1,
  perPage = 20,
  includeInactive = false
): Promise<UserListResponse> {
  const params = new URLSearchParams({
    page: page.toString(),
    per_page: perPage.toString(),
    include_inactive: includeInactive.toString(),
  });

  const response = await fetchWithTimeout(`${API_BASE}/api/v1/users?${params}`);

  if (!response.ok) {
    if (response.status === 403) {
      throw new Error("Access denied. Only admins can view users.");
    }
    throw new Error(`Failed to fetch users: ${response.statusText}`);
  }

  return response.json();
}

export async function fetchUser(userId: number): Promise<UserResponse> {
  const response = await fetchWithTimeout(`${API_BASE}/api/v1/users/${userId}`);

  if (!response.ok) {
    if (response.status === 403) {
      throw new Error("Access denied. Only admins can view user details.");
    }
    if (response.status === 404) {
      throw new Error("User not found");
    }
    throw new Error(`Failed to fetch user: ${response.statusText}`);
  }

  return response.json();
}

export async function createUser(request: CreateUserRequest): Promise<UserResponse> {
  const response = await fetchWithTimeout(`${API_BASE}/api/v1/users`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    if (response.status === 403) {
      throw new Error("Access denied. Only admins can create users.");
    }
    if (response.status === 409) {
      throw new Error("A user with this email already exists.");
    }
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail ?? "Failed to create user");
  }

  return response.json();
}

export async function updateUser(
  userId: number,
  request: UpdateUserRequest
): Promise<UserResponse> {
  const response = await fetchWithTimeout(`${API_BASE}/api/v1/users/${userId}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    if (response.status === 403) {
      throw new Error("Access denied. Only admins can update users.");
    }
    if (response.status === 404) {
      throw new Error("User not found");
    }
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail ?? "Failed to update user");
  }

  return response.json();
}

export async function deleteUser(userId: number): Promise<void> {
  let response: Response;

  try {
    response = await fetchWithTimeout(`${API_BASE}/api/v1/users/${userId}`, {
      method: "DELETE",
    });
  } catch (error) {
    // Network error or timeout
    if (error instanceof Error) {
      throw new Error(error.message);
    }
    throw new Error("Network error. Please check your connection and try again.");
  }

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: null }));
    const errorMessage = errorData.detail;

    if (response.status === 400) {
      throw new Error(errorMessage ?? "Cannot delete this user.");
    }
    if (response.status === 403) {
      throw new Error(errorMessage ?? "Access denied. Only admins can delete users.");
    }
    if (response.status === 404) {
      throw new Error("User not found.");
    }
    if (response.status === 500) {
      throw new Error(errorMessage ?? "Server error. Please try again later.");
    }
    throw new Error(errorMessage ?? `Failed to delete user (${response.status})`);
  }
}

export async function changeUserRole(
  userId: number,
  request: ChangeRoleRequest
): Promise<UserResponse> {
  const response = await fetchWithTimeout(`${API_BASE}/api/v1/users/${userId}/change-role`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    if (response.status === 403) {
      throw new Error("Access denied. Insufficient permissions to change this user's role.");
    }
    if (response.status === 404) {
      throw new Error("User not found");
    }
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail ?? "Failed to change user role");
  }

  return response.json();
}
