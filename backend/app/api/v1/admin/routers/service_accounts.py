# backend/app/api/v1/admin/routers/service_accounts.py
"""
Service account management endpoints for Curatore v2 API (v1).

Provides endpoints for managing service accounts - non-human identities
for automated API access. Service accounts are org-scoped and can be
managed by org_admins or system admins.

Endpoints:
    GET /service-accounts - List service accounts for current org
    POST /service-accounts - Create a new service account
    GET /service-accounts/{id} - Get service account details
    PUT /service-accounts/{id} - Update a service account
    DELETE /service-accounts/{id} - Delete a service account
    POST /service-accounts/{id}/api-keys - Generate API key for service account

Security:
    - All endpoints require org_admin or admin role
    - Service accounts are scoped to organizations
"""

import logging
import secrets
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.api.v1.admin.schemas import (
    ApiKeyCreateRequest,
    ApiKeyListResponse,
    ApiKeyResponse,
    ServiceAccountApiKeyCreateResponse,
    ServiceAccountCreateRequest,
    ServiceAccountListResponse,
    ServiceAccountResponse,
    ServiceAccountUpdateRequest,
)
from app.core.auth.auth_service import auth_service
from app.core.database.models import ApiKey, Organization, ServiceAccount, User
from app.core.shared.database_service import database_service
from app.dependencies import (
    get_effective_org_id,
    require_org_admin_or_above,
    require_org_context,
)

# Initialize router
router = APIRouter(prefix="/service-accounts", tags=["Service Accounts"])

# Initialize logger
logger = logging.getLogger("curatore.api.service_accounts")

# Valid roles for service accounts
VALID_ROLES = {"member", "viewer"}


# =========================================================================
# SERVICE ACCOUNT CRUD ENDPOINTS
# =========================================================================


@router.get(
    "",
    response_model=ServiceAccountListResponse,
    summary="List service accounts",
    description="List service accounts for the current organization.",
)
async def list_service_accounts(
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(100, ge=1, le=500, description="Maximum records to return"),
    org_id: UUID = Depends(require_org_context),
    user: User = Depends(require_org_admin_or_above),
) -> ServiceAccountListResponse:
    """List service accounts for the current organization."""
    logger.info(f"User {user.email} listing service accounts for org {org_id}")

    async with database_service.get_session() as session:
        # Build query
        query = select(ServiceAccount).where(ServiceAccount.organization_id == org_id)

        if is_active is not None:
            query = query.where(ServiceAccount.is_active == is_active)

        # Get total count
        count_query = select(func.count()).select_from(ServiceAccount).where(
            ServiceAccount.organization_id == org_id
        )
        if is_active is not None:
            count_query = count_query.where(ServiceAccount.is_active == is_active)

        result = await session.execute(count_query)
        total = result.scalar() or 0

        # Apply pagination and get results
        query = query.order_by(ServiceAccount.name).offset(skip).limit(limit)
        result = await session.execute(query)
        accounts = result.scalars().all()

        # Get org name
        org_result = await session.execute(
            select(Organization.display_name).where(Organization.id == org_id)
        )
        org_name = org_result.scalar()

        return ServiceAccountListResponse(
            service_accounts=[
                ServiceAccountResponse(
                    id=str(sa.id),
                    name=sa.name,
                    description=sa.description,
                    organization_id=str(sa.organization_id),
                    organization_name=org_name,
                    role=sa.role,
                    is_active=sa.is_active,
                    created_at=sa.created_at,
                    updated_at=sa.updated_at,
                    last_used_at=sa.last_used_at,
                )
                for sa in accounts
            ],
            total=total,
        )


@router.post(
    "",
    response_model=ServiceAccountResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a service account",
    description="Create a new service account for the current organization.",
)
async def create_service_account(
    request: ServiceAccountCreateRequest,
    org_id: UUID = Depends(require_org_context),
    user: User = Depends(require_org_admin_or_above),
) -> ServiceAccountResponse:
    """Create a new service account."""
    logger.info(f"User {user.email} creating service account: {request.name}")

    # Validate role
    if request.role not in VALID_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role. Must be one of: {', '.join(VALID_ROLES)}",
        )

    async with database_service.get_session() as session:
        # Check for duplicate name within org
        result = await session.execute(
            select(ServiceAccount).where(
                ServiceAccount.organization_id == org_id,
                ServiceAccount.name == request.name,
            )
        )
        if result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Service account '{request.name}' already exists in this organization",
            )

        # Get org name
        org_result = await session.execute(
            select(Organization.display_name).where(Organization.id == org_id)
        )
        org_name = org_result.scalar()

        # Create service account
        service_account = ServiceAccount(
            name=request.name,
            description=request.description,
            organization_id=org_id,
            role=request.role,
            created_by=user.id,
        )
        session.add(service_account)
        await session.commit()
        await session.refresh(service_account)

        logger.info(f"Created service account: {service_account.name} (id: {service_account.id})")

        return ServiceAccountResponse(
            id=str(service_account.id),
            name=service_account.name,
            description=service_account.description,
            organization_id=str(service_account.organization_id),
            organization_name=org_name,
            role=service_account.role,
            is_active=service_account.is_active,
            created_at=service_account.created_at,
            updated_at=service_account.updated_at,
            last_used_at=service_account.last_used_at,
        )


