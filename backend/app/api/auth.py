"""Authentication API routes."""

from datetime import UTC, datetime, timedelta

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from jose import jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser
from app.core.config import settings
from app.core.limiter import limiter
from app.db.session import get_db
from app.models.user import User

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
logger = structlog.get_logger()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# =============================================================================
# Pydantic Models
# =============================================================================


class RegisterRequest(BaseModel):
    """User registration request."""

    email: EmailStr
    username: str  # Will be used as full_name
    password: str
    organization_name: str | None = None  # Optional: defaults to "{username}'s Organization"


class TokenResponse(BaseModel):
    """Token response."""

    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    """User response."""

    id: int
    email: str
    username: str | None = None  # Maps to full_name (legacy)
    full_name: str | None = None
    role: str = "user"
    organization_id: str | None = None
    email_verified: bool = False
    is_active: bool = True
    created_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_user(cls, user: "User") -> "UserResponse":
        """Create response from User model."""
        return cls(
            id=user.id,
            email=user.email,
            username=user.full_name,  # Legacy field
            full_name=user.full_name,
            role=user.role,
            organization_id=str(user.organization_id) if user.organization_id else None,
            email_verified=user.email_verified,
            is_active=user.is_active,
            created_at=user.created_at,
        )


# =============================================================================
# Helper Functions
# =============================================================================


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hash a password."""
    return pwd_context.hash(password)


def create_access_token(subject: str | int, expires_delta: timedelta | None = None) -> str:
    """Create a JWT access token.

    Args:
        subject: The subject of the token (user ID or email)
        expires_delta: Optional custom expiration time. Defaults to ACCESS_TOKEN_EXPIRE_MINUTES.

    Returns:
        Encoded JWT token string
    """
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode = {"sub": str(subject), "exp": expire}
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


# =============================================================================
# Auth Endpoints
# =============================================================================


@router.post("/register", response_model=UserResponse)
@limiter.limit("5/minute")  # Strict rate limit to prevent account spam
async def register(
    request: Request,  # Required for rate limiter - must be first
    data: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Register a new user with automatic organization and workspace creation.

    Creates:
    - User account (as organization owner)
    - Organization (with user as owner)
    - Default workspace
    - Workspace membership (user as admin)

    Args:
        request: HTTP request (for rate limiter)
        data: Registration request with email, username, password, organization_name
        db: Database session

    Returns:
        Created user with organization details
    """
    from app.services.signup_service import create_user_with_organization
    
    log = logger.bind(email=data.email, username=data.username)
    log.info("registering_user")

    # Check if email already exists
    result = await db.execute(select(User).where(User.email == data.email))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    # Create user with organization and workspace
    user = await create_user_with_organization(
        db=db,
        email=data.email,
        full_name=data.username,
        hashed_password=get_password_hash(data.password),
        organization_name=data.organization_name,
    )

    log.info("user_registered", user_id=user.id, organization_id=str(user.organization_id))
    return UserResponse.from_user(user)



@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")  # Strict rate limit to prevent brute force attacks
async def login(
    request: Request,  # Required for rate limiter
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Login and get an access token.

    Args:
        form_data: OAuth2 form with username (email) and password
        db: Database session

    Returns:
        Access token
    """
    log = logger.bind(username=form_data.username)
    log.info("login_attempt")

    # Find user by email
    result = await db.execute(select(User).where(User.email == form_data.username))
    user = result.scalar_one_or_none()

    if not user or not verify_password(form_data.password, user.hashed_password):
        log.warning("login_failed")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(user.id)
    log.info("login_success", user_id=user.id)

    return TokenResponse(access_token=access_token)


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: CurrentUser) -> UserResponse:
    """Get current user information.

    Args:
        current_user: Authenticated user

    Returns:
        User information
    """
    return UserResponse.from_user(current_user)
