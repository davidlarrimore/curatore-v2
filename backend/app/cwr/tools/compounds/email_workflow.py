# backend/app/cwr/tools/compounds/email_workflow.py
"""
Two-step email workflow for MCP/AI agents.

Provides prepare_email and confirm_email functions that require explicit
user confirmation before sending. Designed for AI agent safety.

The primitive send_email remains available for procedures that don't
need the two-step confirmation flow.
"""

import logging
import secrets
from datetime import datetime, timedelta
from typing import Any, Dict

from ..base import (
    BaseFunction,
    FunctionCategory,
    FunctionMeta,
    FunctionResult,
)
from ..context import FunctionContext

logger = logging.getLogger("curatore.functions.compounds.email_workflow")

# In-memory store for pending emails (use Redis in production)
# Format: {token: {email_data, created_at, expires_at}}
_pending_emails: Dict[str, Dict[str, Any]] = {}

# Token expiration (15 minutes)
TOKEN_EXPIRATION_MINUTES = 15


def _cleanup_expired():
    """Remove expired pending emails."""
    now = datetime.utcnow()
    expired = [
        token for token, data in _pending_emails.items()
        if data.get("expires_at", now) < now
    ]
    for token in expired:
        del _pending_emails[token]


def _generate_token() -> str:
    """Generate a secure confirmation token."""
    return secrets.token_urlsafe(32)


class PrepareEmailFunction(BaseFunction):
    """
    Prepare an email for sending (requires confirmation).

    Creates an email draft and returns a preview with a confirmation token.
    The email is NOT sent until confirm_email is called with the token.

    This enables AI agents to show users exactly what will be sent
    before actually sending.

    Example:
        # Step 1: Prepare the email
        result = await prepare_email(ctx,
            to=["user@example.com"],
            subject="Weekly Report",
            body="Here is your report...",
        )
        # Returns: {confirmation_token, preview, expires_in}

        # Step 2: Show preview to user, get approval

        # Step 3: Confirm and send
        result = await confirm_email(ctx,
            confirmation_token="abc123...",
        )
    """

    meta = FunctionMeta(
        name="prepare_email",
        category=FunctionCategory.NOTIFY,
        description="Prepare an email for sending. Returns a preview and confirmation token. Call confirm_email with the token to actually send.",
        input_schema={
            "type": "object",
            "properties": {
                "to": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Recipient email addresses",
                    "examples": [["user@example.com"]],
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject line",
                },
                "body": {
                    "type": "string",
                    "description": "Email body content (plain text or HTML)",
                },
                "html": {
                    "type": "boolean",
                    "description": "Whether body is HTML formatted",
                    "default": False,
                },
                "cc": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "CC recipients",
                    "default": None,
                },
            },
            "required": ["to", "subject", "body"],
        },
        output_schema={
            "type": "object",
            "description": "Email preview and confirmation details",
            "properties": {
                "confirmation_token": {
                    "type": "string",
                    "description": "Token to confirm and send the email. Pass to confirm_email.",
                },
                "preview": {
                    "type": "object",
                    "description": "Preview of the email that will be sent",
                },
                "expires_in_minutes": {
                    "type": "integer",
                    "description": "Minutes until the confirmation token expires",
                },
                "instructions": {
                    "type": "string",
                    "description": "Instructions for the user/agent",
                },
            },
        },
        tags=["notify", "email", "mcp", "confirmation"],
        requires_llm=False,
        side_effects=False,  # No side effects - just prepares
        is_primitive=False,  # Compound function
        payload_profile="full",
        examples=[
            {
                "description": "Prepare a simple email",
                "params": {
                    "to": ["user@example.com"],
                    "subject": "Meeting Summary",
                    "body": "Here are the key points from today's meeting...",
                },
            },
        ],
    )

    async def execute(self, ctx: FunctionContext, **params) -> FunctionResult:
        """Prepare email and return confirmation token."""
        _cleanup_expired()

        to = params["to"]
        subject = params["subject"]
        body = params["body"]
        html = params.get("html", False)
        cc = params.get("cc") or []

        # Normalize recipients
        if isinstance(to, str):
            to = [t.strip() for t in to.split(",") if t.strip()]
        if isinstance(cc, str):
            cc = [c.strip() for c in cc.split(",") if c.strip()]

        if not to:
            return FunctionResult.failed_result(
                error="No recipients",
                message="At least one recipient email is required",
            )

        # Generate token and store pending email
        token = _generate_token()
        expires_at = datetime.utcnow() + timedelta(minutes=TOKEN_EXPIRATION_MINUTES)

        email_data = {
            "to": to,
            "subject": subject,
            "body": body,
            "html": html,
            "cc": cc,
            "organization_id": str(ctx.organization_id) if ctx.organization_id else None,
            "created_at": datetime.utcnow().isoformat(),
            "expires_at": expires_at.isoformat(),
        }

        _pending_emails[token] = {
            **email_data,
            "expires_at": expires_at,
        }

        # Create preview
        body_preview = body[:500] + "..." if len(body) > 500 else body
        preview = {
            "to": to,
            "cc": cc if cc else None,
            "subject": subject,
            "body_preview": body_preview,
            "is_html": html,
            "recipient_count": len(to) + len(cc),
        }

        return FunctionResult.success_result(
            data={
                "confirmation_token": token,
                "preview": preview,
                "expires_in_minutes": TOKEN_EXPIRATION_MINUTES,
                "instructions": (
                    "Review the email preview above. To send this email, "
                    f"call confirm_email with confirmation_token='{token}'. "
                    f"The token expires in {TOKEN_EXPIRATION_MINUTES} minutes."
                ),
            },
            message=f"Email prepared for {len(to)} recipients. Awaiting confirmation.",
        )


