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


async def create_user_with_organization(
    db: AsyncSession,
    email: str,
    full_name: str,
    hashed_password: str,
    organization_name: str | None = None,
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

    # Create organization
    organization = Organization(
        id=uuid.uuid4(),
        name=org_name,
        slug=org_slug,
        owner_id=user.id,
        plan_type=PlanType.FREE,
        subscription_status=SubscriptionStatus.TRIAL,
        trial_ends_at=datetime.now(UTC) + timedelta(days=14),  # 14-day trial
        max_users=5,  # Free plan limits
        max_agents=2,
        max_workspaces=1,
        max_call_minutes_per_month=100,
        max_storage_gb=1,
        current_users_count=1,  # The owner
        current_agents_count=0,
        current_workspaces_count=1,  # Default workspace
        features_enabled=["basic_agents", "basic_telephony"],
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
