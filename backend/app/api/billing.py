"""Billing API endpoints for subscription and payment management."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import VerifiedUser
from app.db.session import get_db
from app.models.billing import Invoice, PaymentMethod
from app.models.organization import Organization, PlanType, SubscriptionStatus
from app.services.stripe_service import (
    PLAN_LIMITS,
    StripeAPIError,
    StripeNotConfiguredError,
    attach_payment_method,
    cancel_subscription,
    change_plan,
    create_checkout_session,
    create_portal_session,
    detach_payment_method,
    get_upcoming_invoice,
    reactivate_subscription,
)

router = APIRouter(prefix="/api/v1/billing", tags=["billing"])


# =============================================================================
# Request/Response Models
# =============================================================================


class SubscriptionResponse(BaseModel):
    """Current subscription details."""

    plan_type: str
    status: str
    stripe_subscription_id: str | None
    stripe_price_id: str | None
    subscription_started_at: str | None
    subscription_ends_at: str | None
    next_billing_date: str | None
    cancel_at_period_end: bool = False

    class Config:
        from_attributes = True


class CreateCheckoutRequest(BaseModel):
    """Request to create a Stripe Checkout session."""

    price_id: str
    success_url: str
    cancel_url: str


class CheckoutResponse(BaseModel):
    """Checkout session URL response."""

    checkout_url: str


class ChangePlanRequest(BaseModel):
    """Request to change subscription plan."""

    new_price_id: str


class AttachPaymentMethodRequest(BaseModel):
    """Request to attach a payment method."""

    payment_method_id: str
    set_as_default: bool = True


class PaymentMethodResponse(BaseModel):
    """Payment method details."""

    id: str
    type: str
    is_default: bool
    card_brand: str | None
    card_last4: str | None
    card_exp_month: int | None
    card_exp_year: int | None
    bank_name: str | None
    bank_last4: str | None

    class Config:
        from_attributes = True


class InvoiceResponse(BaseModel):
    """Invoice details."""

    id: str
    stripe_invoice_id: str
    status: str
    currency: str
    amount_due: int
    amount_paid: int
    total: int
    invoice_pdf_url: str | None
    hosted_invoice_url: str | None
    period_start: str | None
    period_end: str | None
    created_at: str

    class Config:
        from_attributes = True


class UpcomingInvoiceResponse(BaseModel):
    """Upcoming invoice preview."""

    amount_due: int
    currency: str
    period_start: str | None
    period_end: str | None
    next_payment_attempt: str | None
    lines: list[dict[str, Any]]


class PortalSessionResponse(BaseModel):
    """Billing portal session URL."""

    portal_url: str


class PlanInfo(BaseModel):
    """Plan information."""

    plan_type: str
    name: str
    limits: dict[str, int | float]


# =============================================================================
# Helper Functions
# =============================================================================


async def _get_user_organization(db: AsyncSession, user: VerifiedUser) -> Organization:
    """Get the organization for the current user."""
    result = await db.execute(
        select(Organization)
        .where(Organization.id == user.organization_id)
        .options(selectinload(Organization.payment_methods))
    )
    org = result.scalar_one_or_none()

    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    return org


# =============================================================================
# Subscription Endpoints
# =============================================================================


@router.get("/subscription", response_model=SubscriptionResponse)
async def get_subscription(
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> SubscriptionResponse:
    """Get current subscription details."""
    org = await _get_user_organization(db, current_user)

    return SubscriptionResponse(
        plan_type=org.plan_type.value if isinstance(org.plan_type, PlanType) else org.plan_type,
        status=org.subscription_status.value
        if isinstance(org.subscription_status, SubscriptionStatus)
        else org.subscription_status,
        stripe_subscription_id=org.stripe_subscription_id,
        stripe_price_id=org.stripe_price_id,
        subscription_started_at=org.subscription_started_at.isoformat()
        if org.subscription_started_at
        else None,
        subscription_ends_at=org.subscription_ends_at.isoformat()
        if org.subscription_ends_at
        else None,
        next_billing_date=org.next_billing_date.isoformat() if org.next_billing_date else None,
        cancel_at_period_end=org.subscription_ends_at is not None,
    )


@router.post("/checkout", response_model=CheckoutResponse)
async def create_checkout(
    request: CreateCheckoutRequest,
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> CheckoutResponse:
    """Create a Stripe Checkout session for subscription."""
    org = await _get_user_organization(db, current_user)

    try:
        checkout_url = await create_checkout_session(
            db=db,
            organization=org,
            price_id=request.price_id,
            success_url=request.success_url,
            cancel_url=request.cancel_url,
        )

        await db.commit()
        return CheckoutResponse(checkout_url=checkout_url)

    except StripeNotConfiguredError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        ) from e
    except StripeAPIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


@router.post("/subscription/cancel")
async def cancel_subscription_endpoint(
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
    cancel_immediately: bool = False,
) -> dict[str, str]:
    """Cancel the current subscription."""
    org = await _get_user_organization(db, current_user)

    try:
        await cancel_subscription(db, org, cancel_at_period_end=not cancel_immediately)
        await db.commit()

        if cancel_immediately:
            return {"message": "Subscription cancelled immediately"}
        return {"message": "Subscription will be cancelled at the end of the billing period"}

    except StripeNotConfiguredError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        ) from e
    except StripeAPIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


@router.post("/subscription/reactivate")
async def reactivate_subscription_endpoint(
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Reactivate a subscription that was set to cancel at period end."""
    org = await _get_user_organization(db, current_user)

    try:
        await reactivate_subscription(db, org)
        await db.commit()
        return {"message": "Subscription reactivated"}

    except StripeNotConfiguredError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        ) from e
    except StripeAPIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


