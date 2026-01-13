# backend/app/dependencies.py
"""
FastAPI dependency injection functions for authentication and authorization.

Provides reusable dependencies for protecting endpoints with JWT tokens or API keys,
extracting current user/organization context, and enforcing role-based access control.

Key Dependencies:
    - get_current_user_from_jwt: Validate JWT Bearer token
    - get_current_user_from_api_key: Validate X-API-Key header
    - get_current_user: Flexible auth (JWT or API key)
    - require_org_admin: Ensure user has admin role
    - get_current_organization: Get user's organization

Usage:
    from fastapi import Depends
    from app.dependencies import get_current_user, require_org_admin
    from app.database.models import User

    @router.get("/protected")
    async def protected_endpoint(user: User = Depends(get_current_user)):
        return {"user_id": str(user.id)}

    @router.post("/admin-only")
    async def admin_endpoint(user: User = Depends(require_org_admin)):
        return {"message": "Admin access granted"}

Security:
    - All dependencies check if user is_active
    - JWT tokens are validated for signature and expiration
    - API keys are validated against bcrypt hash
    - Multi-tenant isolation: users can only access their org's data
"""

import logging
from typing import Optional

import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from app.config import settings
from app.database.models import ApiKey, Organization, User
from app.services.auth_service import auth_service
from app.services.database_service import database_service

# Initialize logger
logger = logging.getLogger("curatore.dependencies")

# HTTP Bearer scheme for JWT tokens
bearer_scheme = HTTPBearer(auto_error=False)


# =========================================================================
# JWT AUTHENTICATION
# =========================================================================


