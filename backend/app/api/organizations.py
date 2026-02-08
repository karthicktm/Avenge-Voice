"""Organization management API endpoints.

Admin-only endpoints for managing organization settings and plans.
"""

from datetime import UTC, datetime
from typing import TypedDict

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AdminUser, VerifiedUser
from app.db.session import get_db
from app.models.organization import Organization, PlanType, SubscriptionStatus
from app.models.user import UserRole

router = APIRouter(prefix="/api/v1/organizations", tags=["organizations"])
logger = structlog.get_logger()


class PlanLimitsDict(TypedDict):
    """Type for plan limits dictionary."""

    max_users: int
    max_agents: int
    max_workspaces: int
    max_call_minutes_per_month: int
    max_storage_gb: int
    features_enabled: list[str]


# Plan limits configuration
PLAN_LIMITS: dict[PlanType, PlanLimitsDict] = {
    PlanType.FREE: {
        "max_users": 5,
        "max_agents": 2,
        "max_workspaces": 1,
        "max_call_minutes_per_month": 100,
        "max_storage_gb": 1,
        "features_enabled": ["basic_agents", "basic_telephony"],
    },
    PlanType.STARTER: {
        "max_users": 10,
        "max_agents": 5,
        "max_workspaces": 3,
        "max_call_minutes_per_month": 500,
        "max_storage_gb": 5,
        "features_enabled": [
            "basic_agents",
            "basic_telephony",
            "crm_integration",
            "call_recording",
        ],
    },
    PlanType.PROFESSIONAL: {
        "max_users": 25,
        "max_agents": 15,
        "max_workspaces": 10,
        "max_call_minutes_per_month": 2000,
        "max_storage_gb": 25,
        "features_enabled": [
            "basic_agents",
            "basic_telephony",
            "crm_integration",
            "call_recording",
            "advanced_analytics",
            "custom_voices",
            "api_access",
        ],
    },
    PlanType.ENTERPRISE: {
        "max_users": 100,
        "max_agents": 50,
        "max_workspaces": 50,
        "max_call_minutes_per_month": 10000,
        "max_storage_gb": 100,
        "features_enabled": [
            "basic_agents",
            "basic_telephony",
            "crm_integration",
            "call_recording",
            "advanced_analytics",
            "custom_voices",
            "api_access",
            "sso",
            "dedicated_support",
            "custom_integrations",
        ],
    },
}


class PlanInfo(BaseModel):
    """Plan information."""

    plan_type: str
    max_users: int
    max_agents: int
    max_workspaces: int
    max_call_minutes_per_month: int
    max_storage_gb: int
    features_enabled: list[str]


class OrganizationResponse(BaseModel):
    """Organization response."""

    id: str
    name: str
    slug: str
    plan_type: str
    subscription_status: str
    trial_ends_at: datetime | None
    max_users: int
    max_agents: int
    max_workspaces: int
    max_call_minutes_per_month: int
    max_storage_gb: int
    current_users_count: int
    current_agents_count: int
    current_workspaces_count: int
    current_month_call_minutes: int
    current_month_storage_gb: float
    features_enabled: list[str]

    model_config = {"from_attributes": True}


class ChangePlanRequest(BaseModel):
    """Request to change organization plan."""

    plan_type: str


class ChangePlanResponse(BaseModel):
    """Response after changing plan."""

    message: str
    new_plan: str
    limits: PlanInfo


