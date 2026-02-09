# Authentication Middleware
"""API key authentication for MCP Gateway."""

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
        Tuple of (is_valid, org_id)
    """
    if not authorization:
        return False, None

    # Extract token from "Bearer xxx" format
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return False, None

    token = parts[1].strip()

    # Check against configured API key
    if token == settings.mcp_api_key:
        return True, settings.default_org_id

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

        # Get authorization header
        authorization = request.headers.get("Authorization")

        # Verify API key
        is_valid, org_id = verify_api_key(authorization)

        if not is_valid:
            logger.warning(f"Unauthorized request to {path}")
            # Return JSONResponse directly instead of raising HTTPException
            # HTTPException doesn't work properly in BaseHTTPMiddleware
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Store org_id in request state for handlers
        request.state.org_id = org_id
        request.state.api_key = settings.mcp_api_key

        return await call_next(request)
