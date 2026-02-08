"""First-run setup API endpoints.

This module provides endpoints for initial platform setup:
- Check if setup is required (no users exist)
- Create initial super admin
"""

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_password_hash
from app.db.session import get_db
from app.models.user import User, UserRole

router = APIRouter(prefix="/api/v1/setup", tags=["setup"])
logger = structlog.get_logger()


class SetupStatusResponse(BaseModel):
    """Response indicating setup status."""

    setup_required: bool
    has_users: bool


class InitialAdminRequest(BaseModel):
    """Request to create initial super admin."""

    email: EmailStr = Field(..., description="Admin email address")
    password: str = Field(..., min_length=8, description="Admin password (min 8 chars)")
    full_name: str = Field(..., min_length=1, max_length=100, description="Admin full name")


class InitialAdminResponse(BaseModel):
    """Response after creating initial admin."""

    message: str
    email: str


@router.get("/status", response_model=SetupStatusResponse)
async def get_setup_status(
    db: AsyncSession = Depends(get_db),
) -> SetupStatusResponse:
    """Check if initial setup is required.

    Returns whether the platform needs initial setup (no users exist).
    This endpoint is public and does not require authentication.

    Returns:
        SetupStatusResponse with setup_required flag
    """
    # Count users in the database
    user_count = await db.scalar(select(func.count()).select_from(User)) or 0

    return SetupStatusResponse(
        setup_required=user_count == 0,
        has_users=user_count > 0,
    )


@router.post("/initial-admin", response_model=InitialAdminResponse)
async def create_initial_admin(
    request: InitialAdminRequest,
    db: AsyncSession = Depends(get_db),
) -> InitialAdminResponse:
    """Create the initial super admin account.

    This endpoint can only be used when no users exist in the system.
    After the first admin is created, this endpoint will return 403.

    Args:
        request: Admin account details
        db: Database session

    Returns:
        InitialAdminResponse on success

    Raises:
        HTTPException: 403 if users already exist
        HTTPException: 409 if email already taken
    """
    log = logger.bind(email=request.email)

    # Check if any users exist
    user_count = await db.scalar(select(func.count()).select_from(User)) or 0

    if user_count > 0:
        log.warning("initial_admin_rejected_users_exist")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Initial setup has already been completed. Cannot create another initial admin.",
        )

    # Check if email is already taken (shouldn't happen if no users, but be safe)
    existing_user = await db.scalar(select(User).where(User.email == request.email))
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    # Create the super admin user
    hashed_password = get_password_hash(request.password)
    user = User(
        email=request.email,
        full_name=request.full_name,
        hashed_password=hashed_password,
        role=UserRole.SUPER_ADMIN,
        email_verified=True,  # Initial admin is auto-verified
        is_active=True,
    )

    db.add(user)
    await db.commit()

    log.info("initial_admin_created", user_id=user.id)

    return InitialAdminResponse(
        message="Initial super admin account created successfully. You can now log in.",
        email=request.email,
    )
