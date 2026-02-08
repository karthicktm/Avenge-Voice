"""Usage alert service for monitoring resource thresholds.

Monitors usage against limits and creates alerts at configurable thresholds
(50%, 80%, 90%, 100%). Sends email notifications and publishes to WebSocket.
"""

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing import AlertStatus, UsageAlert
from app.models.organization import Organization
from app.models.quota import ResourceType
from app.services.realtime_usage_service import (
    get_current_usage,
    mark_alert_sent,
    publish_alert,
)
from app.services.stripe_service import get_plan_limits

logger = structlog.get_logger()

# Alert thresholds as percentages
ALERT_THRESHOLDS = [50, 80, 90, 100]


async def check_and_create_alerts(
    db: AsyncSession,
    org_id: uuid.UUID,
    organization: Organization,
    resource_type: str | ResourceType,
) -> list[UsageAlert]:
    """Check usage against limits and create alerts if thresholds are crossed.

    Args:
        db: Database session
        org_id: Organization ID
        organization: Organization object
        resource_type: Type of resource to check

    Returns:
        List of newly created alerts
    """
    if isinstance(resource_type, ResourceType):
        resource_type = resource_type.value

    log = logger.bind(org_id=str(org_id), resource_type=resource_type)

    # Get current usage from Redis
    current_usage = await get_current_usage(org_id, resource_type)

    # Get limit for this resource
    limits = get_plan_limits(organization.plan_type)
    limit = limits.get(resource_type, -1)

    # Skip if unlimited or no limit defined
    if limit <= 0:
        return []

    # Calculate percentage
    percentage = (current_usage / limit) * 100

    # Get current period bounds
    now = datetime.now(UTC)
    period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if now.month == 12:
        period_end = now.replace(year=now.year + 1, month=1, day=1)
    else:
        period_end = now.replace(month=now.month + 1, day=1)

    created_alerts: list[UsageAlert] = []

    # Check each threshold
    for threshold in ALERT_THRESHOLDS:
        if percentage >= threshold:
            # Check if alert already sent for this threshold this period
            is_new = await mark_alert_sent(org_id, resource_type, str(threshold))

            if is_new:
                # Create new alert record
                alert = UsageAlert(
                    organization_id=org_id,
                    resource_type=resource_type,
                    threshold=str(threshold),
                    status=AlertStatus.PENDING.value,
                    current_usage=current_usage,
                    limit=limit,
                    percentage=percentage,
                    period_start=period_start,
                    period_end=period_end,
                )
                db.add(alert)
                created_alerts.append(alert)

                log.info(
                    "usage_alert_created",
                    threshold=threshold,
                    current=current_usage,
                    limit=limit,
                    percentage=percentage,
                )

                # Publish to WebSocket
                await publish_alert(org_id, resource_type, str(threshold), current_usage, limit)

    if created_alerts:
        await db.flush()

    return created_alerts


async def check_all_resources(
    db: AsyncSession,
    organization: Organization,
) -> list[UsageAlert]:
    """Check all resources for an organization and create alerts.

    Args:
        db: Database session
        organization: Organization to check

    Returns:
        List of all newly created alerts
    """
    all_alerts: list[UsageAlert] = []

    # Check each resource type that has a limit
    limits = get_plan_limits(organization.plan_type)

    for resource_type in ResourceType:
        if limits.get(resource_type.value, -1) > 0:
            alerts = await check_and_create_alerts(db, organization.id, organization, resource_type)
            all_alerts.extend(alerts)

    return all_alerts


async def get_pending_alerts(
    db: AsyncSession,
    org_id: uuid.UUID,
) -> list[UsageAlert]:
    """Get all pending (unacknowledged) alerts for an organization.

    Args:
        db: Database session
        org_id: Organization ID

    Returns:
        List of pending alerts
    """
    result = await db.execute(
        select(UsageAlert)
        .where(
            UsageAlert.organization_id == org_id,
            UsageAlert.status == AlertStatus.PENDING.value,
        )
        .order_by(UsageAlert.created_at.desc())
    )
    return list(result.scalars().all())


