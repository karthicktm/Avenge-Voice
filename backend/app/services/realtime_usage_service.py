"""Real-time usage tracking service using Redis.

This service provides fast, atomic counters for usage tracking with
pub/sub for real-time dashboard updates.

Redis Key Structure:
- usage:counter:{org_id}:{resource_type}:YYYY-MM → int (atomic counter)
- usage:session:{session_id} → hash (active session tracking)
- usage:alert:{org_id}:{resource_type}:{threshold} → "sent" (prevent duplicates)
- usage:updates:{org_id} → pub/sub channel for WebSocket
"""

import asyncio
import json
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.redis import get_redis
from app.models.organization import Organization
from app.models.quota import ResourceType, UsageRecord
from app.services.stripe_service import get_plan_limits

logger = structlog.get_logger()

# Key prefixes
COUNTER_PREFIX = "usage:counter"
SESSION_PREFIX = "usage:session"
ALERT_PREFIX = "usage:alert"
UPDATES_CHANNEL_PREFIX = "usage:updates"

# Sync interval in seconds (sync Redis counters to Postgres)
USAGE_SYNC_INTERVAL_SECONDS = 300  # 5 minutes


def _get_period_key() -> str:
    """Get the current period key (YYYY-MM)."""
    return datetime.now(UTC).strftime("%Y-%m")


def _counter_key(org_id: uuid.UUID, resource_type: str, period: str | None = None) -> str:
    """Build counter key."""
    period = period or _get_period_key()
    return f"{COUNTER_PREFIX}:{org_id}:{resource_type}:{period}"


def _session_key(session_id: str) -> str:
    """Build session key."""
    return f"{SESSION_PREFIX}:{session_id}"


def _alert_key(
    org_id: uuid.UUID, resource_type: str, threshold: str, period: str | None = None
) -> str:
    """Build alert key."""
    period = period or _get_period_key()
    return f"{ALERT_PREFIX}:{org_id}:{resource_type}:{threshold}:{period}"


def _updates_channel(org_id: uuid.UUID) -> str:
    """Build pub/sub channel name for organization updates."""
    return f"{UPDATES_CHANNEL_PREFIX}:{org_id}"


async def increment_usage(
    org_id: uuid.UUID,
    resource_type: str | ResourceType,
    amount: float,
    workspace_id: uuid.UUID | None = None,
    agent_id: uuid.UUID | None = None,
    user_id: int | None = None,
    publish_update: bool = True,
) -> float:
    """Increment usage counter atomically.

    Args:
        org_id: Organization ID
        resource_type: Type of resource
        amount: Amount to increment
        workspace_id: Optional workspace ID for breakdown
        agent_id: Optional agent ID for breakdown
        user_id: Optional user ID for breakdown
        publish_update: Whether to publish update to WebSocket channel

    Returns:
        New total usage for the period
    """
    if isinstance(resource_type, ResourceType):
        resource_type = resource_type.value

    log = logger.bind(org_id=str(org_id), resource_type=resource_type, amount=amount)

    try:
        redis = await get_redis()

        # Increment main org counter
        key = _counter_key(org_id, resource_type)
        new_total = await redis.incrbyfloat(key, amount)

        # Set expiry to 35 days (to cover full month + grace period)
        await redis.expire(key, 35 * 24 * 60 * 60)

        # Also track by workspace if provided
        if workspace_id:
            ws_key = f"{COUNTER_PREFIX}:ws:{workspace_id}:{resource_type}:{_get_period_key()}"
            await redis.incrbyfloat(ws_key, amount)
            await redis.expire(ws_key, 35 * 24 * 60 * 60)

        # Also track by agent if provided
        if agent_id:
            agent_key = f"{COUNTER_PREFIX}:agent:{agent_id}:{resource_type}:{_get_period_key()}"
            await redis.incrbyfloat(agent_key, amount)
            await redis.expire(agent_key, 35 * 24 * 60 * 60)

        # Also track by user if provided
        if user_id:
            user_key = f"{COUNTER_PREFIX}:user:{user_id}:{resource_type}:{_get_period_key()}"
            await redis.incrbyfloat(user_key, amount)
            await redis.expire(user_key, 35 * 24 * 60 * 60)

        # Publish update to WebSocket channel
        if publish_update:
            await _publish_usage_update(org_id, resource_type, new_total)

        log.debug("usage_incremented", new_total=new_total)
        return float(new_total)

    except Exception:
        log.exception("usage_increment_failed")
        raise


