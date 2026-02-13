# backend/app/api/v1/routers/organizations.py
"""
Organization management endpoints for Curatore v2 API (v1).

Provides endpoints for managing organization details and settings.
Users can view and update their own organization's information.
System admins can list and manage all organizations.

Endpoints:
    GET /organizations/me - Get current user's organization
    PUT /organizations/me - Update organization details
    GET /organizations/me/settings - Get organization settings
    PUT /organizations/me/settings - Update organization settings

Admin Endpoints:
    GET /organizations - List all organizations (admin only)
    POST /organizations - Create organization (admin only)
    GET /organizations/{org_id} - Get organization by ID (admin only)
    PUT /organizations/{org_id} - Update organization by ID (admin only)

Security:
    - All endpoints require authentication
    - Only org_admin can update organization details
    - Settings are merged (partial updates supported)
    - Admin endpoints require system admin role
"""

import logging
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.api.v1.admin.schemas import (
    OrganizationAdminListResponse,
    OrganizationAdminResponse,
    OrganizationCreateRequest,
    OrganizationResponse,
    OrganizationSettingsResponse,
    OrganizationSettingsUpdateRequest,
    OrganizationUpdateRequest,
)
from app.core.database.models import Organization, OrganizationConnection, User
from app.core.shared.database_service import database_service
from app.dependencies import get_current_organization, get_current_user, require_admin, require_org_admin

# Initialize router
router = APIRouter(prefix="/organizations", tags=["Organizations"])

# Initialize logger
logger = logging.getLogger("curatore.api.organizations")


# =========================================================================
# ORGANIZATION ENDPOINTS
# =========================================================================


@router.get(
    "/me",
    response_model=OrganizationResponse,
    summary="Get current organization",
    description="Get details of the organization the current user belongs to.",
)
async def get_current_user_organization(
    organization: Organization = Depends(get_current_organization),
) -> OrganizationResponse:
    """
    Get current user's organization.

    Returns detailed information about the organization the authenticated
    user belongs to.

    Args:
        organization: Current user's organization (from dependency)

    Returns:
        OrganizationResponse: Organization details

    Example:
        GET /api/v1/organizations/me
        Authorization: Bearer <access_token>

        Response:
        {
            "id": "123e4567-e89b-12d3-a456-426614174000",
            "name": "Acme Corporation",
            "display_name": "Acme Corp",
            "slug": "acme-corp",
            "is_active": true,
            "settings": {...},
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-12T15:30:00"
        }
    """
    logger.info(f"Organization details requested: {organization.name} (id: {organization.id})")

    return OrganizationResponse(
        id=str(organization.id),
        name=organization.name,
        display_name=organization.display_name,
        slug=organization.slug,
        is_active=organization.is_active,
        settings=organization.settings or {},
        created_at=organization.created_at,
        updated_at=organization.updated_at,
    )


@router.put(
    "/me",
    response_model=OrganizationResponse,
    summary="Update organization",
    description="Update organization details. Requires org_admin role.",
)
async def update_organization(
    request: OrganizationUpdateRequest,
    user: User = Depends(require_org_admin),
) -> OrganizationResponse:
    """
    Update organization details.

    Only organization admins can update organization information.
    Currently supports updating display_name.

    Args:
        request: Organization update details
        user: Current user (must be org_admin)

    Returns:
        OrganizationResponse: Updated organization details

    Raises:
        HTTPException: 403 if user is not org_admin
        HTTPException: 404 if organization not found

    Example:
        PUT /api/v1/organizations/me
        Authorization: Bearer <access_token>
        Content-Type: application/json

        {
            "display_name": "Acme Corporation Ltd."
        }
    """
    logger.info(f"Organization update requested by user {user.email}")

    async with database_service.get_session() as session:
        # Fetch organization
        result = await session.execute(
            select(Organization).where(Organization.id == user.organization_id)
        )
        organization = result.scalar_one_or_none()

        if not organization:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Organization not found",
            )

        # Update fields
        if request.slug is not None:
            # Check uniqueness
            existing = await session.execute(
                select(Organization).where(
                    Organization.slug == request.slug,
                    Organization.id != user.organization_id
                )
            )
            if existing.scalar_one_or_none():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Slug already in use"
                )
            organization.slug = request.slug
            logger.info(f"Updated slug to: {request.slug}")

        if request.display_name is not None:
            organization.display_name = request.display_name
            logger.info(f"Updated display_name to: {request.display_name}")

        organization.updated_at = datetime.utcnow()

        await session.commit()
        await session.refresh(organization)

        logger.info(f"Organization updated successfully: {organization.name}")

        return OrganizationResponse(
            id=str(organization.id),
            name=organization.name,
            display_name=organization.display_name,
            slug=organization.slug,
            is_active=organization.is_active,
            settings=organization.settings or {},
            created_at=organization.created_at,
            updated_at=organization.updated_at,
        )