@router.get(
    "/{service_account_id}",
    response_model=ServiceAccountResponse,
    summary="Get service account details",
    description="Get details of a specific service account.",
)
async def get_service_account(
    service_account_id: UUID,
    org_id: UUID = Depends(require_org_context),
    user: User = Depends(require_org_admin_or_above),
) -> ServiceAccountResponse:
    """Get service account details."""
    async with database_service.get_session() as session:
        result = await session.execute(
            select(ServiceAccount).where(
                ServiceAccount.id == service_account_id,
                ServiceAccount.organization_id == org_id,
            )
        )
        service_account = result.scalar_one_or_none()

        if not service_account:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Service account not found",
            )

        # Get org name
        org_result = await session.execute(
            select(Organization.display_name).where(Organization.id == org_id)
        )
        org_name = org_result.scalar()

        return ServiceAccountResponse(
            id=str(service_account.id),
            name=service_account.name,
            description=service_account.description,
            organization_id=str(service_account.organization_id),
            organization_name=org_name,
            role=service_account.role,
            is_active=service_account.is_active,
            created_at=service_account.created_at,
            updated_at=service_account.updated_at,
            last_used_at=service_account.last_used_at,
        )


@router.put(
    "/{service_account_id}",
    response_model=ServiceAccountResponse,
    summary="Update a service account",
    description="Update a service account's details.",
)
async def update_service_account(
    service_account_id: UUID,
    request: ServiceAccountUpdateRequest,
    org_id: UUID = Depends(require_org_context),
    user: User = Depends(require_org_admin_or_above),
) -> ServiceAccountResponse:
    """Update a service account."""
    logger.info(f"User {user.email} updating service account {service_account_id}")

    # Validate role if provided
    if request.role is not None and request.role not in VALID_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role. Must be one of: {', '.join(VALID_ROLES)}",
        )

    async with database_service.get_session() as session:
        result = await session.execute(
            select(ServiceAccount).where(
                ServiceAccount.id == service_account_id,
                ServiceAccount.organization_id == org_id,
            )
        )
        service_account = result.scalar_one_or_none()

        if not service_account:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Service account not found",
            )

        # Check for duplicate name if being changed
        if request.name is not None and request.name != service_account.name:
            dup_result = await session.execute(
                select(ServiceAccount).where(
                    ServiceAccount.organization_id == org_id,
                    ServiceAccount.name == request.name,
                    ServiceAccount.id != service_account_id,
                )
            )
            if dup_result.scalar_one_or_none():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Service account '{request.name}' already exists",
                )

        # Update fields
        if request.name is not None:
            service_account.name = request.name
        if request.description is not None:
            service_account.description = request.description
        if request.role is not None:
            service_account.role = request.role
        if request.is_active is not None:
            service_account.is_active = request.is_active

        service_account.updated_at = datetime.utcnow()

        await session.commit()
        await session.refresh(service_account)

        # Get org name
        org_result = await session.execute(
            select(Organization.display_name).where(Organization.id == org_id)
        )
        org_name = org_result.scalar()

        logger.info(f"Updated service account: {service_account.name}")

        return ServiceAccountResponse(
            id=str(service_account.id),
            name=service_account.name,
            description=service_account.description,
            organization_id=str(service_account.organization_id),
            organization_name=org_name,
            role=service_account.role,
            is_active=service_account.is_active,
            created_at=service_account.created_at,
            updated_at=service_account.updated_at,
            last_used_at=service_account.last_used_at,
        )


