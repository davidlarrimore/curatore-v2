# backend/app/dependencies.py
"""
FastAPI dependency injection functions for authentication and authorization.

Provides reusable dependencies for protecting endpoints with JWT tokens or API keys,
extracting current user/organization context, and enforcing role-based access control.

Roles: admin (system-wide, organization_id=NULL), member (org-scoped).

Key Dependencies:
    - get_current_user_from_jwt: Validate JWT Bearer token
    - get_current_user_from_api_key: Validate X-API-Key header
    - get_current_user: Flexible auth (JWT or API key)
    - get_current_principal: Get User or ServiceAccount from API key
    - require_admin: Ensure user has system admin role
    - get_effective_org_id: Get org context (supports X-Organization-Id header for admins)
    - require_org_context: Require organization context (not system mode)
    - get_current_organization: Get user's organization

Usage:
    from fastapi import Depends
    from app.dependencies import get_current_user, require_admin
    from app.core.database.models import User

    @router.get("/protected")
    async def protected_endpoint(user: User = Depends(get_current_user)):
        return {"user_id": str(user.id)}

    @router.post("/system-admin-only")
    async def system_admin_endpoint(user: User = Depends(require_admin)):
        return {"message": "System admin access granted"}

Security:
    - All dependencies check if user is_active
    - JWT tokens are validated for signature and expiration
    - API keys are validated against bcrypt hash
    - Multi-tenant isolation: users can only access their org's data
    - System admins can access any org via X-Organization-Id header
"""

import logging
from typing import Optional, Union
from uuid import UUID as UUID_TYPE

import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from app.config import settings
from app.core.auth.auth_service import auth_service
from app.core.database.models import ApiKey, Organization, ServiceAccount, User
from app.core.shared.database_service import database_service

# Type alias for authenticated principals (User or ServiceAccount)
Principal = Union[User, ServiceAccount]

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

    Note: This function only returns User objects. For service account support,
    use get_current_principal_from_api_key() instead.

    Args:
        x_api_key: API key from X-API-Key header

    Returns:
        User: User associated with the API key

    Raises:
        HTTPException: 401 if API key is invalid, expired, or inactive
        HTTPException: 403 if API key belongs to a service account

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
    principal = await get_current_principal_from_api_key(x_api_key)

    # If service account, reject (use get_current_principal_from_api_key for that)
    if isinstance(principal, ServiceAccount):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Service accounts cannot use this endpoint. Use a user API key.",
        )

    return principal


async def get_current_principal_from_api_key(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> Principal:
    """
    Extract and validate principal (User or ServiceAccount) from API key.

    Validates the API key from X-API-Key header, fetches the associated
    principal from database. Returns 401 if key is invalid, expired, or inactive.

    Args:
        x_api_key: API key from X-API-Key header

    Returns:
        Principal: User or ServiceAccount associated with the API key

    Raises:
        HTTPException: 401 if API key is invalid, expired, or inactive

    Example:
        @router.get("/api/endpoint")
        async def api_endpoint(principal: Principal = Depends(get_current_principal_from_api_key)):
            if isinstance(principal, User):
                return {"user_id": str(principal.id)}
            else:
                return {"service_account_id": str(principal.id)}

    Security:
        - Validates API key against bcrypt hash
        - Checks key is not expired
        - Checks key and principal are active
        - Updates last_used_at timestamp on both API key and service account
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

            # Update last_used_at timestamp on API key
            from datetime import datetime
            api_key.last_used_at = datetime.utcnow()

            # Determine if this is a user or service account key
            if api_key.user_id:
                # User key
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

                await session.commit()
                logger.debug(f"User authenticated via API key: {user.email} (key: {key_prefix})")
                return user

            elif api_key.service_account_id:
                # Service account key
                result = await session.execute(
                    select(ServiceAccount).where(ServiceAccount.id == api_key.service_account_id)
                )
                service_account = result.scalar_one_or_none()

                if not service_account:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Service account not found",
                        headers={"WWW-Authenticate": 'ApiKey realm="API Key Required"'},
                    )

                if not service_account.is_active:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Service account is inactive",
                        headers={"WWW-Authenticate": 'ApiKey realm="API Key Required"'},
                    )

                # Update service account's last_used_at
                service_account.last_used_at = datetime.utcnow()
                await session.commit()
                logger.debug(f"Service account authenticated via API key: {service_account.name} (key: {key_prefix})")
                return service_account

            else:
                # Neither user_id nor service_account_id set (should not happen due to CHECK constraint)
                logger.error(f"API key {api_key.id} has neither user_id nor service_account_id")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid API key configuration",
                    headers={"WWW-Authenticate": 'ApiKey realm="API Key Required"'},
                )

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

    When ENABLE_AUTH=false (backward compatibility mode), returns the first user
    in the database without requiring credentials. When ENABLE_AUTH=true, requires
    JWT Bearer token or X-API-Key header.

    Args:
        credentials: HTTP Bearer token from Authorization header (optional)
        x_api_key: API key from X-API-Key header (optional)

    Returns:
        User: Current authenticated user

    Raises:
        HTTPException: 401 if authentication fails (when auth is enabled)
        HTTPException: 500 if no user found (when auth is disabled)

    Example:
        @router.get("/protected")
        async def protected_endpoint(user: User = Depends(get_current_user)):
            # Accepts both "Authorization: Bearer <token>" and "X-API-Key: <key>"
            return {"user_id": str(user.id)}

    Priority:
        1. Check if authentication is disabled (ENABLE_AUTH=false) -> return default user
        2. JWT Bearer token (if provided)
        3. X-API-Key header (if JWT not provided)
    """
    # Backward compatibility mode: if auth is disabled, return first user
    if not settings.enable_auth:
        async with database_service.get_session() as session:
            result = await session.execute(
                select(User).where(User.role == "admin").limit(1)
            )
            user = result.scalar_one_or_none()

            if not user:
                logger.error("No users found in database for backward compatibility mode")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="No users found. Please run database seed: python -m app.core.commands.seed --create-admin",
                )

            logger.debug(f"Backward compatibility mode: using default user {user.email}")
            return user

    # Authentication enabled: require credentials
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


