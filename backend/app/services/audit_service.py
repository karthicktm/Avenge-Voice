"""Audit logging service for tracking user actions.

This service provides structured audit logging for:
- User authentication events (login, logout, password changes)
- User management actions (create, update, delete, role changes)
- Organization and workspace changes
- Agent configuration changes
- System settings changes

Audit logs are written asynchronously to avoid blocking the main request.
"""

import uuid
from typing import Any

import structlog
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditAction, AuditLog
from app.models.user import User

logger = structlog.get_logger()


async def log_audit_event(
    db: AsyncSession,
    action: AuditAction,
    *,
    actor: User | None = None,
    actor_id: int | None = None,
    actor_email: str | None = None,
    actor_role: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    organization_id: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
    description: str | None = None,
    details: dict[str, Any] | None = None,
    request: Request | None = None,
) -> AuditLog:
    """Log an audit event.

    Args:
        db: Database session
        action: The action being logged
        actor: User performing the action (optional, can provide actor_id instead)
        actor_id: ID of user performing the action
        actor_email: Email of actor (for deleted user records)
        actor_role: Role of actor at time of action
        resource_type: Type of resource affected (user, agent, workspace, etc.)
        resource_id: ID of the affected resource
        organization_id: Organization context
        workspace_id: Workspace context
        description: Human-readable description
        details: Additional structured details
        request: FastAPI request object (for IP/user agent)

    Returns:
        The created AuditLog entry
    """
    # Extract actor info from User object if provided
    if actor:
        actor_id = actor.id
        actor_email = actor.email
        actor_role = actor.role.value if actor.role else None

    # Extract request info
    ip_address = None
    user_agent = None
    if request:
        # Get client IP (handle proxies)
        ip_address = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        if not ip_address:
            ip_address = request.client.host if request.client else None
        user_agent = request.headers.get("User-Agent", "")[:500]  # Truncate long UAs

    # Create audit log entry
    audit_log = AuditLog(
        actor_id=actor_id,
        actor_email=actor_email,
        actor_role=actor_role,
        action=action.value,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id else None,
        organization_id=organization_id,
        workspace_id=workspace_id,
        description=description,
        details=details,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    db.add(audit_log)
    await db.commit()
    await db.refresh(audit_log)

    # Log to structured logger as well for real-time monitoring
    logger.info(
        "audit_event",
        action=action.value,
        actor_id=actor_id,
        actor_email=actor_email,
        resource_type=resource_type,
        resource_id=resource_id,
        organization_id=str(organization_id) if organization_id else None,
        description=description,
    )

    return audit_log


# Convenience functions for common audit events


async def log_user_login(
    db: AsyncSession,
    user: User,
    request: Request | None = None,
    success: bool = True,
) -> AuditLog:
    """Log a user login attempt."""
    action = AuditAction.USER_LOGIN if success else AuditAction.USER_LOGIN_FAILED
    return await log_audit_event(
        db,
        action,
        actor=user,
        resource_type="user",
        resource_id=str(user.id),
        organization_id=user.organization_id,
        description=f"User {'logged in' if success else 'failed login attempt'}",
        request=request,
    )


async def log_user_logout(
    db: AsyncSession,
    user: User,
    request: Request | None = None,
    logout_all: bool = False,
) -> AuditLog:
    """Log a user logout."""
    return await log_audit_event(
        db,
        AuditAction.USER_LOGOUT,
        actor=user,
        resource_type="user",
        resource_id=str(user.id),
        organization_id=user.organization_id,
        description="User logged out from all devices" if logout_all else "User logged out",
        details={"logout_all": logout_all},
        request=request,
    )


async def log_user_created(
    db: AsyncSession,
    actor: User,
    created_user: User,
    request: Request | None = None,
) -> AuditLog:
    """Log user creation."""
    return await log_audit_event(
        db,
        AuditAction.USER_CREATED,
        actor=actor,
        resource_type="user",
        resource_id=str(created_user.id),
        organization_id=created_user.organization_id,
        description=f"User {created_user.email} created",
        details={
            "created_user_email": created_user.email,
            "created_user_role": created_user.role.value if created_user.role else None,
        },
        request=request,
    )


async def log_user_updated(
    db: AsyncSession,
    actor: User,
    updated_user: User,
    changes: dict[str, Any],
    request: Request | None = None,
) -> AuditLog:
    """Log user update."""
    return await log_audit_event(
        db,
        AuditAction.USER_UPDATED,
        actor=actor,
        resource_type="user",
        resource_id=str(updated_user.id),
        organization_id=updated_user.organization_id,
        description=f"User {updated_user.email} updated",
        details={"changes": changes},
        request=request,
    )


async def log_user_deleted(
    db: AsyncSession,
    actor: User,
    deleted_user: User,
    request: Request | None = None,
) -> AuditLog:
    """Log user deletion."""
    return await log_audit_event(
        db,
        AuditAction.USER_DELETED,
        actor=actor,
        resource_type="user",
        resource_id=str(deleted_user.id),
        organization_id=deleted_user.organization_id,
        description=f"User {deleted_user.email} deleted",
        details={
            "deleted_user_email": deleted_user.email,
            "deleted_user_role": deleted_user.role.value if deleted_user.role else None,
        },
        request=request,
    )


async def log_user_role_changed(
    db: AsyncSession,
    actor: User,
    target_user: User,
    old_role: str,
    new_role: str,
    request: Request | None = None,
) -> AuditLog:
    """Log user role change."""
    return await log_audit_event(
        db,
        AuditAction.USER_ROLE_CHANGED,
        actor=actor,
        resource_type="user",
        resource_id=str(target_user.id),
        organization_id=target_user.organization_id,
        description=f"User {target_user.email} role changed from {old_role} to {new_role}",
        details={
            "target_user_email": target_user.email,
            "old_role": old_role,
            "new_role": new_role,
        },
        request=request,
    )


async def log_password_reset(
    db: AsyncSession,
    user: User,
    request: Request | None = None,
) -> AuditLog:
    """Log password reset."""
    return await log_audit_event(
        db,
        AuditAction.USER_PASSWORD_RESET,
        actor=user,
        resource_type="user",
        resource_id=str(user.id),
        organization_id=user.organization_id,
        description=f"Password reset for {user.email}",
        request=request,
    )


async def log_email_verified(
    db: AsyncSession,
    user: User,
    request: Request | None = None,
) -> AuditLog:
    """Log email verification."""
    return await log_audit_event(
        db,
        AuditAction.USER_EMAIL_VERIFIED,
        actor=user,
        resource_type="user",
        resource_id=str(user.id),
        organization_id=user.organization_id,
        description=f"Email verified for {user.email}",
        request=request,
    )


async def log_workspace_created(
    db: AsyncSession,
    actor: User,
    workspace_id: uuid.UUID,
    workspace_name: str,
    organization_id: uuid.UUID,
    request: Request | None = None,
) -> AuditLog:
    """Log workspace creation."""
    return await log_audit_event(
        db,
        AuditAction.WORKSPACE_CREATED,
        actor=actor,
        resource_type="workspace",
        resource_id=str(workspace_id),
        organization_id=organization_id,
        workspace_id=workspace_id,
        description=f"Workspace '{workspace_name}' created",
        details={"workspace_name": workspace_name},
        request=request,
    )


async def log_workspace_deleted(
    db: AsyncSession,
    actor: User,
    workspace_id: uuid.UUID,
    workspace_name: str,
    organization_id: uuid.UUID,
    request: Request | None = None,
) -> AuditLog:
    """Log workspace deletion."""
    return await log_audit_event(
        db,
        AuditAction.WORKSPACE_DELETED,
        actor=actor,
        resource_type="workspace",
        resource_id=str(workspace_id),
        organization_id=organization_id,
        description=f"Workspace '{workspace_name}' deleted",
        details={"workspace_name": workspace_name},
        request=request,
    )


async def log_agent_created(
    db: AsyncSession,
    actor: User,
    agent_id: uuid.UUID,
    agent_name: str,
    workspace_id: uuid.UUID | None = None,
    request: Request | None = None,
) -> AuditLog:
    """Log agent creation."""
    return await log_audit_event(
        db,
        AuditAction.AGENT_CREATED,
        actor=actor,
        resource_type="agent",
        resource_id=str(agent_id),
        organization_id=actor.organization_id,
        workspace_id=workspace_id,
        description=f"Agent '{agent_name}' created",
        details={"agent_name": agent_name},
        request=request,
    )


async def log_agent_deleted(
    db: AsyncSession,
    actor: User,
    agent_id: uuid.UUID,
    agent_name: str,
    workspace_id: uuid.UUID | None = None,
    request: Request | None = None,
) -> AuditLog:
    """Log agent deletion."""
    return await log_audit_event(
        db,
        AuditAction.AGENT_DELETED,
        actor=actor,
        resource_type="agent",
        resource_id=str(agent_id),
        organization_id=actor.organization_id,
        workspace_id=workspace_id,
        description=f"Agent '{agent_name}' deleted",
        details={"agent_name": agent_name},
        request=request,
    )


async def log_system_settings_changed(
    db: AsyncSession,
    actor: User,
    changes: dict[str, Any],
    request: Request | None = None,
) -> AuditLog:
    """Log system settings change."""
    return await log_audit_event(
        db,
        AuditAction.SYSTEM_SETTINGS_CHANGED,
        actor=actor,
        resource_type="system",
        resource_id="settings",
        description="System settings changed",
        details={"changes": changes},
        request=request,
    )


async def log_api_key_created(
    db: AsyncSession,
    actor: User,
    key_id: str,
    key_name: str | None = None,
    request: Request | None = None,
) -> AuditLog:
    """Log API key creation."""
    return await log_audit_event(
        db,
        AuditAction.API_KEY_CREATED,
        actor=actor,
        resource_type="api_key",
        resource_id=key_id,
        organization_id=actor.organization_id,
        description=f"API key '{key_name or key_id}' created",
        details={"key_name": key_name},
        request=request,
    )


async def log_api_key_revoked(
    db: AsyncSession,
    actor: User,
    key_id: str,
    key_name: str | None = None,
    request: Request | None = None,
) -> AuditLog:
    """Log API key revocation."""
    return await log_audit_event(
        db,
        AuditAction.API_KEY_REVOKED,
        actor=actor,
        resource_type="api_key",
        resource_id=key_id,
        organization_id=actor.organization_id,
        description=f"API key '{key_name or key_id}' revoked",
        details={"key_name": key_name},
        request=request,
    )
