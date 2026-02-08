"""API endpoints for user integrations (per workspace)."""

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.auth import VerifiedUser, user_id_to_uuid
from app.db.session import get_db
from app.models.user_integration import UserIntegration
from app.models.workspace import Workspace

router = APIRouter(prefix="/api/v1/integrations", tags=["integrations"])


class IntegrationCredentials(BaseModel):
    """Credentials for connecting an integration."""

    credentials: dict[str, Any] = Field(
        ..., description="Integration credentials (api_key, access_token, etc.)"
    )
    metadata: dict[str, Any] | None = Field(
        None, description="Additional integration-specific metadata"
    )


class ConnectIntegrationRequest(BaseModel):
    """Request to connect an integration."""

    integration_id: str = Field(..., description="Integration slug (e.g., 'hubspot', 'slack')")
    integration_name: str = Field(..., description="Display name (e.g., 'HubSpot', 'Slack')")
    workspace_id: str | None = Field(
        None, description="Workspace ID (null for user-level integration)"
    )
    credentials: dict[str, Any] = Field(
        ..., description="Integration credentials (api_key, access_token, etc.)"
    )
    metadata: dict[str, Any] | None = Field(
        None, description="Additional integration-specific metadata"
    )


class UpdateIntegrationRequest(BaseModel):
    """Request to update integration credentials."""

    credentials: dict[str, Any] | None = Field(
        None, description="Updated credentials (partial update supported)"
    )
    metadata: dict[str, Any] | None = Field(None, description="Updated metadata")
    is_active: bool | None = Field(None, description="Enable/disable integration")


class IntegrationResponse(BaseModel):
    """Integration response (credentials masked)."""

    model_config = {"from_attributes": True}

    id: str
    integration_id: str
    integration_name: str
    workspace_id: str | None
    is_active: bool
    is_connected: bool
    connected_at: datetime | None
    last_used_at: datetime | None
    has_credentials: bool
    credential_fields: list[str]  # List of field names that are set


class IntegrationListResponse(BaseModel):
    """List of integrations."""

    integrations: list[IntegrationResponse]
    total: int


def mask_credentials(credentials: dict[str, Any]) -> list[str]:
    """Return list of credential field names that are set (without values)."""
    return [key for key, value in credentials.items() if value]


@router.get("", response_model=IntegrationListResponse)
async def list_integrations(
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = None,
) -> IntegrationListResponse:
    """List user's connected integrations.

    Args:
        workspace_id: Filter by workspace (optional, null returns user-level integrations)
        current_user: Authenticated user
        db: Database session

    Returns:
        List of connected integrations with masked credentials
    """
    user_uuid = user_id_to_uuid(current_user.id)

    # Build query
    query = select(UserIntegration).where(UserIntegration.user_id == user_uuid)

    if workspace_id:
        try:
            ws_uuid = uuid.UUID(workspace_id)
            query = query.where(UserIntegration.workspace_id == ws_uuid)
        except ValueError as err:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid workspace_id format",
            ) from err
    # If workspace_id is None, we return ALL integrations for the user (both workspace-level and user-level)

    result = await db.execute(query.order_by(UserIntegration.created_at.desc()))
    integrations = result.scalars().all()

    responses = [
        IntegrationResponse(
            id=str(integration.id),
            integration_id=integration.integration_id,
            integration_name=integration.integration_name,
            workspace_id=str(integration.workspace_id) if integration.workspace_id else None,
            is_active=integration.is_active,
            is_connected=True,
            connected_at=integration.created_at,
            last_used_at=integration.last_used_at,
            has_credentials=bool(integration.credentials),
            credential_fields=mask_credentials(integration.credentials or {}),
        )
        for integration in integrations
    ]

    return IntegrationListResponse(integrations=responses, total=len(responses))


