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
from pathlib import Path
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


def _process_email_body(body: str, format: str, subject: str) -> tuple:
    """
    Convert body to final HTML based on format.

    Returns (processed_body, is_html) tuple.

    Formats:
        - "template" (default): Convert markdown to HTML, wrap in branded template
        - "html": Pass through as-is
        - "text": Send as plain text
    """
    if format == "html":
        return body, True

    if format == "text":
        return body, False

    # Default: template — markdown → HTML → branded wrapper
    from ..context import _markdown_to_html

    html_content = _markdown_to_html(body)

    # Resolve frontend_base_url for footer link
    frontend_base_url = None
    try:
        from app.core.auth.email_service import email_service
        frontend_base_url = email_service.frontend_base_url
    except Exception:
        pass

    # Load template from CWR templates directory
    try:
        from jinja2 import Environment, FileSystemLoader, select_autoescape

        template_dir = Path(__file__).resolve().parent.parent.parent / "templates" / "email"
        env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            autoescape=select_autoescape(["html", "xml"]),
        )
        template = env.get_template("email_base.html")
        wrapped = template.render(
            subject=subject,
            content=html_content,
            frontend_base_url=frontend_base_url,
        )
        return wrapped, True
    except Exception as e:
        logger.warning(f"Failed to render email template, using raw content: {e}")
        return html_content, True


async def _resolve_attachments(
    attachments: list, ctx: "FunctionContext"
) -> list:
    """
    Resolve attachment references to base64-encoded content.

    Each attachment dict may contain:
    - object_key + bucket: fetch directly from MinIO (preferred)
    - url: fetch via HTTP (fallback, e.g., presigned URL)

    Returns list of dicts with {filename, content, content_type, is_base64}.
    """
    import base64

    resolved = []
    for att in attachments:
        filename = att.get("filename", "attachment")
        content_type = att.get("content_type", "application/octet-stream")
        object_key = att.get("object_key")
        bucket = att.get("bucket")
        url = att.get("url")

        raw_bytes = None

        # Prefer direct MinIO access (no presigned URL needed)
        if object_key and bucket:
            minio = ctx.minio_service
            if minio and minio.enabled:
                logger.info(
                    f"Resolving attachment from storage: {bucket}/{object_key}"
                )
                bio = minio.get_object(bucket=bucket, key=object_key)
                raw_bytes = bio.read()
            else:
                raise RuntimeError(
                    f"MinIO not available to resolve attachment: {filename}"
                )

        # Fallback: fetch via HTTP URL
        elif url:
            import httpx

            logger.info(f"Resolving attachment from URL: {url}")
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                raw_bytes = resp.content

        else:
            raise ValueError(
                f"Attachment '{filename}' has no object_key/bucket or url"
            )

        resolved.append({
            "filename": filename,
            "content": base64.b64encode(raw_bytes).decode("utf-8"),
            "content_type": content_type,
            "is_base64": True,
        })

    return resolved


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
                    "description": "Email body content. Write naturally using markdown formatting (headings, bold, lists, tables). The system automatically styles this into a professional HTML email.",
                },
                "format": {
                    "type": "string",
                    "enum": ["template", "html", "text"],
                    "default": "template",
                    "description": "Body format. 'template' (default) converts markdown to a branded HTML email. 'html' sends body as raw HTML. 'text' sends as plain text.",
                },
                "cc": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "CC recipients",
                    "default": None,
                },
                "attachments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "filename": {"type": "string", "description": "Attachment filename"},
                            "content_type": {"type": "string", "description": "MIME type"},
                            "url": {"type": "string", "description": "URL to download (e.g., presigned URL from generate_document)"},
                            "object_key": {"type": "string", "description": "Object storage key (preferred over url)"},
                            "bucket": {"type": "string", "description": "Object storage bucket (used with object_key)"},
                        },
                        "required": ["filename", "content_type"],
                    },
                    "description": "File attachments. Pass storage references from generate_document output.",
                    "default": [],
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
        email_format = params.get("format", "template")
        cc = params.get("cc") or []
        attachments = params.get("attachments") or []

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

        # Process body through template wrapping
        processed_body, is_html = _process_email_body(body, email_format, subject)

        # Generate token and store pending email
        token = _generate_token()
        expires_at = datetime.utcnow() + timedelta(minutes=TOKEN_EXPIRATION_MINUTES)

        email_data = {
            "to": to,
            "subject": subject,
            "body": processed_body,
            "html": is_html,
            "cc": cc,
            "attachments": attachments,
            "organization_id": str(ctx.organization_id) if ctx.organization_id else None,
            "created_at": datetime.utcnow().isoformat(),
            "expires_at": expires_at.isoformat(),
        }

        _pending_emails[token] = {
            **email_data,
            "expires_at": expires_at,
        }

        # Create preview using original markdown body for readability
        body_preview = body[:500] + "..." if len(body) > 500 else body
        preview = {
            "to": to,
            "cc": cc if cc else None,
            "subject": subject,
            "body_preview": body_preview,
            "format": email_format,
            "recipient_count": len(to) + len(cc),
            "attachments_count": len(attachments),
            "attachment_filenames": [a.get("filename", "unknown") for a in attachments] if attachments else [],
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

        # Resolve attachments from storage references
        resolved_attachments = []
        pending_attachments = email_data.get("attachments") or []
        if pending_attachments:
            try:
                resolved_attachments = await _resolve_attachments(
                    pending_attachments, ctx
                )
            except Exception as e:
                logger.exception(f"Failed to resolve attachments: {e}")
                return FunctionResult.failed_result(
                    error=f"Failed to resolve attachments: {e}",
                    message="Could not fetch attachment files. The email was not sent.",
                )

        # Send via the primitive send_email function
        try:
            from ..primitives.notify.send_email import SendEmailFunction

            send_fn = SendEmailFunction()
            # Body is already processed by prepare_email, pass format
            # matching stored is_html to avoid double-processing
            stored_format = "text" if not email_data.get("html", True) else "html"
            result = await send_fn.execute(
                ctx,
                to=email_data["to"],
                subject=email_data["subject"],
                body=email_data["body"],
                format=stored_format,
                cc=email_data.get("cc"),
                attachments=resolved_attachments if resolved_attachments else None,
            )

            if result.status == "success":
                return FunctionResult.success_result(
                    data={
                        "success": True,
                        "to": email_data["to"],
                        "subject": email_data["subject"],
                        "message_id": result.data.get("message_id") if result.data else None,
                        "attachments_count": len(resolved_attachments),
                    },
                    message=f"Email sent to {len(email_data['to'])} recipients"
                    + (f" with {len(resolved_attachments)} attachment(s)" if resolved_attachments else ""),
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