@router.post("/subscription/change-plan")
async def change_plan_endpoint(
    request: ChangePlanRequest,
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Change subscription plan (upgrade/downgrade)."""
    org = await _get_user_organization(db, current_user)

    try:
        await change_plan(db, org, request.new_price_id)
        await db.commit()
        return {"message": "Plan changed successfully"}

    except StripeNotConfiguredError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        ) from e
    except StripeAPIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


# =============================================================================
# Payment Method Endpoints
# =============================================================================


@router.get("/payment-methods", response_model=list[PaymentMethodResponse])
async def list_payment_methods(
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> list[PaymentMethodResponse]:
    """List all payment methods for the organization."""
    org = await _get_user_organization(db, current_user)

    result = await db.execute(
        select(PaymentMethod)
        .where(PaymentMethod.organization_id == org.id)
        .order_by(PaymentMethod.is_default.desc(), PaymentMethod.created_at.desc())
    )
    payment_methods = result.scalars().all()

    return [
        PaymentMethodResponse(
            id=str(pm.id),
            type=pm.type,
            is_default=pm.is_default,
            card_brand=pm.card_brand,
            card_last4=pm.card_last4,
            card_exp_month=pm.card_exp_month,
            card_exp_year=pm.card_exp_year,
            bank_name=pm.bank_name,
            bank_last4=pm.bank_last4,
        )
        for pm in payment_methods
    ]


@router.post("/payment-methods/attach", response_model=PaymentMethodResponse)
async def attach_payment_method_endpoint(
    request: AttachPaymentMethodRequest,
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> PaymentMethodResponse:
    """Attach a new payment method."""
    org = await _get_user_organization(db, current_user)

    try:
        pm = await attach_payment_method(
            db=db,
            organization=org,
            payment_method_id=request.payment_method_id,
            set_as_default=request.set_as_default,
        )
        await db.commit()

        return PaymentMethodResponse(
            id=str(pm.id),
            type=pm.type,
            is_default=pm.is_default,
            card_brand=pm.card_brand,
            card_last4=pm.card_last4,
            card_exp_month=pm.card_exp_month,
            card_exp_year=pm.card_exp_year,
            bank_name=pm.bank_name,
            bank_last4=pm.bank_last4,
        )

    except StripeNotConfiguredError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        ) from e
    except StripeAPIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


@router.delete("/payment-methods/{payment_method_id}")
async def detach_payment_method_endpoint(
    payment_method_id: str,
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Detach a payment method."""
    org = await _get_user_organization(db, current_user)

    # Find the local payment method record
    result = await db.execute(
        select(PaymentMethod).where(
            PaymentMethod.organization_id == org.id,
            PaymentMethod.id == uuid.UUID(payment_method_id),
        )
    )
    pm = result.scalar_one_or_none()

    if not pm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment method not found",
        )

    try:
        await detach_payment_method(db, org, pm.stripe_payment_method_id)
        await db.commit()
        return {"message": "Payment method removed"}

    except StripeNotConfiguredError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        ) from e
    except StripeAPIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