async def get_current_usage(
    org_id: uuid.UUID,
    resource_type: str | ResourceType,
    period: str | None = None,
) -> float:
    """Get current usage for a resource type.

    Args:
        org_id: Organization ID
        resource_type: Type of resource
        period: Optional period (defaults to current month)

    Returns:
        Current usage amount
    """
    if isinstance(resource_type, ResourceType):
        resource_type = resource_type.value

    try:
        redis = await get_redis()
        key = _counter_key(org_id, resource_type, period)
        value = await redis.get(key)
        return float(value) if value else 0.0
    except Exception:
        logger.exception(
            "get_current_usage_failed", org_id=str(org_id), resource_type=resource_type
        )
        return 0.0


async def get_all_usage(org_id: uuid.UUID, period: str | None = None) -> dict[str, float]:
    """Get all resource usage for an organization.

    Args:
        org_id: Organization ID
        period: Optional period (defaults to current month)

    Returns:
        Dictionary of resource_type -> usage amount
    """
    period = period or _get_period_key()
    pattern = f"{COUNTER_PREFIX}:{org_id}:*:{period}"

    try:
        redis = await get_redis()
        usage: dict[str, float] = {}

        async for key in redis.scan_iter(match=pattern):
            # Extract resource type from key
            parts = key.split(":")
            if len(parts) >= 4:
                resource_type = parts[2]
                value = await redis.get(key)
                usage[resource_type] = float(value) if value else 0.0

        return usage
    except Exception:
        logger.exception("get_all_usage_failed", org_id=str(org_id))
        return {}


