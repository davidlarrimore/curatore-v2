"""
Email service for Curatore v2.

Provides pluggable email backends for sending emails with template support.
Backends include console (dev), SMTP, SendGrid, and AWS SES.

Key Features:
    - Pluggable backend architecture (console, SMTP, SendGrid, SES)
    - Jinja2 template rendering
    - HTML + plain text fallback
    - Async sending
    - Configurable via environment variables

Usage:
    from app.services.email_service import email_service

    # Send verification email
    await email_service.send_verification_email(user, token)

    # Send password reset email
    await email_service.send_password_reset_email(user, token)

Dependencies:
    - jinja2 for template rendering
    - aiosmtplib for SMTP backend
    - sendgrid for SendGrid backend (optional)
    - boto3 for AWS SES backend (optional)

Configuration:
    Uses settings from config.py:
    - email_backend: Backend to use (console, smtp, sendgrid, ses)
    - email_from_address: From email address
    - email_from_name: From name
    - frontend_base_url: Frontend URL for links
    - smtp_*: SMTP configuration
    - sendgrid_api_key: SendGrid API key
    - aws_*: AWS configuration
"""

import logging
from abc import ABC, abstractmethod
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Dict, List, Optional

import aiosmtplib
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.config import settings

logger = logging.getLogger("curatore.email")


class EmailBackend(ABC):
    """Abstract base class for email backends."""

    @abstractmethod
    async def send_email(
        self,
        to: str,
        subject: str,
        html_body: str,
        text_body: str,
        from_address: str,
        from_name: str,
    ) -> bool:
        """
        Send an email.

        Args:
            to: Recipient email address
            subject: Email subject
            html_body: HTML email body
            text_body: Plain text email body
            from_address: From email address
            from_name: From name

        Returns:
            bool: True if sent successfully, False otherwise
        """
        pass


class ConsoleEmailBackend(EmailBackend):
    """
    Console email backend for development.

    Logs emails to stdout instead of actually sending them.
    Useful for local development and testing.
    """

    async def send_email(
        self,
        to: str,
        subject: str,
        html_body: str,
        text_body: str,
        from_address: str,
        from_name: str,
    ) -> bool:
        """Log email to console instead of sending."""
        logger.info("=" * 80)
        logger.info("EMAIL (Console Backend)")
        logger.info("=" * 80)
        logger.info(f"To: {to}")
        logger.info(f"From: {from_name} <{from_address}>")
        logger.info(f"Subject: {subject}")
        logger.info("-" * 80)
        logger.info("Text Body:")
        logger.info(text_body)
        logger.info("-" * 80)
        logger.info("HTML Body:")
        logger.info(html_body)
        logger.info("=" * 80)
        return True


class SMTPEmailBackend(EmailBackend):
    """
    SMTP email backend for production.

    Sends emails via SMTP server with TLS support.
    Supports any SMTP-compatible email service.
    """

    def __init__(
        self,
        host: str,
        port: int,
        username: Optional[str],
        password: Optional[str],
        use_tls: bool = True,
    ):
        """
        Initialize SMTP backend.

        Args:
            host: SMTP server host
            port: SMTP server port
            username: SMTP username (optional)
            password: SMTP password (optional)
            use_tls: Use TLS encryption
        """
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_tls = use_tls

    async def send_email(
        self,
        to: str,
        subject: str,
        html_body: str,
        text_body: str,
        from_address: str,
        from_name: str,
    ) -> bool:
        """Send email via SMTP."""
        try:
            # Create message
            message = MIMEMultipart("alternative")
            message["From"] = f"{from_name} <{from_address}>"
            message["To"] = to
            message["Subject"] = subject

            # Attach text and HTML parts
            text_part = MIMEText(text_body, "plain")
            html_part = MIMEText(html_body, "html")
            message.attach(text_part)
            message.attach(html_part)

            # Send via SMTP
            if self.use_tls:
                await aiosmtplib.send(
                    message,
                    hostname=self.host,
                    port=self.port,
                    username=self.username,
                    password=self.password,
                    start_tls=True,
                )
            else:
                await aiosmtplib.send(
                    message,
                    hostname=self.host,
                    port=self.port,
                    username=self.username,
                    password=self.password,
                )

            logger.info(f"Email sent successfully via SMTP to {to}")
            return True

        except Exception as e:
            logger.error(f"Failed to send email via SMTP: {e}")
            return False