async def get_recent_alerts(
    db: AsyncSession,
    org_id: uuid.UUID,
    limit: int = 20,
) -> list[UsageAlert]:
    """Get recent alerts for an organization.

    Args:
        db: Database session
        org_id: Organization ID
        limit: Maximum number of alerts to return

    Returns:
        List of recent alerts
    """
    result = await db.execute(
        select(UsageAlert)
        .where(UsageAlert.organization_id == org_id)
        .order_by(UsageAlert.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def acknowledge_alert(
    db: AsyncSession,
    alert_id: uuid.UUID,
    user_id: int,
) -> UsageAlert | None:
    """Acknowledge an alert.

    Args:
        db: Database session
        alert_id: Alert ID
        user_id: User acknowledging the alert

    Returns:
        Updated alert or None if not found
    """
    result = await db.execute(select(UsageAlert).where(UsageAlert.id == alert_id))
    alert = result.scalar_one_or_none()

    if not alert:
        return None

    alert.status = AlertStatus.ACKNOWLEDGED.value
    alert.acknowledged_at = datetime.now(UTC)
    alert.acknowledged_by_id = user_id
    db.add(alert)
    await db.flush()

    logger.info("alert_acknowledged", alert_id=str(alert_id), user_id=user_id)
    return alert


async def send_alert_email(
    db: AsyncSession,
    alert: UsageAlert,
    organization: Organization,
) -> bool:
    """Send email notification for an alert.

    Args:
        db: Database session
        alert: Alert to send notification for
        organization: Organization the alert belongs to

    Returns:
        True if email was sent, False otherwise
    """
    log = logger.bind(alert_id=str(alert.id), org_id=str(organization.id))

    # Get billing email
    email = organization.billing_email
    if not email and organization.owner:
        email = organization.owner.email

    if not email:
        log.warning("no_email_for_alert")
        return False

    try:
        from app.services.email_service import send_email

        # Generate email content
        subject = f"Usage Alert: {alert.resource_type} at {alert.threshold}%"
        html_content = _generate_alert_email_html(alert, organization)

        await send_email(
            db=db,
            to_email=email,
            subject=subject,
            html_content=html_content,
        )

        # Mark email as sent
        alert.email_sent = True
        alert.email_sent_at = datetime.now(UTC)
        db.add(alert)
        await db.flush()

        log.info("alert_email_sent", email=email)
        return True

    except Exception:
        log.exception("alert_email_failed")
        return False


def _generate_alert_email_html(alert: UsageAlert, organization: Organization) -> str:
    """Generate HTML email content for an alert.

    Args:
        alert: Alert to generate email for
        organization: Organization

    Returns:
        HTML email content
    """
    # Determine color based on threshold
    threshold = int(alert.threshold)
    if threshold >= 100:
        color = "#dc2626"  # red
        status = "Limit Reached"
    elif threshold >= 90:
        color = "#ea580c"  # orange
        status = "Critical"
    elif threshold >= 80:
        color = "#f59e0b"  # yellow
        status = "Warning"
    else:
        color = "#3b82f6"  # blue
        status = "Notice"

    resource_display = alert.resource_type.replace("_", " ").title()

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                line-height: 1.6;
                color: #333;
                max-width: 600px;
                margin: 0 auto;
                padding: 20px;
                background-color: #f9fafb;
            }}
            .container {{
                background: #ffffff;
                border-radius: 12px;
                padding: 40px;
                box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
            }}
            .header {{
                text-align: center;
                margin-bottom: 30px;
            }}
            .logo {{
                color: #6366f1;
                font-size: 28px;
                font-weight: 700;
                margin-bottom: 10px;
            }}
            .alert-badge {{
                display: inline-block;
                background: {color};
                color: white;
                padding: 8px 16px;
                border-radius: 20px;
                font-size: 14px;
                font-weight: 600;
            }}
            .usage-box {{
                background: #f3f4f6;
                border-radius: 12px;
                padding: 24px;
                margin: 24px 0;
                text-align: center;
            }}
            .usage-type {{
                font-size: 18px;
                color: #374151;
                margin-bottom: 8px;
            }}
            .usage-value {{
                font-size: 36px;
                font-weight: 700;
                color: {color};
            }}
            .usage-limit {{
                font-size: 14px;
                color: #6b7280;
                margin-top: 8px;
            }}
            .progress-bar {{
                background: #e5e7eb;
                border-radius: 9999px;
                height: 12px;
                margin-top: 16px;
                overflow: hidden;
            }}
            .progress-fill {{
                background: {color};
                height: 100%;
                width: {min(alert.percentage, 100)}%;
                border-radius: 9999px;
            }}
            .cta-button {{
                display: inline-block;
                background: #6366f1;
                color: white;
                padding: 12px 24px;
                border-radius: 8px;
                text-decoration: none;
                font-weight: 600;
                margin-top: 24px;
            }}
            .footer {{
                margin-top: 30px;
                padding-top: 20px;
                border-top: 1px solid #e5e7eb;
                font-size: 13px;
                color: #6b7280;
                text-align: center;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <div class="logo">Avenge AI</div>
                <span class="alert-badge">{status}</span>
            </div>

            <p>Hi there,</p>

            <p>Your organization <strong>{organization.name}</strong> has reached
            <strong>{alert.threshold}%</strong> of its {resource_display} limit.</p>

            <div class="usage-box">
                <div class="usage-type">{resource_display}</div>
                <div class="usage-value">{alert.percentage:.1f}%</div>
                <div class="usage-limit">
                    {alert.current_usage:,.0f} / {alert.limit:,.0f} used
                </div>
                <div class="progress-bar">
                    <div class="progress-fill"></div>
                </div>
            </div>

            <p>
                {
        "You've reached your limit for this billing period. Consider upgrading your plan to continue using this feature."
        if threshold >= 100
        else "Consider upgrading your plan if you expect to exceed your limit."
    }
            </p>

            <div style="text-align: center;">
                <a href="#" class="cta-button">View Usage Dashboard</a>
            </div>

            <div class="footer">
                <p>This is an automated message from Avenge AI.</p>
                <p>&copy; 2026 Avenge AI. All rights reserved.</p>
            </div>
        </div>
    </body>
    </html>
    """


async def process_pending_alert_emails(db: AsyncSession) -> int:
    """Process and send emails for pending alerts.

    This should be run as a background task.

    Args:
        db: Database session

    Returns:
        Number of emails sent
    """
    # Get pending alerts that haven't had emails sent
    result = await db.execute(
        select(UsageAlert)
        .where(
            UsageAlert.status == AlertStatus.PENDING.value,
            UsageAlert.email_sent == False,  # noqa: E712
        )
        .limit(50)
    )
    alerts = list(result.scalars().all())

    sent_count = 0

    for alert in alerts:
        # Get organization
        org_result = await db.execute(
            select(Organization).where(Organization.id == alert.organization_id)
        )
        org = org_result.scalar_one_or_none()

        if org:
            if await send_alert_email(db, alert, org):
                sent_count += 1

    if sent_count > 0:
        await db.commit()
        logger.info("pending_alert_emails_processed", sent_count=sent_count)

    return sent_count


def get_alert_thresholds() -> list[int]:
    """Get configured alert thresholds.

    Returns:
        List of threshold percentages
    """
    return ALERT_THRESHOLDS.copy()