async def get_usage_with_limits(
    org_id: uuid.UUID,
    organization: Organization,
    period: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Get usage with limits and percentages for all resources.

    Args:
        org_id: Organization ID
        organization: Organization object for plan limits
        period: Optional period (defaults to current month)

    Returns:
        Dictionary of resource_type -> {current, limit, percentage, remaining}
    """
    usage = await get_all_usage(org_id, period)
    limits = get_plan_limits(organization.plan_type)

    result: dict[str, dict[str, Any]] = {}

    for resource_type in ResourceType:
        rt = resource_type.value
        current = usage.get(rt, 0.0)
        limit = limits.get(rt, -1)  # -1 means unlimited

        if limit == -1:
            # Unlimited
            result[rt] = {
                "current": current,
                "limit": None,
                "percentage": 0,
                "remaining": None,
                "unlimited": True,
            }
        elif limit == 0:
            # Not available for this plan
            result[rt] = {
                "current": current,
                "limit": 0,
                "percentage": 100 if current > 0 else 0,
                "remaining": 0,
                "unlimited": False,
            }
        else:
            percentage = (current / limit * 100) if limit > 0 else 0
            result[rt] = {
                "current": current,
                "limit": limit,
                "percentage": min(percentage, 100),
                "remaining": max(limit - current, 0),
                "unlimited": False,
            }

    return result


async def get_workspace_usage(
    workspace_id: uuid.UUID,
    period: str | None = None,
) -> dict[str, float]:
    """Get usage for a specific workspace.

    Args:
        workspace_id: Workspace ID
        period: Optional period (defaults to current month)

    Returns:
        Dictionary of resource_type -> usage amount
    """
    period = period or _get_period_key()
    pattern = f"{COUNTER_PREFIX}:ws:{workspace_id}:*:{period}"

    try:
        redis = await get_redis()
        usage: dict[str, float] = {}

        async for key in redis.scan_iter(match=pattern):
            parts = key.split(":")
            if len(parts) >= 5:
                resource_type = parts[3]
                value = await redis.get(key)
                usage[resource_type] = float(value) if value else 0.0

        return usage
    except Exception:
        logger.exception("get_workspace_usage_failed", workspace_id=str(workspace_id))
        return {}


async def get_agent_usage(
    agent_id: uuid.UUID,
    period: str | None = None,
) -> dict[str, float]:
    """Get usage for a specific agent.

    Args:
        agent_id: Agent ID
        period: Optional period (defaults to current month)

    Returns:
        Dictionary of resource_type -> usage amount
    """
    period = period or _get_period_key()
    pattern = f"{COUNTER_PREFIX}:agent:{agent_id}:*:{period}"

    try:
        redis = await get_redis()
        usage: dict[str, float] = {}

        async for key in redis.scan_iter(match=pattern):
            parts = key.split(":")
            if len(parts) >= 5:
                resource_type = parts[3]
                value = await redis.get(key)
                usage[resource_type] = float(value) if value else 0.0

        return usage
    except Exception:
        logger.exception("get_agent_usage_failed", agent_id=str(agent_id))
        return {}


# Session tracking for active calls/sessions


async def start_session(
    session_id: str,
    org_id: uuid.UUID,
    workspace_id: uuid.UUID | None = None,
    agent_id: uuid.UUID | None = None,
    user_id: int | None = None,
    session_type: str = "call",
) -> None:
    """Start tracking a session.

    Args:
        session_id: Unique session identifier
        org_id: Organization ID
        workspace_id: Optional workspace ID
        agent_id: Optional agent ID
        user_id: Optional user ID
        session_type: Type of session (call, realtime, etc.)
    """
    try:
        redis = await get_redis()
        key = _session_key(session_id)

        session_data = {
            "org_id": str(org_id),
            "workspace_id": str(workspace_id) if workspace_id else "",
            "agent_id": str(agent_id) if agent_id else "",
            "user_id": str(user_id) if user_id else "",
            "session_type": session_type,
            "started_at": datetime.now(UTC).isoformat(),
            "current_cost_cents": "0",
        }

        await redis.hset(key, mapping=session_data)  # type: ignore[misc]
        # Expire after 24 hours (safety cleanup)
        await redis.expire(key, 24 * 60 * 60)

        logger.debug("session_started", session_id=session_id)
    except Exception:
        logger.exception("session_start_failed", session_id=session_id)


async def update_session_cost(session_id: str, cost_cents: float) -> None:
    """Update the running cost for a session.

    Args:
        session_id: Session identifier
        cost_cents: Current total cost in cents
    """
    try:
        redis = await get_redis()
        key = _session_key(session_id)
        await redis.hset(key, "current_cost_cents", str(cost_cents))  # type: ignore[misc]
    except Exception:
        logger.exception("session_cost_update_failed", session_id=session_id)


async def end_session(session_id: str) -> dict[str, Any] | None:
    """End a session and return its data.

    Args:
        session_id: Session identifier

    Returns:
        Session data or None if not found
    """
    try:
        redis = await get_redis()
        key = _session_key(session_id)

        # Get session data
        data = await redis.hgetall(key)  # type: ignore[misc]
        if not data:
            return None

        # Calculate duration
        started_at = datetime.fromisoformat(data.get("started_at", datetime.now(UTC).isoformat()))
        duration_seconds = (datetime.now(UTC) - started_at).total_seconds()

        # Add duration to response
        session_data = dict(data)
        session_data["duration_seconds"] = duration_seconds
        session_data["ended_at"] = datetime.now(UTC).isoformat()

        # Delete session
        await redis.delete(key)

        logger.debug("session_ended", session_id=session_id, duration_seconds=duration_seconds)
        return session_data
    except Exception:
        logger.exception("session_end_failed", session_id=session_id)
        return None


async def get_active_sessions(org_id: uuid.UUID) -> list[dict[str, Any]]:
    """Get all active sessions for an organization.

    Args:
        org_id: Organization ID

    Returns:
        List of active session data
    """
    try:
        redis = await get_redis()
        sessions: list[dict[str, Any]] = []

        # Scan for all sessions
        async for key in redis.scan_iter(match=f"{SESSION_PREFIX}:*"):
            data = await redis.hgetall(key)  # type: ignore[misc]
            if data.get("org_id") == str(org_id):
                session_id = key.split(":")[-1]
                sessions.append({"session_id": session_id, **data})

        return sessions
    except Exception:
        logger.exception("get_active_sessions_failed", org_id=str(org_id))
        return []


# Pub/Sub for real-time updates


async def _publish_usage_update(
    org_id: uuid.UUID,
    resource_type: str,
    current_usage: float,
) -> None:
    """Publish usage update to WebSocket channel.

    Args:
        org_id: Organization ID
        resource_type: Type of resource
        current_usage: Current usage amount
    """
    try:
        redis = await get_redis()
        channel = _updates_channel(org_id)

        message = json.dumps(
            {
                "type": "usage_update",
                "resource_type": resource_type,
                "current": current_usage,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )

        await redis.publish(channel, message)
    except Exception:
        logger.exception("publish_usage_update_failed", org_id=str(org_id))


async def publish_alert(
    org_id: uuid.UUID,
    resource_type: str,
    threshold: str,
    current_usage: float,
    limit: float,
) -> None:
    """Publish alert to WebSocket channel.

    Args:
        org_id: Organization ID
        resource_type: Type of resource
        threshold: Alert threshold (50, 80, 90, 100)
        current_usage: Current usage amount
        limit: Usage limit
    """
    try:
        redis = await get_redis()
        channel = _updates_channel(org_id)

        message = json.dumps(
            {
                "type": "usage_alert",
                "resource_type": resource_type,
                "threshold": threshold,
                "current": current_usage,
                "limit": limit,
                "percentage": (current_usage / limit * 100) if limit > 0 else 0,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )

        await redis.publish(channel, message)
    except Exception:
        logger.exception("publish_alert_failed", org_id=str(org_id))


async def subscribe_to_usage_updates(org_id: uuid.UUID) -> AsyncGenerator[str, None]:
    """Subscribe to usage updates for an organization.

    Args:
        org_id: Organization ID

    Yields:
        Usage update messages
    """
    try:
        redis = await get_redis()
        pubsub = redis.pubsub()
        channel = _updates_channel(org_id)

        await pubsub.subscribe(channel)

        async for message in pubsub.listen():
            if message["type"] == "message":
                yield json.loads(message["data"])

    except asyncio.CancelledError:
        logger.debug("usage_subscription_cancelled", org_id=str(org_id))
        raise
    except Exception:
        logger.exception("usage_subscription_failed", org_id=str(org_id))
        raise


# Sync to Postgres (background task)


async def sync_to_postgres(db: AsyncSession, org_id: uuid.UUID) -> None:
    """Sync Redis usage counters to Postgres for persistence.

    This should be run periodically as a background task.

    Args:
        db: Database session
        org_id: Organization ID
    """
    log = logger.bind(org_id=str(org_id))

    try:
        usage = await get_all_usage(org_id)
        period = _get_period_key()

        # Parse period into start/end dates
        year, month = map(int, period.split("-"))
        period_start = datetime(year, month, 1, tzinfo=UTC)
        if month == 12:
            period_end = datetime(year + 1, 1, 1, tzinfo=UTC)
        else:
            period_end = datetime(year, month + 1, 1, tzinfo=UTC)

        for resource_type, amount in usage.items():
            # Check if record exists
            result = await db.execute(
                select(UsageRecord).where(
                    UsageRecord.organization_id == org_id,
                    UsageRecord.resource_type == resource_type,
                    UsageRecord.period_start == period_start,
                )
            )
            record = result.scalar_one_or_none()

            if record:
                record.amount = amount
            else:
                record = UsageRecord(
                    organization_id=org_id,
                    resource_type=resource_type,
                    amount=amount,
                    period_start=period_start,
                    period_end=period_end,
                    description=f"Synced from Redis at {datetime.now(UTC).isoformat()}",
                )
                db.add(record)

        await db.flush()
        log.debug("usage_synced_to_postgres", resources_count=len(usage))

    except Exception:
        log.exception("sync_to_postgres_failed")
        raise


# Alert tracking (prevent duplicate alerts)


async def mark_alert_sent(
    org_id: uuid.UUID,
    resource_type: str,
    threshold: str,
) -> bool:
    """Mark an alert as sent (prevents duplicates within period).

    Args:
        org_id: Organization ID
        resource_type: Type of resource
        threshold: Alert threshold

    Returns:
        True if this is a new alert, False if already sent
    """
    try:
        redis = await get_redis()
        key = _alert_key(org_id, resource_type, threshold)

        # SET NX returns True if key was set (new alert)
        result = await redis.set(key, "sent", nx=True)

        if result:
            # Set expiry to end of month
            await redis.expire(key, 35 * 24 * 60 * 60)
            return True

        return False
    except Exception:
        logger.exception("mark_alert_sent_failed", org_id=str(org_id))
        return False


async def reset_period_alerts(org_id: uuid.UUID) -> None:
    """Reset all alerts for an organization (for new period).

    Args:
        org_id: Organization ID
    """
    try:
        redis = await get_redis()
        pattern = f"{ALERT_PREFIX}:{org_id}:*"

        async for key in redis.scan_iter(match=pattern):
            await redis.delete(key)

        logger.debug("period_alerts_reset", org_id=str(org_id))
    except Exception:
        logger.exception("reset_period_alerts_failed", org_id=str(org_id))
