"""
Email service for Curatore v2.

Provides pluggable email backends for sending emails with template support.
Backends include console (dev), SMTP, SendGrid, AWS SES, and Microsoft Graph.

Key Features:
    - Pluggable backend architecture (console, SMTP, SendGrid, SES, Microsoft Graph)
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

    # Send email directly (for send_email function)
    await email_service.send(
        to=["user@example.com"],
        subject="Hello",
        body="Email body",
        html=True,
    )

Dependencies:
    - jinja2 for template rendering
    - aiosmtplib for SMTP backend
    - sendgrid for SendGrid backend (optional)
    - boto3 for AWS SES backend (optional)
    - httpx for Microsoft Graph backend

Configuration:
    Uses settings from config.py:
    - email_backend: Backend to use (console, smtp, sendgrid, ses, microsoft_graph)
    - email_from_address: From email address
    - email_from_name: From name
    - frontend_base_url: Frontend URL for links
    - smtp_*: SMTP configuration
    - sendgrid_api_key: SendGrid API key
    - aws_*: AWS configuration
    - Microsoft Graph: uses connection_service for credentials
"""

import base64
import logging
from abc import ABC, abstractmethod
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiosmtplib
import httpx
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


class MicrosoftGraphEmailBackend(EmailBackend):
    """
    Microsoft Graph API email backend.

    Sends emails via Microsoft Graph API using OAuth2 client credentials.
    Uses the existing Microsoft Graph connection from connection_service.
    Requires Microsoft 365 app registration with Mail.Send permission.
    """

    def __init__(self, sender_user_id: Optional[str] = None):
        """
        Initialize Microsoft Graph backend.

        Args:
            sender_user_id: Default sender user ID/UPN (can be overridden per-send)
        """
        self.default_sender_user_id = sender_user_id
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0
        self._cached_config: Optional[Dict[str, Any]] = None

    async def _get_graph_config(
        self,
        session: Optional[Any] = None,
        organization_id: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Get Microsoft Graph configuration from connection_service.

        Args:
            session: Database session
            organization_id: Organization ID

        Returns:
            dict with tenant_id, client_id, client_secret, graph_base_url
        """
        if session is None or organization_id is None:
            # Fall back to cached config or raise error
            if self._cached_config:
                return self._cached_config
            raise ValueError("Microsoft Graph backend requires session and organization_id")

        from .connection_service import connection_service

        connection = await connection_service.get_default_connection(
            session, organization_id, "microsoft_graph"
        )

        if not connection or not connection.is_active:
            raise ValueError("Microsoft Graph connection not configured or inactive")

        config = connection.config
        if not all([config.get("tenant_id"), config.get("client_id"), config.get("client_secret")]):
            raise ValueError("Microsoft Graph connection missing required credentials")

        self._cached_config = config
        return config

    async def _get_access_token(self, config: Dict[str, Any]) -> str:
        """Get OAuth2 access token using client credentials flow."""
        import time

        tenant_id = config["tenant_id"]
        client_id = config["client_id"]
        client_secret = config["client_secret"]

        # Return cached token if still valid (with 5 minute buffer)
        if self._access_token and time.time() < self._token_expires_at - 300:
            return self._access_token

        token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                token_url,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "scope": "https://graph.microsoft.com/.default",
                    "grant_type": "client_credentials",
                },
            )

            if response.status_code != 200:
                raise Exception(f"Failed to get access token: {response.status_code} - {response.text}")

            token_data = response.json()
            self._access_token = token_data["access_token"]
            # Token typically expires in 3600 seconds
            self._token_expires_at = time.time() + token_data.get("expires_in", 3600)

            return self._access_token

    async def send_email(
        self,
        to: str,
        subject: str,
        html_body: str,
        text_body: str,
        from_address: str,
        from_name: str,
    ) -> bool:
        """Send email via Microsoft Graph API (basic interface)."""
        # This method is called by the base email service for template-based emails
        # It uses cached config if available
        return await self.send_email_extended(
            to=[to],
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            from_address=from_address,
            from_name=from_name,
            cc=None,
            attachments=None,
            session=None,
            organization_id=None,
        )

    async def send_email_extended(
        self,
        to: List[str],
        subject: str,
        html_body: Optional[str],
        text_body: Optional[str],
        from_address: str,
        from_name: str,
        cc: Optional[List[str]] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
        session: Optional[Any] = None,
        organization_id: Optional[Any] = None,
    ) -> bool:
        """
        Send email via Microsoft Graph API with extended options.

        Args:
            to: List of recipient email addresses
            subject: Email subject
            html_body: HTML email body (optional)
            text_body: Plain text email body (optional)
            from_address: From email address (used as sender if no sender_user_id)
            from_name: From name
            cc: List of CC recipient email addresses
            attachments: List of attachments [{filename, content, content_type}]
            session: Database session for fetching connection config
            organization_id: Organization ID for fetching connection config
        """
        try:
            # Get Microsoft Graph configuration from connection_service
            config = await self._get_graph_config(session, organization_id)
            access_token = await self._get_access_token(config)

            graph_base_url = config.get("graph_base_url", "https://graph.microsoft.com/v1.0")
            # Use configured sender or fall back to from_address
            sender_user_id = (
                config.get("email_sender_user_id")
                or self.default_sender_user_id
                or from_address
            )

            # Build recipients list
            to_recipients = [{"emailAddress": {"address": addr}} for addr in to]
            cc_recipients = [{"emailAddress": {"address": addr}} for addr in (cc or [])]

            # Build message body - prefer HTML if available
            if html_body:
                body = {
                    "contentType": "HTML",
                    "content": html_body,
                }
            else:
                body = {
                    "contentType": "Text",
                    "content": text_body or "",
                }

            # Build message payload
            message: Dict[str, Any] = {
                "subject": subject,
                "body": body,
                "toRecipients": to_recipients,
            }

            if cc_recipients:
                message["ccRecipients"] = cc_recipients

            # Add attachments if provided
            if attachments:
                graph_attachments = []
                for att in attachments:
                    # Content can be: raw bytes, raw string, or already base64-encoded string
                    content = att.get("content", "")
                    is_base64 = att.get("is_base64", False)

                    if isinstance(content, bytes):
                        # Raw bytes - encode to base64
                        content_b64 = base64.b64encode(content).decode("utf-8")
                    elif is_base64:
                        # Explicitly marked as base64 - use as-is
                        content_b64 = content
                    elif isinstance(content, str):
                        # Check if it looks like base64 (e.g., from generate_document)
                        # Base64 for binary files: long string of alphanumeric + /+ with = padding
                        import re
                        if len(content) > 100 and re.match(r'^[A-Za-z0-9+/]+=*$', content.replace('\n', '').replace('\r', '')):
                            # Likely already base64 encoded - use as-is
                            content_b64 = content.replace('\n', '').replace('\r', '')
                        else:
                            # Raw string - encode to base64
                            content_b64 = base64.b64encode(content.encode("utf-8")).decode("utf-8")
                    else:
                        content_b64 = base64.b64encode(str(content).encode("utf-8")).decode("utf-8")

                    graph_attachments.append({
                        "@odata.type": "#microsoft.graph.fileAttachment",
                        "name": att.get("filename", "attachment"),
                        "contentType": att.get("content_type", "application/octet-stream"),
                        "contentBytes": content_b64,
                    })
                message["attachments"] = graph_attachments

            # Send via Graph API
            # Using /users/{id}/sendMail for app-only authentication
            send_url = f"{graph_base_url}/users/{sender_user_id}/sendMail"

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    send_url,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    json={"message": message, "saveToSentItems": True},
                )

                if response.status_code == 202:
                    logger.info(f"Email sent successfully via Microsoft Graph to {', '.join(to)}")
                    return True
                else:
                    # Parse error message from response
                    error_msg = f"HTTP {response.status_code}"
                    try:
                        error_data = response.json()
                        if "error" in error_data:
                            error_msg = f"{error_data['error'].get('code', 'Error')}: {error_data['error'].get('message', response.text)}"
                    except Exception:
                        error_msg = f"HTTP {response.status_code}: {response.text[:200]}"

                    logger.error(f"Microsoft Graph sendMail failed: {error_msg}")
                    raise Exception(f"Microsoft Graph API error: {error_msg}")

        except Exception as e:
            logger.error(f"Failed to send email via Microsoft Graph: {e}")
            raise


class EmailService:
    """
    Email service with pluggable backends.

    Handles email template rendering and sending via configured backend.
    Supports console (dev), SMTP, SendGrid, AWS SES, and Microsoft Graph backends.

    Attributes:
        backend: Current email backend instance
        jinja_env: Jinja2 environment for template rendering
        from_address: From email address
        from_name: From name
        frontend_base_url: Frontend base URL for links
        is_configured: Whether the email service is properly configured
    """

    def __init__(self):
        """Initialize email service with configured backend."""
        self._is_configured = False
        self.backend = self._create_backend()
        self.jinja_env = self._create_jinja_env()
        self.from_address = settings.email_from_address
        self.from_name = settings.email_from_name
        self.frontend_base_url = settings.frontend_base_url.rstrip("/")

        logger.info(f"EmailService initialized with backend: {type(self.backend).__name__}")

    @property
    def is_configured(self) -> bool:
        """Check if email service is properly configured."""
        return self._is_configured

    def _create_backend(self) -> EmailBackend:
        """
        Create email backend based on configuration.

        Priority:
        1. If Microsoft Graph config has enable_email=True, use Microsoft Graph
        2. Otherwise, use the email.backend setting from config
        """
        # First, check if Microsoft Graph email is enabled in config.yml
        try:
            from .config_loader import config_loader

            ms_graph_config = config_loader.get_microsoft_graph_config()
            if ms_graph_config and ms_graph_config.enable_email:
                if not ms_graph_config.email_sender_user_id:
                    logger.warning(
                        "Microsoft Graph enable_email is True but email_sender_user_id not configured. "
                        "Using email_from_address as sender."
                    )
                sender_user_id = ms_graph_config.email_sender_user_id or settings.email_from_address
                logger.info("Using Microsoft Graph for email (enable_email=True in config)")
                self._is_configured = True
                return MicrosoftGraphEmailBackend(sender_user_id=sender_user_id)
        except Exception as e:
            logger.debug(f"Could not check Microsoft Graph config: {e}")

        # Fall back to email.backend setting
        backend_type = settings.email_backend.lower()

        if backend_type == "console":
            self._is_configured = True
            return ConsoleEmailBackend()

        elif backend_type == "smtp":
            if not settings.smtp_host:
                logger.warning("SMTP backend selected but smtp_host not configured. Falling back to console.")
                return ConsoleEmailBackend()

            self._is_configured = True
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

            self._is_configured = True
            return SendGridEmailBackend(api_key=settings.sendgrid_api_key)

        elif backend_type == "ses":
            self._is_configured = True
            return SESEmailBackend(
                region=settings.aws_region,
                access_key_id=settings.aws_access_key_id,
                secret_access_key=settings.aws_secret_access_key,
            )

        elif backend_type == "microsoft_graph":
            # Explicit microsoft_graph backend (legacy support)
            # Microsoft Graph backend fetches credentials from connection_service at send time
            self._is_configured = True
            return MicrosoftGraphEmailBackend(
                sender_user_id=settings.email_from_address,
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

    async def send(
        self,
        to: List[str],
        subject: str,
        body: str,
        html: bool = False,
        cc: Optional[List[str]] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
        session: Optional[Any] = None,
        organization_id: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Send an email directly (without templates).

        This method matches the interface expected by the send_email function.

        Args:
            to: List of recipient email addresses
            subject: Email subject
            body: Email body (plain text or HTML)
            html: Whether body is HTML (default: False)
            cc: List of CC recipient email addresses
            attachments: List of attachments [{filename, content, content_type}]
            session: Database session (required for Microsoft Graph backend)
            organization_id: Organization ID (required for Microsoft Graph backend)

        Returns:
            dict: Result with status and details

        Example:
            >>> result = await email_service.send(
            ...     to=["user@example.com"],
            ...     subject="Hello",
            ...     body="<p>This is a test</p>",
            ...     html=True,
            ...     session=db_session,
            ...     organization_id=org_id,
            ... )
        """
        try:
            # Prepare body content
            if html:
                html_body = body
                text_body = "Please view this email in an HTML-capable email client."
            else:
                html_body = f"<pre>{body}</pre>"
                text_body = body

            # Check if backend supports extended sending (with cc, attachments)
            if isinstance(self.backend, MicrosoftGraphEmailBackend):
                success = await self.backend.send_email_extended(
                    to=to,
                    subject=subject,
                    html_body=html_body,
                    text_body=text_body,
                    from_address=self.from_address,
                    from_name=self.from_name,
                    cc=cc,
                    attachments=attachments,
                    session=session,
                    organization_id=organization_id,
                )
            else:
                # For other backends, send to each recipient separately
                # Note: CC and attachments may not be supported by all backends
                if cc:
                    logger.warning(f"CC recipients not supported by {type(self.backend).__name__}")
                if attachments:
                    logger.warning(f"Attachments not supported by {type(self.backend).__name__}")

                success = True
                for recipient in to:
                    result = await self.backend.send_email(
                        to=recipient,
                        subject=subject,
                        html_body=html_body,
                        text_body=text_body,
                        from_address=self.from_address,
                        from_name=self.from_name,
                    )
                    if not result:
                        success = False

            return {
                "success": success,
                "recipients": to,
                "cc": cc or [],
                "subject": subject,
                "backend": type(self.backend).__name__,
            }

        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return {
                "success": False,
                "error": str(e),
                "recipients": to,
            }

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
