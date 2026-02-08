"""Webhook endpoints for external service integrations."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.stripe_webhook_handler import (
    WebhookError,
    WebhookEventAlreadyProcessedError,
    WebhookSignatureError,
    handle_webhook,
    verify_webhook_signature,
)

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


@router.post("/stripe")
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Handle Stripe webhook events.

    This endpoint receives and processes Stripe webhook events for:
    - Subscription lifecycle (created, updated, deleted)
    - Invoice events (paid, payment_failed)
    - Payment method changes
    - Checkout session completion

    The endpoint:
    1. Verifies the webhook signature using the configured secret
    2. Checks for duplicate events (idempotency)
    3. Routes the event to the appropriate handler
    4. Records the event in the billing_events table

    Returns:
        Success message with event ID
    """
    # Get raw body and signature
    payload = await request.body()
    signature = request.headers.get("Stripe-Signature", "")

    if not signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing Stripe-Signature header",
        )

    try:
        # Verify signature and parse event
        event = await verify_webhook_signature(db, payload, signature)

        # Handle the event
        result = await handle_webhook(db, event)

        # Commit the transaction
        await db.commit()

        return result

    except WebhookSignatureError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

    except WebhookEventAlreadyProcessedError:
        # Return 200 for duplicate events (Stripe may retry)
        return {"status": "already_processed"}

    except WebhookError as e:
        # Log but return 200 to prevent Stripe retries for app errors
        # The error is recorded in the billing_events table
        await db.commit()
        return {"status": "error", "message": str(e)}
