"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { useRouter, usePathname } from "next/navigation";

interface User {
  id: number;
  email: string;
  full_name: string | null;
  username?: string; // Legacy field
  role: "super_admin" | "admin" | "user";
  organization_id: string | null;
  email_verified: boolean;
  is_active: boolean;
  created_at: string;
}

interface AuthContextType {
  user: User | null;
  token: string | null;
  isLoading: boolean;
  isSuperAdmin: boolean;
  isAdmin: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, username: string, password: string, plan?: string) => Promise<void>;
  logout: () => void;
  logoutAllDevices: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const router = useRouter();
  const pathname = usePathname();

  // Check for existing token on mount
  useEffect(() => {
    const storedToken = localStorage.getItem("access_token");
    if (storedToken) {
      setToken(storedToken);
      // Validate token by fetching user info
      void fetchUser(storedToken);
    } else {
      setIsLoading(false);
    }
  }, []);

  // Redirect logic
  useEffect(() => {
    if (isLoading) return;

    const isAuthPage = pathname === "/login" || pathname === "/register";
    const isPublicPage = pathname === "/" || pathname.startsWith("/embed"); // Landing page and embed pages are public

    if (!token && !isAuthPage && !isPublicPage) {
      router.push("/login");
    } else if (token && isAuthPage) {
      router.push("/dashboard");
    }
  }, [token, isLoading, pathname, router]);

  const fetchUser = async (accessToken: string) => {
    try {
      const response = await fetch(`${API_BASE}/api/v1/auth/me`, {
        headers: {
          Authorization: `Bearer ${accessToken}`,
        },
      });

      if (response.ok) {
        const userData = await response.json();
        setUser(userData);
      } else {
        // Token invalid, clear it
        localStorage.removeItem("access_token");
        setToken(null);
      }
    } catch {
      localStorage.removeItem("access_token");
      setToken(null);
    } finally {
      setIsLoading(false);
    }
  };

  const login = async (email: string, password: string) => {
    const formData = new URLSearchParams();
    formData.append("username", email);
    formData.append("password", password);

    const response = await fetch(`${API_BASE}/api/v1/auth/login`, {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
      },
      body: formData,
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: "Login failed" }));
      throw new Error(error.detail ?? "Login failed");
    }

    const data = await response.json();
    localStorage.setItem("access_token", data.access_token);
    setToken(data.access_token);
    await fetchUser(data.access_token);
    router.push("/dashboard");
  };

  const register = async (email: string, username: string, password: string, plan?: string) => {
    const response = await fetch(`${API_BASE}/api/v1/auth/register`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ email, username, password, plan_type: plan ?? "free" }),
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: "Registration failed" }));
      throw new Error(error.detail ?? "Registration failed");
    }

    // Don't auto-login - user needs to verify email first
    // The register page will show the verification dialog
  };

  const logout = () => {
    localStorage.removeItem("access_token");
    setToken(null);
    setUser(null);
    router.push("/login");
  };

  const logoutAllDevices = async () => {
    try {
      // Revoke all sessions on the server
      await fetch(`${API_BASE}/api/v1/auth/logout-all`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });
    } catch {
      // Even if server call fails, proceed with local logout
    }
    localStorage.removeItem("access_token");
    setToken(null);
    setUser(null);
    router.push("/login");
  };

  // Computed properties for role checking
  const isSuperAdmin = user?.role === "super_admin";
  const isAdmin = user?.role === "admin" || user?.role === "super_admin";

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        isLoading,
        isSuperAdmin,
        isAdmin,
        login,
        register,
        logout,
        logoutAllDevices,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
