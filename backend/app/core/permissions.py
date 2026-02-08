"""Permission system for role-based access control.

This module defines the permission matrix for the 3-tier role system:
- SUPER_ADMIN: Platform-level administrator (all permissions)
- ADMIN: Organization administrator
- USER: Regular user

Permissions are granular and can be checked individually or in combination.
"""

from enum import Enum

from app.models.user import User, UserRole


class Permission(str, Enum):
    """Enumeration of all available permissions."""

    # System-level permissions (SUPER_ADMIN only)
    MANAGE_SYSTEM_SETTINGS = "manage_system_settings"
    MANAGE_ALL_ORGANIZATIONS = "manage_all_organizations"
    VIEW_SYSTEM_AUDIT_LOGS = "view_system_audit_logs"
    MANAGE_PLATFORM_USERS = "manage_platform_users"

    # Organization-level permissions (ADMIN+)
    MANAGE_ORGANIZATION = "manage_organization"
    MANAGE_ORGANIZATION_BILLING = "manage_organization_billing"
    MANAGE_ORGANIZATION_USERS = "manage_organization_users"
    VIEW_ORGANIZATION_AUDIT_LOGS = "view_organization_audit_logs"

    # Workspace management (ADMIN+)
    CREATE_WORKSPACES = "create_workspaces"
    DELETE_WORKSPACES = "delete_workspaces"
    MANAGE_WORKSPACE = "manage_workspace"
    MANAGE_WORKSPACE_MEMBERS = "manage_workspace_members"

    # User management (ADMIN+)
    INVITE_USERS = "invite_users"
    REMOVE_USERS = "remove_users"
    CHANGE_USER_ROLES = "change_user_roles"

    # Agent management (ADMIN+ for create/delete, USER for use)
    CREATE_AGENTS = "create_agents"
    DELETE_AGENTS = "delete_agents"
    MANAGE_AGENTS = "manage_agents"

    # Resource access (USER+)
    VIEW_WORKSPACE = "view_workspace"
    USE_AGENTS = "use_agents"
    VIEW_CALLS = "view_calls"
    MANAGE_CONTACTS = "manage_contacts"
    MANAGE_CAMPAIGNS = "manage_campaigns"
    VIEW_ANALYTICS = "view_analytics"


# Permission matrix: maps roles to their allowed permissions
ROLE_PERMISSIONS: dict[UserRole, set[Permission]] = {
    UserRole.SUPER_ADMIN: {
        # All permissions
        Permission.MANAGE_SYSTEM_SETTINGS,
        Permission.MANAGE_ALL_ORGANIZATIONS,
        Permission.VIEW_SYSTEM_AUDIT_LOGS,
        Permission.MANAGE_PLATFORM_USERS,
        Permission.MANAGE_ORGANIZATION,
        Permission.MANAGE_ORGANIZATION_BILLING,
        Permission.MANAGE_ORGANIZATION_USERS,
        Permission.VIEW_ORGANIZATION_AUDIT_LOGS,
        Permission.CREATE_WORKSPACES,
        Permission.DELETE_WORKSPACES,
        Permission.MANAGE_WORKSPACE,
        Permission.MANAGE_WORKSPACE_MEMBERS,
        Permission.INVITE_USERS,
        Permission.REMOVE_USERS,
        Permission.CHANGE_USER_ROLES,
        Permission.CREATE_AGENTS,
        Permission.DELETE_AGENTS,
        Permission.MANAGE_AGENTS,
        Permission.VIEW_WORKSPACE,
        Permission.USE_AGENTS,
        Permission.VIEW_CALLS,
        Permission.MANAGE_CONTACTS,
        Permission.MANAGE_CAMPAIGNS,
        Permission.VIEW_ANALYTICS,
    },
    UserRole.ADMIN: {
        # Organization and workspace management
        Permission.MANAGE_ORGANIZATION,
        Permission.MANAGE_ORGANIZATION_BILLING,
        Permission.MANAGE_ORGANIZATION_USERS,
        Permission.VIEW_ORGANIZATION_AUDIT_LOGS,
        Permission.CREATE_WORKSPACES,
        Permission.DELETE_WORKSPACES,
        Permission.MANAGE_WORKSPACE,
        Permission.MANAGE_WORKSPACE_MEMBERS,
        Permission.INVITE_USERS,
        Permission.REMOVE_USERS,
        Permission.CHANGE_USER_ROLES,
        Permission.CREATE_AGENTS,
        Permission.DELETE_AGENTS,
        Permission.MANAGE_AGENTS,
        Permission.VIEW_WORKSPACE,
        Permission.USE_AGENTS,
        Permission.VIEW_CALLS,
        Permission.MANAGE_CONTACTS,
        Permission.MANAGE_CAMPAIGNS,
        Permission.VIEW_ANALYTICS,
    },
    UserRole.USER: {
        # Basic resource access
        Permission.VIEW_WORKSPACE,
        Permission.USE_AGENTS,
        Permission.VIEW_CALLS,
        Permission.MANAGE_CONTACTS,
        Permission.MANAGE_CAMPAIGNS,
        Permission.VIEW_ANALYTICS,
    },
}


