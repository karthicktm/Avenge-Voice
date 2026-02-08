"""User management API endpoints.

Admin-only endpoints for managing users within an organization:
- Create users
- List users
- Get user details
- Update users
- Delete users
- Change user roles
"""

from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_password_hash
from app.core.auth import AdminUser
from app.core.permissions import can_delete_user, can_manage_role
from app.db.session import get_db
from app.models.organization import Organization
from app.models.user import User, UserRole

router = APIRouter(prefix="/api/v1/users", tags=["users"])
logger = structlog.get_logger()


# =============================================================================
# Pydantic Models
# =============================================================================


class UserResponse(BaseModel):
    """User response schema (safe for API)."""

    id: int
    email: str
    full_name: str | None
    role: str
    organization_id: str | None
    email_verified: bool
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None

    model_config = {"from_attributes": True}


class UserListResponse(BaseModel):
    """Paginated list of users."""

    users: list[UserResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class CreateUserRequest(BaseModel):
    """Request to create a new user."""

    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., min_length=8, description="User password (min 8 chars)")
    full_name: str = Field(..., min_length=1, max_length=100, description="User full name")
    role: str = Field(default="user", description="User role: admin or user")


class UpdateUserRequest(BaseModel):
    """Request to update a user."""

    full_name: str | None = Field(None, min_length=1, max_length=100)
    is_active: bool | None = None


class ChangeRoleRequest(BaseModel):
    """Request to change a user's role."""

    role: str = Field(..., description="New role: admin or user")


# =============================================================================
# Helper Functions
# =============================================================================


def user_to_response(user: User) -> UserResponse:
    """Convert User model to response schema."""
    return UserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role.value if isinstance(user.role, UserRole) else user.role,
        organization_id=str(user.organization_id) if user.organization_id else None,
        email_verified=user.email_verified,
        is_active=user.is_active,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )


# =============================================================================
# User CRUD Endpoints
# =============================================================================


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    request: CreateUserRequest,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Create a new user in the organization.

    Only admins can create users. New users are created within the admin's organization.

    Args:
        request: User creation data
        admin: Authenticated admin user
        db: Database session

    Returns:
        Created user

    Raises:
        HTTPException: 400 for invalid role
        HTTPException: 409 if email already exists
    """
    log = logger.bind(admin_id=admin.id, new_user_email=request.email)

    # Validate role
    try:
        new_role = UserRole(request.role)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role. Must be one of: {', '.join(r.value for r in UserRole)}",
        ) from e

    # Cannot create super_admin via API
    if new_role == UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot create super admin users via API",
        )

    # Check if email already exists
    existing = await db.scalar(select(User).where(User.email == request.email))
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    # Create user
    hashed_password = get_password_hash(request.password)
    user = User(
        email=request.email,
        full_name=request.full_name,
        hashed_password=hashed_password,
        role=new_role,
        organization_id=admin.organization_id,
        email_verified=False,
        is_active=True,
    )

    db.add(user)
    await db.commit()
    await db.refresh(user)

    log.info("user_created", new_user_id=user.id)

    return user_to_response(user)


@router.get("", response_model=UserListResponse)
async def list_users(
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, description="Search by email or name"),
    role: str | None = Query(default=None, description="Filter by role"),
    is_active: bool | None = Query(default=None, description="Filter by active status"),
) -> UserListResponse:
    """List users in the organization.

    Args:
        admin: Authenticated admin user
        db: Database session
        page: Page number
        page_size: Items per page
        search: Optional search term
        role: Optional role filter
        is_active: Optional active status filter

    Returns:
        Paginated list of users
    """
    log = logger.bind(admin_id=admin.id)

    # Build base query - filter by organization for non-super-admins
    query = select(User)
    count_query = select(func.count()).select_from(User)

    if admin.role != UserRole.SUPER_ADMIN:
        query = query.where(User.organization_id == admin.organization_id)
        count_query = count_query.where(User.organization_id == admin.organization_id)

    # Apply filters
    if search:
        search_pattern = f"%{search}%"
        query = query.where(
            (User.email.ilike(search_pattern)) | (User.full_name.ilike(search_pattern))
        )
        count_query = count_query.where(
            (User.email.ilike(search_pattern)) | (User.full_name.ilike(search_pattern))
        )

    if role:
        query = query.where(User.role == role)
        count_query = count_query.where(User.role == role)

    if is_active is not None:
        query = query.where(User.is_active == is_active)
        count_query = count_query.where(User.is_active == is_active)

    # Get total count
    total = await db.scalar(count_query) or 0

    # Apply pagination
    offset = (page - 1) * page_size
    query = query.order_by(User.created_at.desc()).offset(offset).limit(page_size)

    result = await db.execute(query)
    users = result.scalars().all()

    total_pages = (total + page_size - 1) // page_size

    log.info("users_listed", count=len(users), total=total)

    return UserListResponse(
        users=[user_to_response(u) for u in users],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: int,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Get a specific user's details.

    Args:
        user_id: User ID to retrieve
        admin: Authenticated admin user
        db: Database session

    Returns:
        User details

    Raises:
        HTTPException: 404 if user not found
    """
    query = select(User).where(User.id == user_id)

    # Non-super-admins can only view users in their organization
    if admin.role != UserRole.SUPER_ADMIN:
        query = query.where(User.organization_id == admin.organization_id)

    user = await db.scalar(query)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    return user_to_response(user)


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    request: UpdateUserRequest,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Update a user's details.

    Args:
        user_id: User ID to update
        request: Update data
        admin: Authenticated admin user
        db: Database session

    Returns:
        Updated user

    Raises:
        HTTPException: 404 if user not found
    """
    log = logger.bind(admin_id=admin.id, target_user_id=user_id)

    query = select(User).where(User.id == user_id)

    if admin.role != UserRole.SUPER_ADMIN:
        query = query.where(User.organization_id == admin.organization_id)

    user = await db.scalar(query)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # Apply updates
    if request.full_name is not None:
        user.full_name = request.full_name

    if request.is_active is not None:
        # Cannot deactivate yourself
        if user.id == admin.id and not request.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot deactivate your own account",
            )
        user.is_active = request.is_active

    await db.commit()
    await db.refresh(user)

    log.info("user_updated")

    return user_to_response(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a user.

    Cannot delete:
    - Yourself
    - Super admins (unless you are a super admin)

    Args:
        user_id: User ID to delete
        admin: Authenticated admin user
        db: Database session

    Raises:
        HTTPException: 400 if trying to delete self
        HTTPException: 403 if not allowed to delete target
        HTTPException: 404 if user not found
    """
    log = logger.bind(admin_id=admin.id, target_user_id=user_id)

    # Cannot delete yourself
    if admin.id == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account",
        )

    query = select(User).where(User.id == user_id)

    if admin.role != UserRole.SUPER_ADMIN:
        query = query.where(User.organization_id == admin.organization_id)

    user = await db.scalar(query)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # Check permission
    if not can_delete_user(admin, user):
        log.warning(
            "user_delete_forbidden",
            reason="insufficient_permissions",
            admin_role=admin.role.value if hasattr(admin.role, "value") else str(admin.role),
            target_role=user.role.value if hasattr(user.role, "value") else str(user.role),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot delete this user",
        )

    # Check if user owns any organization
    owned_orgs_result = await db.execute(
        select(Organization).where(Organization.owner_id == user_id)
    )
    owned_orgs = owned_orgs_result.scalars().all()

    if owned_orgs:
        # Super admin can transfer ownership to themselves and delete
        if admin.role == UserRole.SUPER_ADMIN:
            for owned_org in owned_orgs:
                log.info(
                    "organization_ownership_transferred",
                    organization_id=str(owned_org.id),
                    organization_name=owned_org.name,
                    previous_owner_id=user_id,
                    new_owner_id=admin.id,
                )
                owned_org.owner_id = admin.id
            # Commit ownership transfer first to avoid cascade issues
            await db.commit()
        else:
            org_names = ", ".join(org.name for org in owned_orgs)
            log.warning(
                "user_delete_blocked",
                reason="owns_organization",
                organization_names=org_names,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot delete user who owns organization(s): {org_names}. Transfer ownership first.",
            )

    try:
        # Re-fetch user after potential commit to ensure we have a fresh instance
        user = await db.scalar(select(User).where(User.id == user_id))
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )

        await db.delete(user)
        await db.commit()
        log.info(
            "user_deleted_successfully",
            deleted_user_email=user.email,
            deleted_by_admin_id=admin.id,
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error(
            "user_delete_failed",
            error=str(e),
            error_type=type(e).__name__,
        )
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete user. Please try again.",
        ) from e


@router.post("/{user_id}/change-role", response_model=UserResponse)
async def change_user_role(
    user_id: int,
    request: ChangeRoleRequest,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Change a user's role.

    Cannot:
    - Change your own role
    - Promote to super_admin (requires CLI)
    - Demote super_admin (unless you are super_admin)

    Args:
        user_id: User ID to update
        request: New role
        admin: Authenticated admin user
        db: Database session

    Returns:
        Updated user

    Raises:
        HTTPException: 400 for invalid role or self-modification
        HTTPException: 403 if not allowed
        HTTPException: 404 if user not found
    """
    log = logger.bind(admin_id=admin.id, target_user_id=user_id, new_role=request.role)

    # Cannot change your own role
    if admin.id == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot change your own role",
        )

    # Validate role
    try:
        new_role = UserRole(request.role)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role. Must be one of: {', '.join(r.value for r in UserRole)}",
        ) from e

    # Cannot promote to super_admin via API
    if new_role == UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot promote to super admin via API. Use CLI instead.",
        )

    # Check permission
    if not can_manage_role(admin, new_role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to assign this role",
        )

    query = select(User).where(User.id == user_id)

    if admin.role != UserRole.SUPER_ADMIN:
        query = query.where(User.organization_id == admin.organization_id)

    user = await db.scalar(query)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # Cannot demote super_admin unless you're super_admin
    if user.role == UserRole.SUPER_ADMIN and admin.role != UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only super admins can modify super admin accounts",
        )

    user.role = new_role
    await db.commit()
    await db.refresh(user)

    log.info("user_role_changed")

    return user_to_response(user)