class ConfirmEmailFunction(BaseFunction):
    """
    Confirm and send a prepared email.

    Requires a valid confirmation token from prepare_email.
    This ensures the user has seen the preview before sending.

    Example:
        result = await confirm_email(ctx,
            confirmation_token="abc123...",
        )
    """

    meta = FunctionMeta(
        name="confirm_email",
        category=FunctionCategory.NOTIFY,
        description="Confirm and send a prepared email. Requires the confirmation_token from prepare_email.",
        input_schema={
            "type": "object",
            "properties": {
                "confirmation_token": {
                    "type": "string",
                    "description": "The confirmation token from prepare_email",
                },
            },
            "required": ["confirmation_token"],
        },
        output_schema={
            "type": "object",
            "description": "Email send operation result",
            "properties": {
                "success": {
                    "type": "boolean",
                    "description": "Whether the email was sent",
                },
                "to": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Recipients",
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject",
                },
                "message_id": {
                    "type": "string",
                    "description": "Email service message ID",
                    "nullable": True,
                },
            },
        },
        tags=["notify", "email", "mcp", "confirmation"],
        requires_llm=False,
        side_effects=True,  # Actually sends the email
        is_primitive=False,  # Compound function
        payload_profile="full",
        examples=[
            {
                "description": "Confirm and send email",
                "params": {
                    "confirmation_token": "abc123xyz...",
                },
            },
        ],
    )

    async def execute(self, ctx: FunctionContext, **params) -> FunctionResult:
        """Confirm and send the prepared email."""
        _cleanup_expired()

        token = params["confirmation_token"]

        # Validate token
        if token not in _pending_emails:
            return FunctionResult.failed_result(
                error="Invalid or expired token",
                message=(
                    "The confirmation token is invalid or has expired. "
                    "Please call prepare_email again to create a new email draft."
                ),
            )

        email_data = _pending_emails.pop(token)

        # Check expiration
        if datetime.utcnow() > email_data["expires_at"]:
            return FunctionResult.failed_result(
                error="Token expired",
                message=(
                    "The confirmation token has expired. "
                    "Please call prepare_email again."
                ),
            )

        # Send via the primitive send_email function
        try:
            from ..primitives.notify.send_email import SendEmailFunction

            send_fn = SendEmailFunction()
            result = await send_fn.execute(
                ctx,
                to=email_data["to"],
                subject=email_data["subject"],
                body=email_data["body"],
                html=email_data.get("html", False),
                cc=email_data.get("cc"),
            )

            if result.status == "success":
                return FunctionResult.success_result(
                    data={
                        "success": True,
                        "to": email_data["to"],
                        "subject": email_data["subject"],
                        "message_id": result.data.get("message_id") if result.data else None,
                    },
                    message=f"Email sent to {len(email_data['to'])} recipients",
                    items_processed=len(email_data["to"]),
                )
            else:
                return FunctionResult.failed_result(
                    error=result.error or "Send failed",
                    message=result.message or "Failed to send email",
                )

        except Exception as e:
            logger.exception(f"Failed to send confirmed email: {e}")
            return FunctionResult.failed_result(
                error=str(e),
                message="Failed to send email after confirmation",
            )
