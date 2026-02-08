"""Stripe service for billing and subscription management.

This service reads Stripe credentials from system settings (configured by superadmin).
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import stripe
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing import Invoice, InvoiceStatus, PaymentMethod
from app.models.organization import Organization, PlanType, SubscriptionStatus
from app.models.system_settings import SystemSettings

logger = structlog.get_logger()


class StripeServiceError(Exception):
    """Base exception for Stripe service errors."""


class StripeNotConfiguredError(StripeServiceError):
    """Raised when Stripe is not configured in system settings."""


class StripeAPIError(StripeServiceError):
    """Raised when Stripe API returns an error."""


# Plan limits configuration
PLAN_LIMITS: dict[str, dict[str, int | float]] = {
    "free": {
        "voice_minutes": 10,
        "llm_requests": 100,
        "llm_tokens": 10000,
        "image_generations": 5,
        "video_minutes": 0,
        "storage_gb": 1,
        "max_agents": 1,
        "max_workspaces": 1,
    },
    "starter": {
        "voice_minutes": 500,
        "llm_requests": 10_000,
        "llm_tokens": 500_000,
        "image_generations": 100,
        "video_minutes": 30,
        "storage_gb": 10,
        "max_agents": 5,
        "max_workspaces": 3,
    },
    "professional": {
        "voice_minutes": 2000,
        "llm_requests": 50_000,
        "llm_tokens": 2_000_000,
        "image_generations": 500,
        "video_minutes": 120,
        "storage_gb": 50,
        "max_agents": 20,
        "max_workspaces": 10,
    },
    "enterprise": {
        "voice_minutes": -1,  # Unlimited
        "llm_requests": -1,
        "llm_tokens": -1,
        "image_generations": -1,
        "video_minutes": -1,
        "storage_gb": -1,
        "max_agents": -1,
        "max_workspaces": -1,
    },
}


async def get_stripe_config(db: AsyncSession) -> dict[str, str | None]:
    """Get Stripe configuration from system settings.

    Args:
        db: Database session

    Returns:
        Dictionary with Stripe configuration

    Raises:
        StripeNotConfiguredError: If Stripe is not configured
    """
    result = await db.execute(select(SystemSettings).where(SystemSettings.key.like("stripe_%")))
    settings: dict[str, str | None] = {s.key: s.value for s in result.scalars().all()}

    if not settings.get("stripe_secret_key"):
        msg = "Stripe not configured. Superadmin must configure it in Settings > System."
        raise StripeNotConfiguredError(msg)

    return settings


async def _init_stripe(db: AsyncSession) -> dict[str, str | None]:
    """Initialize Stripe with API key from settings.

    Args:
        db: Database session

    Returns:
        Stripe configuration dictionary

    Raises:
        StripeNotConfiguredError: If Stripe is not configured
    """
    config = await get_stripe_config(db)
    stripe.api_key = config["stripe_secret_key"]
    return config


async def create_customer(
    db: AsyncSession,
    organization: Organization,
) -> str:
    """Create a Stripe customer for an organization.

    Args:
        db: Database session
        organization: Organization to create customer for

    Returns:
        Stripe customer ID

    Raises:
        StripeAPIError: If Stripe API fails
    """
    log = logger.bind(organization_id=str(organization.id))

    try:
        await _init_stripe(db)

        # Use billing email if set, otherwise use owner's email
        email = organization.billing_email
        if not email and organization.owner:
            email = organization.owner.email
        if not email:
            email = "billing@example.com"  # Fallback email

        customer = stripe.Customer.create(
            name=organization.name,
            email=email,
            metadata={
                "organization_id": str(organization.id),
                "organization_slug": organization.slug,
            },
        )

        # Update organization with customer ID
        organization.stripe_customer_id = customer.id
        db.add(organization)
        await db.flush()

        log.info("stripe_customer_created", customer_id=customer.id)
        return str(customer.id)

    except stripe.StripeError as e:
        log.error("stripe_customer_creation_failed", error=str(e))
        raise StripeAPIError(f"Failed to create Stripe customer: {e}") from e


async def create_checkout_session(
    db: AsyncSession,
    organization: Organization,
    price_id: str,
    success_url: str,
    cancel_url: str,
) -> str:
    """Create a Stripe Checkout session for subscription.

    Args:
        db: Database session
        organization: Organization subscribing
        price_id: Stripe price ID
        success_url: URL to redirect on success
        cancel_url: URL to redirect on cancel

    Returns:
        Checkout session URL

    Raises:
        StripeAPIError: If Stripe API fails
    """
    log = logger.bind(organization_id=str(organization.id))

    try:
        await _init_stripe(db)

        # Create customer if not exists
        if not organization.stripe_customer_id:
            await create_customer(db, organization)

        if not organization.stripe_customer_id:
            raise StripeAPIError("Failed to create or retrieve Stripe customer ID")

        session = stripe.checkout.Session.create(
            customer=organization.stripe_customer_id,
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={
                "organization_id": str(organization.id),
            },
            subscription_data={
                "metadata": {
                    "organization_id": str(organization.id),
                },
            },
        )

        log.info("checkout_session_created", session_id=session.id)
        return session.url or ""

    except stripe.StripeError as e:
        log.error("checkout_session_creation_failed", error=str(e))
        raise StripeAPIError(f"Failed to create checkout session: {e}") from e


async def create_subscription(
    db: AsyncSession,
    organization: Organization,
    price_id: str,
) -> str:
    """Create a subscription for an organization.

    Args:
        db: Database session
        organization: Organization to subscribe
        price_id: Stripe price ID

    Returns:
        Subscription ID

    Raises:
        StripeAPIError: If Stripe API fails
    """
    log = logger.bind(organization_id=str(organization.id))

    try:
        await _init_stripe(db)

        # Create customer if not exists
        if not organization.stripe_customer_id:
            await create_customer(db, organization)

        # Get default payment method
        if not organization.payment_methods:
            raise StripeAPIError("No payment method available")

        default_pm = next((pm for pm in organization.payment_methods if pm.is_default), None)
        if not default_pm:
            default_pm = organization.payment_methods[0]

        if not organization.stripe_customer_id:
            raise StripeAPIError("Organization has no Stripe customer ID")

        subscription = stripe.Subscription.create(
            customer=organization.stripe_customer_id,
            items=[{"price": price_id}],
            default_payment_method=default_pm.stripe_payment_method_id,
            metadata={
                "organization_id": str(organization.id),
            },
        )

        # Update organization
        organization.stripe_subscription_id = subscription.id
        organization.stripe_price_id = price_id
        organization.subscription_status = SubscriptionStatus.ACTIVE
        organization.subscription_started_at = datetime.now(UTC)
        db.add(organization)
        await db.flush()

        log.info("subscription_created", subscription_id=subscription.id)
        return str(subscription.id)

    except stripe.StripeError as e:
        log.error("subscription_creation_failed", error=str(e))
        raise StripeAPIError(f"Failed to create subscription: {e}") from e


async def cancel_subscription(
    db: AsyncSession,
    organization: Organization,
    cancel_at_period_end: bool = True,
) -> None:
    """Cancel a subscription.

    Args:
        db: Database session
        organization: Organization with subscription
        cancel_at_period_end: If True, cancel at end of billing period

    Raises:
        StripeAPIError: If Stripe API fails
    """
    log = logger.bind(organization_id=str(organization.id))

    if not organization.stripe_subscription_id:
        raise StripeAPIError("No active subscription to cancel")

    try:
        await _init_stripe(db)

        if cancel_at_period_end:
            stripe.Subscription.modify(
                organization.stripe_subscription_id,
                cancel_at_period_end=True,
            )
        else:
            stripe.Subscription.cancel(organization.stripe_subscription_id)
            organization.subscription_status = SubscriptionStatus.CANCELLED
            organization.stripe_subscription_id = None
            organization.stripe_price_id = None
            db.add(organization)
            await db.flush()

        log.info(
            "subscription_cancelled",
            subscription_id=organization.stripe_subscription_id,
            at_period_end=cancel_at_period_end,
        )

    except stripe.StripeError as e:
        log.error("subscription_cancellation_failed", error=str(e))
        raise StripeAPIError(f"Failed to cancel subscription: {e}") from e


async def change_plan(
    db: AsyncSession,
    organization: Organization,
    new_price_id: str,
) -> None:
    """Change subscription plan (upgrade/downgrade).

    Args:
        db: Database session
        organization: Organization with subscription
        new_price_id: New Stripe price ID

    Raises:
        StripeAPIError: If Stripe API fails
    """
    log = logger.bind(organization_id=str(organization.id))

    if not organization.stripe_subscription_id:
        raise StripeAPIError("No active subscription to modify")

    try:
        await _init_stripe(db)

        # Get current subscription
        subscription = stripe.Subscription.retrieve(organization.stripe_subscription_id)

        # Update the subscription item with new price
        stripe.Subscription.modify(
            organization.stripe_subscription_id,
            items=[
                {
                    "id": subscription["items"]["data"][0]["id"],
                    "price": new_price_id,
                }
            ],
            proration_behavior="create_prorations",
        )

        # Update organization
        organization.stripe_price_id = new_price_id
        db.add(organization)
        await db.flush()

        log.info("plan_changed", new_price_id=new_price_id)

    except stripe.StripeError as e:
        log.error("plan_change_failed", error=str(e))
        raise StripeAPIError(f"Failed to change plan: {e}") from e


async def reactivate_subscription(
    db: AsyncSession,
    organization: Organization,
) -> None:
    """Reactivate a subscription that was set to cancel at period end.

    Args:
        db: Database session
        organization: Organization with subscription

    Raises:
        StripeAPIError: If Stripe API fails
    """
    log = logger.bind(organization_id=str(organization.id))

    if not organization.stripe_subscription_id:
        raise StripeAPIError("No subscription to reactivate")

    try:
        await _init_stripe(db)

        stripe.Subscription.modify(
            organization.stripe_subscription_id,
            cancel_at_period_end=False,
        )

        log.info("subscription_reactivated", subscription_id=organization.stripe_subscription_id)

    except stripe.StripeError as e:
        log.error("subscription_reactivation_failed", error=str(e))
        raise StripeAPIError(f"Failed to reactivate subscription: {e}") from e


async def attach_payment_method(
    db: AsyncSession,
    organization: Organization,
    payment_method_id: str,
    set_as_default: bool = True,
) -> PaymentMethod:
    """Attach a payment method to an organization's customer.

    Args:
        db: Database session
        organization: Organization to attach to
        payment_method_id: Stripe payment method ID
        set_as_default: Whether to set as default payment method

    Returns:
        Created PaymentMethod record

    Raises:
        StripeAPIError: If Stripe API fails
    """
    log = logger.bind(organization_id=str(organization.id))

    try:
        await _init_stripe(db)

        # Create customer if not exists
        if not organization.stripe_customer_id:
            await create_customer(db, organization)

        if not organization.stripe_customer_id:
            raise StripeAPIError("Failed to create or retrieve Stripe customer ID")

        # Attach payment method to customer
        pm = stripe.PaymentMethod.attach(
            payment_method_id,
            customer=organization.stripe_customer_id,
        )

        # Set as default if requested
        if set_as_default:
            stripe.Customer.modify(
                organization.stripe_customer_id,
                invoice_settings={"default_payment_method": payment_method_id},
            )
            # Unset other default payment methods
            from sqlalchemy import update

            await db.execute(
                update(PaymentMethod)
                .where(PaymentMethod.organization_id == organization.id)
                .values(is_default=False)
            )

        # Create local record
        card = pm.get("card", {}) if pm.get("card") else {}
        bank = pm.get("us_bank_account", {}) if pm.get("us_bank_account") else {}

        payment_method = PaymentMethod(
            stripe_payment_method_id=payment_method_id,
            organization_id=organization.id,
            type=pm.get("type", "card"),
            is_default=set_as_default,
            card_brand=card.get("brand"),
            card_last4=card.get("last4"),
            card_exp_month=card.get("exp_month"),
            card_exp_year=card.get("exp_year"),
            bank_name=bank.get("bank_name"),
            bank_last4=bank.get("last4"),
            billing_details=pm.get("billing_details", {}),
        )
        db.add(payment_method)
        await db.flush()

        # Update organization's last4 for display
        if set_as_default:
            organization.payment_method_last4 = card.get("last4") or bank.get("last4")
            db.add(organization)
            await db.flush()

        log.info("payment_method_attached", payment_method_id=payment_method_id)
        return payment_method

    except stripe.StripeError as e:
        log.error("payment_method_attach_failed", error=str(e))
        raise StripeAPIError(f"Failed to attach payment method: {e}") from e


async def detach_payment_method(
    db: AsyncSession,
    organization: Organization,
    payment_method_id: str,
) -> None:
    """Detach a payment method from an organization's customer.

    Args:
        db: Database session
        organization: Organization
        payment_method_id: Stripe payment method ID

    Raises:
        StripeAPIError: If Stripe API fails
    """
    log = logger.bind(organization_id=str(organization.id))

    try:
        await _init_stripe(db)

        stripe.PaymentMethod.detach(payment_method_id)

        # Remove local record
        result = await db.execute(
            select(PaymentMethod).where(PaymentMethod.stripe_payment_method_id == payment_method_id)
        )
        pm = result.scalar_one_or_none()
        if pm:
            await db.delete(pm)
            await db.flush()

        log.info("payment_method_detached", payment_method_id=payment_method_id)

    except stripe.StripeError as e:
        log.error("payment_method_detach_failed", error=str(e))
        raise StripeAPIError(f"Failed to detach payment method: {e}") from e


async def create_portal_session(
    db: AsyncSession,
    organization: Organization,
    return_url: str,
) -> str:
    """Create a Stripe billing portal session.

    Args:
        db: Database session
        organization: Organization
        return_url: URL to return to after portal session

    Returns:
        Portal session URL

    Raises:
        StripeAPIError: If Stripe API fails
    """
    log = logger.bind(organization_id=str(organization.id))

    if not organization.stripe_customer_id:
        raise StripeAPIError("Organization has no Stripe customer")

    try:
        await _init_stripe(db)

        session = stripe.billing_portal.Session.create(
            customer=organization.stripe_customer_id,
            return_url=return_url,
        )

        log.info("portal_session_created")
        return str(session.url)

    except stripe.StripeError as e:
        log.error("portal_session_creation_failed", error=str(e))
        raise StripeAPIError(f"Failed to create portal session: {e}") from e


async def get_upcoming_invoice(
    db: AsyncSession,
    organization: Organization,
) -> dict[str, Any]:
    """Get the upcoming invoice for an organization.

    Args:
        db: Database session
        organization: Organization

    Returns:
        Invoice details

    Raises:
        StripeAPIError: If Stripe API fails
    """
    log = logger.bind(organization_id=str(organization.id))

    if not organization.stripe_customer_id:
        raise StripeAPIError("Organization has no Stripe customer")

    try:
        await _init_stripe(db)

        invoice = stripe.Invoice.create_preview(customer=organization.stripe_customer_id)

        return {
            "amount_due": invoice.amount_due,
            "currency": invoice.currency,
            "period_start": datetime.fromtimestamp(invoice.period_start, tz=UTC)
            if invoice.period_start
            else None,
            "period_end": datetime.fromtimestamp(invoice.period_end, tz=UTC)
            if invoice.period_end
            else None,
            "next_payment_attempt": (
                datetime.fromtimestamp(invoice.next_payment_attempt, tz=UTC)
                if invoice.next_payment_attempt
                else None
            ),
            "lines": [
                {
                    "description": line.description,
                    "amount": line.amount,
                    "quantity": line.quantity,
                }
                for line in invoice.lines.data
            ],
        }

    except stripe.StripeError as e:
        log.error("upcoming_invoice_fetch_failed", error=str(e))
        raise StripeAPIError(f"Failed to fetch upcoming invoice: {e}") from e


async def report_usage(
    db: AsyncSession,
    organization: Organization,
    resource_type: str,
    quantity: int,
    timestamp: datetime | None = None,
) -> None:
    """Report metered usage to Stripe (for usage-based billing).

    Args:
        db: Database session
        organization: Organization
        resource_type: Type of resource used
        quantity: Amount used
        timestamp: Optional timestamp (defaults to now)

    Raises:
        StripeAPIError: If Stripe API fails
    """
    log = logger.bind(organization_id=str(organization.id), resource_type=resource_type)

    if not organization.stripe_subscription_id:
        log.debug("no_subscription_for_usage_reporting")
        return

    try:
        config = await _init_stripe(db)

        # Get the metered price ID for this resource type from config
        price_key = f"stripe_price_{resource_type}_overage"
        metered_price_id = config.get(price_key)

        if not metered_price_id:
            log.debug("no_metered_price_for_resource", resource_type=resource_type)
            return

        # Get subscription item for this price
        subscription = stripe.Subscription.retrieve(organization.stripe_subscription_id)

        subscription_item = None
        for item in subscription["items"]["data"]:
            if item["price"]["id"] == metered_price_id:
                subscription_item = item
                break

        if not subscription_item:
            log.debug("no_subscription_item_for_metered_price", metered_price_id=metered_price_id)
            return

        # Create usage record
        ts = timestamp or datetime.now(UTC)
        stripe.UsageRecord.create(  # type: ignore[attr-defined]
            subscription_item=subscription_item["id"],
            quantity=quantity,
            timestamp=int(ts.timestamp()),
            action="increment",
        )

        log.info("usage_reported", quantity=quantity)

    except stripe.StripeError as e:
        log.error("usage_reporting_failed", error=str(e))
        # Don't raise - usage reporting failure shouldn't block operations


async def sync_invoice_from_stripe(
    db: AsyncSession,
    stripe_invoice: Any,
    organization_id: uuid.UUID,
) -> Invoice:
    """Sync an invoice from Stripe to local database.

    Args:
        db: Database session
        stripe_invoice: Stripe invoice object
        organization_id: Organization ID

    Returns:
        Created or updated Invoice record
    """
    # Check if invoice already exists
    result = await db.execute(select(Invoice).where(Invoice.stripe_invoice_id == stripe_invoice.id))
    invoice = result.scalar_one_or_none()

    # Map Stripe status to our status
    status_map = {
        "draft": InvoiceStatus.DRAFT,
        "open": InvoiceStatus.OPEN,
        "paid": InvoiceStatus.PAID,
        "void": InvoiceStatus.VOID,
        "uncollectible": InvoiceStatus.UNCOLLECTIBLE,
    }
    status = status_map.get(stripe_invoice.status, InvoiceStatus.DRAFT)

    if invoice:
        # Update existing
        invoice.status = status.value
        invoice.amount_due = stripe_invoice.amount_due or 0
        invoice.amount_paid = stripe_invoice.amount_paid or 0
        invoice.subtotal = stripe_invoice.subtotal or 0
        invoice.tax = stripe_invoice.tax or 0
        invoice.total = stripe_invoice.total or 0
        invoice.invoice_pdf_url = stripe_invoice.invoice_pdf
        invoice.hosted_invoice_url = stripe_invoice.hosted_invoice_url
        if stripe_invoice.status == "paid":
            invoice.paid_at = datetime.now(UTC)
    else:
        # Create new
        invoice = Invoice(
            stripe_invoice_id=stripe_invoice.id,
            organization_id=organization_id,
            status=status.value,
            currency=stripe_invoice.currency or "usd",
            amount_due=stripe_invoice.amount_due or 0,
            amount_paid=stripe_invoice.amount_paid or 0,
            subtotal=stripe_invoice.subtotal or 0,
            tax=stripe_invoice.tax or 0,
            total=stripe_invoice.total or 0,
            invoice_pdf_url=stripe_invoice.invoice_pdf,
            hosted_invoice_url=stripe_invoice.hosted_invoice_url,
            period_start=(
                datetime.fromtimestamp(stripe_invoice.period_start, tz=UTC)
                if stripe_invoice.period_start
                else None
            ),
            period_end=(
                datetime.fromtimestamp(stripe_invoice.period_end, tz=UTC)
                if stripe_invoice.period_end
                else None
            ),
            due_date=(
                datetime.fromtimestamp(stripe_invoice.due_date, tz=UTC)
                if stripe_invoice.due_date
                else None
            ),
            line_items=[
                {
                    "id": line.id,
                    "description": line.description,
                    "amount": line.amount,
                    "quantity": line.quantity,
                }
                for line in (stripe_invoice.lines.data if stripe_invoice.lines else [])
            ],
        )
        db.add(invoice)

    await db.flush()
    return invoice


def get_plan_limits(plan_type: PlanType) -> dict[str, int | float]:
    """Get limits for a plan type.

    Args:
        plan_type: The plan type

    Returns:
        Dictionary of resource limits
    """
    return PLAN_LIMITS.get(plan_type.value, PLAN_LIMITS["free"])
