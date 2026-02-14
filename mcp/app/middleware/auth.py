# Authentication Middleware
"""API key authentication for MCP Gateway.

Follows the same SERVICE_API_KEY pattern as document-service and
playwright-service, plus extracts per-user identity from
X-OpenWebUI-User-Email for delegation to the backend.
"""

import logging
from typing import Optional, Tuple

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.config import settings

logger = logging.getLogger("mcp.middleware.auth")


def verify_api_key(authorization: Optional[str]) -> Tuple[bool, Optional[str]]:
    """
    Verify API key from Authorization header.

    Args:
        authorization: Authorization header value (e.g., "Bearer xxx")

    Returns:
        Tuple of (is_valid, user_email) where user_email is extracted
        from X-OpenWebUI-User-Email if present (set later in middleware).
    """
    if not authorization:
        return False, None

    # Extract token from "Bearer xxx" format
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return False, None

    token = parts[1].strip()

    # Check against configured SERVICE_API_KEY
    if token == settings.service_api_key:
        return True, None

    return False, None


class AuthMiddleware(BaseHTTPMiddleware):
    """Middleware to verify API key authentication."""

    # Paths that don't require authentication
    PUBLIC_PATHS = {"/health", "/health/", "/", "/openapi.json"}

    async def dispatch(self, request: Request, call_next):
        """Check authentication for protected endpoints."""
        path = request.url.path

        # Skip auth for CORS preflight requests
        if request.method == "OPTIONS":
            return await call_next(request)

        # Skip auth for public paths
        if path in self.PUBLIC_PATHS:
            return await call_next(request)

        # Dev mode: if service_api_key is empty, pass all requests through
        if not settings.service_api_key:
            logger.debug("Dev mode: SERVICE_API_KEY not set, skipping auth")
            request.state.api_key = settings.backend_api_key or None
            request.state.user_email = request.headers.get("X-OpenWebUI-User-Email")
            return await call_next(request)

        # Get authorization header
        authorization = request.headers.get("Authorization")

        # Verify SERVICE_API_KEY
        is_valid, _ = verify_api_key(authorization)

        if not is_valid:
            logger.warning(f"Unauthorized request to {path}")
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Store backend API key for forwarding to backend
        request.state.api_key = settings.backend_api_key or None

        # Extract user email from Open WebUI forwarded header
        request.state.user_email = request.headers.get("X-OpenWebUI-User-Email")

        return await call_next(request)
