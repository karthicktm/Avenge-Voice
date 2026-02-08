"""Campaign endpoints for outbound calling campaigns."""

import uuid
from datetime import UTC, datetime, time

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import VerifiedUser, user_id_to_uuid
from app.db.session import get_db
from app.models.agent import Agent
from app.models.campaign import (
    CallDisposition,
    Campaign,
    CampaignContact,
    CampaignContactStatus,
    CampaignStatus,
)
from app.models.contact import Contact

router = APIRouter(prefix="/campaigns", tags=["campaigns"])

# Validation constants
MAX_CAMPAIGN_NAME_LENGTH = 255
MAX_CALLS_PER_MINUTE = 30
MAX_CONCURRENT_CALLS = 10
TIME_PARTS_COUNT = 2
MAX_HOUR = 23
MAX_MINUTE = 59
MIN_CALLING_DAY = 0
MAX_CALLING_DAY = 6


# =============================================================================
# Pydantic Schemas
# =============================================================================


class CampaignContactResponse(BaseModel):
    """Campaign contact response."""

    model_config = {"from_attributes": True}

    id: str
    contact_id: int
    status: str
    attempts: int
    last_attempt_at: datetime | None
    next_attempt_at: datetime | None
    last_call_duration_seconds: int
    last_call_outcome: str | None
    priority: int
    # Disposition fields
    disposition: str | None = None
    disposition_notes: str | None = None
    callback_requested_at: datetime | None = None
    # Contact details (joined)
    contact_name: str | None = None
    contact_phone: str | None = None


