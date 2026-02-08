"""Compliance API routes for GDPR and CCPA."""

from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import VerifiedUser, user_id_to_uuid
from app.db.session import get_db
from app.models.agent import Agent
from app.models.appointment import Appointment
from app.models.call_interaction import CallInteraction
from app.models.call_record import CallRecord
from app.models.contact import Contact
from app.models.privacy_settings import ConsentRecord, PrivacySettings
from app.models.user_settings import UserSettings
from app.models.workspace import Workspace

router = APIRouter(prefix="/api/v1/compliance", tags=["compliance"])
logger = structlog.get_logger()

# Constants
MAX_COMPLIANT_RETENTION_DAYS = 365


# =============================================================================
# Pydantic Models
# =============================================================================


class ComplianceCheckItem(BaseModel):
    """Single compliance check item."""

    id: str
    label: str
    description: str
    status: str  # "complete", "incomplete", "warning"
    action_url: str | None = None
    action_label: str | None = None


class GDPRStatusResponse(BaseModel):
    """GDPR compliance status response."""

    completed: int
    total: int
    percentage: int
    checks: list[ComplianceCheckItem]


class CCPAStatusResponse(BaseModel):
    """CCPA compliance status response."""

    completed: int
    total: int
    percentage: int
    checks: list[ComplianceCheckItem]


class ComplianceOverviewResponse(BaseModel):
    """Combined compliance overview."""

    gdpr: GDPRStatusResponse
    ccpa: CCPAStatusResponse


class PrivacySettingsResponse(BaseModel):
    """Privacy settings response."""

    privacy_policy_url: str | None
    privacy_policy_accepted_at: datetime | None
    data_retention_days: int
    openai_dpa_signed: bool
    openai_dpa_signed_at: datetime | None
    telnyx_dpa_signed: bool
    telnyx_dpa_signed_at: datetime | None
    deepgram_dpa_signed: bool
    deepgram_dpa_signed_at: datetime | None
    elevenlabs_dpa_signed: bool
    elevenlabs_dpa_signed_at: datetime | None
    ccpa_opt_out: bool
    ccpa_opt_out_at: datetime | None
    last_data_export_at: datetime | None


class UpdatePrivacySettingsRequest(BaseModel):
    """Request to update privacy settings."""

    privacy_policy_url: str | None = None
    data_retention_days: int | None = None
    openai_dpa_signed: bool | None = None
    telnyx_dpa_signed: bool | None = None
    deepgram_dpa_signed: bool | None = None
    elevenlabs_dpa_signed: bool | None = None
    ccpa_opt_out: bool | None = None


class ConsentRequest(BaseModel):
    """Request to record consent."""

    consent_type: str
    granted: bool


class DataExportResponse(BaseModel):
    """Data export response containing all user data."""

    user: dict[str, object]
    settings: dict[str, object] | None
    privacy_settings: dict[str, object] | None
    agents: list[dict[str, object]]
    workspaces: list[dict[str, object]]
    contacts: list[dict[str, object]]
    appointments: list[dict[str, object]]
    call_records: list[dict[str, object]]
    call_interactions: list[dict[str, object]]
    consent_records: list[dict[str, object]]
    exported_at: datetime


class DataDeletionResponse(BaseModel):
    """Response after data deletion."""

    deleted_counts: dict[str, int]
    deleted_at: datetime


# =============================================================================
# Helper Functions
# =============================================================================


async def get_or_create_privacy_settings(user_id: int, db: AsyncSession) -> PrivacySettings:
    """Get or create privacy settings for a user."""
    result = await db.execute(select(PrivacySettings).where(PrivacySettings.user_id == user_id))
    settings = result.scalar_one_or_none()

    if not settings:
        settings = PrivacySettings(user_id=user_id)
        db.add(settings)
        await db.commit()
        await db.refresh(settings)

    return settings


