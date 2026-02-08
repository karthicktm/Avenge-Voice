"""Email service using Resend for transactional emails.

This service reads Resend credentials from system settings (configured by superadmin).
"""

import resend
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system_settings import SystemSettings

logger = structlog.get_logger()


class EmailServiceError(Exception):
    """Base exception for email service errors."""


class ResendNotConfiguredError(EmailServiceError):
    """Raised when Resend is not configured in system settings."""


async def get_resend_config(db: AsyncSession) -> dict[str, str]:
    """Get Resend configuration from system settings.

    Args:
        db: Database session

    Returns:
        Dictionary with api_key and from_email

    Raises:
        ResendNotConfiguredError: If Resend is not configured
    """
    # Get API key
    result = await db.execute(select(SystemSettings).where(SystemSettings.key == "resend_api_key"))
    api_key_setting = result.scalar_one_or_none()

    # Get from email
    result = await db.execute(
        select(SystemSettings).where(SystemSettings.key == "resend_from_email")
    )
    from_email_setting = result.scalar_one_or_none()

    api_key = api_key_setting.value if api_key_setting else None
    from_email = from_email_setting.value if from_email_setting else None

    if not api_key or not from_email:
        msg = "Resend not configured. Superadmin must configure it in Settings > System."
        raise ResendNotConfiguredError(msg)

    return {
        "api_key": api_key,
        "from_email": from_email,
    }


async def send_email(
    db: AsyncSession,
    to_email: str,
    subject: str,
    html_content: str,
    user_id: str | None = None,  # Kept for backwards compatibility but not used
) -> dict[str, str]:
    """Send an email using Resend.

    Args:
        db: Database session
        to_email: Recipient email address
        subject: Email subject
        html_content: HTML email content
        user_id: Deprecated, kept for backwards compatibility

    Returns:
        Resend API response with email ID

    Raises:
        ResendNotConfiguredError: If Resend is not configured
        EmailServiceError: If email sending fails
    """
    log = logger.bind(to_email=to_email, subject=subject)

    try:
        # Get Resend configuration from system settings
        config = await get_resend_config(db)
        resend.api_key = config["api_key"]

        # Send email
        params = {
            "from": config["from_email"],
            "to": [to_email],
            "subject": subject,
            "html": html_content,
        }

        log.info("sending_email")
        response = resend.Emails.send(params)
        log.info("email_sent", email_id=response.get("id"))

        return response

    except ResendNotConfiguredError:
        log.error("resend_not_configured")
        raise
    except Exception as e:
        log.error("email_send_failed", error=str(e))
        raise EmailServiceError(f"Failed to send email: {e}") from e