class SendGridEmailBackend(EmailBackend):
    """
    SendGrid email backend.

    Sends emails via SendGrid API.
    Requires sendgrid Python package.
    """

    def __init__(self, api_key: str):
        """
        Initialize SendGrid backend.

        Args:
            api_key: SendGrid API key
        """
        self.api_key = api_key
        try:
            from sendgrid import SendGridAPIClient
            from sendgrid.helpers.mail import Content, Email, Mail, To

            self.sg = SendGridAPIClient(api_key)
            self.Email = Email
            self.To = To
            self.Content = Content
            self.Mail = Mail
        except ImportError:
            logger.error("sendgrid package not installed. Install with: pip install sendgrid")
            raise

    async def send_email(
        self,
        to: str,
        subject: str,
        html_body: str,
        text_body: str,
        from_address: str,
        from_name: str,
    ) -> bool:
        """Send email via SendGrid API."""
        try:
            from_email = self.Email(from_address, from_name)
            to_email = self.To(to)
            content = self.Content("text/html", html_body)

            mail = self.Mail(from_email, to_email, subject, content)
            mail.add_content(self.Content("text/plain", text_body))

            response = self.sg.send(mail)

            if response.status_code in [200, 202]:
                logger.info(f"Email sent successfully via SendGrid to {to}")
                return True
            else:
                logger.error(f"SendGrid returned status code {response.status_code}")
                return False

        except Exception as e:
            logger.error(f"Failed to send email via SendGrid: {e}")
            return False


class SESEmailBackend(EmailBackend):
    """
    AWS SES email backend.

    Sends emails via AWS Simple Email Service.
    Requires boto3 Python package.
    """

    def __init__(
        self,
        region: str,
        access_key_id: Optional[str] = None,
        secret_access_key: Optional[str] = None,
    ):
        """
        Initialize AWS SES backend.

        Args:
            region: AWS region
            access_key_id: AWS access key ID (optional, uses IAM role if not provided)
            secret_access_key: AWS secret access key (optional)
        """
        try:
            import boto3

            if access_key_id and secret_access_key:
                self.ses = boto3.client(
                    "ses",
                    region_name=region,
                    aws_access_key_id=access_key_id,
                    aws_secret_access_key=secret_access_key,
                )
            else:
                self.ses = boto3.client("ses", region_name=region)

        except ImportError:
            logger.error("boto3 package not installed. Install with: pip install boto3")
            raise

    async def send_email(
        self,
        to: str,
        subject: str,
        html_body: str,
        text_body: str,
        from_address: str,
        from_name: str,
    ) -> bool:
        """Send email via AWS SES."""
        try:
            response = self.ses.send_email(
                Source=f"{from_name} <{from_address}>",
                Destination={"ToAddresses": [to]},
                Message={
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {
                        "Text": {"Data": text_body, "Charset": "UTF-8"},
                        "Html": {"Data": html_body, "Charset": "UTF-8"},
                    },
                },
            )

            logger.info(f"Email sent successfully via AWS SES to {to}: {response['MessageId']}")
            return True

        except Exception as e:
            logger.error(f"Failed to send email via AWS SES: {e}")
            return False