@router.get(
    "/me/settings",
    response_model=OrganizationSettingsResponse,
    summary="Get organization settings",
    description="Get organization-specific settings (quality thresholds, preferences, etc.).",
)
async def get_organization_settings(
    organization: Organization = Depends(get_current_organization),
) -> OrganizationSettingsResponse:
    """
    Get organization settings.

    Returns organization-specific settings including quality thresholds,
    file size limits, allowed formats, and other preferences.

    Args:
        organization: Current user's organization (from dependency)

    Returns:
        OrganizationSettingsResponse: Organization settings

    Example:
        GET /api/v1/organizations/me/settings
        Authorization: Bearer <access_token>

        Response:
        {
            "settings": {
                "quality_thresholds": {
                    "conversion": 70,
                    "clarity": 7,
                    "completeness": 7,
                    "relevance": 7,
                    "markdown": 7
                },
                "auto_optimize": false,
                "max_file_size_mb": 100
            }
        }
    """
    logger.info(f"Settings requested for organization: {organization.name}")

    return OrganizationSettingsResponse(
        settings=organization.settings or {}
    )


@router.put(
    "/me/settings",
    response_model=OrganizationSettingsResponse,
    summary="Update organization settings",
    description="Update organization settings (merged with existing). Requires org_admin role.",
)
async def update_organization_settings(
    request: OrganizationSettingsUpdateRequest,
    user: User = Depends(require_org_admin),
) -> OrganizationSettingsResponse:
    """
    Update organization settings.

    Updates are merged with existing settings (partial updates supported).
    Only organization admins can update settings.

    Args:
        request: Settings to update
        user: Current user (must be org_admin)

    Returns:
        OrganizationSettingsResponse: Updated settings

    Raises:
        HTTPException: 403 if user is not org_admin
        HTTPException: 404 if organization not found

    Example:
        PUT /api/v1/organizations/me/settings
        Authorization: Bearer <access_token>
        Content-Type: application/json

        {
            "settings": {
                "auto_optimize": true,
                "max_file_size_mb": 200
            }
        }

    Note:
        Settings are deep-merged with existing settings. To remove a setting,
        explicitly set it to null.
    """
    logger.info(f"Settings update requested by user {user.email}")

    async with database_service.get_session() as session:
        # Fetch organization
        result = await session.execute(
            select(Organization).where(Organization.id == user.organization_id)
        )
        organization = result.scalar_one_or_none()

        if not organization:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Organization not found",
            )

        # Merge settings (deep merge for nested dicts)
        current_settings = organization.settings or {}
        new_settings = _deep_merge(current_settings, request.settings)

        organization.settings = new_settings
        organization.updated_at = datetime.utcnow()

        await session.commit()
        await session.refresh(organization)

        logger.info(f"Settings updated for organization: {organization.name}")

        return OrganizationSettingsResponse(
            settings=organization.settings or {}
        )


# =========================================================================
# HELPER FUNCTIONS
# =========================================================================


