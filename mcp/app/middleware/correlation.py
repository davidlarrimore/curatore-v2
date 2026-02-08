# Correlation ID Middleware
"""Request correlation ID tracking for distributed tracing."""

import logging
import uuid
from contextvars import ContextVar
from typing import Optional

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("mcp.middleware.correlation")

# Context variable to store correlation ID
_correlation_id: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)


def get_correlation_id() -> Optional[str]:
    """Get the current correlation ID from context."""
    return _correlation_id.get()


def set_correlation_id(correlation_id: str) -> None:
    """Set the correlation ID in context."""
    _correlation_id.set(correlation_id)


class CorrelationMiddleware(BaseHTTPMiddleware):
    """Middleware to extract or generate correlation ID."""

    CORRELATION_HEADER = "X-Correlation-ID"

    async def dispatch(self, request: Request, call_next):
        """Extract or generate correlation ID for request."""
        # Get from header or generate new
        correlation_id = request.headers.get(self.CORRELATION_HEADER)
        if not correlation_id:
            correlation_id = str(uuid.uuid4())

        # Store in context and request state
        set_correlation_id(correlation_id)
        request.state.correlation_id = correlation_id

        # Log request with correlation ID
        logger.debug(
            f"[{correlation_id}] {request.method} {request.url.path}"
        )

        # Process request
        response = await call_next(request)

        # Add correlation ID to response headers
        response.headers[self.CORRELATION_HEADER] = correlation_id

        return response
