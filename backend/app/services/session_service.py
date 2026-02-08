"""Session management service using Redis.

This service provides JWT token tracking for:
- Session creation and validation
- Session revocation (logout)
- Revoke all sessions (logout everywhere)
- Token blacklisting

Uses Redis for fast session lookups with automatic expiration.
"""

import uuid
from datetime import UTC, datetime

import structlog

from app.core.config import settings
from app.db.redis import get_redis

logger = structlog.get_logger()

# Redis key prefixes
SESSION_PREFIX = "session:"
USER_SESSIONS_PREFIX = "user_sessions:"
BLACKLIST_PREFIX = "token_blacklist:"

# Default session expiry (should match JWT expiry)
SESSION_EXPIRY_SECONDS = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60


def generate_session_id() -> str:
    """Generate a unique session ID (JWT ID / jti claim)."""
    return str(uuid.uuid4())


async def create_session(
    user_id: int,
    token_jti: str,
    user_agent: str | None = None,
    ip_address: str | None = None,
    expires_in: int = SESSION_EXPIRY_SECONDS,
) -> bool:
    """Create a new session for a user.

    Args:
        user_id: User's database ID
        token_jti: JWT ID (jti claim) for this token
        user_agent: Optional browser/client user agent
        ip_address: Optional client IP address
        expires_in: Session expiry in seconds

    Returns:
        True if session was created successfully
    """
    log = logger.bind(user_id=user_id, token_jti=token_jti)

    try:
        redis = await get_redis()

        # Store session data
        session_key = f"{SESSION_PREFIX}{token_jti}"
        session_data = {
            "user_id": str(user_id),
            "created_at": datetime.now(UTC).isoformat(),
            "user_agent": user_agent or "",
            "ip_address": ip_address or "",
        }

        await redis.hset(session_key, mapping=session_data)
        await redis.expire(session_key, expires_in)

        # Add to user's session list
        user_sessions_key = f"{USER_SESSIONS_PREFIX}{user_id}"
        await redis.sadd(user_sessions_key, token_jti)
        await redis.expire(user_sessions_key, expires_in)

        log.info("session_created")
        return True

    except Exception:
        log.exception("session_creation_failed")
        return False


async def is_session_valid(user_id: int, token_jti: str) -> bool:
    """Check if a session is valid (exists and not revoked).

    Args:
        user_id: User's database ID
        token_jti: JWT ID to validate

    Returns:
        True if session is valid
    """
    try:
        redis = await get_redis()

        # Check if token is blacklisted
        blacklist_key = f"{BLACKLIST_PREFIX}{token_jti}"
        if await redis.exists(blacklist_key):
            return False

        # Check if session exists
        session_key = f"{SESSION_PREFIX}{token_jti}"
        session_data = await redis.hgetall(session_key)

        if not session_data:
            return False

        # Verify user_id matches
        stored_user_id = session_data.get("user_id")
        if stored_user_id != str(user_id):
            return False

        return True

    except Exception:
        logger.exception("session_validation_error", user_id=user_id, token_jti=token_jti)
        # Fail open - if Redis is down, allow the request
        # (JWT signature is still validated)
        return True


async def revoke_session(user_id: int, token_jti: str) -> bool:
    """Revoke a specific session (logout single device).

    Args:
        user_id: User's database ID
        token_jti: JWT ID to revoke

    Returns:
        True if session was revoked
    """
    log = logger.bind(user_id=user_id, token_jti=token_jti)

    try:
        redis = await get_redis()

        # Add to blacklist
        blacklist_key = f"{BLACKLIST_PREFIX}{token_jti}"
        await redis.set(blacklist_key, "1", ex=SESSION_EXPIRY_SECONDS)

        # Remove session
        session_key = f"{SESSION_PREFIX}{token_jti}"
        await redis.delete(session_key)

        # Remove from user's session list
        user_sessions_key = f"{USER_SESSIONS_PREFIX}{user_id}"
        await redis.srem(user_sessions_key, token_jti)

        log.info("session_revoked")
        return True

    except Exception:
        log.exception("session_revocation_failed")
        return False


async def revoke_all_sessions(user_id: int, except_jti: str | None = None) -> int:
    """Revoke all sessions for a user (logout everywhere).

    Args:
        user_id: User's database ID
        except_jti: Optional JWT ID to keep active (current session)

    Returns:
        Number of sessions revoked
    """
    log = logger.bind(user_id=user_id)

    try:
        redis = await get_redis()

        # Get all user's sessions
        user_sessions_key = f"{USER_SESSIONS_PREFIX}{user_id}"
        session_ids = await redis.smembers(user_sessions_key)

        if not session_ids:
            return 0

        revoked = 0
        for jti in session_ids:
            if except_jti and jti == except_jti:
                continue

            # Blacklist each session
            blacklist_key = f"{BLACKLIST_PREFIX}{jti}"
            await redis.set(blacklist_key, "1", ex=SESSION_EXPIRY_SECONDS)

            # Delete session
            session_key = f"{SESSION_PREFIX}{jti}"
            await redis.delete(session_key)

            revoked += 1

        # Clear user's session list (or leave only current)
        if except_jti:
            await redis.delete(user_sessions_key)
            await redis.sadd(user_sessions_key, except_jti)
            await redis.expire(user_sessions_key, SESSION_EXPIRY_SECONDS)
        else:
            await redis.delete(user_sessions_key)

        log.info("all_sessions_revoked", count=revoked)
        return revoked

    except Exception:
        log.exception("revoke_all_sessions_failed")
        return 0


async def get_user_sessions(user_id: int) -> list[dict[str, str | None]]:
    """Get all active sessions for a user.

    Args:
        user_id: User's database ID

    Returns:
        List of session info dicts
    """
    try:
        redis = await get_redis()

        user_sessions_key = f"{USER_SESSIONS_PREFIX}{user_id}"
        session_ids = await redis.smembers(user_sessions_key)

        sessions = []
        for jti in session_ids:
            session_key = f"{SESSION_PREFIX}{jti}"
            session_data = await redis.hgetall(session_key)

            if session_data:
                sessions.append(
                    {
                        "id": jti,
                        "created_at": session_data.get("created_at"),
                        "user_agent": session_data.get("user_agent"),
                        "ip_address": session_data.get("ip_address"),
                    }
                )

        return sessions

    except Exception:
        logger.exception("get_user_sessions_failed", user_id=user_id)
        return []


async def cleanup_expired_sessions(user_id: int) -> int:
    """Clean up expired session references for a user.

    This is called periodically to remove stale session IDs from
    the user's session set.

    Args:
        user_id: User's database ID

    Returns:
        Number of stale references cleaned up
    """
    try:
        redis = await get_redis()

        user_sessions_key = f"{USER_SESSIONS_PREFIX}{user_id}"
        session_ids = await redis.smembers(user_sessions_key)

        cleaned = 0
        for jti in session_ids:
            session_key = f"{SESSION_PREFIX}{jti}"
            if not await redis.exists(session_key):
                await redis.srem(user_sessions_key, jti)
                cleaned += 1

        return cleaned

    except Exception:
        logger.exception("cleanup_expired_sessions_failed", user_id=user_id)
        return 0
