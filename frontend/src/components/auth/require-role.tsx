"use client";

import { type ReactNode } from "react";
import { useAuth } from "@/hooks/use-auth";

interface RequireRoleProps {
  role: "super_admin" | "admin" | "owner" | "user";
  children: ReactNode;
  fallback?: ReactNode;
}

/**
 * Component that only renders children if user has the specified role or higher.
 *
 * Role hierarchy: super_admin > admin > user
 *
 * @example
 * <RequireRole role="admin">
 *   <AdminPanel />
 * </RequireRole>
 */
export function RequireRole({ role, children, fallback = null }: RequireRoleProps) {
  const { user } = useAuth();

  if (!user) {
    return <>{fallback}</>;
  }

  // Role hierarchy check
  const roleHierarchy = {
    super_admin: 4,
    admin: 3,
    owner: 2,
    user: 1,
  };

  const userLevel = roleHierarchy[user.role];
  const requiredLevel = roleHierarchy[role];

  if (userLevel >= requiredLevel) {
    return <>{children}</>;
  }

  return <>{fallback}</>;
}

interface RequireSuperAdminProps {
  children: ReactNode;
  fallback?: ReactNode;
}

/**
 * Component that only renders children if user is a super admin.
 *
 * @example
 * <RequireSuperAdmin>
 *   <SuperAdminDashboard />
 * </RequireSuperAdmin>
 */
export function RequireSuperAdmin({ children, fallback = null }: RequireSuperAdminProps) {
  const { isSuperAdmin } = useAuth();

  if (isSuperAdmin) {
    return <>{children}</>;
  }

  return <>{fallback}</>;
}

interface RequireAdminProps {
  children: ReactNode;
  fallback?: ReactNode;
}

/**
 * Component that only renders children if user is an admin or super admin.
 *
 * @example
 * <RequireAdmin>
 *   <BillingSettings />
 * </RequireAdmin>
 */
export function RequireAdmin({ children, fallback = null }: RequireAdminProps) {
  const { isAdmin } = useAuth();

  if (isAdmin) {
    return <>{children}</>;
  }

  return <>{fallback}</>;
}