class CampaignResponse(BaseModel):
    """Campaign response schema."""

    model_config = {"from_attributes": True}

    id: str
    workspace_id: str
    agent_id: str
    agent_name: str | None = None
    name: str
    description: str | None
    status: str
    from_phone_number: str
    scheduled_start: datetime | None
    scheduled_end: datetime | None
    # Scheduler fields
    calling_hours_start: str | None = None  # Time as HH:MM string
    calling_hours_end: str | None = None  # Time as HH:MM string
    calling_days: list[int] | None = None  # 0=Mon, 6=Sun
    timezone: str | None = None
    # Call settings
    calls_per_minute: int
    max_concurrent_calls: int
    max_attempts_per_contact: int
    retry_delay_minutes: int
    total_contacts: int
    contacts_called: int
    contacts_completed: int
    contacts_failed: int
    total_call_duration_seconds: int
    # Error tracking
    last_error: str | None = None
    error_count: int = 0
    last_error_at: datetime | None = None
    # Timestamps
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CampaignCreate(BaseModel):
    """Campaign creation schema."""

    workspace_id: str
    agent_id: str
    name: str
    description: str | None = None
    from_phone_number: str
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None
    # Scheduler fields
    calling_hours_start: str | None = None  # Time as HH:MM string
    calling_hours_end: str | None = None  # Time as HH:MM string
    calling_days: list[int] | None = None  # 0=Mon, 6=Sun
    timezone: str | None = "UTC"
    # Call settings
    calls_per_minute: int = 2
    max_concurrent_calls: int = 1
    max_attempts_per_contact: int = 3
    retry_delay_minutes: int = 60
    contact_ids: list[int] = []

    @field_validator("workspace_id", "agent_id")
    @classmethod
    def validate_uuid(cls, v: str) -> str:
        """Validate UUID fields."""
        try:
            uuid.UUID(v)
        except ValueError as e:
            raise ValueError("Must be a valid UUID") from e
        return v

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate campaign name."""
        v = v.strip()
        if not v:
            raise ValueError("Campaign name cannot be empty")
        if len(v) > MAX_CAMPAIGN_NAME_LENGTH:
            raise ValueError(f"Campaign name cannot exceed {MAX_CAMPAIGN_NAME_LENGTH} characters")
        return v

    @field_validator("from_phone_number")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        """Validate phone number format."""
        v = v.strip()
        if not v:
            raise ValueError("Phone number cannot be empty")
        return v

    @field_validator("calls_per_minute")
    @classmethod
    def validate_calls_per_minute(cls, v: int) -> int:
        """Validate calls per minute."""
        if v < 1 or v > MAX_CALLS_PER_MINUTE:
            raise ValueError(f"calls_per_minute must be between 1 and {MAX_CALLS_PER_MINUTE}")
        return v

    @field_validator("max_concurrent_calls")
    @classmethod
    def validate_max_concurrent(cls, v: int) -> int:
        """Validate max concurrent calls."""
        if v < 1 or v > MAX_CONCURRENT_CALLS:
            raise ValueError(f"max_concurrent_calls must be between 1 and {MAX_CONCURRENT_CALLS}")
        return v

    @field_validator("calling_hours_start", "calling_hours_end")
    @classmethod
    def validate_time_format(cls, v: str | None) -> str | None:
        """Validate time format (HH:MM)."""
        if v is None:
            return v
        parts = v.split(":")
        if len(parts) != TIME_PARTS_COUNT:
            raise ValueError("Time must be in HH:MM format (e.g., 09:00)")
        try:
            hour, minute = int(parts[0]), int(parts[1])
        except ValueError as e:
            raise ValueError("Time must be in HH:MM format (e.g., 09:00)") from e
        if not (0 <= hour <= MAX_HOUR and 0 <= minute <= MAX_MINUTE):
            raise ValueError("Invalid time values")
        return v

    @field_validator("calling_days")
    @classmethod
    def validate_calling_days(cls, v: list[int] | None) -> list[int] | None:
        """Validate calling days (0-6 for Mon-Sun)."""
        if v is None:
            return v
        for day in v:
            if not (MIN_CALLING_DAY <= day <= MAX_CALLING_DAY):
                raise ValueError("Calling days must be 0-6 (Monday=0, Sunday=6)")
        return sorted(set(v))  # Remove duplicates and sort


class CampaignUpdate(BaseModel):
    """Campaign update schema."""

    name: str | None = None
    description: str | None = None
    from_phone_number: str | None = None
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None
    # Scheduler fields
    calling_hours_start: str | None = None  # Time as HH:MM string
    calling_hours_end: str | None = None  # Time as HH:MM string
    calling_days: list[int] | None = None  # 0=Mon, 6=Sun
    timezone: str | None = None
    # Call settings
    calls_per_minute: int | None = None
    max_concurrent_calls: int | None = None
    max_attempts_per_contact: int | None = None
    retry_delay_minutes: int | None = None


class AddContactsRequest(BaseModel):
    """Request to add contacts to campaign."""

    contact_ids: list[int]


class AddContactsByFilterRequest(BaseModel):
    """Request to add contacts to campaign by filter criteria."""

    status: list[str] | None = None  # Filter by contact status (new, contacted, qualified, etc.)
    tags: list[str] | None = None  # Filter by tags (any match)
    exclude_existing: bool = True  # Exclude contacts already in campaign

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: list[str] | None) -> list[str] | None:
        """Validate status values."""
        if v is None:
            return v
        valid_statuses = {"new", "contacted", "qualified", "converted", "lost"}
        for status in v:
            if status not in valid_statuses:
                raise ValueError(f"Invalid status '{status}'. Valid: {', '.join(valid_statuses)}")
        return v


class FilteredContactsResponse(BaseModel):
    """Response for filtered contacts count."""

    total_matching: int
    already_in_campaign: int
    will_be_added: int


class UpdateDispositionRequest(BaseModel):
    """Request to update contact disposition."""

    disposition: str
    disposition_notes: str | None = None
    callback_requested_at: datetime | None = None

    @field_validator("disposition")
    @classmethod
    def validate_disposition(cls, v: str) -> str:
        """Validate disposition is a valid enum value."""
        valid_dispositions = {d.value for d in CallDisposition}
        if v not in valid_dispositions:
            raise ValueError(
                f"Invalid disposition. Must be one of: {', '.join(valid_dispositions)}"
            )
        return v


class DispositionStatsResponse(BaseModel):
    """Disposition breakdown statistics."""

    total: int
    by_disposition: dict[str, int]
    callbacks_pending: int


class CampaignStatsResponse(BaseModel):
    """Campaign statistics response."""

    total_contacts: int
    contacts_pending: int
    contacts_calling: int
    contacts_completed: int
    contacts_failed: int
    contacts_no_answer: int
    contacts_busy: int
    contacts_skipped: int
    total_calls_made: int
    total_call_duration_seconds: int
    average_call_duration_seconds: float
    completion_rate: float


# =============================================================================
# Helper Functions
# =============================================================================


def format_time(t: time | None) -> str | None:
    """Format time as HH:MM string."""
    if t is None:
        return None
    return t.strftime("%H:%M")


def parse_time(time_str: str | None) -> time | None:
    """Parse HH:MM string to time object."""
    if time_str is None:
        return None
    parts = time_str.split(":")
    return time(hour=int(parts[0]), minute=int(parts[1]))


def campaign_to_response(campaign: Campaign) -> CampaignResponse:
    """Convert Campaign model to response schema."""
    return CampaignResponse(
        id=str(campaign.id),
        workspace_id=str(campaign.workspace_id),
        agent_id=str(campaign.agent_id),
        agent_name=campaign.agent.name if campaign.agent else None,
        name=campaign.name,
        description=campaign.description,
        status=campaign.status,
        from_phone_number=campaign.from_phone_number,
        scheduled_start=campaign.scheduled_start,
        scheduled_end=campaign.scheduled_end,
        calling_hours_start=format_time(campaign.calling_hours_start),
        calling_hours_end=format_time(campaign.calling_hours_end),
        calling_days=campaign.calling_days,
        timezone=campaign.timezone,
        calls_per_minute=campaign.calls_per_minute,
        max_concurrent_calls=campaign.max_concurrent_calls,
        max_attempts_per_contact=campaign.max_attempts_per_contact,
        retry_delay_minutes=campaign.retry_delay_minutes,
        total_contacts=campaign.total_contacts,
        contacts_called=campaign.contacts_called,
        contacts_completed=campaign.contacts_completed,
        contacts_failed=campaign.contacts_failed,
        total_call_duration_seconds=campaign.total_call_duration_seconds,
        last_error=campaign.last_error,
        error_count=campaign.error_count,
        last_error_at=campaign.last_error_at,
        started_at=campaign.started_at,
        completed_at=campaign.completed_at,
        created_at=campaign.created_at,
        updated_at=campaign.updated_at,
    )


async def get_campaign_or_404(campaign_id: str, user_id: int, db: AsyncSession) -> Campaign:
    """Get campaign by ID or raise 404."""
    try:
        campaign_uuid = uuid.UUID(campaign_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid campaign ID") from e

    result = await db.execute(
        select(Campaign)
        .options(selectinload(Campaign.agent))
        .where(Campaign.id == campaign_uuid, Campaign.user_id == user_id_to_uuid(user_id))
    )
    campaign = result.scalar_one_or_none()

    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    return campaign


# =============================================================================
# Campaign CRUD Endpoints
# =============================================================================


@router.get("", response_model=list[CampaignResponse])
async def list_campaigns(
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Query(None, description="Filter by workspace"),
    status: str | None = Query(None, description="Filter by status"),
) -> list[CampaignResponse]:
    """List all campaigns for the user."""
    query = (
        select(Campaign)
        .options(selectinload(Campaign.agent))
        .where(Campaign.user_id == user_id_to_uuid(current_user.id))
        .order_by(Campaign.created_at.desc())
    )

    if workspace_id:
        try:
            ws_uuid = uuid.UUID(workspace_id)
            query = query.where(Campaign.workspace_id == ws_uuid)
        except ValueError:
            pass

    if status:
        query = query.where(Campaign.status == status)

    result = await db.execute(query)
    campaigns = result.scalars().all()

    return [campaign_to_response(c) for c in campaigns]


@router.get("/{campaign_id}", response_model=CampaignResponse)
async def get_campaign(
    campaign_id: str,
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> CampaignResponse:
    """Get a specific campaign."""
    campaign = await get_campaign_or_404(campaign_id, current_user.id, db)
    return campaign_to_response(campaign)


@router.post("", response_model=CampaignResponse)
async def create_campaign(
    data: CampaignCreate,
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> CampaignResponse:
    """Create a new campaign."""
    user_uuid = user_id_to_uuid(current_user.id)

    # Verify agent exists and belongs to user
    agent_uuid = uuid.UUID(data.agent_id)
    result = await db.execute(
        select(Agent).where(Agent.id == agent_uuid, Agent.user_id == user_uuid)
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Create campaign
    campaign = Campaign(
        user_id=user_uuid,
        workspace_id=uuid.UUID(data.workspace_id),
        agent_id=agent_uuid,
        name=data.name,
        description=data.description,
        status=CampaignStatus.DRAFT.value,
        from_phone_number=data.from_phone_number,
        scheduled_start=data.scheduled_start,
        scheduled_end=data.scheduled_end,
        calling_hours_start=parse_time(data.calling_hours_start),
        calling_hours_end=parse_time(data.calling_hours_end),
        calling_days=data.calling_days,
        timezone=data.timezone,
        calls_per_minute=data.calls_per_minute,
        max_concurrent_calls=data.max_concurrent_calls,
        max_attempts_per_contact=data.max_attempts_per_contact,
        retry_delay_minutes=data.retry_delay_minutes,
    )
    db.add(campaign)
    await db.flush()

    # Add contacts if provided
    if data.contact_ids:
        # Verify contacts exist and belong to user
        result = await db.execute(
            select(Contact).where(
                Contact.id.in_(data.contact_ids),
                Contact.user_id == user_uuid,  # Ensure user owns contacts
            )
        )
        contacts = result.scalars().all()
        valid_contact_ids = {c.id for c in contacts}

        for contact_id in data.contact_ids:
            if contact_id in valid_contact_ids:
                campaign_contact = CampaignContact(
                    campaign_id=campaign.id,
                    contact_id=contact_id,
                    status=CampaignContactStatus.PENDING.value,
                )
                db.add(campaign_contact)

        campaign.total_contacts = len(valid_contact_ids)

    await db.commit()
    await db.refresh(campaign)

    # Re-attach agent for response
    campaign.agent = agent
    return campaign_to_response(campaign)


@router.put("/{campaign_id}", response_model=CampaignResponse)
async def update_campaign(
    campaign_id: str,
    data: CampaignUpdate,
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> CampaignResponse:
    """Update a campaign."""
    campaign = await get_campaign_or_404(campaign_id, current_user.id, db)

    # Only allow updates to draft campaigns
    if campaign.status not in (CampaignStatus.DRAFT.value, CampaignStatus.PAUSED.value):
        raise HTTPException(status_code=400, detail="Cannot update a running or completed campaign")

    # Update fields, handling time fields specially
    update_data = data.model_dump(exclude_unset=True)

    # Convert time strings to time objects
    if "calling_hours_start" in update_data:
        update_data["calling_hours_start"] = parse_time(update_data["calling_hours_start"])
    if "calling_hours_end" in update_data:
        update_data["calling_hours_end"] = parse_time(update_data["calling_hours_end"])
    for field, value in update_data.items():
        setattr(campaign, field, value)

    await db.commit()
    await db.refresh(campaign)

    return campaign_to_response(campaign)


@router.delete("/{campaign_id}")
async def delete_campaign(
    campaign_id: str,
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Delete a campaign."""
    campaign = await get_campaign_or_404(campaign_id, current_user.id, db)

    # Don't allow deleting running campaigns
    if campaign.status == CampaignStatus.RUNNING.value:
        raise HTTPException(
            status_code=400, detail="Cannot delete a running campaign. Stop it first."
        )

    await db.delete(campaign)
    await db.commit()

    return {"message": "Campaign deleted successfully"}


