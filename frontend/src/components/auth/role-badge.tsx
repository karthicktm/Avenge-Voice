"use client";

import { Badge } from "@/components/ui/badge";
import { Shield, Crown, User } from "lucide-react";

interface RoleBadgeProps {
    role: "super_admin" | "organization_owner" | "user";
    className?: string;
}

/**
 * Badge component to display user role with appropriate styling and icon.
 */
export function RoleBadge({ role, className }: RoleBadgeProps) {
    const roleConfig = {
        super_admin: {
            label: "Super Admin",
            icon: Crown,
            variant: "default" as const,
            className: "bg-purple-600 hover:bg-purple-700 text-white",
        },
        organization_owner: {
            label: "Owner",
            icon: Shield,
            variant: "default" as const,
            className: "bg-blue-600 hover:bg-blue-700 text-white",
        },
        user: {
            label: "Member",
            icon: User,
            variant: "secondary" as const,
            className: "",
        },
    };

    const config = roleConfig[role];
    const Icon = config.icon;

    return (
        <Badge variant={config.variant} className={`${config.className} ${className || ""}`}>
            <Icon className="mr-1 h-3 w-3" />
            {config.label}
        </Badge>
    );
}
