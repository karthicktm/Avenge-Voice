"""Password reset API endpoints.

Provides secure password reset functionality:
- Request reset code (sends email)
- Reset password with code
"""

from datetime import UTC, datetime, timedelta

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_password_hash
from app.core.limiter import limiter
from app.db.session import get_db
from app.models.user import User
from app.services import email_service, email_verification_service

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
logger = structlog.get_logger()

# Constants
RESET_CODE_EXPIRY_MINUTES = 10
MIN_PASSWORD_LENGTH = 8


class ForgotPasswordRequest(BaseModel):
    """Request to initiate password reset."""

    email: EmailStr = Field(..., description="Email address for password reset")


class ForgotPasswordResponse(BaseModel):
    """Response for forgot password request."""

    message: str


class ResetPasswordRequest(BaseModel):
    """Request to reset password with code."""

    email: EmailStr = Field(..., description="Email address")
    code: str = Field(..., min_length=6, max_length=6, description="6-digit reset code")
    new_password: str = Field(..., min_length=MIN_PASSWORD_LENGTH, description="New password")


class ResetPasswordResponse(BaseModel):
    """Response for password reset."""

    message: str


@router.post("/forgot-password", response_model=ForgotPasswordResponse)
@limiter.limit("3/minute")
async def forgot_password(
    request: Request,
    body: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> ForgotPasswordResponse:
    """Request a password reset code.

    Always returns success to prevent email enumeration attacks.
    If email exists, sends a reset code.

    Args:
        request: FastAPI request (for rate limiting)
        body: Request with email
        db: Database session

    Returns:
        Success message (always, regardless of email existence)
    """
    log = logger.bind(email=body.email)
    log.info("password_reset_requested")

    # Always return success message to prevent email enumeration
    success_message = "If an account exists with this email, a reset code has been sent."

    # Look up user
    user = await db.scalar(select(User).where(User.email == body.email))

    if not user:
        log.info("password_reset_email_not_found")
        return ForgotPasswordResponse(message=success_message)

    if not user.is_active:
        log.info("password_reset_user_inactive")
        return ForgotPasswordResponse(message=success_message)

    # Check rate limiting on OTP sends
    if not user.can_request_otp():
        log.warning("password_reset_rate_limited")
        return ForgotPasswordResponse(message=success_message)

    # Generate reset code
    code = email_verification_service.generate_verification_code()
    hashed_code = email_verification_service.hash_verification_code(code)

    # Store code in user record (reusing OTP fields)
    user.otp_secret = hashed_code
    user.otp_expires_at = datetime.now(UTC) + timedelta(minutes=RESET_CODE_EXPIRY_MINUTES)
    user.last_otp_sent_at = datetime.now(UTC)

    await db.commit()

    # Send email with reset code
    try:
        await email_service.send_password_reset_email(
            to_email=user.email,
            code=code,
            expiry_minutes=RESET_CODE_EXPIRY_MINUTES,
        )
        log.info("password_reset_email_sent")
    except Exception:
        log.exception("password_reset_email_failed")
        # Still return success to not reveal email existence

    return ForgotPasswordResponse(message=success_message)


@router.post("/reset-password", response_model=ResetPasswordResponse)
@limiter.limit("5/minute")
async def reset_password(
    request: Request,
    body: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> ResetPasswordResponse:
    """Reset password using the code from email.

    Args:
        request: FastAPI request (for rate limiting)
        body: Request with email, code, and new password
        db: Database session

    Returns:
        Success message

    Raises:
        HTTPException: 400 for invalid/expired code
    """
    log = logger.bind(email=body.email)
    log.info("password_reset_attempt")

    # Look up user
    user = await db.scalar(select(User).where(User.email == body.email))

    if not user:
        log.warning("password_reset_user_not_found")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset code",
        )

    # Check if code exists and hasn't expired
    if not user.otp_secret or not user.otp_expires_at:
        log.warning("password_reset_no_code")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset code",
        )

    if datetime.now(UTC) > user.otp_expires_at:
        log.warning("password_reset_code_expired")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset code has expired. Please request a new one.",
        )

    # Verify the code
    if not email_verification_service.verify_code_timing_safe(user.otp_secret, body.code):
        log.warning("password_reset_invalid_code")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset code",
        )

    # Update password
    user.hashed_password = get_password_hash(body.new_password)

    # Clear the reset code
    user.otp_secret = None
    user.otp_expires_at = None

    # Reset failed login attempts
    user.failed_login_attempts = 0
    user.locked_until = None

    await db.commit()

    log.info("password_reset_successful")

    return ResetPasswordResponse(
        message="Password has been reset successfully. You can now log in."
    )
