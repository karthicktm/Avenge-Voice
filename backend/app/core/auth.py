"""Authentication dependencies and utilities."""

import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.models.user import User, UserRole

security = HTTPBearer()


def decode_access_token(token: str) -> dict[str, Any] | None:
    """Decode a JWT access token and return the payload.

    Args:
        token: JWT token string

    Returns:
        Token payload dict or None if invalid
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except JWTError:
        return None


def user_id_to_uuid(user_id: int) -> uuid.UUID:
    """Convert integer user ID to a deterministic UUID.

    Some models (Agent, UserSettings) use UUID for user_id instead of int.
    This function generates a consistent UUID from the integer user ID
    using a namespace-based approach.
    """
    # Use a fixed namespace UUID for this application
    namespace = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")  # UUID namespace DNS
    return uuid.uuid5(namespace, f"user:{user_id}")


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Get current authenticated user from JWT token."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        token = credentials.credentials
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: str | None = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError as exc:
        raise credentials_exception from exc

    # Fetch user from database
    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()

    if user is None:
        raise credentials_exception

    return user


async def get_user_id_from_uuid(user_uuid: uuid.UUID, db: AsyncSession) -> int | None:
    """Look up the integer user ID from a generated UUID.

    Since user_id_to_uuid is a one-way hash, we need to scan users and compare.
    This is O(n) but typically small for most applications.

    Args:
        user_uuid: The UUID generated via user_id_to_uuid
        db: Database session

    Returns:
        The integer user ID, or None if not found
    """
    result = await db.execute(select(User))
    users = result.scalars().all()

    for user in users:
        if user_id_to_uuid(user.id) == user_uuid:
            return user.id

    return None


# Type alias for dependency injection
CurrentUser = Annotated[User, Depends(get_current_user)]


# =============================================================================
# Route Guards - Specialized Auth Dependencies
# =============================================================================


async def get_verified_user(current_user: CurrentUser) -> User:
    """Require authenticated user with verified email.

    Use this for endpoints that require email verification.

    Args:
        current_user: Authenticated user from JWT

    Returns:
        Verified user

    Raises:
        HTTPException: 403 if email not verified
    """
    if not current_user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email verification required. Please verify your email to access this resource.",
        )
    return current_user


def require_role(allowed_roles: list[UserRole]) -> Callable[[User], Awaitable[User]]:
    """Create a dependency that requires specific roles.

    Args:
        allowed_roles: List of roles that are allowed access

    Returns:
        Dependency function that validates user role
    """

    async def role_checker(current_user: CurrentUser) -> User:
        """Check if user has required role.

        Args:
            current_user: Authenticated user

        Returns:
            User if authorized

        Raises:
            HTTPException: 403 if email not verified
            HTTPException: 403 if user doesn't have required role
        """
        # First check email verification
        if not current_user.email_verified:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Email verification required.",
            )

        # Check role
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions. Required role: "
                + ", ".join(r.value for r in allowed_roles),
            )
        return current_user

    return role_checker


async def get_admin_user(current_user: CurrentUser) -> User:
    """Require authenticated admin user (ADMIN or SUPER_ADMIN).

    Use this for admin-only endpoints.

    Args:
        current_user: Authenticated user

    Returns:
        Admin user

    Raises:
        HTTPException: 403 if not admin
    """
    if not current_user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email verification required.",
        )

    if current_user.role not in [UserRole.SUPER_ADMIN, UserRole.ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )
    return current_user


async def get_super_admin_user(current_user: CurrentUser) -> User:
    """Require authenticated super admin user.

    Use this for platform administration endpoints.

    Args:
        current_user: Authenticated user

    Returns:
        Super admin user

    Raises:
        HTTPException: 403 if not super admin
    """
    if not current_user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email verification required.",
        )

    if current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super admin access required.",
        )
    return current_user


# Type aliases for route guards
VerifiedUser = Annotated[User, Depends(get_verified_user)]
AdminUser = Annotated[User, Depends(get_admin_user)]
SuperAdminUser = Annotated[User, Depends(get_super_admin_user)]