# =============================================================================
# Campaign Contact Management
# =============================================================================


@router.get("/{campaign_id}/contacts", response_model=list[CampaignContactResponse])
async def list_campaign_contacts(
    campaign_id: str,
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
    status: str | None = Query(None, description="Filter by status"),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
) -> list[CampaignContactResponse]:
    """List contacts in a campaign."""
    campaign = await get_campaign_or_404(campaign_id, current_user.id, db)

    query = (
        select(CampaignContact)
        .options(selectinload(CampaignContact.contact))
        .where(CampaignContact.campaign_id == campaign.id)
        .order_by(CampaignContact.priority.desc(), CampaignContact.created_at)
        .limit(limit)
        .offset(offset)
    )

    if status:
        query = query.where(CampaignContact.status == status)

    result = await db.execute(query)
    campaign_contacts = result.scalars().all()

    return [
        CampaignContactResponse(
            id=str(cc.id),
            contact_id=cc.contact_id,
            status=cc.status,
            attempts=cc.attempts,
            last_attempt_at=cc.last_attempt_at,
            next_attempt_at=cc.next_attempt_at,
            last_call_duration_seconds=cc.last_call_duration_seconds,
            last_call_outcome=cc.last_call_outcome,
            priority=cc.priority,
            disposition=cc.disposition,
            disposition_notes=cc.disposition_notes,
            callback_requested_at=cc.callback_requested_at,
            contact_name=f"{cc.contact.first_name} {cc.contact.last_name or ''}".strip()
            if cc.contact
            else None,
            contact_phone=cc.contact.phone_number if cc.contact else None,
        )
        for cc in campaign_contacts
    ]


