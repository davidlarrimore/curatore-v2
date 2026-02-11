# backend/app/functions/notify/send_email.py
"""
Send Email function - Send email notifications.

Sends emails using configured email service.
"""

from typing import Any, Dict, List, Optional, Union
import logging

from ...base import (
    BaseFunction,
    FunctionMeta,
    FunctionCategory,
    FunctionResult,
)
from ...context import FunctionContext

logger = logging.getLogger("curatore.functions.notify.send_email")


class SendEmailFunction(BaseFunction):
    """
    Send email notification.

    Sends an email using the configured email service (SMTP, SES, etc.).

    Example:
        result = await fn.send_email(ctx,
            to=["user@example.com"],
            subject="Daily Digest",
            body="Here is your daily summary...",
        )
    """

    meta = FunctionMeta(
        name="send_email",
        category=FunctionCategory.NOTIFY,
        description="Send email notification",
        input_schema={
            "type": "object",
            "properties": {
                "to": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Recipient email addresses (list, single email, or comma-separated string)",
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject",
                },
                "body": {
                    "type": "string",
                    "description": "Email body (plain text or HTML)",
                },
                "html": {
                    "type": "boolean",
                    "description": "Whether body is HTML",
                    "default": False,
                },
                "cc": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "CC recipients (list, single email, or comma-separated string)",
                    "default": None,
                },
                "attachments": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Attachments: [{filename, content, content_type}]",
                    "default": None,
                },
            },
            "required": ["to", "subject", "body"],
        },
        output_schema={
            "type": "object",
            "description": "Email send operation result",
            "properties": {
                "to": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of recipient email addresses",
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject line",
                },
                "status": {
                    "type": "string",
                    "description": "Send status (sent, logged)",
                    "examples": ["sent"],
                },
                "success": {
                    "type": "boolean",
                    "description": "Whether the email was sent successfully",
                },
                "message_id": {
                    "type": "string",
                    "description": "Email service message ID",
                    "nullable": True,
                },
                "error": {
                    "type": "string",
                    "description": "Error message if send failed",
                    "nullable": True,
                },
            },
        },
        tags=["notify", "email"],
        requires_llm=False,
        side_effects=True,
        is_primitive=True,
        payload_profile="full",
        examples=[
            {
                "description": "Simple email",
                "params": {
                    "to": ["user@example.com"],
                    "subject": "Test Email",
                    "body": "This is a test email.",
                },
            },
            {
                "description": "HTML formatted email",
                "params": {
                    "to": ["user@example.com"],
                    "subject": "Weekly Report",
                    "body": "<html><body><h1>Report</h1><p>Content here...</p></body></html>",
                    "html": True,
                },
            },
        ],
    )

    def _normalize_recipients(self, recipients: Any) -> List[str]:
        """
        Normalize recipients to a list of email addresses.

        Handles:
        - Single email string: "user@example.com"
        - Comma-separated string: "a@example.com, b@example.com"
        - List of emails: ["a@example.com", "b@example.com"]
        - String representation of list: "['a@example.com']"
        """
        if not recipients:
            return []

        # Already a list
        if isinstance(recipients, list):
            return [r.strip() for r in recipients if r and isinstance(r, str)]

        # String handling
        if isinstance(recipients, str):
            # Handle string representation of list: "['email@example.com']"
            if recipients.startswith("[") and recipients.endswith("]"):
                # Parse as a simple list - strip brackets and quotes
                inner = recipients[1:-1].strip()
                if not inner:
                    return []
                # Split by comma, strip quotes and whitespace
                parts = inner.split(",")
                return [
                    p.strip().strip("'").strip('"').strip()
                    for p in parts
                    if p.strip().strip("'").strip('"').strip()
                ]

            # Comma-separated string
            if "," in recipients:
                return [r.strip() for r in recipients.split(",") if r.strip()]

            # Single email
            return [recipients.strip()] if recipients.strip() else []

        return []

    async def execute(self, ctx: FunctionContext, **params) -> FunctionResult:
        """Send email."""
        to = self._normalize_recipients(params["to"])
        subject = params["subject"]
        body = params["body"]
        html = params.get("html", False)
        cc = self._normalize_recipients(params.get("cc"))
        attachments = params.get("attachments") or []

        if not to:
            return FunctionResult.failed_result(
                error="No recipients",
                message="At least one recipient is required",
            )

        if ctx.dry_run:
            return FunctionResult.success_result(
                data={
                    "to": to,
                    "subject": subject,
                    "body_preview": body[:100] + "..." if len(body) > 100 else body,
                },
                message=f"Dry run: would send email to {len(to)} recipients",
            )

        try:
            # Try to import email service
            # Note: Email service may not be configured in all deployments
            try:
                from app.core.auth.email_service import email_service

                if not email_service or not email_service.is_configured:
                    return FunctionResult.failed_result(
                        error="Email service not configured",
                        message="Email service is not available",
                    )

                result = await email_service.send(
                    to=to,
                    subject=subject,
                    body=body,
                    html=html,
                    cc=cc,
                    attachments=attachments,
                    session=ctx.session,
                    organization_id=ctx.organization_id,
                )

                # Check if the send was actually successful
                if not result.get("success", False):
                    return FunctionResult.failed_result(
                        error=result.get("error", "Email send failed"),
                        message=f"Failed to send email: {result.get('error', 'Unknown error')}",
                        data=result,
                    )

                return FunctionResult.success_result(
                    data=result,
                    message=f"Email sent to {len(to)} recipients",
                    items_processed=len(to),
                )

            except ImportError:
                # Email service not implemented yet
                logger.warning("Email service not available - logging email instead")
                ctx.log_info(
                    f"Would send email: to={to}, subject={subject}",
                    body_preview=body[:200],
                )
                return FunctionResult.success_result(
                    data={
                        "to": to,
                        "subject": subject,
                        "status": "logged",
                    },
                    message="Email logged (email service not configured)",
                )

        except Exception as e:
            logger.exception(f"Failed to send email: {e}")
            return FunctionResult.failed_result(
                error=str(e),
                message="Failed to send email",
            )
