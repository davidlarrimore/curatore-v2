# backend/app/api/v1/admin/routers/data_connections.py
"""
Data Connection management endpoints for Curatore v2 API (v1).

Manages per-org enablement of data source integrations (SAM.gov, SharePoint,
Salesforce, Forecasts, Web Scraping).  These are separate from infrastructure
"services" (LLM, extraction, playwright) and credential "connections".

Endpoints:
    GET  /data-connections               - Catalog with per-org enablement counts (admin)
    GET  /data-connections/orgs/{org_id}  - Per-org connection statuses (admin)
    PUT  /data-connections/{source_type}/orgs/{org_id} - Toggle connection (admin)
    GET  /data-connections/me             - Current org's connection statuses (any user)

Security:
    - Catalog / per-org / toggle endpoints require system admin
    - /me endpoint requires any authenticated user with org context
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select

from app.api.v1.admin.schemas import (
    DataConnectionCatalogEntry,
    DataConnectionCatalogResponse,
    DataConnectionOrgStatusResponse,
    DataConnectionStatus,
    DataConnectionToggleRequest,
)
from app.core.database.models import DataSourceTypeOverride, Organization, User
from app.core.metadata.registry_service import (
    MANAGEABLE_DATA_SOURCE_TYPES,
    metadata_registry_service,
)
from app.core.shared.database_service import database_service
from app.dependencies import get_current_org_id, get_current_user, require_admin

# Initialize router
router = APIRouter(prefix="/data-connections", tags=["Data Connections"])

# Initialize logger
logger = logging.getLogger("curatore.api.data_connections")

# Ordered list for consistent API output
MANAGEABLE_SOURCE_TYPES = sorted(MANAGEABLE_DATA_SOURCE_TYPES)


# =========================================================================
# CATALOG ENDPOINT (system admin)
# =========================================================================


@router.get("/", response_model=DataConnectionCatalogResponse)
async def list_data_connections(
    admin: User = Depends(require_admin),
):
    """
    List all manageable data connections with per-org enablement counts.

    Returns the data source catalog filtered to manageable types, enriched
    with how many organizations have each source enabled.
    """
    metadata_registry_service._ensure_loaded()
    baseline = metadata_registry_service._data_sources

    async with database_service.get_session() as session:
        # Count total active orgs
        total_orgs_result = await session.execute(
            select(func.count()).select_from(Organization).where(
                Organization.is_active == True
            )
        )
        total_orgs = total_orgs_result.scalar() or 0

        # Count enabled overrides per source type
        enabled_counts_result = await session.execute(
            select(
                DataSourceTypeOverride.source_type,
                func.count().label("cnt"),
            )
            .where(
                DataSourceTypeOverride.organization_id.isnot(None),
                DataSourceTypeOverride.is_active == True,
                DataSourceTypeOverride.source_type.in_(MANAGEABLE_SOURCE_TYPES),
            )
            .group_by(DataSourceTypeOverride.source_type)
        )
        enabled_counts = {row.source_type: row.cnt for row in enabled_counts_result}

        # Check for global-level overrides (organization_id IS NULL, is_active=False)
        global_disabled_result = await session.execute(
            select(DataSourceTypeOverride.source_type).where(
                DataSourceTypeOverride.organization_id.is_(None),
                DataSourceTypeOverride.is_active == False,
                DataSourceTypeOverride.source_type.in_(MANAGEABLE_SOURCE_TYPES),
            )
        )
        globally_disabled = {row.source_type for row in global_disabled_result}

    entries = []
    for st in MANAGEABLE_SOURCE_TYPES:
        defn = baseline.get(st, {})
        entries.append(
            DataConnectionCatalogEntry(
                source_type=st,
                display_name=defn.get("display_name", st),
                description=defn.get("description"),
                capabilities=defn.get("capabilities"),
                is_globally_active=st not in globally_disabled,
                enabled_org_count=enabled_counts.get(st, 0),
                total_org_count=total_orgs,
            )
        )

    return DataConnectionCatalogResponse(
        data_connections=entries,
        total=len(entries),
    )


# =========================================================================
# PER-ORG STATUS ENDPOINT (system admin)
# =========================================================================


@router.get("/orgs/{org_id}", response_model=DataConnectionOrgStatusResponse)
async def get_org_data_connections(
    org_id: UUID,
    admin: User = Depends(require_admin),
):
    """
    Get data connection statuses for a specific organization.
    """
    async with database_service.get_session() as session:
        # Validate org exists
        org_result = await session.execute(
            select(Organization).where(Organization.id == org_id)
        )
        org = org_result.scalar_one_or_none()
        if not org:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Organization not found",
            )

        catalog = await metadata_registry_service.get_data_source_catalog(
            session, org_id
        )

        # Get override timestamps
        overrides_result = await session.execute(
            select(DataSourceTypeOverride).where(
                DataSourceTypeOverride.organization_id == org_id,
                DataSourceTypeOverride.source_type.in_(MANAGEABLE_SOURCE_TYPES),
            )
        )
        override_map = {
            o.source_type: o for o in overrides_result.scalars()
        }

    statuses = []
    for st in MANAGEABLE_SOURCE_TYPES:
        defn = catalog.get(st, {})
        override = override_map.get(st)
        statuses.append(
            DataConnectionStatus(
                source_type=st,
                display_name=defn.get("display_name", st),
                description=defn.get("description"),
                is_enabled=defn.get("is_active", False),
                capabilities=defn.get("capabilities"),
                updated_at=override.updated_at if override else None,
            )
        )

    return DataConnectionOrgStatusResponse(
        data_connections=statuses,
        organization_id=str(org_id),
        organization_name=org.display_name if org else None,
    )


# =========================================================================
# TOGGLE ENDPOINT (system admin)
# =========================================================================


@router.put("/{source_type}/orgs/{org_id}")
async def toggle_data_connection(
    source_type: str,
    org_id: UUID,
    request: DataConnectionToggleRequest,
    admin: User = Depends(require_admin),
):
    """
    Enable or disable a data connection for a specific organization.
    """
    if source_type not in MANAGEABLE_DATA_SOURCE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid source_type '{source_type}'. Must be one of: {MANAGEABLE_SOURCE_TYPES}",
        )

    async with database_service.get_session() as session:
        # Validate org exists
        org_result = await session.execute(
            select(Organization).where(Organization.id == org_id)
        )
        org = org_result.scalar_one_or_none()
        if not org:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Organization not found",
            )

        result = await metadata_registry_service.upsert_data_source_override(
            session,
            organization_id=org_id,
            source_type=source_type,
            is_active=request.is_enabled,
        )
        await session.commit()

    logger.info(
        f"Data connection '{source_type}' {'enabled' if request.is_enabled else 'disabled'} "
        f"for org {org.display_name} ({org_id}) by admin {admin.email}"
    )

    return {
        "source_type": source_type,
        "organization_id": str(org_id),
        "is_enabled": request.is_enabled,
        "message": f"Data connection '{source_type}' {'enabled' if request.is_enabled else 'disabled'} for {org.display_name}",
    }


# =========================================================================
# CURRENT ORG STATUS ENDPOINT (any authenticated user)
# =========================================================================


@router.get("/me", response_model=DataConnectionOrgStatusResponse)
async def get_my_data_connections(
    current_user: User = Depends(get_current_user),
    org_id: UUID = Depends(get_current_org_id),
):
    """
    Get data connection statuses for the current user's organization.

    Used by the frontend sidebar to determine which navigation items to show.
    """
    async with database_service.get_session() as session:
        catalog = await metadata_registry_service.get_data_source_catalog(
            session, org_id
        )

        # Get org name
        org_result = await session.execute(
            select(Organization.display_name).where(Organization.id == org_id)
        )
        org_name = org_result.scalar_one_or_none()

    statuses = []
    for st in MANAGEABLE_SOURCE_TYPES:
        defn = catalog.get(st, {})
        statuses.append(
            DataConnectionStatus(
                source_type=st,
                display_name=defn.get("display_name", st),
                description=defn.get("description"),
                is_enabled=defn.get("is_active", False),
                capabilities=defn.get("capabilities"),
            )
        )

    return DataConnectionOrgStatusResponse(
        data_connections=statuses,
        organization_id=str(org_id),
        organization_name=org_name,
    )
