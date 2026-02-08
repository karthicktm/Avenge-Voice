"""Email verification service for handling verification codes."""

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

logger = structlog.get_logger()


def generate_verification_code() -> str:
    """Generate a 6-digit verification code.

    Returns:
        6-digit numeric code as string
    """
    # Generate a secure random 6-digit code
    code = secrets.randbelow(1000000)
    return f"{code:06d}"


def hash_verification_code(code: str) -> str:
    """Hash a verification code using HMAC-SHA256.

    Uses HMAC-SHA256 which is fast enough for 6-digit codes while being secure.
    This prevents exposure of verification codes if the database is compromised.

    Args:
        code: Plain text verification code

    Returns:
        Hashed verification code
    """
    return hmac.new(
        settings.SECRET_KEY.encode(),
        code.encode(),
        hashlib.sha256,
    ).hexdigest()


def verify_code(stored_hash: str, provided_code: str) -> bool:
    """Verify a verification code against its stored hash.

    Uses constant-time comparison to prevent timing attacks.

    Args:
        stored_hash: The hashed code stored in the database
        provided_code: The plain text code provided by the user

    Returns:
        True if codes match, False otherwise
    """
    provided_hash = hash_verification_code(provided_code)
    return secrets.compare_digest(stored_hash, provided_hash)


def verify_code_timing_safe(stored_code: str, provided_code: str) -> bool:
    """Verify code with timing attack protection.

    DEPRECATED: Use verify_code() instead which handles hashed codes.
    This function is kept for backward compatibility during migration.

    Uses constant-time comparison to prevent timing attacks.

    Args:
        stored_code: The code stored in the database (may be hashed or plain)
        provided_code: The code provided by the user

    Returns:
        True if codes match, False otherwise
    """
    # Check if stored_code looks like a hash (64 hex chars for SHA-256)
    if len(stored_code) == 64 and all(c in "0123456789abcdef" for c in stored_code):
        return verify_code(stored_code, provided_code)

    # Legacy plain text comparison (for migration period)
    return secrets.compare_digest(stored_code, provided_code)


async def can_request_verification_code(
    db: AsyncSession,
    user_id: int,
    last_sent_at: datetime | None,
) -> tuple[bool, int]:
    """Check if user can request a new verification code (rate limiting).

    Args:
        db: Database session
        user_id: User ID
        last_sent_at: When the last code was sent

    Returns:
        Tuple of (can_request, seconds_until_next_request)
    """
    if last_sent_at is None:
        return True, 0

    # Allow 1 code per minute
    now = datetime.now(UTC)
    time_since_last = now - last_sent_at.replace(tzinfo=UTC)
    cooldown_seconds = 60

    if time_since_last.total_seconds() >= cooldown_seconds:
        return True, 0

    seconds_remaining = int(cooldown_seconds - time_since_last.total_seconds())
    return False, seconds_remaining


def is_code_expired(created_at: datetime, expiry_minutes: int = 10) -> bool:
    """Check if verification code has expired.

    Args:
        created_at: When the code was created
        expiry_minutes: Expiry time in minutes (default: 10)

    Returns:
        True if code is expired, False otherwise
    """
    now = datetime.now(UTC)
    expiry_time = created_at.replace(tzinfo=UTC) + timedelta(minutes=expiry_minutes)
    return now > expiry_time
