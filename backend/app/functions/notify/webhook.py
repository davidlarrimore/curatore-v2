# backend/app/functions/notify/webhook.py
"""
Webhook function - Call external webhooks.

Makes HTTP calls to external webhook endpoints.
"""

from typing import Any, Dict, List, Optional
import logging

import httpx

from ..base import (
    BaseFunction,
    FunctionMeta,
    FunctionCategory,
    FunctionResult,
    ParameterDoc,
)
from ..context import FunctionContext

logger = logging.getLogger("curatore.functions.notify.webhook")


class WebhookFunction(BaseFunction):
    """
    Call an external webhook endpoint.

    Makes HTTP POST/GET requests to external URLs with JSON payloads.

    Example:
        result = await fn.webhook(ctx,
            url="https://api.example.com/webhook",
            payload={"event": "digest_ready", "data": {...}},
        )
    """

    meta = FunctionMeta(
        name="webhook",
        category=FunctionCategory.NOTIFY,
        description="Call an external webhook endpoint",
        parameters=[
            ParameterDoc(
                name="url",
                type="str",
                description="Webhook URL",
                required=True,
            ),
            ParameterDoc(
                name="payload",
                type="dict",
                description="JSON payload to send",
                required=False,
                default=None,
            ),
            ParameterDoc(
                name="method",
                type="str",
                description="HTTP method",
                required=False,
                default="POST",
                enum_values=["GET", "POST", "PUT", "PATCH"],
            ),
            ParameterDoc(
                name="headers",
                type="dict",
                description="Additional headers",
                required=False,
                default=None,
            ),
            ParameterDoc(
                name="timeout",
                type="int",
                description="Request timeout in seconds",
                required=False,
                default=30,
            ),
            ParameterDoc(
                name="retry_count",
                type="int",
                description="Number of retries on failure",
                required=False,
                default=2,
            ),
        ],
        returns="dict: Response status and body",
        tags=["notify", "webhook", "http"],
        requires_llm=False,
        examples=[
            {
                "description": "Call Slack webhook",
                "params": {
                    "url": "https://hooks.slack.com/services/...",
                    "payload": {"text": "New digest available!"},
                },
            },
        ],
    )

    async def execute(self, ctx: FunctionContext, **params) -> FunctionResult:
        """Call webhook."""
        url = params["url"]
        payload = params.get("payload")
        method = params.get("method", "POST")
        headers = params.get("headers") or {}
        timeout = params.get("timeout", 30)
        retry_count = params.get("retry_count", 2)

        if ctx.dry_run:
            return FunctionResult.success_result(
                data={
                    "url": url,
                    "method": method,
                    "payload_keys": list(payload.keys()) if payload else None,
                },
                message=f"Dry run: would call {method} {url}",
            )

        # Ensure headers dict
        headers = dict(headers)
        if "Content-Type" not in headers:
            headers["Content-Type"] = "application/json"

        last_error = None
        for attempt in range(retry_count + 1):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    if method.upper() == "GET":
                        response = await client.get(url, headers=headers, params=payload)
                    elif method.upper() == "POST":
                        response = await client.post(url, headers=headers, json=payload)
                    elif method.upper() == "PUT":
                        response = await client.put(url, headers=headers, json=payload)
                    elif method.upper() == "PATCH":
                        response = await client.patch(url, headers=headers, json=payload)
                    else:
                        return FunctionResult.failed_result(
                            error=f"Unsupported method: {method}",
                            message="Invalid HTTP method",
                        )

                # Check response
                if response.is_success:
                    # Try to parse JSON response
                    try:
                        response_data = response.json()
                    except Exception:
                        response_data = response.text[:500] if response.text else None

                    return FunctionResult.success_result(
                        data={
                            "status_code": response.status_code,
                            "response": response_data,
                        },
                        message=f"Webhook called successfully: {response.status_code}",
                        items_processed=1,
                    )
                else:
                    last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                    if attempt < retry_count:
                        logger.warning(f"Webhook failed (attempt {attempt + 1}): {last_error}")
                        continue

            except httpx.TimeoutException as e:
                last_error = f"Timeout: {e}"
                if attempt < retry_count:
                    logger.warning(f"Webhook timeout (attempt {attempt + 1})")
                    continue
            except Exception as e:
                last_error = str(e)
                if attempt < retry_count:
                    logger.warning(f"Webhook error (attempt {attempt + 1}): {e}")
                    continue

        return FunctionResult.failed_result(
            error=last_error or "Unknown error",
            message=f"Webhook failed after {retry_count + 1} attempts",
        )