@router.get("/me", response_model=OrganizationResponse)
async def get_current_organization(
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> OrganizationResponse:
    """Get the current user's organization.

    Args:
        current_user: Authenticated user
        db: Database session

    Returns:
        Organization details

    Raises:
        HTTPException: 404 if organization not found
    """
    if not current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User is not part of any organization",
        )

    org = await db.scalar(
        select(Organization).where(Organization.id == current_user.organization_id)
    )

    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    return OrganizationResponse(
        id=str(org.id),
        name=org.name,
        slug=org.slug,
        plan_type=org.plan_type.value if isinstance(org.plan_type, PlanType) else org.plan_type,
        subscription_status=(
            org.subscription_status.value
            if isinstance(org.subscription_status, SubscriptionStatus)
            else org.subscription_status
        ),
        trial_ends_at=org.trial_ends_at,
        max_users=org.max_users,
        max_agents=org.max_agents,
        max_workspaces=org.max_workspaces,
        max_call_minutes_per_month=org.max_call_minutes_per_month,
        max_storage_gb=org.max_storage_gb,
        current_users_count=org.current_users_count,
        current_agents_count=org.current_agents_count,
        current_workspaces_count=org.current_workspaces_count,
        current_month_call_minutes=org.current_month_call_minutes,
        current_month_storage_gb=org.current_month_storage_gb,
        features_enabled=org.features_enabled or [],
    )


@router.get("/plans", response_model=list[PlanInfo])
async def get_available_plans() -> list[PlanInfo]:
    """Get all available plans with their limits.

    Returns:
        List of available plans
    """
    return [
        PlanInfo(
            plan_type=plan_type.value,
            **limits,
        )
        for plan_type, limits in PLAN_LIMITS.items()
    ]


@router.post("/change-plan", response_model=ChangePlanResponse)
async def change_organization_plan(
    request: ChangePlanRequest,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> ChangePlanResponse:
    """Change the organization's plan.

    Only admins can change plans. Super admins can change to any plan.
    Regular admins cannot downgrade if it would exceed limits.

    Args:
        request: Plan change request
        admin: Authenticated admin user
        db: Database session

    Returns:
        Success response with new plan details

    Raises:
        HTTPException: 400 for invalid plan
        HTTPException: 403 if not allowed
        HTTPException: 404 if organization not found
    """
    log = logger.bind(admin_id=admin.id, new_plan=request.plan_type)

    # Validate plan type
    try:
        new_plan = PlanType(request.plan_type)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid plan type. Must be one of: {', '.join(p.value for p in PlanType)}",
        ) from e

    # Get organization
    if not admin.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User is not part of any organization",
        )

    org = await db.scalar(select(Organization).where(Organization.id == admin.organization_id))

    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    # Get new plan limits
    new_limits = PLAN_LIMITS[new_plan]

    # Check if downgrade would exceed limits (unless super admin)
    if admin.role != UserRole.SUPER_ADMIN:
        if org.current_users_count > new_limits["max_users"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot downgrade: current users ({org.current_users_count}) exceeds new limit ({new_limits['max_users']})",
            )
        if org.current_agents_count > new_limits["max_agents"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot downgrade: current agents ({org.current_agents_count}) exceeds new limit ({new_limits['max_agents']})",
            )
        if org.current_workspaces_count > new_limits["max_workspaces"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot downgrade: current workspaces ({org.current_workspaces_count}) exceeds new limit ({new_limits['max_workspaces']})",
            )

    # Update organization plan
    org.plan_type = new_plan
    org.max_users = new_limits["max_users"]
    org.max_agents = new_limits["max_agents"]
    org.max_workspaces = new_limits["max_workspaces"]
    org.max_call_minutes_per_month = new_limits["max_call_minutes_per_month"]
    org.max_storage_gb = new_limits["max_storage_gb"]
    org.features_enabled = new_limits["features_enabled"]

    # If changing from trial to any paid plan, update subscription status
    if org.subscription_status == SubscriptionStatus.TRIAL and new_plan != PlanType.FREE:
        org.subscription_status = SubscriptionStatus.ACTIVE
        org.subscription_started_at = datetime.now(UTC)

    await db.commit()
    await db.refresh(org)

    log.info("organization_plan_changed", organization_id=str(org.id), old_plan=org.plan_type)

    return ChangePlanResponse(
        message=f"Successfully changed to {new_plan.value} plan",
        new_plan=new_plan.value,
        limits=PlanInfo(plan_type=new_plan.value, **new_limits),
    )
