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

    # Generate and send verification code
    from app.services import email_service, email_verification_service

    code = email_verification_service.generate_verification_code()
    user.otp_secret = email_verification_service.hash_verification_code(code)
    user.otp_expires_at = datetime.now(UTC) + timedelta(minutes=10)
    user.last_otp_sent_at = datetime.now(UTC)
    await db.commit()

    # Send verification email (best effort - don't fail registration if email fails)
    try:
        html_content = email_service.generate_verification_code_email(code, user.full_name)
        await email_service.send_email(
            db=db,
            to_email=user.email,
            subject="Verify Your Email - Avenge AI",
            html_content=html_content,
        )
        log.info("verification_code_sent_on_registration")
    except Exception as e:
        log.warning("verification_code_send_failed_on_registration", error=str(e))
        # Don't fail registration if email fails

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

    if (
        not user
        or not user.hashed_password
        or not verify_password(form_data.password, user.hashed_password)
    ):
        log.warning("login_failed")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check if email is verified
    if not user.email_verified:
        log.warning("login_attempted_unverified_email")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email not verified. Please check your email for the verification code.",
        )

    # Update last login timestamp
    user.last_login_at = datetime.now(UTC)
    await db.commit()

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


# =============================================================================
# Email Verification Endpoints
# =============================================================================


class SendVerificationCodeRequest(BaseModel):
    """Request to send verification code."""

    email: EmailStr


class VerifyEmailCodeRequest(BaseModel):
    """Request to verify email code."""

    email: EmailStr
    code: str


class VerificationCodeResponse(BaseModel):
    """Response after sending verification code."""

    message: str
    expires_in_minutes: int = 10


@router.post("/send-verification-code", response_model=VerificationCodeResponse)
@limiter.limit("3/minute")  # Strict rate limit
async def send_verification_code(
    request: Request,
    data: SendVerificationCodeRequest,
    db: AsyncSession = Depends(get_db),
) -> VerificationCodeResponse:
    """Send verification code to email.

    Args:
        request: HTTP request (for rate limiter)
        data: Email to send code to
        db: Database session

    Returns:
        Success message with expiry time
    """
    from app.services import email_service, email_verification_service

    log = logger.bind(email=data.email)
    log.info("send_verification_code_requested")

    # Find user by email
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # Check if already verified
    if user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already verified",
        )

    # Check rate limiting
    can_request, seconds_remaining = await email_verification_service.can_request_verification_code(
        db, user.id, user.last_otp_sent_at
    )

    if not can_request:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Please wait {seconds_remaining} seconds before requesting a new code",
        )

    # Generate verification code
    code = email_verification_service.generate_verification_code()

    # Update user with hashed code (HMAC-SHA256)
    user.otp_secret = email_verification_service.hash_verification_code(code)
    user.otp_expires_at = datetime.now(UTC) + timedelta(minutes=10)
    user.last_otp_sent_at = datetime.now(UTC)
    await db.commit()

    # Send email
    try:
        html_content = email_service.generate_verification_code_email(code, user.full_name)
        await email_service.send_email(
            db=db,
            to_email=user.email,
            subject="Your Verification Code - Avenge AI",
            html_content=html_content,
        )
        log.info("verification_code_sent")
    except email_service.ResendNotConfiguredError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Email service not configured. Please contact support.",
        ) from None
    except Exception as e:
        log.exception("verification_code_send_failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send verification code",
        ) from e

    return VerificationCodeResponse(
        message="Verification code sent to your email",
        expires_in_minutes=10,
    )


@router.post("/verify-email-code", response_model=TokenResponse)
@limiter.limit("5/minute")  # Allow some retries for typos
async def verify_email_code(
    request: Request,
    data: VerifyEmailCodeRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Verify email with code and activate account.

    Args:
        request: HTTP request (for rate limiter)
        data: Email and verification code
        db: Database session

    Returns:
        Access token for immediate login
    """
    from app.services import email_verification_service

    log = logger.bind(email=data.email)
    log.info("verify_email_code_requested")

    # Find user by email
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # Check if already verified
    if user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already verified",
        )

    # Check if code exists
    if not user.otp_secret or not user.otp_expires_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No verification code found. Please request a new one.",
        )

    # Check if code is expired
    if email_verification_service.is_code_expired(user.otp_expires_at):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification code expired. Please request a new one.",
        )

    # Verify code (timing-safe comparison)
    if not email_verification_service.verify_code_timing_safe(user.otp_secret, data.code):
        log.warning("invalid_verification_code")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification code",
        )

    # Activate account
    user.email_verified = True
    user.otp_secret = None  # Clear the code
    user.otp_expires_at = None
    await db.commit()

    log.info("email_verified", user_id=user.id)

    # Create access token for immediate login
    access_token = create_access_token(user.id)

    return TokenResponse(access_token=access_token)


# =============================================================================
# Logout Endpoints
# =============================================================================


class LogoutResponse(BaseModel):
    """Response after logout."""

    message: str


@router.post("/logout", response_model=LogoutResponse)
async def logout(
    current_user: CurrentUser,
) -> LogoutResponse:
    """Logout the current session.

    Note: With stateless JWT tokens, this is primarily a signal to the client
    to clear the token. The token remains valid until expiration.

    For true session invalidation, use /logout-all which revokes all sessions
    stored in Redis.

    Args:
        current_user: Authenticated user

    Returns:
        Logout success message
    """
    logger.info("user_logged_out", user_id=current_user.id)
    return LogoutResponse(message="Successfully logged out")


class LogoutAllResponse(BaseModel):
    """Response after logging out all devices."""

    message: str
    sessions_revoked: int


@router.post("/logout-all", response_model=LogoutAllResponse)
async def logout_all(
    current_user: CurrentUser,
) -> LogoutAllResponse:
    """Logout from all devices by revoking all sessions.

    This revokes all active sessions for the user in Redis,
    effectively logging them out of all devices.

    Args:
        current_user: Authenticated user

    Returns:
        Logout success message with count of revoked sessions
    """
    from app.services import session_service

    log = logger.bind(user_id=current_user.id)
    log.info("logout_all_requested")

    # Revoke all sessions
    revoked_count = await session_service.revoke_all_sessions(current_user.id)

    log.info("logout_all_completed", sessions_revoked=revoked_count)
    return LogoutAllResponse(
        message="Successfully logged out of all devices",
        sessions_revoked=revoked_count,
    )