def generate_verification_code_email(code: str, user_name: str | None = None) -> str:
    """Generate HTML email template for verification code.

    Args:
        code: 6-digit verification code
        user_name: Optional user name for personalization

    Returns:
        HTML email content
    """
    greeting = f"Hi {user_name}," if user_name else "Hi there,"

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
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
            .logo {{
                text-align: center;
                margin-bottom: 30px;
            }}
            .logo h1 {{
                color: #6366f1;
                margin: 0;
                font-size: 32px;
                font-weight: 700;
            }}
            .code-container {{
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                border-radius: 12px;
                padding: 30px;
                text-align: center;
                margin: 30px 0;
            }}
            .code {{
                font-size: 42px;
                font-weight: bold;
                color: #ffffff;
                letter-spacing: 12px;
                font-family: 'Courier New', monospace;
                text-shadow: 0 2px 4px rgba(0,0,0,0.2);
            }}
            .expiry {{
                color: #ffffff;
                margin-top: 15px;
                font-size: 14px;
                opacity: 0.9;
            }}
            .footer {{
                margin-top: 30px;
                padding-top: 20px;
                border-top: 1px solid #e5e7eb;
                font-size: 13px;
                color: #6b7280;
                text-align: center;
            }}
            .warning {{
                background: #fef3c7;
                border-left: 4px solid #f59e0b;
                padding: 16px;
                margin: 20px 0;
                border-radius: 6px;
                font-size: 14px;
            }}
            .warning strong {{
                color: #92400e;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="logo">
                <h1>Avenge AI</h1>
            </div>

            <p style="font-size: 16px;">{greeting}</p>

            <p style="font-size: 16px;">Thanks for signing up! Please verify your email address by entering this code:</p>

            <div class="code-container">
                <div class="code">{code}</div>
                <div class="expiry">Expires in 10 minutes</div>
            </div>

            <div class="warning">
                <strong>Security Notice:</strong> If you didn't request this code, please ignore this email. Never share this code with anyone.
            </div>

            <div class="footer">
                <p>This is an automated message from Avenge AI.</p>
                <p style="margin-top: 10px;">&copy; 2026 Avenge AI. All rights reserved.</p>
            </div>
        </div>
    </body>
    </html>
    """


def generate_password_reset_email(code: str, expiry_minutes: int = 10) -> str:
    """Generate HTML email template for password reset.

    Args:
        code: 6-digit reset code
        expiry_minutes: Minutes until code expires

    Returns:
        HTML email content
    """
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
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
            .logo {{
                text-align: center;
                margin-bottom: 30px;
            }}
            .logo h1 {{
                color: #6366f1;
                margin: 0;
                font-size: 32px;
                font-weight: 700;
            }}
            .code-container {{
                background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%);
                border-radius: 12px;
                padding: 30px;
                text-align: center;
                margin: 30px 0;
            }}
            .code {{
                font-size: 42px;
                font-weight: bold;
                color: #ffffff;
                letter-spacing: 12px;
                font-family: 'Courier New', monospace;
                text-shadow: 0 2px 4px rgba(0,0,0,0.2);
            }}
            .expiry {{
                color: #ffffff;
                margin-top: 15px;
                font-size: 14px;
                opacity: 0.9;
            }}
            .footer {{
                margin-top: 30px;
                padding-top: 20px;
                border-top: 1px solid #e5e7eb;
                font-size: 13px;
                color: #6b7280;
                text-align: center;
            }}
            .warning {{
                background: #fef2f2;
                border-left: 4px solid #ef4444;
                padding: 16px;
                margin: 20px 0;
                border-radius: 6px;
                font-size: 14px;
            }}
            .warning strong {{
                color: #991b1b;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="logo">
                <h1>Avenge AI</h1>
            </div>

            <p style="font-size: 16px;">Hi there,</p>

            <p style="font-size: 16px;">We received a request to reset your password. Enter this code to set a new password:</p>

            <div class="code-container">
                <div class="code">{code}</div>
                <div class="expiry">Expires in {expiry_minutes} minutes</div>
            </div>

            <div class="warning">
                <strong>Security Notice:</strong> If you didn't request a password reset, please ignore this email. Your password will remain unchanged.
            </div>

            <div class="footer">
                <p>This is an automated message from Avenge AI.</p>
                <p style="margin-top: 10px;">&copy; 2026 Avenge AI. All rights reserved.</p>
            </div>
        </div>
    </body>
    </html>
    """


async def send_password_reset_email(
    to_email: str,
    code: str,
    expiry_minutes: int = 10,
) -> dict[str, str]:
    """Send a password reset email.

    Note: This function needs a database session, so it uses the session factory.

    Args:
        to_email: Recipient email address
        code: 6-digit reset code
        expiry_minutes: Minutes until code expires

    Returns:
        Resend API response

    Raises:
        ResendNotConfiguredError: If Resend is not configured
        EmailServiceError: If email sending fails
    """
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        html_content = generate_password_reset_email(code, expiry_minutes)
        return await send_email(
            db=db,
            to_email=to_email,
            subject="Reset Your Password - Avenge AI",
            html_content=html_content,
        )