@router.get("/{integration_id}", response_model=IntegrationResponse)
async def get_integration(
    integration_id: str,
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = None,
) -> IntegrationResponse:
    """Get a specific integration's connection status.

    Args:
        integration_id: Integration slug (e.g., 'hubspot')
        workspace_id: Workspace ID (optional)
        current_user: Authenticated user
        db: Database session

    Returns:
        Integration details with masked credentials
    """
    user_uuid = user_id_to_uuid(current_user.id)

    # Build query conditions
    conditions = [
        UserIntegration.user_id == user_uuid,
        UserIntegration.integration_id == integration_id,
    ]

    if workspace_id:
        try:
            ws_uuid = uuid.UUID(workspace_id)
            conditions.append(UserIntegration.workspace_id == ws_uuid)
        except ValueError as err:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid workspace_id format",
            ) from err
    else:
        conditions.append(UserIntegration.workspace_id.is_(None))

    result = await db.execute(select(UserIntegration).where(and_(*conditions)))
    integration = result.scalar_one_or_none()

    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Integration '{integration_id}' not connected",
        )

    return IntegrationResponse(
        id=str(integration.id),
        integration_id=integration.integration_id,
        integration_name=integration.integration_name,
        workspace_id=str(integration.workspace_id) if integration.workspace_id else None,
        is_active=integration.is_active,
        is_connected=True,
        connected_at=integration.created_at,
        last_used_at=integration.last_used_at,
        has_credentials=bool(integration.credentials),
        credential_fields=mask_credentials(integration.credentials or {}),
    )


@router.post("", status_code=status.HTTP_201_CREATED, response_model=IntegrationResponse)
async def connect_integration(
    request: ConnectIntegrationRequest,
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> IntegrationResponse:
    """Connect a new integration.

    Args:
        request: Integration connection request
        current_user: Authenticated user
        db: Database session

    Returns:
        Connected integration details
    """
    user_uuid = user_id_to_uuid(current_user.id)
    workspace_uuid: uuid.UUID | None = None

    # Validate workspace if provided
    if request.workspace_id:
        try:
            workspace_uuid = uuid.UUID(request.workspace_id)
        except ValueError as err:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid workspace_id format",
            ) from err

        # Verify workspace belongs to user (Workspace.user_id is int, not UUID)
        ws_result = await db.execute(
            select(Workspace).where(
                and_(Workspace.id == workspace_uuid, Workspace.user_id == current_user.id)
            )
        )
        workspace = ws_result.scalar_one_or_none()
        if not workspace:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workspace not found",
            )

    # Check if integration already exists for this user/workspace combo
    conditions = [
        UserIntegration.user_id == user_uuid,
        UserIntegration.integration_id == request.integration_id,
    ]
    if workspace_uuid:
        conditions.append(UserIntegration.workspace_id == workspace_uuid)
    else:
        conditions.append(UserIntegration.workspace_id.is_(None))

    existing = await db.execute(select(UserIntegration).where(and_(*conditions)))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Integration '{request.integration_id}' already connected for this workspace",
        )

    # Create new integration
    integration = UserIntegration(
        user_id=user_uuid,
        workspace_id=workspace_uuid,
        integration_id=request.integration_id,
        integration_name=request.integration_name,
        credentials=request.credentials,
        integration_metadata=request.metadata,
        is_active=True,
    )

    db.add(integration)
    await db.commit()
    await db.refresh(integration)

    return IntegrationResponse(
        id=str(integration.id),
        integration_id=integration.integration_id,
        integration_name=integration.integration_name,
        workspace_id=str(integration.workspace_id) if integration.workspace_id else None,
        is_active=integration.is_active,
        is_connected=True,
        connected_at=integration.created_at,
        last_used_at=integration.last_used_at,
        has_credentials=bool(integration.credentials),
        credential_fields=mask_credentials(integration.credentials or {}),
    )


