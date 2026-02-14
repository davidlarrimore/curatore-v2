# backend/app/api/v1/routers/api_keys.py
"""
API Key management endpoints for Curatore v2 API (v1).

Provides endpoints for users to generate and manage their API keys for
programmatic access to the platform.

Endpoints:
    GET /api-keys - List user's API keys
    POST /api-keys - Generate new API key
    PUT /api-keys/{key_id} - Update API key (name)
    DELETE /api-keys/{key_id} - Revoke API key

Security:
    - All endpoints require authentication
    - Users can only manage their own API keys
    - Full API key shown only once on creation
    - Keys are hashed with bcrypt before storage
"""

import logging
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.api.v1.admin.schemas import (
    ApiKeyCreateRequest,
    ApiKeyCreateResponse,
    ApiKeyListResponse,
    ApiKeyResponse,
    ApiKeyUpdateRequest,
)
from app.core.auth.auth_service import auth_service
from app.core.database.models import ApiKey, User
from app.core.shared.database_service import database_service
from app.dependencies import get_current_org_id, get_current_user

# Initialize router
router = APIRouter(prefix="/api-keys", tags=["API Keys"])

# Initialize logger
logger = logging.getLogger("curatore.api.api_keys")


# =========================================================================
# API KEY ENDPOINTS
# =========================================================================


@router.get(
    "",
    response_model=ApiKeyListResponse,
    summary="List API keys",
    description="List all API keys for the current user.",
)
async def list_api_keys(
    is_active: bool = Query(None, description="Filter by active status (optional)"),
    skip: int = Query(0, ge=0, description="Number of keys to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Max keys to return"),
    current_user: User = Depends(get_current_user),
) -> ApiKeyListResponse:
    """
    List user's API keys.

    Returns a paginated list of API keys owned by the authenticated user.
    Does not return the full key value (only prefix for identification).

    Args:
        is_active: Filter by active status (optional)
        skip: Number of keys to skip (for pagination)
        limit: Maximum keys to return
        current_user: Current authenticated user

    Returns:
        ApiKeyListResponse: List of API keys with total count

    Example:
        GET /api/v1/api-keys?is_active=true
        Authorization: Bearer <access_token>

        Response:
        {
            "keys": [
                {
                    "id": "...",
                    "name": "Production API Key",
                    "prefix": "cur_1a2b3c4d",
                    "is_active": true,
                    "created_at": "2024-01-01T00:00:00",
                    "last_used_at": "2024-01-12T15:30:00",
                    "expires_at": null
                }
            ],
            "total": 1
        }
    """
    logger.info(f"API keys list requested by {current_user.email}")

    async with database_service.get_session() as session:
        # Build query
        query = select(ApiKey).where(ApiKey.user_id == current_user.id)

        # Apply filters
        if is_active is not None:
            query = query.where(ApiKey.is_active == is_active)

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await session.execute(count_query)
        total = total_result.scalar() or 0

        # Apply pagination and execute
        query = query.order_by(ApiKey.created_at.desc()).offset(skip).limit(limit)
        result = await session.execute(query)
        keys = result.scalars().all()

        logger.info(f"Returning {len(keys)} API keys (total: {total})")

        return ApiKeyListResponse(
            keys=[
                ApiKeyResponse(
                    id=str(key.id),
                    name=key.name,
                    prefix=key.prefix,
                    is_active=key.is_active,
                    created_at=key.created_at,
                    last_used_at=key.last_used_at,
                    expires_at=key.expires_at,
                )
                for key in keys
            ],
            total=total,
        )


