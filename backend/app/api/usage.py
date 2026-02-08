"""Usage API endpoints for tracking and monitoring resource consumption."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import VerifiedUser
from app.db.session import get_db
from app.models.billing import UsageAlert
from app.models.organization import Organization
from app.models.quota import ResourceType, UsageRecord
from app.services.realtime_usage_service import (
    get_agent_usage,
    get_current_usage,
    get_usage_with_limits,
    get_workspace_usage,
)
from app.services.stripe_service import get_plan_limits
from app.services.usage_alert_service import (
    acknowledge_alert,
    get_pending_alerts,
    get_recent_alerts,
)

router = APIRouter(prefix="/api/v1/usage", tags=["usage"])


# =============================================================================
# Response Models
# =============================================================================


class ResourceUsage(BaseModel):
    """Usage for a single resource type."""

    resource_type: str
    current: float
    limit: float | None
    percentage: float
    remaining: float | None
    unlimited: bool = False


class UsageOverview(BaseModel):
    """Overview of all resource usage."""

    resources: dict[str, ResourceUsage]
    period: str
    period_start: str
    period_end: str


class UsageHistoryEntry(BaseModel):
    """Historical usage entry."""

    period: str
    resource_type: str
    amount: float


class UsageBreakdown(BaseModel):
    """Usage breakdown by entity."""

    entity_type: str  # workspace, agent, user
    entity_id: str
    entity_name: str | None
    usage: dict[str, float]


class AlertResponse(BaseModel):
    """Usage alert response."""

    id: str
    resource_type: str
    threshold: str
    status: str
    current_usage: float
    limit: float
    percentage: float
    created_at: str
    acknowledged_at: str | None

    class Config:
        from_attributes = True


# =============================================================================
# Helper Functions
# =============================================================================


async def _get_user_organization(db: AsyncSession, user: VerifiedUser) -> Organization:
    """Get the organization for the current user."""
    result = await db.execute(select(Organization).where(Organization.id == user.organization_id))
    org = result.scalar_one_or_none()

    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    return org


def _get_current_period() -> tuple[str, datetime, datetime]:
    """Get current billing period info."""
    now = datetime.now(UTC)
    period = now.strftime("%Y-%m")
    period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    if now.month == 12:
        period_end = now.replace(year=now.year + 1, month=1, day=1)
    else:
        period_end = now.replace(month=now.month + 1, day=1)

    return period, period_start, period_end


# =============================================================================
# Usage Endpoints
# =============================================================================


@router.get("/current", response_model=UsageOverview)
async def get_current_usage_overview(
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> UsageOverview:
    """Get current usage overview for all resources."""
    org = await _get_user_organization(db, current_user)
    period, period_start, period_end = _get_current_period()

    usage_data = await get_usage_with_limits(org.id, org)

    resources = {
        rt: ResourceUsage(
            resource_type=rt,
            current=data["current"],
            limit=data["limit"],
            percentage=data["percentage"],
            remaining=data["remaining"],
            unlimited=data["unlimited"],
        )
        for rt, data in usage_data.items()
    }

    return UsageOverview(
        resources=resources,
        period=period,
        period_start=period_start.isoformat(),
        period_end=period_end.isoformat(),
    )


@router.get("/current/{resource_type}", response_model=ResourceUsage)
async def get_resource_usage(
    resource_type: str,
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> ResourceUsage:
    """Get current usage for a specific resource type."""
    org = await _get_user_organization(db, current_user)

    # Validate resource type
    try:
        rt = ResourceType(resource_type)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid resource type: {resource_type}",
        ) from e

    current = await get_current_usage(org.id, rt)
    limits = get_plan_limits(org.plan_type)
    limit = limits.get(resource_type, -1)

    if limit == -1:
        return ResourceUsage(
            resource_type=resource_type,
            current=current,
            limit=None,
            percentage=0,
            remaining=None,
            unlimited=True,
        )
    if limit == 0:
        return ResourceUsage(
            resource_type=resource_type,
            current=current,
            limit=0,
            percentage=100 if current > 0 else 0,
            remaining=0,
            unlimited=False,
        )
    percentage = (current / limit * 100) if limit > 0 else 0
    return ResourceUsage(
        resource_type=resource_type,
        current=current,
        limit=limit,
        percentage=min(percentage, 100),
        remaining=max(limit - current, 0),
        unlimited=False,
    )


@router.get("/history", response_model=list[UsageHistoryEntry])
async def get_usage_history(
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
    resource_type: str | None = None,
    months: int = 6,
) -> list[UsageHistoryEntry]:
    """Get historical usage data."""
    org = await _get_user_organization(db, current_user)

    # Query usage records grouped by month
    query = (
        select(
            func.to_char(UsageRecord.period_start, "YYYY-MM").label("period"),
            UsageRecord.resource_type,
            func.sum(UsageRecord.amount).label("total"),
        )
        .where(UsageRecord.organization_id == org.id)
        .group_by(
            func.to_char(UsageRecord.period_start, "YYYY-MM"),
            UsageRecord.resource_type,
        )
        .order_by(func.to_char(UsageRecord.period_start, "YYYY-MM").desc())
        .limit(months * len(ResourceType))
    )

    if resource_type:
        query = query.where(UsageRecord.resource_type == resource_type)

    result = await db.execute(query)
    rows = result.all()

    return [
        UsageHistoryEntry(
            period=row.period,
            resource_type=row.resource_type,
            amount=row.total or 0,
        )
        for row in rows
    ]


@router.get("/breakdown", response_model=list[UsageBreakdown])
async def get_usage_breakdown(
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
    breakdown_by: str = "workspace",
) -> list[UsageBreakdown]:
    """Get usage breakdown by workspace, agent, or user."""
    org = await _get_user_organization(db, current_user)

    if breakdown_by not in ["workspace", "agent", "user"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="breakdown_by must be 'workspace', 'agent', or 'user'",
        )

    breakdowns: list[UsageBreakdown] = []

    if breakdown_by == "workspace":
        # Get workspaces
        from app.models.workspace import Workspace

        result = await db.execute(select(Workspace).where(Workspace.organization_id == org.id))
        workspaces = result.scalars().all()

        for ws in workspaces:
            usage = await get_workspace_usage(ws.id)
            breakdowns.append(
                UsageBreakdown(
                    entity_type="workspace",
                    entity_id=str(ws.id),
                    entity_name=ws.name,
                    usage=usage,
                )
            )

    elif breakdown_by == "agent":
        # Get agents via the junction table
        from app.models.agent import Agent
        from app.models.workspace import AgentWorkspace, Workspace

        result = await db.execute(
            select(Agent)
            .join(AgentWorkspace, Agent.id == AgentWorkspace.agent_id)
            .join(Workspace, AgentWorkspace.workspace_id == Workspace.id)
            .where(Workspace.organization_id == org.id)
            .distinct()
        )
        agents = result.scalars().all()

        for agent in agents:
            usage = await get_agent_usage(agent.id)
            breakdowns.append(
                UsageBreakdown(
                    entity_type="agent",
                    entity_id=str(agent.id),
                    entity_name=agent.name,
                    usage=usage,
                )
            )

    # Note: User breakdown would require tracking user_id in usage

    return breakdowns


# =============================================================================
# Alert Endpoints
# =============================================================================


@router.get("/alerts", response_model=list[AlertResponse])
async def get_alerts(
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
    pending_only: bool = False,
    limit: int = 20,
) -> list[AlertResponse]:
    """Get usage alerts for the organization."""
    org = await _get_user_organization(db, current_user)

    if pending_only:
        alerts = await get_pending_alerts(db, org.id)
    else:
        alerts = await get_recent_alerts(db, org.id, limit=limit)

    return [
        AlertResponse(
            id=str(alert.id),
            resource_type=alert.resource_type,
            threshold=alert.threshold,
            status=alert.status,
            current_usage=alert.current_usage,
            limit=alert.limit,
            percentage=alert.percentage,
            created_at=alert.created_at.isoformat(),
            acknowledged_at=alert.acknowledged_at.isoformat() if alert.acknowledged_at else None,
        )
        for alert in alerts
    ]


@router.get("/alerts/pending/count")
async def get_pending_alerts_count(
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    """Get count of pending alerts."""
    org = await _get_user_organization(db, current_user)
    alerts = await get_pending_alerts(db, org.id)
    return {"count": len(alerts)}


@router.post("/alerts/{alert_id}/acknowledge", response_model=AlertResponse)
async def acknowledge_alert_endpoint(
    alert_id: str,
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> AlertResponse:
    """Acknowledge a usage alert."""
    org = await _get_user_organization(db, current_user)

    # Verify alert belongs to organization
    result = await db.execute(
        select(UsageAlert).where(
            UsageAlert.id == uuid.UUID(alert_id),
            UsageAlert.organization_id == org.id,
        )
    )
    alert = result.scalar_one_or_none()

    if not alert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alert not found",
        )

    updated_alert = await acknowledge_alert(db, uuid.UUID(alert_id), current_user.id)
    await db.commit()

    if not updated_alert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alert not found",
        )

    return AlertResponse(
        id=str(updated_alert.id),
        resource_type=updated_alert.resource_type,
        threshold=updated_alert.threshold,
        status=updated_alert.status,
        current_usage=updated_alert.current_usage,
        limit=updated_alert.limit,
        percentage=updated_alert.percentage,
        created_at=updated_alert.created_at.isoformat(),
        acknowledged_at=updated_alert.acknowledged_at.isoformat()
        if updated_alert.acknowledged_at
        else None,
    )


# =============================================================================
# Resource Type Information
# =============================================================================


@router.get("/resource-types")
async def list_resource_types() -> list[dict[str, str]]:
    """List all available resource types."""
    return [
        {
            "value": rt.value,
            "name": rt.value.replace("_", " ").title(),
        }
        for rt in ResourceType
    ]