# =============================================================================
# Invoice Endpoints
# =============================================================================


@router.get("/invoices", response_model=list[InvoiceResponse])
async def list_invoices(
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
    limit: int = 20,
    offset: int = 0,
) -> list[InvoiceResponse]:
    """List invoices for the organization."""
    org = await _get_user_organization(db, current_user)

    result = await db.execute(
        select(Invoice)
        .where(Invoice.organization_id == org.id)
        .order_by(Invoice.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    invoices = result.scalars().all()

    return [
        InvoiceResponse(
            id=str(inv.id),
            stripe_invoice_id=inv.stripe_invoice_id,
            status=inv.status,
            currency=inv.currency,
            amount_due=inv.amount_due,
            amount_paid=inv.amount_paid,
            total=inv.total,
            invoice_pdf_url=inv.invoice_pdf_url,
            hosted_invoice_url=inv.hosted_invoice_url,
            period_start=inv.period_start.isoformat() if inv.period_start else None,
            period_end=inv.period_end.isoformat() if inv.period_end else None,
            created_at=inv.created_at.isoformat(),
        )
        for inv in invoices
    ]


@router.get("/invoices/upcoming", response_model=UpcomingInvoiceResponse)
async def get_upcoming_invoice_endpoint(
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> UpcomingInvoiceResponse:
    """Get the upcoming invoice preview."""
    org = await _get_user_organization(db, current_user)

    try:
        invoice = await get_upcoming_invoice(db, org)

        return UpcomingInvoiceResponse(
            amount_due=invoice["amount_due"],
            currency=invoice["currency"],
            period_start=invoice["period_start"].isoformat() if invoice["period_start"] else None,
            period_end=invoice["period_end"].isoformat() if invoice["period_end"] else None,
            next_payment_attempt=invoice["next_payment_attempt"].isoformat()
            if invoice["next_payment_attempt"]
            else None,
            lines=invoice["lines"],
        )

    except StripeNotConfiguredError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        ) from e
    except StripeAPIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


# =============================================================================
# Portal Endpoint
# =============================================================================


@router.post("/portal-session", response_model=PortalSessionResponse)
async def create_portal_session_endpoint(
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
    return_url: str | None = None,
) -> PortalSessionResponse:
    """Create a Stripe billing portal session."""
    org = await _get_user_organization(db, current_user)

    if not return_url:
        return_url = "/"

    try:
        portal_url = await create_portal_session(db, org, return_url)
        return PortalSessionResponse(portal_url=portal_url)

    except StripeNotConfiguredError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        ) from e
    except StripeAPIError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


# =============================================================================
# Plan Information
# =============================================================================


@router.get("/plans", response_model=list[PlanInfo])
async def list_plans() -> list[PlanInfo]:
    """List available plans with their limits."""
    plan_names = {
        "free": "Free",
        "starter": "Starter",
        "professional": "Professional",
        "enterprise": "Enterprise",
    }

    return [
        PlanInfo(
            plan_type=plan_type,
            name=plan_names.get(plan_type, plan_type.title()),
            limits=limits,
        )
        for plan_type, limits in PLAN_LIMITS.items()
    ]