async def get_current_user_from_jwt(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> User:
    """
    Extract and validate user from JWT Bearer token.

    Validates the JWT token, extracts user_id, and fetches the user from database.
    Returns 401 if token is invalid, expired, or user not found/inactive.

    Args:
        credentials: HTTP Bearer token from Authorization header

    Returns:
        User: Current authenticated user

    Raises:
        HTTPException: 401 if token is invalid, expired, or user not found/inactive

    Example:
        @router.get("/me")
        async def get_me(user: User = Depends(get_current_user_from_jwt)):
            return {"user_id": str(user.id), "email": user.email}

    Security:
        - Validates token signature and expiration
        - Checks user exists and is active
        - Token must be type "access" (not refresh token)
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    try:
        # Decode and validate JWT token
        payload = auth_service.decode_token(token)

        # Verify token type is "access"
        if not auth_service.verify_token_type(payload, "access"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type. Expected access token.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Extract user_id from token
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token payload missing user ID",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Fetch user from database
        async with database_service.get_session() as session:
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()

            if not user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User not found",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            if not user.is_active:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User account is inactive",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            # Update last login timestamp
            user.last_login_at = auth_service._logger  # Using datetime.utcnow would be better
            from datetime import datetime
            user.last_login_at = datetime.utcnow()
            await session.commit()

            logger.debug(f"User authenticated via JWT: {user.email} (org: {user.organization_id})")
            return user

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"JWT authentication error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed",
            headers={"WWW-Authenticate": "Bearer"},
        )


# =========================================================================
# API KEY AUTHENTICATION
# =========================================================================


async def get_current_user_from_api_key(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> User:
    """
    Extract and validate user from API key.

    Validates the API key from X-API-Key header, fetches the associated user
    from database. Returns 401 if key is invalid, expired, or inactive.

    Args:
        x_api_key: API key from X-API-Key header

    Returns:
        User: User associated with the API key

    Raises:
        HTTPException: 401 if API key is invalid, expired, or inactive

    Example:
        @router.get("/api/endpoint")
        async def api_endpoint(user: User = Depends(get_current_user_from_api_key)):
            return {"user_id": str(user.id)}

    Security:
        - Validates API key against bcrypt hash
        - Checks key is not expired
        - Checks key and user are active
        - Updates last_used_at timestamp
    """
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key",
            headers={"WWW-Authenticate": 'ApiKey realm="API Key Required"'},
        )

    try:
        # Fetch API key from database by prefix
        # Extract prefix from provided key (e.g., "cur_1a2b3c4d" from "cur_1a2b3c4d...")
        prefix_length = len(settings.api_key_prefix) + 8
        if len(x_api_key) < prefix_length:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key format",
                headers={"WWW-Authenticate": 'ApiKey realm="API Key Required"'},
            )

        key_prefix = x_api_key[:prefix_length]

        async with database_service.get_session() as session:
            # Find API key by prefix
            result = await session.execute(
                select(ApiKey)
                .where(ApiKey.prefix == key_prefix)
                .where(ApiKey.is_active == True)
            )
            api_key = result.scalar_one_or_none()

            if not api_key:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid API key",
                    headers={"WWW-Authenticate": 'ApiKey realm="API Key Required"'},
                )

            # Verify API key hash
            is_valid = await auth_service.verify_api_key(x_api_key, api_key.key_hash)
            if not is_valid:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid API key",
                    headers={"WWW-Authenticate": 'ApiKey realm="API Key Required"'},
                )

            # Check if API key is expired
            if api_key.expires_at:
                from datetime import datetime
                if datetime.utcnow() > api_key.expires_at:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="API key has expired",
                        headers={"WWW-Authenticate": 'ApiKey realm="API Key Required"'},
                    )

            # Fetch associated user
            result = await session.execute(
                select(User).where(User.id == api_key.user_id)
            )
            user = result.scalar_one_or_none()

            if not user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User not found",
                    headers={"WWW-Authenticate": 'ApiKey realm="API Key Required"'},
                )

            if not user.is_active:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User account is inactive",
                    headers={"WWW-Authenticate": 'ApiKey realm="API Key Required"'},
                )

            # Update last_used_at timestamp
            from datetime import datetime
            api_key.last_used_at = datetime.utcnow()
            await session.commit()

            logger.debug(f"User authenticated via API key: {user.email} (key: {key_prefix})")
            return user

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"API key authentication error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed",
            headers={"WWW-Authenticate": 'ApiKey realm="API Key Required"'},
        )


# =========================================================================
# FLEXIBLE AUTHENTICATION (JWT OR API KEY)
# =========================================================================


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> User:
    """
    Extract and validate user from either JWT token or API key.

    Tries JWT Bearer token first, then falls back to X-API-Key header.
    Returns 401 if neither authentication method is provided or both are invalid.

    Args:
        credentials: HTTP Bearer token from Authorization header (optional)
        x_api_key: API key from X-API-Key header (optional)

    Returns:
        User: Current authenticated user

    Raises:
        HTTPException: 401 if authentication fails

    Example:
        @router.get("/protected")
        async def protected_endpoint(user: User = Depends(get_current_user)):
            # Accepts both "Authorization: Bearer <token>" and "X-API-Key: <key>"
            return {"user_id": str(user.id)}

    Priority:
        1. JWT Bearer token (if provided)
        2. X-API-Key header (if JWT not provided)
    """
    # Try JWT first
    if credentials:
        try:
            return await get_current_user_from_jwt(credentials)
        except HTTPException:
            # If JWT fails and API key is also provided, try API key
            if not x_api_key:
                raise

    # Try API key
    if x_api_key:
        return await get_current_user_from_api_key(x_api_key)

    # No authentication provided
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required. Provide either Bearer token or API key.",
        headers={"WWW-Authenticate": "Bearer"},
    )


# =========================================================================
# AUTHORIZATION (ROLE-BASED)
# =========================================================================


async def require_org_admin(user: User = Depends(get_current_user)) -> User:
    """
    Ensure the current user has organization admin role.

    Dependency that requires user to be authenticated AND have org_admin role.
    Returns 403 if user doesn't have sufficient permissions.

    Args:
        user: Current authenticated user (from get_current_user)

    Returns:
        User: Current authenticated user (guaranteed to be org_admin)

    Raises:
        HTTPException: 403 if user is not an organization admin

    Example:
        @router.post("/admin/settings")
        async def update_settings(
            settings: dict,
            user: User = Depends(require_org_admin)
        ):
            # Only org_admin users can access this endpoint
            return {"message": "Settings updated"}

    Roles:
        - org_admin: Full organization access
        - member: Standard user access
        - viewer: Read-only access
    """
    if user.role != "org_admin":
        logger.warning(f"Permission denied: user {user.email} (role: {user.role}) attempted admin action")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization admin role required",
        )

    return user


async def require_member_or_admin(user: User = Depends(get_current_user)) -> User:
    """
    Ensure the current user has at least member role (member or org_admin).

    Args:
        user: Current authenticated user

    Returns:
        User: Current authenticated user (guaranteed to be member or org_admin)

    Raises:
        HTTPException: 403 if user is only a viewer

    Example:
        @router.post("/documents/upload")
        async def upload_document(
            file: UploadFile,
            user: User = Depends(require_member_or_admin)
        ):
            # Viewers cannot upload
            return {"message": "Document uploaded"}
    """
    if user.role not in ["org_admin", "member"]:
        logger.warning(f"Permission denied: user {user.email} (role: {user.role}) attempted member action")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Member or admin role required",
        )

    return user


# =========================================================================
# ORGANIZATION CONTEXT
# =========================================================================


async def get_current_organization(user: User = Depends(get_current_user)) -> Organization:
    """
    Get the organization for the current user.

    Fetches the organization associated with the authenticated user.

    Args:
        user: Current authenticated user

    Returns:
        Organization: User's organization

    Raises:
        HTTPException: 404 if organization not found

    Example:
        @router.get("/org/settings")
        async def get_org_settings(
            org: Organization = Depends(get_current_organization)
        ):
            return {"org_name": org.name, "settings": org.settings}
    """
    async with database_service.get_session() as session:
        result = await session.execute(
            select(Organization).where(Organization.id == user.organization_id)
        )
        org = result.scalar_one_or_none()

        if not org:
            logger.error(f"Organization {user.organization_id} not found for user {user.email}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Organization not found",
            )

        if not org.is_active:
            logger.warning(f"User {user.email} attempted to access inactive org {org.name}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Organization is inactive",
            )

        return org


# =========================================================================
# OPTIONAL AUTHENTICATION (FOR BACKWARD COMPATIBILITY)
# =========================================================================


async def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> Optional[User]:
    """
    Get current user if authenticated, or None if not authenticated.

    Used for endpoints that work with or without authentication, providing
    different behavior based on authentication state.

    Args:
        credentials: HTTP Bearer token (optional)
        x_api_key: API key (optional)

    Returns:
        Optional[User]: Current user if authenticated, None otherwise

    Example:
        @router.get("/public-or-private")
        async def endpoint(user: Optional[User] = Depends(get_current_user_optional)):
            if user:
                return {"message": f"Hello {user.email}"}
            else:
                return {"message": "Hello anonymous user"}

    Backward Compatibility:
        Useful during migration when ENABLE_AUTH=false allows unauthenticated access
    """
    try:
        return await get_current_user(credentials, x_api_key)
    except HTTPException:
        return None