def has_permission(user: User, permission: Permission) -> bool:
    """Check if a user has a specific permission.

    Args:
        user: User to check
        permission: Permission to verify

    Returns:
        True if user has the permission, False otherwise
    """
    role_permissions = ROLE_PERMISSIONS.get(user.role, set())
    return permission in role_permissions


def has_any_permission(user: User, permissions: list[Permission]) -> bool:
    """Check if a user has any of the specified permissions.

    Args:
        user: User to check
        permissions: List of permissions (any match is sufficient)

    Returns:
        True if user has any of the permissions, False otherwise
    """
    role_permissions = ROLE_PERMISSIONS.get(user.role, set())
    return bool(role_permissions & set(permissions))


def has_all_permissions(user: User, permissions: list[Permission]) -> bool:
    """Check if a user has all of the specified permissions.

    Args:
        user: User to check
        permissions: List of permissions (all must match)

    Returns:
        True if user has all permissions, False otherwise
    """
    role_permissions = ROLE_PERMISSIONS.get(user.role, set())
    return set(permissions) <= role_permissions


def get_user_permissions(user: User) -> set[Permission]:
    """Get all permissions for a user based on their role.

    Args:
        user: User to get permissions for

    Returns:
        Set of permissions the user has
    """
    return ROLE_PERMISSIONS.get(user.role, set())


def can_manage_role(manager: User, target_role: UserRole) -> bool:
    """Check if a user can manage users with a specific role.

    Role hierarchy enforcement:
    - SUPER_ADMIN can manage all roles
    - ADMIN can manage ADMIN and USER (but not promote to SUPER_ADMIN)
    - USER cannot manage any roles

    Args:
        manager: User performing the action
        target_role: Role being assigned/modified

    Returns:
        True if manager can manage users with target_role
    """
    if manager.role == UserRole.SUPER_ADMIN:
        return True  # Super admin can manage everyone

    if manager.role == UserRole.ADMIN:
        # Admin can manage other admins and users, but not super admins
        return target_role in [UserRole.ADMIN, UserRole.USER]

    return False  # Regular users cannot manage roles


def can_delete_user(deleter: User, target: User) -> bool:
    """Check if a user can delete another user.

    Rules:
    - Cannot delete yourself
    - SUPER_ADMIN can delete anyone except themselves
    - ADMIN can delete ADMIN and USER in their org (but not SUPER_ADMIN)
    - USER cannot delete anyone

    Args:
        deleter: User performing the deletion
        target: User being deleted

    Returns:
        True if deletion is allowed
    """
    # Cannot delete yourself
    if deleter.id == target.id:
        return False

    # Super admin can delete anyone else
    if deleter.role == UserRole.SUPER_ADMIN:
        return True

    # Admin can delete non-super-admins in their organization
    if deleter.role == UserRole.ADMIN:
        if target.role == UserRole.SUPER_ADMIN:
            return False
        # TODO: Add organization check when multi-org support is added
        return True

    return False