@router.post("/{campaign_id}/contacts")
async def add_contacts_to_campaign(
    campaign_id: str,
    data: AddContactsRequest,
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    """Add contacts to a campaign."""
    campaign = await get_campaign_or_404(campaign_id, current_user.id, db)

    # Only allow adding to draft campaigns
    if campaign.status != CampaignStatus.DRAFT.value:
        raise HTTPException(status_code=400, detail="Can only add contacts to draft campaigns")

    # Get existing contact IDs in campaign
    result = await db.execute(
        select(CampaignContact.contact_id).where(CampaignContact.campaign_id == campaign.id)
    )
    existing_ids = {row[0] for row in result.fetchall()}

    # Verify contacts exist and belong to user
    # Note: Contact.user_id is an integer, not UUID
    contact_result = await db.execute(
        select(Contact).where(
            Contact.id.in_(data.contact_ids),
            Contact.user_id == current_user.id,  # Ensure user owns contacts
        )
    )
    contacts = contact_result.scalars().all()
    valid_contact_ids = {c.id for c in contacts}

    # Add new contacts
    added = 0
    for contact_id in data.contact_ids:
        if contact_id in valid_contact_ids and contact_id not in existing_ids:
            campaign_contact = CampaignContact(
                campaign_id=campaign.id,
                contact_id=contact_id,
                status=CampaignContactStatus.PENDING.value,
            )
            db.add(campaign_contact)
            added += 1

    if added > 0:
        campaign.total_contacts += added
        await db.commit()

    return {"added": added}


@router.post("/{campaign_id}/contacts/filter/preview", response_model=FilteredContactsResponse)
async def preview_contacts_by_filter(
    campaign_id: str,
    data: AddContactsByFilterRequest,
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> FilteredContactsResponse:
    """Preview how many contacts would be added by filter criteria."""
    campaign = await get_campaign_or_404(campaign_id, current_user.id, db)

    # Build filter query for contacts
    # Note: Contact.user_id is an integer, not UUID
    query = select(Contact).where(Contact.user_id == current_user.id)

    # Filter by workspace if campaign has one
    if campaign.workspace_id:
        query = query.where(Contact.workspace_id == campaign.workspace_id)

    # Filter by status
    if data.status:
        query = query.where(Contact.status.in_(data.status))

    # Filter by tags (any tag matches)
    if data.tags:
        tag_conditions = [Contact.tags.ilike(f"%{tag}%") for tag in data.tags]
        query = query.where(or_(*tag_conditions))

    # Get matching contacts
    result = await db.execute(query)
    matching_contacts = result.scalars().all()
    total_matching = len(matching_contacts)
    matching_ids = {c.id for c in matching_contacts}

    # Get existing contacts in campaign
    existing_result = await db.execute(
        select(CampaignContact.contact_id).where(CampaignContact.campaign_id == campaign.id)
    )
    existing_ids = {row[0] for row in existing_result.fetchall()}

    already_in_campaign = len(matching_ids & existing_ids)
    will_be_added = len(matching_ids - existing_ids) if data.exclude_existing else total_matching

    return FilteredContactsResponse(
        total_matching=total_matching,
        already_in_campaign=already_in_campaign,
        will_be_added=will_be_added,
    )


@router.post("/{campaign_id}/contacts/filter")
async def add_contacts_by_filter(
    campaign_id: str,
    data: AddContactsByFilterRequest,
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    """Add contacts to campaign by filter criteria."""
    campaign = await get_campaign_or_404(campaign_id, current_user.id, db)

    # Only allow adding to draft campaigns
    if campaign.status != CampaignStatus.DRAFT.value:
        raise HTTPException(status_code=400, detail="Can only add contacts to draft campaigns")

    # Build filter query for contacts
    # Note: Contact.user_id is an integer, not UUID
    query = select(Contact).where(Contact.user_id == current_user.id)

    # Filter by workspace if campaign has one
    if campaign.workspace_id:
        query = query.where(Contact.workspace_id == campaign.workspace_id)

    # Filter by status
    if data.status:
        query = query.where(Contact.status.in_(data.status))

    # Filter by tags (any tag matches)
    if data.tags:
        tag_conditions = [Contact.tags.ilike(f"%{tag}%") for tag in data.tags]
        query = query.where(or_(*tag_conditions))

    # Get matching contacts
    result = await db.execute(query)
    matching_contacts = result.scalars().all()
    matching_ids = {c.id for c in matching_contacts}

    # Get existing contacts in campaign if excluding
    existing_ids: set[int] = set()
    if data.exclude_existing:
        existing_result = await db.execute(
            select(CampaignContact.contact_id).where(CampaignContact.campaign_id == campaign.id)
        )
        existing_ids = {row[0] for row in existing_result.fetchall()}

    # Add contacts to campaign
    added = 0
    for contact_id in matching_ids:
        if contact_id not in existing_ids:
            campaign_contact = CampaignContact(
                campaign_id=campaign.id,
                contact_id=contact_id,
                status=CampaignContactStatus.PENDING.value,
            )
            db.add(campaign_contact)
            added += 1

    if added > 0:
        campaign.total_contacts += added
        await db.commit()

    return {"added": added, "total_matching": len(matching_ids)}


@router.delete("/{campaign_id}/contacts/{contact_id}")
async def remove_contact_from_campaign(
    campaign_id: str,
    contact_id: int,
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Remove a contact from a campaign."""
    campaign = await get_campaign_or_404(campaign_id, current_user.id, db)

    # Only allow removing from draft campaigns
    if campaign.status != CampaignStatus.DRAFT.value:
        raise HTTPException(status_code=400, detail="Can only remove contacts from draft campaigns")

    result = await db.execute(
        select(CampaignContact).where(
            CampaignContact.campaign_id == campaign.id,
            CampaignContact.contact_id == contact_id,
        )
    )
    campaign_contact = result.scalar_one_or_none()

    if campaign_contact:
        await db.delete(campaign_contact)
        campaign.total_contacts = max(0, campaign.total_contacts - 1)
        await db.commit()

    return {"message": "Contact removed from campaign"}


# =============================================================================
# Campaign Control
# =============================================================================


@router.post("/{campaign_id}/start", response_model=CampaignResponse)
async def start_campaign(
    campaign_id: str,
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> CampaignResponse:
    """Start a campaign."""
    campaign = await get_campaign_or_404(campaign_id, current_user.id, db)

    if campaign.status not in (CampaignStatus.DRAFT.value, CampaignStatus.PAUSED.value):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot start campaign with status '{campaign.status}'",
        )

    if campaign.total_contacts == 0:
        raise HTTPException(status_code=400, detail="Cannot start campaign with no contacts")

    campaign.status = CampaignStatus.RUNNING.value
    if not campaign.started_at:
        campaign.started_at = datetime.now(UTC)

    await db.commit()
    await db.refresh(campaign)

    return campaign_to_response(campaign)


@router.post("/{campaign_id}/pause", response_model=CampaignResponse)
async def pause_campaign(
    campaign_id: str,
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> CampaignResponse:
    """Pause a running campaign."""
    campaign = await get_campaign_or_404(campaign_id, current_user.id, db)

    if campaign.status != CampaignStatus.RUNNING.value:
        raise HTTPException(status_code=400, detail="Can only pause a running campaign")

    campaign.status = CampaignStatus.PAUSED.value
    await db.commit()
    await db.refresh(campaign)

    return campaign_to_response(campaign)


@router.post("/{campaign_id}/stop", response_model=CampaignResponse)
async def stop_campaign(
    campaign_id: str,
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> CampaignResponse:
    """Stop a campaign (cannot be resumed)."""
    campaign = await get_campaign_or_404(campaign_id, current_user.id, db)

    if campaign.status in (CampaignStatus.COMPLETED.value, CampaignStatus.CANCELED.value):
        raise HTTPException(status_code=400, detail="Campaign is already stopped")

    campaign.status = CampaignStatus.CANCELED.value
    campaign.completed_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(campaign)

    return campaign_to_response(campaign)


@router.post("/{campaign_id}/restart", response_model=CampaignResponse)
async def restart_campaign(
    campaign_id: str,
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> CampaignResponse:
    """Restart a completed or canceled campaign.

    This resets failed/no-answer contacts back to pending status so they can be retried.
    Successfully completed contacts are not reset.
    """
    campaign = await get_campaign_or_404(campaign_id, current_user.id, db)

    if campaign.status not in (CampaignStatus.COMPLETED.value, CampaignStatus.CANCELED.value):
        raise HTTPException(
            status_code=400,
            detail=f"Can only restart completed or canceled campaigns (current: {campaign.status})",
        )

    # Reset contacts that weren't successfully completed back to pending
    # This includes: failed, no_answer, busy, skipped, and calling (stuck) statuses
    reset_statuses = [
        CampaignContactStatus.FAILED.value,
        CampaignContactStatus.NO_ANSWER.value,
        CampaignContactStatus.BUSY.value,
        CampaignContactStatus.SKIPPED.value,
        CampaignContactStatus.CALLING.value,  # Reset stuck "calling" contacts too
    ]

    # Get contacts to reset
    result = await db.execute(
        select(CampaignContact).where(
            CampaignContact.campaign_id == campaign.id,
            CampaignContact.status.in_(reset_statuses),
        )
    )
    contacts_to_reset = result.scalars().all()

    # Reset each contact
    for contact in contacts_to_reset:
        contact.status = CampaignContactStatus.PENDING.value
        contact.attempts = 0
        contact.next_attempt_at = None
        contact.last_attempt_at = None
        contact.last_call_outcome = None

    # Update campaign status and clear error fields
    campaign.status = CampaignStatus.RUNNING.value
    campaign.completed_at = None
    campaign.contacts_failed = 0
    campaign.last_error = None
    campaign.error_count = 0
    campaign.last_error_at = None

    await db.commit()
    await db.refresh(campaign)

    return campaign_to_response(campaign)


# =============================================================================
# Campaign Statistics
# =============================================================================


@router.get("/{campaign_id}/stats", response_model=CampaignStatsResponse)
async def get_campaign_stats(
    campaign_id: str,
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> CampaignStatsResponse:
    """Get detailed statistics for a campaign."""
    campaign = await get_campaign_or_404(campaign_id, current_user.id, db)

    # Get status counts
    result = await db.execute(
        select(CampaignContact.status, func.count(CampaignContact.id))
        .where(CampaignContact.campaign_id == campaign.id)
        .group_by(CampaignContact.status)
    )
    status_counts: dict[str, int] = {row[0]: row[1] for row in result.fetchall()}

    total_calls = campaign.contacts_called
    avg_duration = campaign.total_call_duration_seconds / total_calls if total_calls > 0 else 0
    completion_rate = (
        campaign.contacts_completed / campaign.total_contacts * 100
        if campaign.total_contacts > 0
        else 0
    )

    return CampaignStatsResponse(
        total_contacts=campaign.total_contacts,
        contacts_pending=status_counts.get(CampaignContactStatus.PENDING.value, 0),
        contacts_calling=status_counts.get(CampaignContactStatus.CALLING.value, 0),
        contacts_completed=status_counts.get(CampaignContactStatus.COMPLETED.value, 0),
        contacts_failed=status_counts.get(CampaignContactStatus.FAILED.value, 0),
        contacts_no_answer=status_counts.get(CampaignContactStatus.NO_ANSWER.value, 0),
        contacts_busy=status_counts.get(CampaignContactStatus.BUSY.value, 0),
        contacts_skipped=status_counts.get(CampaignContactStatus.SKIPPED.value, 0),
        total_calls_made=total_calls,
        total_call_duration_seconds=campaign.total_call_duration_seconds,
        average_call_duration_seconds=avg_duration,
        completion_rate=completion_rate,
    )


@router.get("/{campaign_id}/dispositions", response_model=DispositionStatsResponse)
async def get_disposition_stats(
    campaign_id: str,
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> DispositionStatsResponse:
    """Get disposition breakdown statistics for a campaign."""
    campaign = await get_campaign_or_404(campaign_id, current_user.id, db)

    # Get disposition counts
    result = await db.execute(
        select(CampaignContact.disposition, func.count(CampaignContact.id))
        .where(
            CampaignContact.campaign_id == campaign.id,
            CampaignContact.disposition.isnot(None),
        )
        .group_by(CampaignContact.disposition)
    )
    disposition_counts: dict[str, int] = {row[0]: row[1] for row in result.fetchall()}

    # Count pending callbacks
    callback_result = await db.execute(
        select(func.count(CampaignContact.id)).where(
            CampaignContact.campaign_id == campaign.id,
            CampaignContact.callback_requested_at.isnot(None),
            CampaignContact.status != CampaignContactStatus.COMPLETED.value,
        )
    )
    callbacks_pending = callback_result.scalar() or 0

    return DispositionStatsResponse(
        total=sum(disposition_counts.values()),
        by_disposition=disposition_counts,
        callbacks_pending=callbacks_pending,
    )


@router.put("/{campaign_id}/contacts/{contact_id}/disposition")
async def update_contact_disposition(
    campaign_id: str,
    contact_id: int,
    data: UpdateDispositionRequest,
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> CampaignContactResponse:
    """Update the disposition for a contact in a campaign."""
    campaign = await get_campaign_or_404(campaign_id, current_user.id, db)

    result = await db.execute(
        select(CampaignContact)
        .options(selectinload(CampaignContact.contact))
        .where(
            CampaignContact.campaign_id == campaign.id,
            CampaignContact.contact_id == contact_id,
        )
    )
    campaign_contact = result.scalar_one_or_none()

    if not campaign_contact:
        raise HTTPException(status_code=404, detail="Contact not found in campaign")

    # Update disposition fields
    campaign_contact.disposition = data.disposition
    campaign_contact.disposition_notes = data.disposition_notes
    campaign_contact.callback_requested_at = data.callback_requested_at

    await db.commit()
    await db.refresh(campaign_contact)

    return CampaignContactResponse(
        id=str(campaign_contact.id),
        contact_id=campaign_contact.contact_id,
        status=campaign_contact.status,
        attempts=campaign_contact.attempts,
        last_attempt_at=campaign_contact.last_attempt_at,
        next_attempt_at=campaign_contact.next_attempt_at,
        last_call_duration_seconds=campaign_contact.last_call_duration_seconds,
        last_call_outcome=campaign_contact.last_call_outcome,
        priority=campaign_contact.priority,
        disposition=campaign_contact.disposition,
        disposition_notes=campaign_contact.disposition_notes,
        callback_requested_at=campaign_contact.callback_requested_at,
        contact_name=f"{campaign_contact.contact.first_name} {campaign_contact.contact.last_name or ''}".strip()
        if campaign_contact.contact
        else None,
        contact_phone=campaign_contact.contact.phone_number if campaign_contact.contact else None,
    )


@router.get("/dispositions/options")
async def get_disposition_options() -> dict[str, list[dict[str, str]]]:
    """Get available disposition options grouped by category."""
    return {
        "positive": [
            {"value": CallDisposition.INTERESTED.value, "label": "Interested"},
            {"value": CallDisposition.APPOINTMENT_BOOKED.value, "label": "Appointment Booked"},
            {"value": CallDisposition.SALE_MADE.value, "label": "Sale Made"},
            {"value": CallDisposition.CALLBACK_REQUESTED.value, "label": "Callback Requested"},
            {"value": CallDisposition.INFO_SENT.value, "label": "Info Sent"},
        ],
        "neutral": [
            {"value": CallDisposition.VOICEMAIL_LEFT.value, "label": "Voicemail Left"},
            {"value": CallDisposition.WRONG_NUMBER.value, "label": "Wrong Number"},
            {"value": CallDisposition.NOT_AVAILABLE.value, "label": "Not Available"},
            {"value": CallDisposition.TRANSFERRED.value, "label": "Transferred"},
        ],
        "negative": [
            {"value": CallDisposition.NOT_INTERESTED.value, "label": "Not Interested"},
            {"value": CallDisposition.DO_NOT_CALL.value, "label": "Do Not Call"},
            {"value": CallDisposition.HUNG_UP.value, "label": "Hung Up"},
            {"value": CallDisposition.INVALID_NUMBER.value, "label": "Invalid Number"},
        ],
        "technical": [
            {"value": CallDisposition.NO_ANSWER.value, "label": "No Answer"},
            {"value": CallDisposition.BUSY.value, "label": "Busy"},
            {"value": CallDisposition.FAILED.value, "label": "Failed"},
            {"value": CallDisposition.MACHINE_DETECTED.value, "label": "Machine Detected"},
        ],
    }