class EmailService:
    """
    Email service with pluggable backends.

    Handles email template rendering and sending via configured backend.
    Supports console (dev), SMTP, SendGrid, and AWS SES backends.

    Attributes:
        backend: Current email backend instance
        jinja_env: Jinja2 environment for template rendering
        from_address: From email address
        from_name: From name
        frontend_base_url: Frontend base URL for links
    """

    def __init__(self):
        """Initialize email service with configured backend."""
        self.backend = self._create_backend()
        self.jinja_env = self._create_jinja_env()
        self.from_address = settings.email_from_address
        self.from_name = settings.email_from_name
        self.frontend_base_url = settings.frontend_base_url.rstrip("/")

        logger.info(f"EmailService initialized with backend: {settings.email_backend}")

    def _create_backend(self) -> EmailBackend:
        """Create email backend based on configuration."""
        backend_type = settings.email_backend.lower()

        if backend_type == "console":
            return ConsoleEmailBackend()

        elif backend_type == "smtp":
            if not settings.smtp_host:
                logger.warning("SMTP backend selected but smtp_host not configured. Falling back to console.")
                return ConsoleEmailBackend()

            return SMTPEmailBackend(
                host=settings.smtp_host,
                port=settings.smtp_port,
                username=settings.smtp_username,
                password=settings.smtp_password,
                use_tls=settings.smtp_use_tls,
            )

        elif backend_type == "sendgrid":
            if not settings.sendgrid_api_key:
                logger.warning("SendGrid backend selected but sendgrid_api_key not configured. Falling back to console.")
                return ConsoleEmailBackend()

            return SendGridEmailBackend(api_key=settings.sendgrid_api_key)

        elif backend_type == "ses":
            return SESEmailBackend(
                region=settings.aws_region,
                access_key_id=settings.aws_access_key_id,
                secret_access_key=settings.aws_secret_access_key,
            )

        else:
            logger.warning(f"Unknown email backend: {backend_type}. Falling back to console.")
            return ConsoleEmailBackend()

    def _create_jinja_env(self) -> Environment:
        """Create Jinja2 environment for email templates."""
        template_dir = Path(__file__).parent.parent / "templates" / "emails"
        template_dir.mkdir(parents=True, exist_ok=True)

        env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            autoescape=select_autoescape(["html", "xml"]),
        )

        return env

    async def send_email(
        self,
        to: str,
        subject: str,
        template_name: str,
        context: Dict,
    ) -> bool:
        """
        Send an email using a template.

        Args:
            to: Recipient email address
            subject: Email subject
            template_name: Template name (without extension)
            context: Template context variables

        Returns:
            bool: True if sent successfully, False otherwise

        Example:
            >>> await email_service.send_email(
            ...     to="user@example.com",
            ...     subject="Welcome to Curatore",
            ...     template_name="welcome",
            ...     context={"user_name": "John Doe"}
            ... )
        """
        try:
            # Render HTML template
            html_template = self.jinja_env.get_template(f"{template_name}.html")
            html_body = html_template.render(**context)

            # Render text template (fallback)
            try:
                text_template = self.jinja_env.get_template(f"{template_name}.txt")
                text_body = text_template.render(**context)
            except Exception:
                # If text template doesn't exist, use a simple text version
                text_body = f"Please view this email in an HTML-capable email client.\n\nSubject: {subject}"

            # Send via backend
            return await self.backend.send_email(
                to=to,
                subject=subject,
                html_body=html_body,
                text_body=text_body,
                from_address=self.from_address,
                from_name=self.from_name,
            )

        except Exception as e:
            logger.error(f"Failed to send email to {to}: {e}")
            return False

    async def send_verification_email(self, user_email: str, user_name: str, verification_token: str) -> bool:
        """
        Send email verification email.

        Args:
            user_email: User's email address
            user_name: User's name
            verification_token: Verification token

        Returns:
            bool: True if sent successfully
        """
        verification_url = f"{self.frontend_base_url}/verify-email?token={verification_token}"

        return await self.send_email(
            to=user_email,
            subject="Verify your email address",
            template_name="verification",
            context={
                "user_name": user_name,
                "verification_url": verification_url,
                "frontend_base_url": self.frontend_base_url,
            },
        )

    async def send_password_reset_email(self, user_email: str, user_name: str, reset_token: str) -> bool:
        """
        Send password reset email.

        Args:
            user_email: User's email address
            user_name: User's name
            reset_token: Password reset token

        Returns:
            bool: True if sent successfully
        """
        reset_url = f"{self.frontend_base_url}/reset-password?token={reset_token}"

        return await self.send_email(
            to=user_email,
            subject="Reset your password",
            template_name="password_reset",
            context={
                "user_name": user_name,
                "reset_url": reset_url,
                "frontend_base_url": self.frontend_base_url,
                "expire_hours": settings.password_reset_token_expire_hours,
            },
        )

    async def send_welcome_email(self, user_email: str, user_name: str) -> bool:
        """
        Send welcome email after verification.

        Args:
            user_email: User's email address
            user_name: User's name

        Returns:
            bool: True if sent successfully
        """
        return await self.send_email(
            to=user_email,
            subject="Welcome to Curatore!",
            template_name="welcome",
            context={
                "user_name": user_name,
                "frontend_base_url": self.frontend_base_url,
            },
        )

    async def send_invitation_email(
        self,
        user_email: str,
        user_name: str,
        invitation_token: str,
        invited_by: str,
        organization_name: str,
    ) -> bool:
        """
        Send user invitation email.

        Args:
            user_email: User's email address
            user_name: User's name
            invitation_token: Invitation/setup token
            invited_by: Name of person who invited the user
            organization_name: Organization name

        Returns:
            bool: True if sent successfully
        """
        setup_url = f"{self.frontend_base_url}/set-password?token={invitation_token}"

        return await self.send_email(
            to=user_email,
            subject=f"You've been invited to {organization_name}",
            template_name="user_invitation",
            context={
                "user_name": user_name,
                "setup_url": setup_url,
                "invited_by": invited_by,
                "organization_name": organization_name,
                "frontend_base_url": self.frontend_base_url,
            },
        )


# Global singleton instance
email_service = EmailService()
