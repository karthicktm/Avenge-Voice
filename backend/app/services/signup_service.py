"""Enhanced signup service with automatic organization and workspace creation."""

import re
import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization, PlanType, SubscriptionStatus
from app.models.user import User, UserRole
from app.models.workspace import Workspace
from app.models.workspace_member import WorkspaceMember, WorkspaceRole

logger = structlog.get_logger()


def generate_slug(name: str) -> str:
    """Generate a URL-friendly slug from a name.

    Args:
        name: Organization or workspace name

    Returns:
        URL-friendly slug
    """
    # Convert to lowercase and replace spaces/special chars with hyphens
    slug = re.sub(r"[^\w\s-]", "", name.lower())
    slug = re.sub(r"[-\s]+", "-", slug)
    return slug.strip("-")


# Plan limits configuration
PLAN_LIMITS = {
    "free": {
        "max_users": 5,
        "max_agents": 1,
        "max_workspaces": 1,
        "max_call_minutes_per_month": 10,
        "max_storage_gb": 1,
        "features_enabled": ["basic_agents"],
    },
    "starter": {
        "max_users": 10,
        "max_agents": 5,
        "max_workspaces": 3,
        "max_call_minutes_per_month": 500,
        "max_storage_gb": 10,
        "features_enabled": ["basic_agents", "basic_telephony", "email_support"],
    },
    "professional": {
        "max_users": 50,
        "max_agents": 20,
        "max_workspaces": 10,
        "max_call_minutes_per_month": 2000,
        "max_storage_gb": 50,
        "features_enabled": [
            "basic_agents",
            "advanced_agents",
            "basic_telephony",
            "advanced_telephony",
            "priority_support",
            "analytics",
        ],
    },
    "enterprise": {
        "max_users": 9999,
        "max_agents": 9999,
        "max_workspaces": 9999,
        "max_call_minutes_per_month": 999999,
        "max_storage_gb": 1000,
        "features_enabled": [
            "basic_agents",
            "advanced_agents",
            "basic_telephony",
            "advanced_telephony",
            "priority_support",
            "analytics",
            "custom_integrations",
            "sla_guarantee",
            "dedicated_support",
        ],
    },
}


async def create_user_with_organization(
    db: AsyncSession,
    email: str,
    full_name: str,
    hashed_password: str,
    organization_name: str | None = None,
    plan_type: str = "free",
) -> User:
    """Create a new user with automatic organization and workspace setup.

    This function creates:
    1. User account (as organization owner)
    2. Organization (with user as owner)
    3. Default workspace
    4. Workspace membership (user as admin)

    Args:
        db: Database session
        email: User email
        full_name: User's full name
        hashed_password: Pre-hashed password
        organization_name: Optional organization name (defaults to "{full_name}'s Organization")
        plan_type: Subscription plan type (free, starter, professional, enterprise)

    Returns:
        Created user with organization and workspace
    """
    log = logger.bind(email=email, full_name=full_name)

    # Determine organization name
    org_name = organization_name or f"{full_name}'s Organization"
    org_slug = generate_slug(org_name)

    # Check if slug already exists, append number if needed
    base_slug = org_slug
    counter = 1
    while True:
        result = await db.execute(select(Organization).where(Organization.slug == org_slug))
        if not result.scalar_one_or_none():
            break
        org_slug = f"{base_slug}-{counter}"
        counter += 1

    log.info("creating_user_with_organization", org_name=org_name, org_slug=org_slug)

    # Create user first (without organization)
    user = User(
        email=email,
        full_name=full_name,
        hashed_password=hashed_password,
        role=UserRole.ADMIN,  # User becomes organization admin
        email_verified=False,  # Will need to verify email
        is_active=True,
    )
    db.add(user)
    await db.flush()  # Get user ID without committing

    # Get plan limits
    plan_key = plan_type.lower() if plan_type else "free"
    if plan_key not in PLAN_LIMITS:
        plan_key = "free"
    limits = PLAN_LIMITS[plan_key]

    # Map plan_type string to PlanType enum
    plan_type_enum = {
        "free": PlanType.FREE,
        "starter": PlanType.STARTER,
        "professional": PlanType.PROFESSIONAL,
        "enterprise": PlanType.ENTERPRISE,
    }.get(plan_key, PlanType.FREE)

    # Create organization
    organization = Organization(
        id=uuid.uuid4(),
        name=org_name,
        slug=org_slug,
        owner_id=user.id,
        plan_type=plan_type_enum,
        subscription_status=SubscriptionStatus.TRIAL if plan_key != "free" else SubscriptionStatus.ACTIVE,
        trial_ends_at=datetime.now(UTC) + timedelta(days=14) if plan_key != "free" else None,
        max_users=limits["max_users"],
        max_agents=limits["max_agents"],
        max_workspaces=limits["max_workspaces"],
        max_call_minutes_per_month=limits["max_call_minutes_per_month"],
        max_storage_gb=limits["max_storage_gb"],
        current_users_count=1,  # The owner
        current_agents_count=0,
        current_workspaces_count=1,  # Default workspace
        features_enabled=limits["features_enabled"],
    )
    db.add(organization)
    await db.flush()  # Get organization ID

    # Update user with organization
    user.organization_id = organization.id

    # Create default workspace
    workspace = Workspace(
        id=uuid.uuid4(),
        user_id=user.id,  # Legacy field
        organization_id=organization.id,
        name=f"{full_name}'s Workspace",
        description="Your default workspace",
        is_default=True,
    )
    db.add(workspace)
    await db.flush()

    # Add user as workspace admin
    workspace_member = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=user.id,
        role=WorkspaceRole.ADMIN,
        invited_by=user.id,  # Self-invited
    )
    db.add(workspace_member)

    # Commit all changes
    await db.commit()
    await db.refresh(user)
    await db.refresh(organization)
    await db.refresh(workspace)

    log.info(
        "user_created_with_organization",
        user_id=user.id,
        organization_id=str(organization.id),
        workspace_id=str(workspace.id),
        org_slug=org_slug,
    )

    return user