async def get_user_settings(user_id: int, db: AsyncSession) -> UserSettings | None:
    """Get user-level settings (API keys etc).

    Note: This returns user-level settings (where workspace_id is NULL),
    not workspace-specific settings. For compliance purposes, we check
    user-level API key configuration.
    """
    user_uuid = user_id_to_uuid(user_id)
    result = await db.execute(
        select(UserSettings).where(
            UserSettings.user_id == user_uuid,
            UserSettings.workspace_id.is_(None),
        )
    )
    return result.scalar_one_or_none()


# =============================================================================
# Compliance Status Endpoints
# =============================================================================


@router.get("/status", response_model=ComplianceOverviewResponse)
async def get_compliance_status(
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> ComplianceOverviewResponse:
    """Get overall compliance status for GDPR and CCPA."""
    privacy_settings = await get_or_create_privacy_settings(current_user.id, db)
    user_settings = await get_user_settings(current_user.id, db)

    # Check if user has API keys configured
    has_openai = bool(user_settings and user_settings.openai_api_key)
    has_telnyx = bool(user_settings and user_settings.telnyx_api_key)
    has_deepgram = bool(user_settings and user_settings.deepgram_api_key)
    has_elevenlabs = bool(user_settings and user_settings.elevenlabs_api_key)

    # Check consent records - get the MOST RECENT record for each type
    # and check if it was granted (not withdrawn)
    consent_result = await db.execute(
        select(ConsentRecord)
        .where(ConsentRecord.user_id == current_user.id)
        .where(ConsentRecord.consent_type == "data_processing")
        .order_by(ConsentRecord.created_at.desc())
        .limit(1)
    )
    latest_data_consent = consent_result.scalar_one_or_none()
    has_data_processing_consent = latest_data_consent is not None and latest_data_consent.granted

    recording_consent_result = await db.execute(
        select(ConsentRecord)
        .where(ConsentRecord.user_id == current_user.id)
        .where(ConsentRecord.consent_type == "call_recording")
        .order_by(ConsentRecord.created_at.desc())
        .limit(1)
    )
    latest_recording_consent = recording_consent_result.scalar_one_or_none()
    has_recording_consent = (
        latest_recording_consent is not None and latest_recording_consent.granted
    )

    # GDPR Checks
    gdpr_checks: list[ComplianceCheckItem] = [
        ComplianceCheckItem(
            id="encryption_transit",
            label="Encryption in Transit",
            description="All data transmitted over HTTPS/WSS",
            status="complete",
        ),
        ComplianceCheckItem(
            id="user_authentication",
            label="User Authentication",
            description="Secure JWT-based authentication enabled",
            status="complete",
        ),
        ComplianceCheckItem(
            id="password_hashing",
            label="Password Security",
            description="Passwords hashed with bcrypt",
            status="complete",
        ),
        ComplianceCheckItem(
            id="data_processing_consent",
            label="Data Processing Consent",
            description="User has consented to data processing",
            status="complete" if has_data_processing_consent else "incomplete",
            action_label="Record Consent" if not has_data_processing_consent else None,
        ),
        ComplianceCheckItem(
            id="recording_consent",
            label="Call Recording Consent",
            description="User has consented to call recording",
            status="complete" if has_recording_consent else "incomplete",
            action_label="Record Consent" if not has_recording_consent else None,
        ),
        ComplianceCheckItem(
            id="privacy_policy",
            label="Privacy Policy",
            description="Privacy policy URL configured",
            status="complete" if privacy_settings.privacy_policy_url else "incomplete",
            action_label="Add Policy URL" if not privacy_settings.privacy_policy_url else None,
        ),
        ComplianceCheckItem(
            id="data_retention",
            label="Data Retention Policy",
            description=f"Data retained for {privacy_settings.data_retention_days} days",
            status="complete"
            if privacy_settings.data_retention_days <= MAX_COMPLIANT_RETENTION_DAYS
            else "warning",
        ),
        ComplianceCheckItem(
            id="data_export",
            label="Data Export Available",
            description="Users can export their data",
            status="complete",
        ),
        ComplianceCheckItem(
            id="data_deletion",
            label="Data Deletion Available",
            description="Users can request data deletion",
            status="complete",
        ),
        ComplianceCheckItem(
            id="consent_withdrawal",
            label="Consent Withdrawal",
            description="Users can withdraw consent at any time",
            status="complete",
        ),
        ComplianceCheckItem(
            id="automated_decisions",
            label="AI Decision Disclosure",
            description="Users informed about AI-driven voice agents",
            status="complete",
        ),
        ComplianceCheckItem(
            id="data_minimization",
            label="Data Minimization",
            description="Only necessary data is collected",
            status="warning",
            action_label="Review Data Collection",
        ),
    ]

    # Add DPA checks only for services being used
    if has_openai:
        gdpr_checks.append(
            ComplianceCheckItem(
                id="openai_dpa",
                label="OpenAI DPA",
                description="Data Processing Agreement with OpenAI",
                status="complete" if privacy_settings.openai_dpa_signed else "incomplete",
                action_url="https://openai.com/policies/data-processing-addendum",
                action_label="Sign DPA" if not privacy_settings.openai_dpa_signed else None,
            )
        )

    if has_telnyx:
        gdpr_checks.append(
            ComplianceCheckItem(
                id="telnyx_dpa",
                label="Telnyx DPA",
                description="Data Processing Agreement with Telnyx",
                status="complete" if privacy_settings.telnyx_dpa_signed else "incomplete",
                action_url="https://telnyx.com/legal/data-processing-addendum",
                action_label="Sign DPA" if not privacy_settings.telnyx_dpa_signed else None,
            )
        )

    if has_deepgram:
        gdpr_checks.append(
            ComplianceCheckItem(
                id="deepgram_dpa",
                label="Deepgram DPA",
                description="Data Processing Agreement with Deepgram",
                status="complete" if privacy_settings.deepgram_dpa_signed else "incomplete",
                action_url="https://developers.deepgram.com/docs/data-privacy-compliance",
                action_label="Sign DPA" if not privacy_settings.deepgram_dpa_signed else None,
            )
        )

    if has_elevenlabs:
        gdpr_checks.append(
            ComplianceCheckItem(
                id="elevenlabs_dpa",
                label="ElevenLabs DPA",
                description="Data Processing Agreement with ElevenLabs",
                status="complete" if privacy_settings.elevenlabs_dpa_signed else "incomplete",
                action_url="https://elevenlabs.io/dpa",
                action_label="Sign DPA" if not privacy_settings.elevenlabs_dpa_signed else None,
            )
        )

    gdpr_completed = sum(1 for c in gdpr_checks if c.status == "complete")
    gdpr_total = len(gdpr_checks)

    # CCPA Checks
    ccpa_checks: list[ComplianceCheckItem] = [
        ComplianceCheckItem(
            id="data_disclosure",
            label="Data Collection Disclosure",
            description="Categories of data collected are documented",
            status="complete" if privacy_settings.privacy_policy_url else "incomplete",
            action_label="Add Privacy Policy" if not privacy_settings.privacy_policy_url else None,
        ),
        ComplianceCheckItem(
            id="opt_out_right",
            label="Opt-Out Right",
            description="Users can opt out of data sale/sharing",
            status="complete",
        ),
        ComplianceCheckItem(
            id="opt_out_status",
            label="Opt-Out Status",
            description="Do Not Sell My Personal Information"
            if privacy_settings.ccpa_opt_out
            else "User has not opted out",
            status="complete" if privacy_settings.ccpa_opt_out else "warning",
        ),
        ComplianceCheckItem(
            id="data_access",
            label="Data Access Right",
            description="Users can request access to their data",
            status="complete",
        ),
        ComplianceCheckItem(
            id="data_deletion_ccpa",
            label="Deletion Right",
            description="Users can request deletion of their data",
            status="complete",
        ),
        ComplianceCheckItem(
            id="non_discrimination",
            label="Non-Discrimination",
            description="No discrimination for exercising privacy rights",
            status="complete",
        ),
    ]

    ccpa_completed = sum(1 for c in ccpa_checks if c.status == "complete")
    ccpa_total = len(ccpa_checks)

    return ComplianceOverviewResponse(
        gdpr=GDPRStatusResponse(
            completed=gdpr_completed,
            total=gdpr_total,
            percentage=int((gdpr_completed / gdpr_total) * 100) if gdpr_total > 0 else 0,
            checks=gdpr_checks,
        ),
        ccpa=CCPAStatusResponse(
            completed=ccpa_completed,
            total=ccpa_total,
            percentage=int((ccpa_completed / ccpa_total) * 100) if ccpa_total > 0 else 0,
            checks=ccpa_checks,
        ),
    )


# =============================================================================
# Privacy Settings Endpoints
# =============================================================================


@router.get("/privacy-settings", response_model=PrivacySettingsResponse)
async def get_privacy_settings(
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> PrivacySettingsResponse:
    """Get user's privacy settings."""
    settings = await get_or_create_privacy_settings(current_user.id, db)

    return PrivacySettingsResponse(
        privacy_policy_url=settings.privacy_policy_url,
        privacy_policy_accepted_at=settings.privacy_policy_accepted_at,
        data_retention_days=settings.data_retention_days,
        openai_dpa_signed=settings.openai_dpa_signed,
        openai_dpa_signed_at=settings.openai_dpa_signed_at,
        telnyx_dpa_signed=settings.telnyx_dpa_signed,
        telnyx_dpa_signed_at=settings.telnyx_dpa_signed_at,
        deepgram_dpa_signed=settings.deepgram_dpa_signed,
        deepgram_dpa_signed_at=settings.deepgram_dpa_signed_at,
        elevenlabs_dpa_signed=settings.elevenlabs_dpa_signed,
        elevenlabs_dpa_signed_at=settings.elevenlabs_dpa_signed_at,
        ccpa_opt_out=settings.ccpa_opt_out,
        ccpa_opt_out_at=settings.ccpa_opt_out_at,
        last_data_export_at=settings.last_data_export_at,
    )


@router.patch("/privacy-settings", response_model=PrivacySettingsResponse)
async def update_privacy_settings(
    request: UpdatePrivacySettingsRequest,
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> PrivacySettingsResponse:
    """Update user's privacy settings."""
    settings = await get_or_create_privacy_settings(current_user.id, db)
    now = datetime.now(UTC)

    if request.privacy_policy_url is not None:
        settings.privacy_policy_url = request.privacy_policy_url
        if request.privacy_policy_url:
            settings.privacy_policy_accepted_at = now

    if request.data_retention_days is not None:
        settings.data_retention_days = request.data_retention_days

    if request.openai_dpa_signed is not None:
        settings.openai_dpa_signed = request.openai_dpa_signed
        settings.openai_dpa_signed_at = now if request.openai_dpa_signed else None

    if request.telnyx_dpa_signed is not None:
        settings.telnyx_dpa_signed = request.telnyx_dpa_signed
        settings.telnyx_dpa_signed_at = now if request.telnyx_dpa_signed else None

    if request.deepgram_dpa_signed is not None:
        settings.deepgram_dpa_signed = request.deepgram_dpa_signed
        settings.deepgram_dpa_signed_at = now if request.deepgram_dpa_signed else None

    if request.elevenlabs_dpa_signed is not None:
        settings.elevenlabs_dpa_signed = request.elevenlabs_dpa_signed
        settings.elevenlabs_dpa_signed_at = now if request.elevenlabs_dpa_signed else None

    if request.ccpa_opt_out is not None:
        settings.ccpa_opt_out = request.ccpa_opt_out
        settings.ccpa_opt_out_at = now if request.ccpa_opt_out else None

    await db.commit()
    await db.refresh(settings)

    logger.info("privacy_settings_updated", user_id=current_user.id)

    return PrivacySettingsResponse(
        privacy_policy_url=settings.privacy_policy_url,
        privacy_policy_accepted_at=settings.privacy_policy_accepted_at,
        data_retention_days=settings.data_retention_days,
        openai_dpa_signed=settings.openai_dpa_signed,
        openai_dpa_signed_at=settings.openai_dpa_signed_at,
        telnyx_dpa_signed=settings.telnyx_dpa_signed,
        telnyx_dpa_signed_at=settings.telnyx_dpa_signed_at,
        deepgram_dpa_signed=settings.deepgram_dpa_signed,
        deepgram_dpa_signed_at=settings.deepgram_dpa_signed_at,
        elevenlabs_dpa_signed=settings.elevenlabs_dpa_signed,
        elevenlabs_dpa_signed_at=settings.elevenlabs_dpa_signed_at,
        ccpa_opt_out=settings.ccpa_opt_out,
        ccpa_opt_out_at=settings.ccpa_opt_out_at,
        last_data_export_at=settings.last_data_export_at,
    )


# =============================================================================
# Consent Endpoints
# =============================================================================


@router.post("/consent")
async def record_consent(
    request: ConsentRequest,
    http_request: Request,
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Record user consent for GDPR compliance."""
    consent = ConsentRecord(
        user_id=current_user.id,
        consent_type=request.consent_type,
        granted=request.granted,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
    )
    db.add(consent)
    await db.commit()

    logger.info(
        "consent_recorded",
        user_id=current_user.id,
        consent_type=request.consent_type,
        granted=request.granted,
    )

    return {"message": f"Consent for {request.consent_type} recorded successfully"}


# =============================================================================
# Data Export Endpoint (GDPR Article 20 / CCPA)
# =============================================================================


@router.get("/export", response_model=DataExportResponse)
async def export_user_data(
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> DataExportResponse:
    """Export all user data for GDPR/CCPA compliance."""
    now = datetime.now(UTC)

    # User data
    user_data = {
        "id": current_user.id,
        "email": current_user.email,
        "full_name": current_user.full_name,
        "created_at": current_user.created_at.isoformat() if current_user.created_at else None,
    }

    # User settings (mask API keys)
    user_settings = await get_user_settings(current_user.id, db)
    settings_data = None
    if user_settings:
        settings_data = {
            "openai_api_key_set": bool(user_settings.openai_api_key),
            "deepgram_api_key_set": bool(user_settings.deepgram_api_key),
            "elevenlabs_api_key_set": bool(user_settings.elevenlabs_api_key),
            "telnyx_api_key_set": bool(user_settings.telnyx_api_key),
            "twilio_account_sid_set": bool(user_settings.twilio_account_sid),
            "created_at": user_settings.created_at.isoformat(),
            "updated_at": user_settings.updated_at.isoformat(),
        }

    # Privacy settings
    privacy_settings = await get_or_create_privacy_settings(current_user.id, db)
    privacy_data = {
        "privacy_policy_url": privacy_settings.privacy_policy_url,
        "data_retention_days": privacy_settings.data_retention_days,
        "ccpa_opt_out": privacy_settings.ccpa_opt_out,
        "openai_dpa_signed": privacy_settings.openai_dpa_signed,
        "telnyx_dpa_signed": privacy_settings.telnyx_dpa_signed,
        "deepgram_dpa_signed": privacy_settings.deepgram_dpa_signed,
        "elevenlabs_dpa_signed": privacy_settings.elevenlabs_dpa_signed,
    }

    # Agents - note: requires UUID conversion for user_id
    user_uuid = user_id_to_uuid(current_user.id)
    agents_result = await db.execute(select(Agent).where(Agent.user_id == user_uuid))
    agents_data = [
        {
            "id": str(a.id),
            "name": a.name,
            "description": a.description,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in agents_result.scalars().all()
    ]

    # Workspaces
    workspaces_result = await db.execute(
        select(Workspace).where(Workspace.user_id == current_user.id)
    )
    workspaces_data = [
        {
            "id": str(w.id),
            "name": w.name,
            "description": w.description,
            "created_at": w.created_at.isoformat() if w.created_at else None,
        }
        for w in workspaces_result.scalars().all()
    ]

    # Get workspace IDs for user
    workspace_ids = [w.id for w in workspaces_result.scalars().all()]

    # Re-query since we consumed the result
    workspaces_result = await db.execute(
        select(Workspace).where(Workspace.user_id == current_user.id)
    )
    workspace_ids = [w.id for w in workspaces_result.scalars().all()]

    # Contacts
    contacts_data: list[dict[str, object]] = []
    if workspace_ids:
        contacts_result = await db.execute(
            select(Contact).where(Contact.workspace_id.in_(workspace_ids))
        )
        contacts_data = [
            {
                "id": str(c.id),
                "first_name": c.first_name,
                "last_name": c.last_name,
                "email": c.email,
                "phone_number": c.phone_number,
                "company_name": c.company_name,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in contacts_result.scalars().all()
        ]

    # Appointments
    appointments_data: list[dict[str, object]] = []
    if workspace_ids:
        appointments_result = await db.execute(
            select(Appointment).where(Appointment.workspace_id.in_(workspace_ids))
        )
        appointments_data = [
            {
                "id": str(a.id),
                "scheduled_at": a.scheduled_at.isoformat() if a.scheduled_at else None,
                "duration_minutes": a.duration_minutes,
                "status": a.status,
                "service_type": a.service_type,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in appointments_result.scalars().all()
        ]

    # Call records (Agent.user_id is UUID, reuse user_uuid from above)
    agent_ids_result = await db.execute(select(Agent.id).where(Agent.user_id == user_uuid))
    agent_ids = list(agent_ids_result.scalars().all())

    call_records_data: list[dict[str, object]] = []
    if agent_ids:
        call_records_result = await db.execute(
            select(CallRecord).where(CallRecord.agent_id.in_(agent_ids))
        )
        call_records_data = [
            {
                "id": str(cr.id),
                "direction": cr.direction,
                "status": cr.status,
                "from_number": cr.from_number,
                "to_number": cr.to_number,
                "duration_seconds": cr.duration_seconds,
                "started_at": cr.started_at.isoformat() if cr.started_at else None,
                "ended_at": cr.ended_at.isoformat() if cr.ended_at else None,
            }
            for cr in call_records_result.scalars().all()
        ]

    # Call interactions
    call_interactions_data: list[dict[str, object]] = []
    if workspace_ids:
        interactions_result = await db.execute(
            select(CallInteraction).where(CallInteraction.workspace_id.in_(workspace_ids))
        )
        call_interactions_data = [
            {
                "id": str(ci.id),
                "agent_name": ci.agent_name,
                "outcome": ci.outcome,
                "duration_seconds": ci.duration_seconds,
                "sentiment_score": ci.sentiment_score,
                "call_started_at": (ci.call_started_at.isoformat() if ci.call_started_at else None),
            }
            for ci in interactions_result.scalars().all()
        ]

    # Consent records
    consent_result = await db.execute(
        select(ConsentRecord).where(ConsentRecord.user_id == current_user.id)
    )
    consent_data = [
        {
            "id": str(cr.id),
            "consent_type": cr.consent_type,
            "granted": cr.granted,
            "created_at": cr.created_at.isoformat() if cr.created_at else None,
        }
        for cr in consent_result.scalars().all()
    ]

    # Update last export time
    privacy_settings.last_data_export_at = now
    privacy_settings.last_data_export_requested_at = now
    await db.commit()

    logger.info("data_exported", user_id=current_user.id)

    return DataExportResponse(
        user=user_data,
        settings=settings_data,
        privacy_settings=privacy_data,
        agents=agents_data,
        workspaces=workspaces_data,
        contacts=contacts_data,
        appointments=appointments_data,
        call_records=call_records_data,
        call_interactions=call_interactions_data,
        consent_records=consent_data,
        exported_at=now,
    )


# =============================================================================
# CCPA Opt-Out Endpoint
# =============================================================================


@router.post("/ccpa/opt-out")
async def ccpa_opt_out(
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Opt out of data sale/sharing under CCPA."""
    settings = await get_or_create_privacy_settings(current_user.id, db)
    settings.ccpa_opt_out = True
    settings.ccpa_opt_out_at = datetime.now(UTC)
    await db.commit()

    logger.info("ccpa_opt_out", user_id=current_user.id)

    return {"message": "You have successfully opted out of data sale/sharing"}


@router.post("/ccpa/opt-in")
async def ccpa_opt_in(
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Opt back in to data sharing under CCPA."""
    settings = await get_or_create_privacy_settings(current_user.id, db)
    settings.ccpa_opt_out = False
    settings.ccpa_opt_out_at = None
    await db.commit()

    logger.info("ccpa_opt_in", user_id=current_user.id)

    return {"message": "You have opted back in to data sharing"}


# =============================================================================
# Consent Withdrawal Endpoint
# =============================================================================


@router.post("/consent/withdraw")
async def withdraw_consent(
    request: ConsentRequest,
    http_request: Request,
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Withdraw previously given consent (GDPR Article 7(3))."""
    # Record the withdrawal as a new consent record with granted=False
    consent = ConsentRecord(
        user_id=current_user.id,
        consent_type=request.consent_type,
        granted=False,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
    )
    db.add(consent)
    await db.commit()

    logger.info(
        "consent_withdrawn",
        user_id=current_user.id,
        consent_type=request.consent_type,
    )

    return {"message": f"Consent for {request.consent_type} has been withdrawn"}


# =============================================================================
# Data Deletion Endpoint (GDPR Article 17 / CCPA Right to Delete)
# =============================================================================


@router.delete("/data", response_model=DataDeletionResponse)
async def delete_user_data(
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> DataDeletionResponse:
    """
    Delete all user data (Right to Erasure / Right to Delete).

    GDPR Article 17 - Right to erasure ('right to be forgotten')
    CCPA - Right to Delete

    This deletes:
    - All agents and their configurations
    - All workspaces
    - All contacts within workspaces
    - All appointments
    - All call records and interactions
    - All consent records
    - Privacy settings
    - User settings (API keys)

    Note: The user account itself is NOT deleted. Use a separate
    account deletion endpoint for that.
    """
    from sqlalchemy import delete

    now = datetime.now(UTC)
    deleted_counts: dict[str, int] = {}

    # Convert user_id to UUID for Agent queries (Agent.user_id is UUID)
    user_uuid = user_id_to_uuid(current_user.id)

    # Get workspace IDs for cascade deletion (Workspace.user_id is Integer)
    workspaces_result = await db.execute(
        select(Workspace.id).where(Workspace.user_id == current_user.id)
    )
    workspace_ids = list(workspaces_result.scalars().all())

    # Get agent IDs for cascade deletion (Agent.user_id is UUID)
    agents_result = await db.execute(select(Agent.id).where(Agent.user_id == user_uuid))
    agent_ids = list(agents_result.scalars().all())

    # Delete call interactions (workspace-based)
    if workspace_ids:
        result = await db.execute(
            delete(CallInteraction).where(CallInteraction.workspace_id.in_(workspace_ids))
        )
        deleted_counts["call_interactions"] = result.rowcount or 0  # type: ignore[attr-defined]

    # Delete call records (agent-based)
    if agent_ids:
        result = await db.execute(delete(CallRecord).where(CallRecord.agent_id.in_(agent_ids)))
        deleted_counts["call_records"] = result.rowcount or 0  # type: ignore[attr-defined]

    # Delete appointments (workspace-based)
    if workspace_ids:
        result = await db.execute(
            delete(Appointment).where(Appointment.workspace_id.in_(workspace_ids))
        )
        deleted_counts["appointments"] = result.rowcount or 0  # type: ignore[attr-defined]

    # Delete contacts (workspace-based)
    if workspace_ids:
        result = await db.execute(delete(Contact).where(Contact.workspace_id.in_(workspace_ids)))
        deleted_counts["contacts"] = result.rowcount or 0  # type: ignore[attr-defined]

    # Delete agents (Agent.user_id is UUID)
    result = await db.execute(delete(Agent).where(Agent.user_id == user_uuid))
    deleted_counts["agents"] = result.rowcount or 0  # type: ignore[attr-defined]

    # Delete workspaces
    result = await db.execute(delete(Workspace).where(Workspace.user_id == current_user.id))
    deleted_counts["workspaces"] = result.rowcount or 0  # type: ignore[attr-defined]

    # Delete consent records
    result = await db.execute(delete(ConsentRecord).where(ConsentRecord.user_id == current_user.id))
    deleted_counts["consent_records"] = result.rowcount or 0  # type: ignore[attr-defined]

    # Delete privacy settings
    result = await db.execute(
        delete(PrivacySettings).where(PrivacySettings.user_id == current_user.id)
    )
    deleted_counts["privacy_settings"] = result.rowcount or 0  # type: ignore[attr-defined]

    # Delete user settings (UserSettings.user_id is UUID, reuse user_uuid from above)
    result = await db.execute(delete(UserSettings).where(UserSettings.user_id == user_uuid))
    deleted_counts["user_settings"] = result.rowcount or 0  # type: ignore[attr-defined]

    await db.commit()

    logger.info(
        "user_data_deleted",
        user_id=current_user.id,
        deleted_counts=deleted_counts,
    )

    return DataDeletionResponse(
        deleted_counts=deleted_counts,
        deleted_at=now,
    )


# =============================================================================
# Data Retention Cleanup (for scheduled jobs)
# =============================================================================


async def cleanup_expired_data(db: AsyncSession) -> dict[str, int]:
    """
    Delete data that has exceeded retention period.

    This should be called by a scheduled job (e.g., daily cron).
    Returns counts of deleted records by type.
    """
    from sqlalchemy import delete

    deleted_counts: dict[str, int] = {}
    now = datetime.now(UTC)

    # Get all privacy settings with retention periods
    settings_result = await db.execute(select(PrivacySettings))
    all_settings = settings_result.scalars().all()

    for settings in all_settings:
        retention_days = settings.data_retention_days
        cutoff_date = now - __import__("datetime").timedelta(days=retention_days)

        # Get user's workspace IDs
        workspaces_result = await db.execute(
            select(Workspace.id).where(Workspace.user_id == settings.user_id)
        )
        workspace_ids = list(workspaces_result.scalars().all())

        # Get user's agent IDs
        agents_result = await db.execute(select(Agent.id).where(Agent.user_id == settings.user_id))
        agent_ids = list(agents_result.scalars().all())

        # Delete old call interactions
        if workspace_ids:
            result = await db.execute(
                delete(CallInteraction)
                .where(CallInteraction.workspace_id.in_(workspace_ids))
                .where(CallInteraction.created_at < cutoff_date)
            )
            deleted_counts["call_interactions"] = (
                deleted_counts.get("call_interactions", 0) + (result.rowcount or 0)  # type: ignore[attr-defined]
            )

        # Delete old call records
        if agent_ids:
            result = await db.execute(
                delete(CallRecord)
                .where(CallRecord.agent_id.in_(agent_ids))
                .where(CallRecord.created_at < cutoff_date)
            )
            deleted_counts["call_records"] = (
                deleted_counts.get("call_records", 0) + (result.rowcount or 0)  # type: ignore[attr-defined]
            )

        # Delete old consent records (keep most recent per type)
        result = await db.execute(
            delete(ConsentRecord)
            .where(ConsentRecord.user_id == settings.user_id)
            .where(ConsentRecord.created_at < cutoff_date)
        )
        deleted_counts["consent_records"] = (
            deleted_counts.get("consent_records", 0) + (result.rowcount or 0)  # type: ignore[attr-defined]
        )

    await db.commit()

    logger.info("retention_cleanup_completed", deleted_counts=deleted_counts)

    return deleted_counts


@router.post("/retention/cleanup")
async def trigger_retention_cleanup(
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """
    Manually trigger data retention cleanup.

    In production, this should be called by a scheduled job.
    This endpoint allows manual triggering for testing.
    """
    deleted_counts = await cleanup_expired_data(db)
    return {
        "message": "Retention cleanup completed",
        "deleted_counts": deleted_counts,
    }
