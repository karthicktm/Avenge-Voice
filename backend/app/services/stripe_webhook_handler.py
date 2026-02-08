"""Stripe webhook handler for processing billing events.

Handles Stripe webhook events with idempotency checking via BillingEvent records.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import stripe
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing import (
    BillingEvent,
    BillingEventStatus,
    PaymentMethod,
)
from app.models.organization import Organization, PlanType, SubscriptionStatus
from app.services.stripe_service import (
    get_stripe_config,
    sync_invoice_from_stripe,
)

logger = structlog.get_logger()


class WebhookError(Exception):
    """Webhook processing error."""


class WebhookSignatureError(WebhookError):
    """Invalid webhook signature."""


class WebhookEventAlreadyProcessedError(WebhookError):
    """Event already processed (idempotency check)."""


async def verify_webhook_signature(
    db: AsyncSession,
    payload: bytes,
    signature: str,
) -> dict[str, Any]:
    """Verify Stripe webhook signature and parse event.

    Args:
        db: Database session
        payload: Raw request body
        signature: Stripe-Signature header value

    Returns:
        Parsed Stripe event

    Raises:
        WebhookSignatureError: If signature is invalid
    """
    try:
        config = await get_stripe_config(db)
        webhook_secret = config.get("stripe_webhook_secret")

        if not webhook_secret:
            raise WebhookSignatureError("Webhook secret not configured")

        event = stripe.Webhook.construct_event(payload, signature, webhook_secret)  # type: ignore[no-untyped-call]
        return dict(event)

    except stripe.SignatureVerificationError as e:
        logger.warning("webhook_signature_invalid", error=str(e))
        raise WebhookSignatureError("Invalid signature") from e


async def check_idempotency(
    db: AsyncSession,
    stripe_event_id: str,
) -> bool:
    """Check if event was already processed.

    Args:
        db: Database session
        stripe_event_id: Stripe event ID

    Returns:
        True if event is new, False if already processed
    """
    result = await db.execute(
        select(BillingEvent).where(BillingEvent.stripe_event_id == stripe_event_id)
    )
    existing = result.scalar_one_or_none()
    return existing is None


async def handle_webhook(
    db: AsyncSession,
    event: dict[str, Any],
) -> dict[str, str]:
    """Handle a Stripe webhook event.

    Args:
        db: Database session
        event: Parsed Stripe event

    Returns:
        Result message

    Raises:
        WebhookEventAlreadyProcessedError: If event was already processed
    """
    event_id = event.get("id", "")
    event_type = event.get("type", "")
    log = logger.bind(event_id=event_id, event_type=event_type)

    # Check idempotency
    if not await check_idempotency(db, event_id):
        log.info("webhook_event_already_processed")
        raise WebhookEventAlreadyProcessedError(f"Event {event_id} already processed")

    # Extract organization from event metadata
    org_id = await _extract_organization_id(event)

    # Create billing event record
    billing_event = BillingEvent(
        stripe_event_id=event_id,
        event_type=event_type,
        status=BillingEventStatus.PENDING.value,
        organization_id=org_id,
        payload=event,
    )
    db.add(billing_event)
    await db.flush()

    try:
        # Route to appropriate handler
        handlers = {
            "customer.subscription.created": _handle_subscription_created,
            "customer.subscription.updated": _handle_subscription_updated,
            "customer.subscription.deleted": _handle_subscription_deleted,
            "invoice.paid": _handle_invoice_paid,
            "invoice.payment_failed": _handle_invoice_payment_failed,
            "payment_method.attached": _handle_payment_method_attached,
            "payment_method.detached": _handle_payment_method_detached,
            "checkout.session.completed": _handle_checkout_completed,
        }

        handler = handlers.get(event_type)
        if handler:
            await handler(db, event, org_id)
            billing_event.status = BillingEventStatus.PROCESSED.value
            log.info("webhook_event_processed")
        else:
            billing_event.status = BillingEventStatus.SKIPPED.value
            log.debug("webhook_event_skipped_no_handler")

        billing_event.processed_at = datetime.now(UTC)
        await db.flush()

        return {"status": "processed", "event_id": event_id}

    except Exception as e:
        billing_event.status = BillingEventStatus.FAILED.value
        billing_event.error_message = str(e)
        await db.flush()

        log.exception("webhook_event_processing_failed")
        raise


async def _extract_organization_id(event: dict[str, Any]) -> uuid.UUID | None:
    """Extract organization ID from event metadata.

    Args:
        event: Stripe event

    Returns:
        Organization ID or None
    """
    data = event.get("data", {}).get("object", {})

    # Try subscription metadata
    metadata = data.get("metadata", {})
    org_id_str = metadata.get("organization_id")

    # Try customer metadata if not in main object
    if not org_id_str:
        customer = data.get("customer")
        if isinstance(customer, dict):
            org_id_str = customer.get("metadata", {}).get("organization_id")

    if org_id_str:
        try:
            return uuid.UUID(org_id_str)
        except ValueError:
            pass

    return None


async def _get_organization_by_customer(
    db: AsyncSession,
    customer_id: str,
) -> Organization | None:
    """Get organization by Stripe customer ID.

    Args:
        db: Database session
        customer_id: Stripe customer ID

    Returns:
        Organization or None
    """
    result = await db.execute(
        select(Organization).where(Organization.stripe_customer_id == customer_id)
    )
    return result.scalar_one_or_none()


async def _handle_subscription_created(
    db: AsyncSession,
    event: dict[str, Any],
    org_id: uuid.UUID | None,
) -> None:
    """Handle subscription created event."""
    subscription = event["data"]["object"]
    customer_id = subscription.get("customer")

    # Get organization
    org = None
    if org_id:
        result = await db.execute(select(Organization).where(Organization.id == org_id))
        org = result.scalar_one_or_none()

    if not org and customer_id:
        org = await _get_organization_by_customer(db, customer_id)

    if not org:
        logger.warning("subscription_created_no_org", customer_id=customer_id)
        return

    # Update organization
    org.stripe_subscription_id = subscription["id"]
    org.subscription_status = _map_subscription_status(subscription["status"])

    # Get price ID from subscription items
    items = subscription.get("items", {}).get("data", [])
    if items:
        org.stripe_price_id = items[0].get("price", {}).get("id")

    # Set subscription dates
    if subscription.get("current_period_start"):
        org.subscription_started_at = datetime.fromtimestamp(
            subscription["current_period_start"], tz=UTC
        )
    if subscription.get("current_period_end"):
        org.next_billing_date = datetime.fromtimestamp(subscription["current_period_end"], tz=UTC)

    # Determine plan type from price
    await _update_plan_from_price(db, org)

    db.add(org)
    await db.flush()

    logger.info(
        "subscription_created_processed",
        org_id=str(org.id),
        subscription_id=subscription["id"],
    )


async def _handle_subscription_updated(
    db: AsyncSession,
    event: dict[str, Any],
    org_id: uuid.UUID | None,
) -> None:
    """Handle subscription updated event."""
    subscription = event["data"]["object"]
    customer_id = subscription.get("customer")

    # Get organization
    org = None
    if org_id:
        result = await db.execute(select(Organization).where(Organization.id == org_id))
        org = result.scalar_one_or_none()

    if not org and customer_id:
        org = await _get_organization_by_customer(db, customer_id)

    if not org:
        logger.warning("subscription_updated_no_org", customer_id=customer_id)
        return

    # Update status
    org.subscription_status = _map_subscription_status(subscription["status"])

    # Update price if changed
    items = subscription.get("items", {}).get("data", [])
    if items:
        new_price_id = items[0].get("price", {}).get("id")
        if new_price_id and new_price_id != org.stripe_price_id:
            org.stripe_price_id = new_price_id
            await _update_plan_from_price(db, org)

    # Update billing date
    if subscription.get("current_period_end"):
        org.next_billing_date = datetime.fromtimestamp(subscription["current_period_end"], tz=UTC)

    # Check for cancellation
    if subscription.get("cancel_at_period_end"):
        org.subscription_ends_at = datetime.fromtimestamp(
            subscription["current_period_end"], tz=UTC
        )
    else:
        org.subscription_ends_at = None

    db.add(org)
    await db.flush()

    logger.info(
        "subscription_updated_processed",
        org_id=str(org.id),
        status=subscription["status"],
    )


async def _handle_subscription_deleted(
    db: AsyncSession,
    event: dict[str, Any],
    org_id: uuid.UUID | None,
) -> None:
    """Handle subscription deleted (cancelled) event."""
    subscription = event["data"]["object"]
    customer_id = subscription.get("customer")

    # Get organization
    org = None
    if org_id:
        result = await db.execute(select(Organization).where(Organization.id == org_id))
        org = result.scalar_one_or_none()

    if not org and customer_id:
        org = await _get_organization_by_customer(db, customer_id)

    if not org:
        logger.warning("subscription_deleted_no_org", customer_id=customer_id)
        return

    # Downgrade to free plan
    org.subscription_status = SubscriptionStatus.CANCELLED
    org.stripe_subscription_id = None
    org.stripe_price_id = None
    org.plan_type = PlanType.FREE
    org.subscription_ends_at = datetime.now(UTC)

    # Reset limits to free tier
    org.max_agents = 1
    org.max_workspaces = 1
    org.max_call_minutes_per_month = 10

    db.add(org)
    await db.flush()

    logger.info("subscription_deleted_processed", org_id=str(org.id))


async def _handle_invoice_paid(
    db: AsyncSession,
    event: dict[str, Any],
    org_id: uuid.UUID | None,
) -> None:
    """Handle invoice paid event."""
    invoice_data = event["data"]["object"]
    customer_id = invoice_data.get("customer")

    # Get organization
    org = None
    if org_id:
        result = await db.execute(select(Organization).where(Organization.id == org_id))
        org = result.scalar_one_or_none()

    if not org and customer_id:
        org = await _get_organization_by_customer(db, customer_id)

    if not org:
        logger.warning("invoice_paid_no_org", customer_id=customer_id)
        return

    # Sync invoice to local database
    await sync_invoice_from_stripe(db, stripe.Invoice.construct_from(invoice_data, None), org.id)

    # Ensure subscription is active after successful payment
    if org.subscription_status == SubscriptionStatus.PAST_DUE:
        org.subscription_status = SubscriptionStatus.ACTIVE
        db.add(org)
        await db.flush()

    logger.info("invoice_paid_processed", org_id=str(org.id), invoice_id=invoice_data["id"])


async def _handle_invoice_payment_failed(
    db: AsyncSession,
    event: dict[str, Any],
    org_id: uuid.UUID | None,
) -> None:
    """Handle invoice payment failed event."""
    invoice_data = event["data"]["object"]
    customer_id = invoice_data.get("customer")

    # Get organization
    org = None
    if org_id:
        result = await db.execute(select(Organization).where(Organization.id == org_id))
        org = result.scalar_one_or_none()

    if not org and customer_id:
        org = await _get_organization_by_customer(db, customer_id)

    if not org:
        logger.warning("invoice_payment_failed_no_org", customer_id=customer_id)
        return

    # Mark subscription as past due
    org.subscription_status = SubscriptionStatus.PAST_DUE
    db.add(org)

    # Sync invoice
    await sync_invoice_from_stripe(db, stripe.Invoice.construct_from(invoice_data, None), org.id)

    await db.flush()

    logger.warning("invoice_payment_failed_processed", org_id=str(org.id))

    # TODO: Send notification email about failed payment


async def _handle_payment_method_attached(
    db: AsyncSession,
    event: dict[str, Any],
    org_id: uuid.UUID | None,
) -> None:
    """Handle payment method attached event."""
    pm_data = event["data"]["object"]
    customer_id = pm_data.get("customer")

    # Get organization
    org = None
    if customer_id:
        org = await _get_organization_by_customer(db, customer_id)

    if not org:
        logger.debug("payment_method_attached_no_org", customer_id=customer_id)
        return

    # Check if already exists
    result = await db.execute(
        select(PaymentMethod).where(PaymentMethod.stripe_payment_method_id == pm_data["id"])
    )
    existing = result.scalar_one_or_none()

    if existing:
        logger.debug("payment_method_already_exists", pm_id=pm_data["id"])
        return

    # Create local record
    card = pm_data.get("card", {}) if pm_data.get("card") else {}
    bank = pm_data.get("us_bank_account", {}) if pm_data.get("us_bank_account") else {}

    payment_method = PaymentMethod(
        stripe_payment_method_id=pm_data["id"],
        organization_id=org.id,
        type=pm_data.get("type", "card"),
        is_default=False,
        card_brand=card.get("brand"),
        card_last4=card.get("last4"),
        card_exp_month=card.get("exp_month"),
        card_exp_year=card.get("exp_year"),
        bank_name=bank.get("bank_name"),
        bank_last4=bank.get("last4"),
        billing_details=pm_data.get("billing_details", {}),
    )
    db.add(payment_method)
    await db.flush()

    logger.info("payment_method_attached_processed", org_id=str(org.id), pm_id=pm_data["id"])


async def _handle_payment_method_detached(
    db: AsyncSession,
    event: dict[str, Any],
    org_id: uuid.UUID | None,
) -> None:
    """Handle payment method detached event."""
    pm_data = event["data"]["object"]

    # Find and remove local record
    result = await db.execute(
        select(PaymentMethod).where(PaymentMethod.stripe_payment_method_id == pm_data["id"])
    )
    pm = result.scalar_one_or_none()

    if pm:
        await db.delete(pm)
        await db.flush()
        logger.info("payment_method_detached_processed", pm_id=pm_data["id"])
    else:
        logger.debug("payment_method_detached_not_found", pm_id=pm_data["id"])


async def _handle_checkout_completed(
    db: AsyncSession,
    event: dict[str, Any],
    org_id: uuid.UUID | None,
) -> None:
    """Handle checkout session completed event."""
    session = event["data"]["object"]
    customer_id = session.get("customer")
    subscription_id = session.get("subscription")

    if not subscription_id:
        logger.debug("checkout_completed_no_subscription")
        return

    # Get organization from metadata
    org = None
    if org_id:
        result = await db.execute(select(Organization).where(Organization.id == org_id))
        org = result.scalar_one_or_none()

    if not org and customer_id:
        org = await _get_organization_by_customer(db, customer_id)

    if not org:
        logger.warning("checkout_completed_no_org", customer_id=customer_id)
        return

    # Update organization with subscription info
    org.stripe_customer_id = customer_id
    org.stripe_subscription_id = subscription_id
    org.subscription_status = SubscriptionStatus.ACTIVE
    org.subscription_started_at = datetime.now(UTC)

    db.add(org)
    await db.flush()

    logger.info(
        "checkout_completed_processed",
        org_id=str(org.id),
        subscription_id=subscription_id,
    )


def _map_subscription_status(stripe_status: str) -> SubscriptionStatus:
    """Map Stripe subscription status to our enum."""
    status_map = {
        "trialing": SubscriptionStatus.TRIAL,
        "active": SubscriptionStatus.ACTIVE,
        "past_due": SubscriptionStatus.PAST_DUE,
        "canceled": SubscriptionStatus.CANCELLED,
        "unpaid": SubscriptionStatus.PAST_DUE,
        "incomplete": SubscriptionStatus.TRIAL,
        "incomplete_expired": SubscriptionStatus.CANCELLED,
    }
    return status_map.get(stripe_status, SubscriptionStatus.ACTIVE)


async def _update_plan_from_price(db: AsyncSession, org: Organization) -> None:
    """Update organization plan based on Stripe price ID.

    Args:
        db: Database session
        org: Organization to update
    """
    if not org.stripe_price_id:
        return

    from app.services.stripe_service import get_stripe_config

    try:
        config = await get_stripe_config(db)

        # Map price IDs to plan types
        price_plan_map = {
            config.get("stripe_price_free"): PlanType.FREE,
            config.get("stripe_price_starter"): PlanType.STARTER,
            config.get("stripe_price_professional"): PlanType.PROFESSIONAL,
            config.get("stripe_price_enterprise"): PlanType.ENTERPRISE,
        }

        plan_type = price_plan_map.get(org.stripe_price_id)
        if plan_type:
            org.plan_type = plan_type

            # Update limits based on plan
            from app.services.stripe_service import get_plan_limits

            limits = get_plan_limits(plan_type)
            if limits.get("max_agents", 0) > 0:
                org.max_agents = int(limits["max_agents"])
            if limits.get("max_workspaces", 0) > 0:
                org.max_workspaces = int(limits["max_workspaces"])
            if limits.get("voice_minutes", 0) > 0:
                org.max_call_minutes_per_month = int(limits["voice_minutes"])

    except Exception:
        logger.exception("update_plan_from_price_failed", org_id=str(org.id))