@router.post(
    "",
    response_model=ApiKeyCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate API key",
    description="Generate a new API key. The full key is shown only once!",
)
async def create_api_key(
    request: ApiKeyCreateRequest,
    current_user: User = Depends(get_current_user),
    org_id: UUID = Depends(get_current_org_id),
) -> ApiKeyCreateResponse:
    """
    Generate new API key.

    Creates a new API key for the authenticated user. The full key is
    returned in the response and will NEVER be shown again. Store it securely!

    Args:
        request: API key creation details (name, expiration)
        current_user: Current authenticated user

    Returns:
        ApiKeyCreateResponse: Created API key with full key value

    Example:
        POST /api/v1/api-keys
        Authorization: Bearer <access_token>
        Content-Type: application/json

        {
            "name": "Production API Key",
            "expires_days": 90
        }

        Response:
        {
            "id": "...",
            "name": "Production API Key",
            "key": "cur_1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p",
            "prefix": "cur_1a2b3c4d",
            "created_at": "2024-01-01T00:00:00",
            "expires_at": "2024-04-01T00:00:00"
        }

    Security:
        - Full key shown ONLY in this response
        - Key is hashed with bcrypt before storage
        - Store the key securely (it cannot be retrieved later)
    """
    logger.info(f"API key creation requested by {current_user.email} (name: {request.name})")

    # Generate API key
    full_key, key_hash, prefix = auth_service.generate_api_key()

    # Calculate expiration
    expires_at = None
    if request.expires_days:
        expires_at = datetime.utcnow() + timedelta(days=request.expires_days)

    async with database_service.get_session() as session:
        # Create API key record
        api_key = ApiKey(
            id=uuid4(),
            user_id=current_user.id,
            organization_id=org_id,
            name=request.name,
            key_hash=key_hash,
            prefix=prefix,
            is_active=True,
            expires_at=expires_at,
        )

        session.add(api_key)
        await session.commit()
        await session.refresh(api_key)

        logger.info(
            f"API key created: {api_key.name} (id: {api_key.id}, prefix: {prefix}, "
            f"expires: {expires_at or 'never'})"
        )
        logger.warning(
            f"⚠️  IMPORTANT: Full key generated for {current_user.email}: {full_key[:15]}... "
            f"(this is the only time it will be shown)"
        )

        return ApiKeyCreateResponse(
            id=str(api_key.id),
            name=api_key.name,
            key=full_key,  # Full key shown ONLY here!
            prefix=api_key.prefix,
            created_at=api_key.created_at,
            expires_at=api_key.expires_at,
        )


@router.put(
    "/{key_id}",
    response_model=ApiKeyResponse,
    summary="Update API key",
    description="Update API key details (name only).",
)
async def update_api_key(
    key_id: str,
    request: ApiKeyUpdateRequest,
    current_user: User = Depends(get_current_user),
) -> ApiKeyResponse:
    """
    Update API key details.

    Currently only supports updating the key name. Cannot change expiration
    or reactivate a revoked key.

    Args:
        key_id: API key UUID
        request: Update details (name)
        current_user: Current authenticated user

    Returns:
        ApiKeyResponse: Updated API key details

    Raises:
        HTTPException: 404 if key not found or not owned by user

    Example:
        PUT /api/v1/api-keys/123e4567-e89b-12d3-a456-426614174000
        Authorization: Bearer <access_token>
        Content-Type: application/json

        {
            "name": "Updated Production Key"
        }
    """
    logger.info(f"API key update requested for {key_id} by {current_user.email}")

    async with database_service.get_session() as session:
        result = await session.execute(
            select(ApiKey)
            .where(ApiKey.id == UUID(key_id))
            .where(ApiKey.user_id == current_user.id)
        )
        api_key = result.scalar_one_or_none()

        if not api_key:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="API key not found",
            )

        # Update name
        if request.name is not None:
            api_key.name = request.name
            logger.info(f"Updated API key name to: {request.name}")

        await session.commit()
        await session.refresh(api_key)

        logger.info(f"API key updated successfully: {api_key.prefix}")

        return ApiKeyResponse(
            id=str(api_key.id),
            name=api_key.name,
            prefix=api_key.prefix,
            is_active=api_key.is_active,
            created_at=api_key.created_at,
            last_used_at=api_key.last_used_at,
            expires_at=api_key.expires_at,
        )


@router.delete(
    "/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke API key",
    description="Revoke an API key (soft delete). Cannot be undone.",
)
async def revoke_api_key(
    key_id: str,
    current_user: User = Depends(get_current_user),
) -> None:
    """
    Revoke API key.

    Performs a soft delete by setting is_active=False. The key can no longer
    be used for authentication. This action cannot be undone.

    Args:
        key_id: API key UUID
        current_user: Current authenticated user

    Raises:
        HTTPException: 404 if key not found or not owned by user
        HTTPException: 400 if key is already revoked

    Example:
        DELETE /api/v1/api-keys/123e4567-e89b-12d3-a456-426614174000
        Authorization: Bearer <access_token>

    Note:
        Revoked keys remain in the database for audit purposes. To reactivate,
        generate a new key instead.
    """
    logger.info(f"API key revocation requested for {key_id} by {current_user.email}")

    async with database_service.get_session() as session:
        result = await session.execute(
            select(ApiKey)
            .where(ApiKey.id == UUID(key_id))
            .where(ApiKey.user_id == current_user.id)
        )
        api_key = result.scalar_one_or_none()

        if not api_key:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="API key not found",
            )

        if not api_key.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="API key is already revoked",
            )

        api_key.is_active = False
        await session.commit()

        logger.info(f"API key revoked: {api_key.prefix} (name: {api_key.name})")
