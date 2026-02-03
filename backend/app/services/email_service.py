"""Email service for sending transactional emails."""

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import structlog

from app.core.config import settings

logger = structlog.get_logger()


class EmailService:
    """Service for sending transactional emails.

    Handles:
    - Email verification
    - OTP delivery
    - Workspace invitations
    - Welcome emails
    - Usage warnings
    """

    def __init__(self) -> None:
        """Initialize email service."""
        self.smtp_host = getattr(settings, "SMTP_HOST", "localhost")
        self.smtp_port = getattr(settings, "SMTP_PORT", 587)
        self.smtp_user = getattr(settings, "SMTP_USER", "")
        self.smtp_password = getattr(settings, "SMTP_PASSWORD", "")
        self.from_email = getattr(settings, "FROM_EMAIL", "noreply@avenge-voice.com")
        self.from_name = getattr(settings, "FROM_NAME", "Avenge Voice")
        self.frontend_url = getattr(settings, "FRONTEND_URL", "http://localhost:3000")

    async def send_email(
        self,
        to_email: str,
        subject: str,
        html_content: str,
        text_content: str | None = None,
    ) -> bool:
        """Send an email.

        Args:
            to_email: Recipient email address
            subject: Email subject
            html_content: HTML email content
            text_content: Plain text email content (optional)

        Returns:
            True if email sent successfully, False otherwise
        """
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = f"{self.from_name} <{self.from_email}>"
            msg["To"] = to_email

            # Add plain text version
            if text_content:
                part1 = MIMEText(text_content, "plain")
                msg.attach(part1)

            # Add HTML version
            part2 = MIMEText(html_content, "html")
            msg.attach(part2)

            # Send email
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                if self.smtp_user and self.smtp_password:
                    server.login(self.smtp_user, self.smtp_password)
                server.send_message(msg)

            logger.info("email_sent", to=to_email, subject=subject)
            return True

        except Exception as e:
            logger.error("email_send_failed", to=to_email, subject=subject, error=str(e))
            return False

    async def send_verification_email(self, user_email: str, token: str, user_name: str | None = None) -> bool:
        """Send email verification email.

        Args:
            user_email: User's email address
            token: Verification token
            user_name: User's name (optional)

        Returns:
            True if email sent successfully
        """
        verification_url = f"{self.frontend_url}/verify-email?token={token}"

        subject = "Verify your email address"

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .button {{ 
                    display: inline-block; 
                    padding: 12px 24px; 
                    background-color: #6366f1; 
                    color: white; 
                    text-decoration: none; 
                    border-radius: 6px;
                    margin: 20px 0;
                }}
                .footer {{ margin-top: 40px; font-size: 12px; color: #666; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h2>Welcome to Avenge Voice{f", {user_name}" if user_name else ""}!</h2>
                <p>Thank you for signing up. Please verify your email address to get started.</p>
                <p>Click the button below to verify your email:</p>
                <a href="{verification_url}" class="button">Verify Email Address</a>
                <p>Or copy and paste this link into your browser:</p>
                <p style="word-break: break-all; color: #6366f1;">{verification_url}</p>
                <p>This link will expire in 24 hours.</p>
                <div class="footer">
                    <p>If you didn't create an account, you can safely ignore this email.</p>
                    <p>&copy; 2026 Avenge Voice. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """

        text_content = f"""
        Welcome to Avenge Voice{f", {user_name}" if user_name else ""}!

        Thank you for signing up. Please verify your email address to get started.

        Verify your email by visiting this link:
        {verification_url}

        This link will expire in 24 hours.

        If you didn't create an account, you can safely ignore this email.
        """

        return await self.send_email(user_email, subject, html_content, text_content)

    async def send_otp_email(self, user_email: str, otp_code: str, user_name: str | None = None) -> bool:
        """Send OTP code email.

        Args:
            user_email: User's email address
            otp_code: 6-digit OTP code
            user_name: User's name (optional)

        Returns:
            True if email sent successfully
        """
        subject = "Your verification code"

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .otp-code {{ 
                    font-size: 32px; 
                    font-weight: bold; 
                    letter-spacing: 8px; 
                    color: #6366f1; 
                    text-align: center;
                    padding: 20px;
                    background-color: #f3f4f6;
                    border-radius: 8px;
                    margin: 20px 0;
                }}
                .footer {{ margin-top: 40px; font-size: 12px; color: #666; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h2>Your Verification Code</h2>
                <p>{"Hi " + user_name + "," if user_name else "Hi,"}</p>
                <p>Use the following code to complete your verification:</p>
                <div class="otp-code">{otp_code}</div>
                <p>This code will expire in 10 minutes.</p>
                <p>If you didn't request this code, please ignore this email or contact support if you have concerns.</p>
                <div class="footer">
                    <p>For security reasons, never share this code with anyone.</p>
                    <p>&copy; 2026 Avenge Voice. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """

        text_content = f"""
        Your Verification Code

        {"Hi " + user_name + "," if user_name else "Hi,"}

        Use the following code to complete your verification:

        {otp_code}

        This code will expire in 10 minutes.

        If you didn't request this code, please ignore this email or contact support if you have concerns.

        For security reasons, never share this code with anyone.
        """

        return await self.send_email(user_email, subject, html_content, text_content)

    async def send_invitation_email(
        self,
        to_email: str,
        workspace_name: str,
        inviter_name: str,
        invitation_token: str,
        role: str,
    ) -> bool:
        """Send workspace invitation email.

        Args:
            to_email: Invitee's email address
            workspace_name: Name of the workspace
            inviter_name: Name of the person who sent the invitation
            invitation_token: Invitation token
            role: Role being assigned

        Returns:
            True if email sent successfully
        """
        invitation_url = f"{self.frontend_url}/accept-invitation?token={invitation_token}"

        subject = f"{inviter_name} invited you to join {workspace_name}"

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .button {{ 
                    display: inline-block; 
                    padding: 12px 24px; 
                    background-color: #6366f1; 
                    color: white; 
                    text-decoration: none; 
                    border-radius: 6px;
                    margin: 20px 0;
                }}
                .info-box {{ 
                    background-color: #f3f4f6; 
                    padding: 15px; 
                    border-radius: 6px; 
                    margin: 20px 0;
                }}
                .footer {{ margin-top: 40px; font-size: 12px; color: #666; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h2>You've been invited!</h2>
                <p><strong>{inviter_name}</strong> has invited you to join the <strong>{workspace_name}</strong> workspace on Avenge Voice.</p>
                <div class="info-box">
                    <p><strong>Role:</strong> {role.title()}</p>
                    <p><strong>Workspace:</strong> {workspace_name}</p>
                </div>
                <p>Click the button below to accept the invitation:</p>
                <a href="{invitation_url}" class="button">Accept Invitation</a>
                <p>Or copy and paste this link into your browser:</p>
                <p style="word-break: break-all; color: #6366f1;">{invitation_url}</p>
                <p>This invitation will expire in 7 days.</p>
                <div class="footer">
                    <p>If you don't want to join this workspace, you can safely ignore this email.</p>
                    <p>&copy; 2026 Avenge Voice. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """

        text_content = f"""
        You've been invited!

        {inviter_name} has invited you to join the {workspace_name} workspace on Avenge Voice.

        Role: {role.title()}
        Workspace: {workspace_name}

        Accept the invitation by visiting this link:
        {invitation_url}

        This invitation will expire in 7 days.

        If you don't want to join this workspace, you can safely ignore this email.
        """

        return await self.send_email(to_email, subject, html_content, text_content)

    async def send_welcome_email(
        self,
        user_email: str,
        user_name: str,
        organization_name: str,
    ) -> bool:
        """Send welcome email after successful signup.

        Args:
            user_email: User's email address
            user_name: User's name
            organization_name: Organization name

        Returns:
            True if email sent successfully
        """
        dashboard_url = f"{self.frontend_url}/dashboard"

        subject = f"Welcome to Avenge Voice, {user_name}!"

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .button {{ 
                    display: inline-block; 
                    padding: 12px 24px; 
                    background-color: #6366f1; 
                    color: white; 
                    text-decoration: none; 
                    border-radius: 6px;
                    margin: 20px 0;
                }}
                .feature-list {{ list-style: none; padding: 0; }}
                .feature-list li {{ padding: 8px 0; }}
                .feature-list li:before {{ content: "✓ "; color: #10b981; font-weight: bold; }}
                .footer {{ margin-top: 40px; font-size: 12px; color: #666; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h2>Welcome to Avenge Voice!</h2>
                <p>Hi {user_name},</p>
                <p>Your organization <strong>{organization_name}</strong> is all set up and ready to go!</p>
                <h3>What's next?</h3>
                <ul class="feature-list">
                    <li>Create your first voice agent</li>
                    <li>Invite team members to your workspace</li>
                    <li>Configure integrations</li>
                    <li>Start making calls</li>
                </ul>
                <a href="{dashboard_url}" class="button">Go to Dashboard</a>
                <p>If you have any questions, our support team is here to help!</p>
                <div class="footer">
                    <p>Need help getting started? Check out our documentation or contact support.</p>
                    <p>&copy; 2026 Avenge Voice. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """

        text_content = f"""
        Welcome to Avenge Voice!

        Hi {user_name},

        Your organization {organization_name} is all set up and ready to go!

        What's next?
        ✓ Create your first voice agent
        ✓ Invite team members to your workspace
        ✓ Configure integrations
        ✓ Start making calls

        Go to your dashboard: {dashboard_url}

        If you have any questions, our support team is here to help!

        Need help getting started? Check out our documentation or contact support.
        """

        return await self.send_email(user_email, subject, html_content, text_content)

    async def send_usage_warning_email(
        self,
        user_email: str,
        user_name: str,
        organization_name: str,
        resource_type: str,
        usage_percentage: float,
    ) -> bool:
        """Send usage warning email when approaching limits.

        Args:
            user_email: User's email address
            user_name: User's name
            organization_name: Organization name
            resource_type: Type of resource (users, agents, call_minutes, etc.)
            usage_percentage: Current usage percentage

        Returns:
            True if email sent successfully
        """
        upgrade_url = f"{self.frontend_url}/settings/billing"

        subject = f"Usage Alert: {resource_type.replace('_', ' ').title()} at {usage_percentage:.0f}%"

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .warning-box {{ 
                    background-color: #fef3c7; 
                    border-left: 4px solid #f59e0b;
                    padding: 15px; 
                    border-radius: 6px; 
                    margin: 20px 0;
                }}
                .button {{ 
                    display: inline-block; 
                    padding: 12px 24px; 
                    background-color: #6366f1; 
                    color: white; 
                    text-decoration: none; 
                    border-radius: 6px;
                    margin: 20px 0;
                }}
                .footer {{ margin-top: 40px; font-size: 12px; color: #666; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h2>Usage Alert for {organization_name}</h2>
                <p>Hi {user_name},</p>
                <div class="warning-box">
                    <p><strong>Your {resource_type.replace('_', ' ')} usage is at {usage_percentage:.0f}%</strong></p>
                    <p>You're approaching your plan limit. Consider upgrading to avoid service interruptions.</p>
                </div>
                <p>To continue using Avenge Voice without interruption, we recommend upgrading your plan.</p>
                <a href="{upgrade_url}" class="button">Upgrade Plan</a>
                <p>Questions? Our support team is here to help you choose the right plan for your needs.</p>
                <div class="footer">
                    <p>&copy; 2026 Avenge Voice. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """

        text_content = f"""
        Usage Alert for {organization_name}

        Hi {user_name},

        Your {resource_type.replace('_', ' ')} usage is at {usage_percentage:.0f}%

        You're approaching your plan limit. Consider upgrading to avoid service interruptions.

        To continue using Avenge Voice without interruption, we recommend upgrading your plan.

        Upgrade your plan: {upgrade_url}

        Questions? Our support team is here to help you choose the right plan for your needs.
        """

        return await self.send_email(user_email, subject, html_content, text_content)


# Singleton instance
email_service = EmailService()
