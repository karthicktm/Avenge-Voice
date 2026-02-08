"""WebSocket endpoint for real-time usage updates."""

import asyncio
import uuid

import structlog
from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.organization import Organization
from app.services.realtime_usage_service import subscribe_to_usage_updates

logger = structlog.get_logger()

router = APIRouter(tags=["usage-websocket"])


async def _verify_user_access(
    db: AsyncSession,
    organization_id: uuid.UUID,
    token: str,
) -> bool:
    """Verify user has access to the organization.

    Args:
        db: Database session
        organization_id: Organization ID to check access for
        token: JWT token for authentication

    Returns:
        True if user has access, False otherwise
    """
    from app.core.auth import decode_access_token

    try:
        payload = decode_access_token(token)
        if not payload:
            return False

        user_org_id = payload.get("organization_id")
        if not user_org_id:
            return False

        return str(user_org_id) == str(organization_id)

    except Exception:
        logger.exception("token_verification_failed")
        return False


@router.websocket("/ws/usage/{organization_id}")
async def usage_websocket(
    websocket: WebSocket,
    organization_id: str,
    token: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> None:
    """WebSocket endpoint for real-time usage updates.

    Clients connect to this endpoint to receive:
    - usage_update: When resource usage changes
    - usage_alert: When a usage threshold is crossed

    Message format:
    {
        "type": "usage_update" | "usage_alert",
        "resource_type": "voice_minutes",
        "current": 150.5,
        "timestamp": "2024-01-15T10:30:00Z",
        ...
    }

    Authentication is done via the 'token' query parameter.
    """
    log = logger.bind(organization_id=organization_id)

    # Validate organization ID
    try:
        org_uuid = uuid.UUID(organization_id)
    except ValueError:
        log.warning("invalid_organization_id")
        await websocket.close(code=4000, reason="Invalid organization ID")
        return

    # Verify access
    if not await _verify_user_access(db, org_uuid, token):
        log.warning("unauthorized_access")
        await websocket.close(code=4001, reason="Unauthorized")
        return

    # Verify organization exists
    result = await db.execute(select(Organization).where(Organization.id == org_uuid))
    org = result.scalar_one_or_none()

    if not org:
        log.warning("organization_not_found")
        await websocket.close(code=4004, reason="Organization not found")
        return

    # Accept connection
    await websocket.accept()
    log.info("usage_websocket_connected")

    try:
        # Subscribe to Redis pub/sub and forward messages
        async for message in subscribe_to_usage_updates(org_uuid):
            await websocket.send_json(message)

    except WebSocketDisconnect:
        log.info("usage_websocket_disconnected")

    except asyncio.CancelledError:
        log.debug("usage_websocket_cancelled")

    except Exception:
        log.exception("usage_websocket_error")
        await websocket.close(code=1011, reason="Internal error")


@router.websocket("/ws/usage")
async def usage_websocket_legacy(
    websocket: WebSocket,
    token: str = Query(...),
    organization_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Legacy WebSocket endpoint with organization_id as query param.

    Maintained for backwards compatibility.
    """
    await usage_websocket(websocket, organization_id, token, db)