@router.delete(
    "/{service_account_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a service account",
    description="Delete a service account and all its API keys.",
)
async def delete_service_account(
    service_account_id: UUID,
    org_id: UUID = Depends(require_org_context),
    user: User = Depends(require_org_admin_or_above),
) -> None:
    """Delete a service account."""
    logger.info(f"User {user.email} deleting service account {service_account_id}")

    async with database_service.get_session() as session:
        result = await session.execute(
            select(ServiceAccount).where(
                ServiceAccount.id == service_account_id,
                ServiceAccount.organization_id == org_id,
            )
        )
        service_account = result.scalar_one_or_none()

        if not service_account:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Service account not found",
            )

        await session.delete(service_account)
        await session.commit()

        logger.info(f"Deleted service account: {service_account.name}")


# =========================================================================
# SERVICE ACCOUNT API KEY ENDPOINTS
# =========================================================================


@router.get(
    "/{service_account_id}/api-keys",
    response_model=ApiKeyListResponse,
    summary="List API keys for a service account",
    description="List all API keys for a service account.",
)
async def list_service_account_api_keys(
    service_account_id: UUID,
    org_id: UUID = Depends(require_org_context),
    user: User = Depends(require_org_admin_or_above),
) -> ApiKeyListResponse:
    """List API keys for a service account."""
    async with database_service.get_session() as session:
        # Verify service account exists and belongs to org
        result = await session.execute(
            select(ServiceAccount).where(
                ServiceAccount.id == service_account_id,
                ServiceAccount.organization_id == org_id,
            )
        )
        service_account = result.scalar_one_or_none()

        if not service_account:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Service account not found",
            )

        # Get API keys
        result = await session.execute(
            select(ApiKey).where(ApiKey.service_account_id == service_account_id)
        )
        keys = result.scalars().all()

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
            total=len(keys),
        )


@router.post(
    "/{service_account_id}/api-keys",
    response_model=ServiceAccountApiKeyCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create API key for service account",
    description="Generate a new API key for a service account. The full key is only shown once!",
)
async def create_service_account_api_key(
    service_account_id: UUID,
    request: ApiKeyCreateRequest,
    org_id: UUID = Depends(require_org_context),
    user: User = Depends(require_org_admin_or_above),
) -> ServiceAccountApiKeyCreateResponse:
    """Create an API key for a service account."""
    logger.info(f"User {user.email} creating API key for service account {service_account_id}")

    async with database_service.get_session() as session:
        # Verify service account exists and belongs to org
        result = await session.execute(
            select(ServiceAccount).where(
                ServiceAccount.id == service_account_id,
                ServiceAccount.organization_id == org_id,
            )
        )
        service_account = result.scalar_one_or_none()

        if not service_account:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Service account not found",
            )

        # Generate API key
        full_key, key_hash, prefix = auth_service.generate_api_key()

        # Calculate expiration
        expires_at = None
        if request.expires_days:
            expires_at = datetime.utcnow() + timedelta(days=request.expires_days)

        # Create API key
        api_key = ApiKey(
            organization_id=org_id,
            service_account_id=service_account_id,
            name=request.name,
            key_hash=key_hash,
            prefix=prefix,
            expires_at=expires_at,
        )
        session.add(api_key)
        await session.commit()
        await session.refresh(api_key)

        logger.info(f"Created API key {prefix} for service account {service_account.name}")

        return ServiceAccountApiKeyCreateResponse(
            id=str(api_key.id),
            name=api_key.name,
            key=full_key,  # Only shown once!
            prefix=api_key.prefix,
            service_account_id=str(service_account.id),
            service_account_name=service_account.name,
            created_at=api_key.created_at,
            expires_at=api_key.expires_at,
        )


@router.delete(
    "/{service_account_id}/api-keys/{api_key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete API key",
    description="Delete an API key for a service account.",
)
async def delete_service_account_api_key(
    service_account_id: UUID,
    api_key_id: UUID,
    org_id: UUID = Depends(require_org_context),
    user: User = Depends(require_org_admin_or_above),
) -> None:
    """Delete an API key for a service account."""
    logger.info(f"User {user.email} deleting API key {api_key_id}")

    async with database_service.get_session() as session:
        # Verify API key belongs to service account and org
        result = await session.execute(
            select(ApiKey).where(
                ApiKey.id == api_key_id,
                ApiKey.service_account_id == service_account_id,
                ApiKey.organization_id == org_id,
            )
        )
        api_key = result.scalar_one_or_none()

        if not api_key:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="API key not found",
            )

        await session.delete(api_key)
        await session.commit()

        logger.info(f"Deleted API key: {api_key.prefix}")
