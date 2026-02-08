"""API endpoints for user settings."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import SuperAdminUser, VerifiedUser, user_id_to_uuid
from app.db.session import get_db
from app.models.system_settings import SystemSettings
from app.models.user_settings import UserSettings
from app.models.workspace import Workspace

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


class UpdateSettingsRequest(BaseModel):
    """Request to update user settings."""

    openai_api_key: str | None = None
    deepgram_api_key: str | None = None
    elevenlabs_api_key: str | None = None
    telnyx_api_key: str | None = None
    telnyx_public_key: str | None = None
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None


class SettingsResponse(BaseModel):
    """Settings response (API keys masked for security)."""

    openai_api_key_set: bool
    deepgram_api_key_set: bool
    elevenlabs_api_key_set: bool
    telnyx_api_key_set: bool
    twilio_account_sid_set: bool
    workspace_id: str | None = None


async def _validate_workspace_ownership(
    workspace_id_str: str,
    user_id: int,
    db: AsyncSession,
) -> uuid.UUID:
    """Validate workspace_id and verify ownership."""
    try:
        workspace_uuid = uuid.UUID(workspace_id_str)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid workspace_id format") from e

    ws_result = await db.execute(
        select(Workspace).where(
            Workspace.id == workspace_uuid,
            Workspace.user_id == user_id,
        )
    )
    if not ws_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Workspace not found")

    return workspace_uuid


@router.get("", response_model=SettingsResponse)
async def get_settings(
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = None,
) -> SettingsResponse:
    """Get user settings (API keys masked).

    Args:
        current_user: Authenticated user
        db: Database session
        workspace_id: Optional workspace ID for workspace-specific settings

    Returns:
        Settings with masked API keys
    """
    user_uuid = user_id_to_uuid(current_user.id)

    # Build query conditions
    conditions = [UserSettings.user_id == user_uuid]

    if workspace_id:
        workspace_uuid = await _validate_workspace_ownership(workspace_id, current_user.id, db)
        conditions.append(UserSettings.workspace_id == workspace_uuid)
    else:
        conditions.append(UserSettings.workspace_id.is_(None))

    result = await db.execute(select(UserSettings).where(and_(*conditions)))
    settings = result.scalar_one_or_none()

    if not settings:
        return SettingsResponse(
            openai_api_key_set=False,
            deepgram_api_key_set=False,
            elevenlabs_api_key_set=False,
            telnyx_api_key_set=False,
            twilio_account_sid_set=False,
            workspace_id=workspace_id,
        )

    return SettingsResponse(
        openai_api_key_set=bool(settings.openai_api_key),
        deepgram_api_key_set=bool(settings.deepgram_api_key),
        elevenlabs_api_key_set=bool(settings.elevenlabs_api_key),
        telnyx_api_key_set=bool(settings.telnyx_api_key),
        twilio_account_sid_set=bool(settings.twilio_account_sid),
        workspace_id=str(settings.workspace_id) if settings.workspace_id else None,
    )


@router.post("", status_code=status.HTTP_200_OK)
async def update_settings(
    request: UpdateSettingsRequest,
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = None,
) -> dict[str, str]:
    """Update user settings.

    Args:
        request: Settings update request
        current_user: Authenticated user
        db: Database session
        workspace_id: Optional workspace ID for workspace-specific settings

    Returns:
        Success message
    """
    user_uuid = user_id_to_uuid(current_user.id)

    # Build query conditions
    conditions = [UserSettings.user_id == user_uuid]
    workspace_uuid: uuid.UUID | None = None

    if workspace_id:
        workspace_uuid = await _validate_workspace_ownership(workspace_id, current_user.id, db)
        conditions.append(UserSettings.workspace_id == workspace_uuid)
    else:
        conditions.append(UserSettings.workspace_id.is_(None))

    result = await db.execute(select(UserSettings).where(and_(*conditions)))
    settings = result.scalar_one_or_none()

    if settings:
        # Update existing
        if request.openai_api_key is not None:
            settings.openai_api_key = request.openai_api_key or None
        if request.deepgram_api_key is not None:
            settings.deepgram_api_key = request.deepgram_api_key or None
        if request.elevenlabs_api_key is not None:
            settings.elevenlabs_api_key = request.elevenlabs_api_key or None
        if request.telnyx_api_key is not None:
            settings.telnyx_api_key = request.telnyx_api_key or None
        if request.telnyx_public_key is not None:
            settings.telnyx_public_key = request.telnyx_public_key or None
        if request.twilio_account_sid is not None:
            settings.twilio_account_sid = request.twilio_account_sid or None
        if request.twilio_auth_token is not None:
            settings.twilio_auth_token = request.twilio_auth_token or None

        db.add(settings)
    else:
        # Create new
        settings = UserSettings(
            user_id=user_uuid,
            workspace_id=workspace_uuid,
            openai_api_key=request.openai_api_key,
            deepgram_api_key=request.deepgram_api_key,
            elevenlabs_api_key=request.elevenlabs_api_key,
            telnyx_api_key=request.telnyx_api_key,
            telnyx_public_key=request.telnyx_public_key,
            twilio_account_sid=request.twilio_account_sid,
            twilio_auth_token=request.twilio_auth_token,
        )
        db.add(settings)

    await db.commit()

    return {"message": "Settings updated successfully"}


async def get_user_api_keys(
    user_id: uuid.UUID,
    db: AsyncSession,
    workspace_id: uuid.UUID | None = None,
) -> UserSettings | None:
    """Get user API keys for internal use.

    Settings are strictly isolated per workspace - no fallback to user-level settings.
    User-level settings (workspace_id=NULL) are only for admin/default use cases,
    not shared with workspaces.

    Args:
        user_id: User ID (UUID)
        db: Database session
        workspace_id: Optional workspace ID for workspace-specific settings

    Returns:
        UserSettings or None
    """
    # Build conditions based on workspace_id
    conditions = [UserSettings.user_id == user_id]

    if workspace_id:
        # Get workspace-specific settings only - no fallback
        conditions.append(UserSettings.workspace_id == workspace_id)
    else:
        # Get user-level settings (admin/default)
        conditions.append(UserSettings.workspace_id.is_(None))

    result = await db.execute(select(UserSettings).where(and_(*conditions)))
    return result.scalar_one_or_none()


# =============================================================================
# System Settings (Superadmin Only)
# =============================================================================


class SystemSettingsResponse(BaseModel):
    """System settings response for superadmin."""

    # Resend (Email)
    resend_api_key_set: bool = False
    resend_from_email: str | None = None

    # Stripe (Billing)
    stripe_secret_key_set: bool = False
    stripe_publishable_key: str | None = None
    stripe_webhook_secret_set: bool = False
    stripe_price_free: str | None = None
    stripe_price_starter: str | None = None
    stripe_price_professional: str | None = None
    stripe_price_enterprise: str | None = None


class UpdateSystemSettingsRequest(BaseModel):
    """Request to update system settings."""

    # Resend (Email)
    resend_api_key: str | None = None
    resend_from_email: str | None = None

    # Stripe (Billing)
    stripe_secret_key: str | None = None
    stripe_publishable_key: str | None = None
    stripe_webhook_secret: str | None = None
    stripe_price_free: str | None = None
    stripe_price_starter: str | None = None
    stripe_price_professional: str | None = None
    stripe_price_enterprise: str | None = None


@router.get("/system", response_model=SystemSettingsResponse)
async def get_system_settings(
    super_admin: SuperAdminUser,
    db: AsyncSession = Depends(get_db),
) -> SystemSettingsResponse:
    """Get system settings (superadmin only).

    Args:
        super_admin: Authenticated super admin user
        db: Database session

    Returns:
        System settings
    """
    # Get all system settings at once
    result = await db.execute(select(SystemSettings))
    settings = {s.key: s.value for s in result.scalars().all()}

    return SystemSettingsResponse(
        # Resend
        resend_api_key_set=bool(settings.get("resend_api_key")),
        resend_from_email=settings.get("resend_from_email"),
        # Stripe
        stripe_secret_key_set=bool(settings.get("stripe_secret_key")),
        stripe_publishable_key=settings.get("stripe_publishable_key"),
        stripe_webhook_secret_set=bool(settings.get("stripe_webhook_secret")),
        stripe_price_free=settings.get("stripe_price_free"),
        stripe_price_starter=settings.get("stripe_price_starter"),
        stripe_price_professional=settings.get("stripe_price_professional"),
        stripe_price_enterprise=settings.get("stripe_price_enterprise"),
    )


@router.post("/system", status_code=status.HTTP_200_OK)
async def update_system_settings(
    request: UpdateSystemSettingsRequest,
    super_admin: SuperAdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Update system settings (superadmin only).

    Args:
        request: System settings update request
        super_admin: Authenticated super admin user
        db: Database session

    Returns:
        Success message
    """

    # Helper function to update a setting
    async def update_setting(key: str, value: str | None) -> None:
        if value is None:
            return
        result = await db.execute(select(SystemSettings).where(SystemSettings.key == key))
        setting = result.scalar_one_or_none()
        if setting:
            setting.value = value or None
        else:
            setting = SystemSettings(key=key, value=value or None)
            db.add(setting)

    # Update Resend settings
    await update_setting("resend_api_key", request.resend_api_key)
    await update_setting("resend_from_email", request.resend_from_email)

    # Update Stripe settings
    await update_setting("stripe_secret_key", request.stripe_secret_key)
    await update_setting("stripe_publishable_key", request.stripe_publishable_key)
    await update_setting("stripe_webhook_secret", request.stripe_webhook_secret)
    await update_setting("stripe_price_free", request.stripe_price_free)
    await update_setting("stripe_price_starter", request.stripe_price_starter)
    await update_setting("stripe_price_professional", request.stripe_price_professional)
    await update_setting("stripe_price_enterprise", request.stripe_price_enterprise)

    await db.commit()

    return {"message": "System settings updated successfully"}


async def get_system_setting(db: AsyncSession, key: str) -> str | None:
    """Get a system setting value by key.

    Args:
        db: Database session
        key: Setting key

    Returns:
        Setting value or None
    """
    result = await db.execute(select(SystemSettings).where(SystemSettings.key == key))
    setting = result.scalar_one_or_none()
    return setting.value if setting else None