def _deep_merge(base: Dict[str, Any], update: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deep merge two dictionaries.

    Recursively merges 'update' into 'base'. For nested dictionaries,
    performs a deep merge. For other values, 'update' overwrites 'base'.

    Args:
        base: Base dictionary
        update: Dictionary with updates to merge

    Returns:
        Dict[str, Any]: Merged dictionary

    Example:
        >>> base = {"a": {"b": 1, "c": 2}, "d": 3}
        >>> update = {"a": {"c": 99, "e": 4}}
        >>> _deep_merge(base, update)
        {"a": {"b": 1, "c": 99, "e": 4}, "d": 3}
    """
    result = base.copy()

    for key, value in update.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            # Recursively merge nested dicts
            result[key] = _deep_merge(result[key], value)
        else:
            # Overwrite with new value
            result[key] = value

    return result


# =========================================================================
# ADMIN ORGANIZATION ENDPOINTS
# =========================================================================


@router.get(
    "",
    response_model=OrganizationAdminListResponse,
    summary="List all organizations",
    description="List all organizations in the system. Admin only.",
)
async def list_organizations(
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    search: Optional[str] = Query(None, description="Search by name or display_name"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(100, ge=1, le=500, description="Maximum records to return"),
    user: User = Depends(require_admin),
) -> OrganizationAdminListResponse:
    """List all organizations in the system."""
    logger.info(f"Admin {user.email} listing all organizations")

    async with database_service.get_session() as session:
        # Build query
        query = select(Organization)

        if is_active is not None:
            query = query.where(Organization.is_active == is_active)
        if search:
            search_filter = f"%{search}%"
            query = query.where(
                Organization.name.ilike(search_filter) |
                Organization.display_name.ilike(search_filter)
            )

        # Get total count
        count_query = select(func.count()).select_from(Organization)
        if is_active is not None:
            count_query = count_query.where(Organization.is_active == is_active)
        if search:
            search_filter = f"%{search}%"
            count_query = count_query.where(
                Organization.name.ilike(search_filter) |
                Organization.display_name.ilike(search_filter)
            )

        result = await session.execute(count_query)
        total = result.scalar() or 0

        # Apply pagination
        query = query.order_by(Organization.name).offset(skip).limit(limit)
        result = await session.execute(query)
        organizations = result.scalars().all()

        # Get user counts and enabled connection counts for each org
        org_responses = []
        for org in organizations:
            # Count users
            user_count_result = await session.execute(
                select(func.count()).select_from(User).where(User.organization_id == org.id)
            )
            user_count = user_count_result.scalar() or 0

            # Count enabled connections
            conn_count_result = await session.execute(
                select(func.count()).select_from(OrganizationConnection).where(
                    OrganizationConnection.organization_id == org.id,
                    OrganizationConnection.is_enabled == True,
                )
            )
            enabled_connections_count = conn_count_result.scalar() or 0

            org_responses.append(
                OrganizationAdminResponse(
                    id=str(org.id),
                    name=org.name,
                    display_name=org.display_name,
                    slug=org.slug,
                    is_active=org.is_active,
                    settings=org.settings or {},
                    user_count=user_count,
                    enabled_connections_count=enabled_connections_count,
                    created_at=org.created_at,
                    updated_at=org.updated_at,
                )
            )

        return OrganizationAdminListResponse(
            organizations=org_responses,
            total=total,
        )


@router.post(
    "",
    response_model=OrganizationAdminResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create organization",
    description="Create a new organization. Admin only.",
)
async def create_organization(
    request: OrganizationCreateRequest,
    user: User = Depends(require_admin),
) -> OrganizationAdminResponse:
    """Create a new organization."""
    logger.info(f"Admin {user.email} creating organization: {request.name}")

    async with database_service.get_session() as session:
        # Check for duplicate name
        result = await session.execute(
            select(Organization).where(Organization.name == request.name)
        )
        if result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Organization with name '{request.name}' already exists",
            )

        # Check for duplicate slug
        result = await session.execute(
            select(Organization).where(Organization.slug == request.slug)
        )
        if result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Organization with slug '{request.slug}' already exists",
            )

        # Create organization
        organization = Organization(
            name=request.name,
            display_name=request.display_name,
            slug=request.slug,
            settings=request.settings,
            created_by=user.id,
        )
        session.add(organization)
        await session.commit()
        await session.refresh(organization)

        logger.info(f"Created organization: {organization.name} (id: {organization.id})")

        return OrganizationAdminResponse(
            id=str(organization.id),
            name=organization.name,
            display_name=organization.display_name,
            slug=organization.slug,
            is_active=organization.is_active,
            settings=organization.settings or {},
            user_count=0,
            enabled_connections_count=0,
            created_at=organization.created_at,
            updated_at=organization.updated_at,
        )


@router.get(
    "/by-slug/{slug}",
    response_model=OrganizationResponse,
    summary="Get organization by slug",
    description="Get organization details by slug. Returns the organization if the user has access.",
)
async def get_organization_by_slug(
    slug: str,
    user: User = Depends(get_current_user),
) -> OrganizationResponse:
    """Get organization by slug.

    Returns organization details if the user has access to the organization.
    System admins can access any organization.
    Org members can only access their own organization.
    """
    logger.info(f"User {user.email} looking up organization by slug: {slug}")

    async with database_service.get_session() as session:
        result = await session.execute(
            select(Organization).where(Organization.slug == slug)
        )
        organization = result.scalar_one_or_none()

        if not organization:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Organization not found",
            )

        # Check access: system admins can access any org, others only their own
        if user.role != "admin" and user.organization_id != organization.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to this organization",
            )

        return OrganizationResponse(
            id=str(organization.id),
            name=organization.name,
            display_name=organization.display_name,
            slug=organization.slug,
            is_active=organization.is_active,
            settings=organization.settings or {},
            created_at=organization.created_at,
            updated_at=organization.updated_at,
        )


@router.get(
    "/{org_id}",
    response_model=OrganizationAdminResponse,
    summary="Get organization by ID",
    description="Get organization details by ID. Admin only.",
)
async def get_organization_by_id(
    org_id: UUID,
    user: User = Depends(require_admin),
) -> OrganizationAdminResponse:
    """Get organization by ID."""
    async with database_service.get_session() as session:
        result = await session.execute(
            select(Organization).where(Organization.id == org_id)
        )
        organization = result.scalar_one_or_none()

        if not organization:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Organization not found",
            )

        # Count users
        user_count_result = await session.execute(
            select(func.count()).select_from(User).where(User.organization_id == org_id)
        )
        user_count = user_count_result.scalar() or 0

        # Count enabled connections
        conn_count_result = await session.execute(
            select(func.count()).select_from(OrganizationConnection).where(
                OrganizationConnection.organization_id == org_id,
                OrganizationConnection.is_enabled == True,
            )
        )
        enabled_connections_count = conn_count_result.scalar() or 0

        return OrganizationAdminResponse(
            id=str(organization.id),
            name=organization.name,
            display_name=organization.display_name,
            slug=organization.slug,
            is_active=organization.is_active,
            settings=organization.settings or {},
            user_count=user_count,
            enabled_connections_count=enabled_connections_count,
            created_at=organization.created_at,
            updated_at=organization.updated_at,
        )


@router.put(
    "/{org_id}",
    response_model=OrganizationAdminResponse,
    summary="Update organization by ID",
    description="Update organization details by ID. Admin only.",
)
async def update_organization_by_id(
    org_id: UUID,
    request: OrganizationUpdateRequest,
    user: User = Depends(require_admin),
) -> OrganizationAdminResponse:
    """Update organization by ID."""
    logger.info(f"Admin {user.email} updating organization {org_id}")

    async with database_service.get_session() as session:
        result = await session.execute(
            select(Organization).where(Organization.id == org_id)
        )
        organization = result.scalar_one_or_none()

        if not organization:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Organization not found",
            )

        # Update fields
        if request.slug is not None:
            # Check uniqueness
            existing = await session.execute(
                select(Organization).where(
                    Organization.slug == request.slug,
                    Organization.id != org_id
                )
            )
            if existing.scalar_one_or_none():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Slug already in use"
                )
            organization.slug = request.slug
            logger.info(f"Updated slug to: {request.slug}")

        if request.display_name is not None:
            organization.display_name = request.display_name
            logger.info(f"Updated display_name to: {request.display_name}")

        organization.updated_at = datetime.utcnow()

        await session.commit()
        await session.refresh(organization)

        # Count users
        user_count_result = await session.execute(
            select(func.count()).select_from(User).where(User.organization_id == org_id)
        )
        user_count = user_count_result.scalar() or 0

        # Count enabled connections
        conn_count_result = await session.execute(
            select(func.count()).select_from(OrganizationConnection).where(
                OrganizationConnection.organization_id == org_id,
                OrganizationConnection.is_enabled == True,
            )
        )
        enabled_connections_count = conn_count_result.scalar() or 0

        logger.info(f"Updated organization: {organization.name}")

        return OrganizationAdminResponse(
            id=str(organization.id),
            name=organization.name,
            display_name=organization.display_name,
            slug=organization.slug,
            is_active=organization.is_active,
            settings=organization.settings or {},
            user_count=user_count,
            enabled_connections_count=enabled_connections_count,
            created_at=organization.created_at,
            updated_at=organization.updated_at,
        )