@router.put("/{integration_id}", response_model=IntegrationResponse)
async def update_integration(
    integration_id: str,
    request: UpdateIntegrationRequest,
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = None,
) -> IntegrationResponse:
    """Update an integration's credentials or settings.

    Args:
        integration_id: Integration slug (e.g., 'hubspot')
        request: Update request
        workspace_id: Workspace ID (optional)
        current_user: Authenticated user
        db: Database session

    Returns:
        Updated integration details
    """
    user_uuid = user_id_to_uuid(current_user.id)

    # Build query conditions
    conditions = [
        UserIntegration.user_id == user_uuid,
        UserIntegration.integration_id == integration_id,
    ]

    if workspace_id:
        try:
            ws_uuid = uuid.UUID(workspace_id)
            conditions.append(UserIntegration.workspace_id == ws_uuid)
        except ValueError as err:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid workspace_id format",
            ) from err
    else:
        conditions.append(UserIntegration.workspace_id.is_(None))

    result = await db.execute(select(UserIntegration).where(and_(*conditions)))
    integration = result.scalar_one_or_none()

    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Integration '{integration_id}' not connected",
        )

    # Update fields
    if request.credentials is not None:
        # Merge with existing credentials (partial update)
        # Create a new dict to ensure SQLAlchemy detects the change
        existing_creds = dict(integration.credentials or {})
        existing_creds.update(request.credentials)
        integration.credentials = existing_creds
        flag_modified(integration, "credentials")

    if request.metadata is not None:
        # Create a new dict to ensure SQLAlchemy detects the change
        existing_meta = dict(integration.integration_metadata or {})
        existing_meta.update(request.metadata)
        integration.integration_metadata = existing_meta
        flag_modified(integration, "integration_metadata")

    if request.is_active is not None:
        integration.is_active = request.is_active

    integration.updated_at = datetime.now(UTC)

    db.add(integration)
    await db.commit()
    await db.refresh(integration)

    return IntegrationResponse(
        id=str(integration.id),
        integration_id=integration.integration_id,
        integration_name=integration.integration_name,
        workspace_id=str(integration.workspace_id) if integration.workspace_id else None,
        is_active=integration.is_active,
        is_connected=True,
        connected_at=integration.created_at,
        last_used_at=integration.last_used_at,
        has_credentials=bool(integration.credentials),
        credential_fields=mask_credentials(integration.credentials or {}),
    )


@router.delete("/{integration_id}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_integration(
    integration_id: str,
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = None,
) -> None:
    """Disconnect an integration.

    Args:
        integration_id: Integration slug (e.g., 'hubspot')
        workspace_id: Workspace ID (optional)
        current_user: Authenticated user
        db: Database session
    """
    user_uuid = user_id_to_uuid(current_user.id)

    # Build query conditions
    conditions = [
        UserIntegration.user_id == user_uuid,
        UserIntegration.integration_id == integration_id,
    ]

    if workspace_id:
        try:
            ws_uuid = uuid.UUID(workspace_id)
            conditions.append(UserIntegration.workspace_id == ws_uuid)
        except ValueError as err:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid workspace_id format",
            ) from err
    else:
        conditions.append(UserIntegration.workspace_id.is_(None))

    result = await db.execute(select(UserIntegration).where(and_(*conditions)))
    integration = result.scalar_one_or_none()

    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Integration '{integration_id}' not connected",
        )

    await db.delete(integration)
    await db.commit()


async def get_integration_credentials(
    user_id: uuid.UUID,
    integration_id: str,
    db: AsyncSession,
    workspace_id: uuid.UUID | None = None,
) -> dict[str, Any] | None:
    """Get integration credentials for internal use.

    Args:
        user_id: User ID (UUID)
        integration_id: Integration slug
        db: Database session
        workspace_id: Workspace ID (optional)

    Returns:
        Credentials dict or None if not connected
    """
    conditions = [
        UserIntegration.user_id == user_id,
        UserIntegration.integration_id == integration_id,
        UserIntegration.is_active.is_(True),
    ]

    if workspace_id:
        conditions.append(UserIntegration.workspace_id == workspace_id)
    else:
        conditions.append(UserIntegration.workspace_id.is_(None))

    result = await db.execute(select(UserIntegration).where(and_(*conditions)))
    integration = result.scalar_one_or_none()

    if integration:
        # Update last_used_at
        integration.last_used_at = datetime.now(UTC)
        db.add(integration)
        await db.commit()
        return integration.credentials

    return None


async def get_workspace_integrations(
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    db: AsyncSession,
) -> dict[str, dict[str, Any]]:
    """Get all active integration credentials for a workspace.

    Args:
        user_id: User ID
        workspace_id: Workspace ID
        db: Database session

    Returns:
        Dict mapping integration_id to credentials
    """
    result = await db.execute(
        select(UserIntegration).where(
            and_(
                UserIntegration.user_id == user_id,
                UserIntegration.workspace_id == workspace_id,
                UserIntegration.is_active.is_(True),
            )
        )
    )
    integrations = result.scalars().all()

    return {
        integration.integration_id: integration.credentials
        for integration in integrations
        if integration.credentials
    }
