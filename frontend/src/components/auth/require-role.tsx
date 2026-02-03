"use client";

import { type ReactNode } from "react";
import { useAuth } from "@/hooks/use-auth";

interface RequireRoleProps {
    role: "super_admin" | "organization_owner" | "user";
    children: ReactNode;
    fallback?: ReactNode;
}

/**
 * Component that only renders children if user has the specified role or higher.
 * 
 * Role hierarchy: super_admin > organization_owner > user
 * 
 * @example
 * <RequireRole role="organization_owner">
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
        super_admin: 3,
        organization_owner: 2,
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

interface RequireOrganizationOwnerProps {
    children: ReactNode;
    fallback?: ReactNode;
}

/**
 * Component that only renders children if user is an organization owner or super admin.
 * 
 * @example
 * <RequireOrganizationOwner>
 *   <BillingSettings />
 * </RequireOrganizationOwner>
 */
export function RequireOrganizationOwner({ children, fallback = null }: RequireOrganizationOwnerProps) {
    const { isSuperAdmin, isOrganizationOwner } = useAuth();

    if (isSuperAdmin || isOrganizationOwner) {
        return <>{children}</>;
    }

    return <>{fallback}</>;
}
