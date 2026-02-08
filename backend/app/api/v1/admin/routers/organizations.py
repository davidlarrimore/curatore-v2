# backend/app/api/v1/routers/organizations.py
"""
Organization management endpoints for Curatore v2 API (v1).

Provides endpoints for managing organization details and settings.
Users can view and update their own organization's information.

Endpoints:
    GET /organizations/me - Get current user's organization
    PUT /organizations/me - Update organization details
    GET /organizations/me/settings - Get organization settings
    PUT /organizations/me/settings - Update organization settings

Security:
    - All endpoints require authentication
    - Only org_admin can update organization details
    - Settings are merged (partial updates supported)
"""

import logging
from datetime import datetime
from typing import Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.api.v1.admin.schemas import (
    OrganizationResponse,
    OrganizationUpdateRequest,
    OrganizationSettingsResponse,
    OrganizationSettingsUpdateRequest,
)
from app.core.database.models import Organization, User
from app.dependencies import get_current_user, require_org_admin, get_current_organization
from app.core.shared.database_service import database_service

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