async def require_admin(user: User = Depends(get_current_user)) -> User:
    """
    Ensure the current user has system admin role.

    Dependency that requires user to be authenticated AND have 'admin' role.
    System admins have access to all organizations and system-level configuration.

    Args:
        user: Current authenticated user (from get_current_user)

    Returns:
        User: Current authenticated user (guaranteed to be admin)

    Raises:
        HTTPException: 403 if user is not a system admin

    Example:
        @router.get("/system/organizations")
        async def list_all_organizations(user: User = Depends(require_admin)):
            # Only system admins can list all organizations
            return await list_orgs()

    Note:
        Admin users have organization_id=NULL and can access any org via
        the X-Organization-Id header.
    """
    if user.role != "admin":
        logger.warning(f"Permission denied: user {user.email} (role: {user.role}) attempted system admin action")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="System admin role required",
        )

    return user


# =========================================================================
# ORGANIZATION CONTEXT
# =========================================================================


async def get_effective_org_id(
    user: User = Depends(get_current_user),
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id"),
) -> Optional[UUID_TYPE]:
    """
    Get effective organization context.

    For system admins:
        - If X-Organization-Id header is provided, use that org (after validation)
        - If no header, return None (system context)

    For non-admin users:
        - Always use user.organization_id (header is ignored)

    Args:
        user: Current authenticated user
        x_organization_id: Optional X-Organization-Id header (admin only)

    Returns:
        Optional[UUID]: Organization ID for org context, None for system context

    Raises:
        HTTPException: 404 if specified organization not found or inactive

    Example:
        @router.get("/assets")
        async def list_assets(
            org_id: Optional[UUID] = Depends(get_effective_org_id),
        ):
            if org_id:
                # Org context: filter by org
                return await list_assets_for_org(org_id)
            else:
                # System context: return all assets (admin only)
                return await list_all_assets()

    Note:
        System context (None) is only possible for admin users.
        Non-admin users always have an org context.
    """
    # Non-admin users: always use their organization
    if user.role != "admin":
        return user.organization_id

    # Admin users: use header if provided, otherwise system context (None)
    if x_organization_id:
        try:
            org_id = UUID_TYPE(x_organization_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid organization ID format",
            )

        # Validate org exists and is active
        async with database_service.get_session() as session:
            result = await session.execute(
                select(Organization).where(Organization.id == org_id)
            )
            org = result.scalar_one_or_none()

            if not org:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Organization not found",
                )

            if not org.is_active:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Organization is inactive",
                )

            logger.debug(f"Admin {user.email} using org context: {org.name}")
            return org_id

    # No header: system context
    logger.debug(f"Admin {user.email} using system context")
    return None


async def require_org_context(
    org_id: Optional[UUID_TYPE] = Depends(get_effective_org_id),
) -> UUID_TYPE:
    """
    Require an organization context (not system context).

    Use this dependency for endpoints that require an organization context.
    System admins must provide X-Organization-Id header to access these endpoints.

    Args:
        org_id: Organization ID from get_effective_org_id

    Returns:
        UUID: Organization ID (guaranteed to be set)

    Raises:
        HTTPException: 400 if no organization context is set

    Example:
        @router.get("/assets")
        async def list_assets(
            org_id: UUID = Depends(require_org_context),
        ):
            # org_id is guaranteed to be set
            return await list_assets_for_org(org_id)
    """
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Organization context required. Provide X-Organization-Id header.",
        )

    return org_id


