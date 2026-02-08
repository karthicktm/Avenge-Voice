"""Quota service for checking and enforcing resource limits.

This module provides the core quota checking logic for the hierarchical quota system.
It checks quotas at all applicable levels (workspace -> user -> agent) and enforces
the STRICTER limit at any level.
"""

import uuid
from datetime import UTC, datetime
from typing import Any, NamedTuple

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.quota import (
    AgentQuota,
    QuotaPeriod,
    ResourceType,
    UsageRecord,
    UserQuota,
    WorkspaceQuota,
)

logger = structlog.get_logger()


class QuotaCheckResult(NamedTuple):
    """Result of a quota check."""

    allowed: bool
    reason: str
    current_usage: float
    limit: float | None
    remaining: float | None


def get_period_bounds(period: QuotaPeriod) -> tuple[datetime, datetime]:
    """Get the start and end times for a quota period.

    Args:
        period: The quota period type

    Returns:
        Tuple of (period_start, period_end) datetimes
    """
    now = datetime.now(UTC)

    if period == QuotaPeriod.DAILY:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start.replace(hour=23, minute=59, second=59, microsecond=999999)
    elif period == QuotaPeriod.WEEKLY:
        # Week starts on Monday
        days_since_monday = now.weekday()
        start = (now - __import__("datetime").timedelta(days=days_since_monday)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        end = (start + __import__("datetime").timedelta(days=6)).replace(
            hour=23, minute=59, second=59, microsecond=999999
        )
    elif period == QuotaPeriod.MONTHLY:
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        # Get last day of month
        if now.month == 12:
            end = now.replace(year=now.year + 1, month=1, day=1) - __import__("datetime").timedelta(
                days=1
            )
        else:
            end = now.replace(month=now.month + 1, day=1) - __import__("datetime").timedelta(days=1)
        end = end.replace(hour=23, minute=59, second=59, microsecond=999999)
    elif period == QuotaPeriod.YEARLY:
        start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        end = now.replace(month=12, day=31, hour=23, minute=59, second=59, microsecond=999999)
    else:  # LIFETIME
        start = datetime.min.replace(tzinfo=UTC)
        end = datetime.max.replace(tzinfo=UTC)

    return start, end


async def get_usage_for_period(
    db: AsyncSession,
    resource_type: ResourceType,
    period: QuotaPeriod,
    organization_id: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
    user_id: int | None = None,
    agent_id: uuid.UUID | None = None,
) -> float:
    """Get total usage for a resource type within a period.

    Args:
        db: Database session
        resource_type: Type of resource
        period: Time period for aggregation
        organization_id: Optional organization filter
        workspace_id: Optional workspace filter
        user_id: Optional user filter
        agent_id: Optional agent filter

    Returns:
        Total usage amount for the period
    """
    period_start, period_end = get_period_bounds(period)

    query = (
        select(func.coalesce(func.sum(UsageRecord.amount), 0))
        .where(UsageRecord.resource_type == resource_type.value)
        .where(UsageRecord.period_start >= period_start)
        .where(UsageRecord.period_end <= period_end)
    )

    if organization_id:
        query = query.where(UsageRecord.organization_id == organization_id)
    if workspace_id:
        query = query.where(UsageRecord.workspace_id == workspace_id)
    if user_id:
        query = query.where(UsageRecord.user_id == user_id)
    if agent_id:
        query = query.where(UsageRecord.agent_id == agent_id)

    result = await db.scalar(query)
    return float(result or 0)


async def check_workspace_quota(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    resource_type: ResourceType,
    amount: float,
) -> QuotaCheckResult:
    """Check if a workspace has quota available for a resource.

    Args:
        db: Database session
        workspace_id: Workspace to check
        resource_type: Type of resource
        amount: Amount to check against quota

    Returns:
        QuotaCheckResult indicating if request is allowed
    """
    log = logger.bind(workspace_id=str(workspace_id), resource_type=resource_type.value)

    # Get workspace quota
    quota = await db.scalar(
        select(WorkspaceQuota).where(WorkspaceQuota.workspace_id == workspace_id)
    )

    if not quota:
        # No quota defined means unlimited
        log.debug("no_workspace_quota_defined")
        return QuotaCheckResult(
            allowed=True,
            reason="No quota limits defined",
            current_usage=0,
            limit=None,
            remaining=None,
        )

    # Check resource allocations
    allocations = quota.resource_allocations or {}
    if resource_type.value not in allocations:
        log.debug("resource_not_in_allocations")
        return QuotaCheckResult(
            allowed=True,
            reason=f"No limit defined for {resource_type.value}",
            current_usage=0,
            limit=None,
            remaining=None,
        )

    allocation = allocations[resource_type.value]
    limit = allocation.get("limit", 0)
    period = QuotaPeriod(allocation.get("period", "monthly"))

    # Get current usage
    current_usage = await get_usage_for_period(db, resource_type, period, workspace_id=workspace_id)

    remaining = limit - current_usage
    if current_usage + amount > limit:
        log.warning(
            "workspace_quota_exceeded",
            current=current_usage,
            limit=limit,
            requested=amount,
        )
        return QuotaCheckResult(
            allowed=False,
            reason=f"Workspace quota exceeded for {resource_type.value}: {current_usage}/{limit} used",
            current_usage=current_usage,
            limit=limit,
            remaining=remaining,
        )

    return QuotaCheckResult(
        allowed=True,
        reason="Within quota",
        current_usage=current_usage,
        limit=limit,
        remaining=remaining,
    )


async def check_user_quota(
    db: AsyncSession,
    user_id: int,
    workspace_id: uuid.UUID,
    resource_type: ResourceType,
    amount: float,
) -> QuotaCheckResult:
    """Check if a user has quota available within a workspace.

    Args:
        db: Database session
        user_id: User to check
        workspace_id: Workspace context
        resource_type: Type of resource
        amount: Amount to check

    Returns:
        QuotaCheckResult indicating if request is allowed
    """
    log = logger.bind(
        user_id=user_id, workspace_id=str(workspace_id), resource_type=resource_type.value
    )

    # Get user quota
    quota = await db.scalar(
        select(UserQuota).where(
            UserQuota.user_id == user_id,
            UserQuota.workspace_id == workspace_id,
        )
    )

    if not quota:
        log.debug("no_user_quota_defined")
        return QuotaCheckResult(
            allowed=True,
            reason="No user-specific limits",
            current_usage=0,
            limit=None,
            remaining=None,
        )

    allocations = quota.resource_allocations or {}
    if resource_type.value not in allocations:
        return QuotaCheckResult(
            allowed=True,
            reason=f"No user limit for {resource_type.value}",
            current_usage=0,
            limit=None,
            remaining=None,
        )

    allocation = allocations[resource_type.value]
    limit = allocation.get("limit", 0)
    period = QuotaPeriod(allocation.get("period", "monthly"))

    current_usage = await get_usage_for_period(
        db, resource_type, period, user_id=user_id, workspace_id=workspace_id
    )

    remaining = limit - current_usage
    if current_usage + amount > limit:
        log.warning("user_quota_exceeded", current=current_usage, limit=limit, requested=amount)
        return QuotaCheckResult(
            allowed=False,
            reason=f"User quota exceeded for {resource_type.value}: {current_usage}/{limit}",
            current_usage=current_usage,
            limit=limit,
            remaining=remaining,
        )

    return QuotaCheckResult(
        allowed=True,
        reason="Within quota",
        current_usage=current_usage,
        limit=limit,
        remaining=remaining,
    )


async def check_agent_quota(
    db: AsyncSession,
    agent_id: uuid.UUID,
    resource_type: ResourceType,
    amount: float,
) -> QuotaCheckResult:
    """Check if an agent has quota available.

    Args:
        db: Database session
        agent_id: Agent to check
        resource_type: Type of resource
        amount: Amount to check

    Returns:
        QuotaCheckResult indicating if request is allowed
    """
    log = logger.bind(agent_id=str(agent_id), resource_type=resource_type.value)

    quota = await db.scalar(select(AgentQuota).where(AgentQuota.agent_id == agent_id))

    if not quota:
        log.debug("no_agent_quota_defined")
        return QuotaCheckResult(
            allowed=True,
            reason="No agent-specific limits",
            current_usage=0,
            limit=None,
            remaining=None,
        )

    # Check specific agent limits
    if resource_type == ResourceType.CONCURRENT_CALLS:
        return QuotaCheckResult(
            allowed=amount <= quota.max_concurrent_calls,
            reason=f"Max concurrent calls: {quota.max_concurrent_calls}",
            current_usage=0,  # Would need real-time tracking
            limit=quota.max_concurrent_calls,
            remaining=quota.max_concurrent_calls,
        )

    if resource_type == ResourceType.CALLS_PER_DAY:
        current_usage = await get_usage_for_period(
            db, ResourceType.CALLS_PER_DAY, QuotaPeriod.DAILY, agent_id=agent_id
        )
        remaining = quota.max_calls_per_day - current_usage
        if current_usage + amount > quota.max_calls_per_day:
            return QuotaCheckResult(
                allowed=False,
                reason=f"Daily call limit reached: {current_usage}/{quota.max_calls_per_day}",
                current_usage=current_usage,
                limit=quota.max_calls_per_day,
                remaining=remaining,
            )
        return QuotaCheckResult(
            allowed=True,
            reason="Within daily limit",
            current_usage=current_usage,
            limit=quota.max_calls_per_day,
            remaining=remaining,
        )

    # Check resource allocations
    allocations = quota.resource_allocations or {}
    if resource_type.value not in allocations:
        return QuotaCheckResult(
            allowed=True,
            reason=f"No agent limit for {resource_type.value}",
            current_usage=0,
            limit=None,
            remaining=None,
        )

    allocation = allocations[resource_type.value]
    limit = allocation.get("limit", 0)
    period = QuotaPeriod(allocation.get("period", "daily"))

    current_usage = await get_usage_for_period(db, resource_type, period, agent_id=agent_id)
    remaining = limit - current_usage

    if current_usage + amount > limit:
        return QuotaCheckResult(
            allowed=False,
            reason=f"Agent quota exceeded: {current_usage}/{limit}",
            current_usage=current_usage,
            limit=limit,
            remaining=remaining,
        )

    return QuotaCheckResult(
        allowed=True,
        reason="Within quota",
        current_usage=current_usage,
        limit=limit,
        remaining=remaining,
    )


async def check_quota(
    db: AsyncSession,
    resource_type: ResourceType,
    amount: float,
    organization_id: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
    user_id: int | None = None,
    agent_id: uuid.UUID | None = None,
) -> QuotaCheckResult:
    """Check all applicable quotas for a resource request.

    Enforces the STRICTER limit at any level of the hierarchy.
    Checks are performed in order: workspace -> user -> agent

    Args:
        db: Database session
        resource_type: Type of resource
        amount: Amount being requested
        organization_id: Optional organization context
        workspace_id: Optional workspace context
        user_id: Optional user context
        agent_id: Optional agent context

    Returns:
        QuotaCheckResult from the strictest applicable limit
    """
    log = logger.bind(
        resource_type=resource_type.value,
        amount=amount,
        organization_id=str(organization_id) if organization_id else None,
        workspace_id=str(workspace_id) if workspace_id else None,
        user_id=user_id,
        agent_id=str(agent_id) if agent_id else None,
    )

    # Check workspace quota if workspace_id provided
    if workspace_id:
        result = await check_workspace_quota(db, workspace_id, resource_type, amount)
        if not result.allowed:
            log.info("quota_denied_workspace", reason=result.reason)
            return result

    # Check user quota if both user_id and workspace_id provided
    if user_id and workspace_id:
        result = await check_user_quota(db, user_id, workspace_id, resource_type, amount)
        if not result.allowed:
            log.info("quota_denied_user", reason=result.reason)
            return result

    # Check agent quota if agent_id provided
    if agent_id:
        result = await check_agent_quota(db, agent_id, resource_type, amount)
        if not result.allowed:
            log.info("quota_denied_agent", reason=result.reason)
            return result

    log.debug("quota_check_passed")
    return QuotaCheckResult(
        allowed=True,
        reason="All quota checks passed",
        current_usage=0,
        limit=None,
        remaining=None,
    )


async def record_usage(
    db: AsyncSession,
    resource_type: ResourceType,
    amount: float,
    organization_id: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
    user_id: int | None = None,
    agent_id: uuid.UUID | None = None,
    description: str | None = None,
    extra_data: dict[str, Any] | None = None,
) -> UsageRecord:
    """Record resource usage for quota tracking.

    Args:
        db: Database session
        resource_type: Type of resource used
        amount: Amount consumed
        organization_id: Optional organization context
        workspace_id: Optional workspace context
        user_id: Optional user context
        agent_id: Optional agent context
        description: Optional description
        extra_data: Optional additional data

    Returns:
        Created UsageRecord
    """
    now = datetime.now(UTC)
    period_start, period_end = get_period_bounds(QuotaPeriod.MONTHLY)

    record = UsageRecord(
        organization_id=organization_id,
        workspace_id=workspace_id,
        user_id=user_id,
        agent_id=agent_id,
        resource_type=resource_type.value,
        amount=amount,
        period_start=period_start,
        period_end=period_end,
        description=description,
        extra_data=extra_data,
    )

    db.add(record)
    await db.flush()

    logger.info(
        "usage_recorded",
        resource_type=resource_type.value,
        amount=amount,
        record_id=str(record.id),
    )

    return record