async def get_current_organization(
    user: User = Depends(get_current_user),
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id"),
) -> Organization:
    """
    Get the organization for the current context.

    For regular users, returns their organization.
    For admin users, uses X-Organization-Id header if provided, otherwise raises error.

    Args:
        user: Current authenticated user
        x_organization_id: Optional org ID header (for admins)

    Returns:
        Organization: Organization for current context

    Raises:
        HTTPException: 404 if organization not found
        HTTPException: 400 if admin user without X-Organization-Id header

    Example:
        @router.get("/org/settings")
        async def get_org_settings(
            org: Organization = Depends(get_current_organization)
        ):
            return {"org_name": org.name, "settings": org.settings}
    """
    # Determine which org ID to use
    if user.role == "admin":
        if not x_organization_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Admin users must provide X-Organization-Id header",
            )
        try:
            org_id = UUID_TYPE(x_organization_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid organization ID format",
            )
    else:
        org_id = user.organization_id

    async with database_service.get_session() as session:
        result = await session.execute(
            select(Organization).where(Organization.id == org_id)
        )
        org = result.scalar_one_or_none()

        if not org:
            logger.error(f"Organization {org_id} not found for user {user.email}")
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


# =========================================================================
# ORGANIZATION ID HELPER
# =========================================================================


async def get_current_org_id(
    org_id: Optional[UUID_TYPE] = Depends(get_effective_org_id),
) -> UUID_TYPE:
    """
    Get the organization ID for the current context.

    A convenience dependency that extracts the organization ID from the context.
    For regular users, this is their organization_id.
    For admin users with X-Organization-Id header, this is the specified org.
    For admin users without the header, this raises an error.

    Args:
        org_id: Organization ID from get_effective_org_id

    Returns:
        UUID: Organization ID for current context

    Raises:
        HTTPException: 400 if no organization context

    Example:
        @router.get("/org-data")
        async def get_org_data(
            org_id: UUID = Depends(get_current_org_id)
        ):
            # Query using org_id
            return {"org_id": str(org_id)}

    Note:
        This dependency requires an org context. Admin users must provide
        X-Organization-Id header. Use get_effective_org_id directly if you
        want to allow system context (None) for admins.
    """
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Organization context required. Provide X-Organization-Id header.",
        )
    return org_id


# Alias for backwards compatibility
get_optional_current_user = get_current_user_optional


# =========================================================================
# DATA SOURCE ENABLEMENT
# =========================================================================


def require_data_source_enabled(*source_types: str):
    """
    Dependency factory: 403 if none of the given source types are enabled for the org.

    Uses the cached data source catalog (5-min TTL) so there is no extra DB query
    in the common case.

    Args:
        source_types: One or more source type identifiers. At least one must be
            enabled for the request to proceed (OR logic).

    Returns:
        A FastAPI dependency that raises 403 if the data source is not enabled.

    Example:
        router = APIRouter(
            dependencies=[Depends(require_data_source_enabled("sam_gov"))]
        )
    """
    async def _check(
        org_id: UUID_TYPE = Depends(get_current_org_id),
    ):
        from app.core.metadata.registry_service import metadata_registry_service

        async with database_service.get_session() as session:
            catalog = await metadata_registry_service.get_data_source_catalog(
                session, org_id
            )
            for st in source_types:
                if catalog.get(st, {}).get("is_active", False):
                    return  # At least one enabled
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Data connection is not enabled for this organization.",
        )

    return _check


# =========================================================================
# DOCUMENT ID VALIDATION
# =========================================================================


def validate_document_id_param(document_id: str) -> str:
    """
    Validate document ID parameter from API endpoint.

    Ensures document_id is a valid UUID. This dependency should be used on
    all endpoints that accept document_id as a path or query parameter.

    Args:
        document_id: Document ID from path or query parameter

    Returns:
        str: Validated document ID (normalized to lowercase)

    Raises:
        HTTPException: 400 if document_id is not a valid UUID

    Example:
        from fastapi import Depends
        from app.dependencies import validate_document_id_param

        @router.get("/documents/{document_id}")
        async def get_document(
            document_id: str = Depends(validate_document_id_param)
        ):
            # document_id is guaranteed to be a valid UUID
            return {"document_id": document_id}

    Security:
        - Enforces UUID-only format
        - Provides clear error messages for API consumers
    """
    from app.core.utils.validators import validate_document_id

    try:
        return validate_document_id(document_id)
    except ValueError as e:
        logger.warning(f"Invalid document_id parameter: {document_id} - {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
