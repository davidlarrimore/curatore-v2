# backend/app/api/v1/routers/forecasts.py
"""
Acquisition Forecast API endpoints for Curatore v2.

Provides endpoints for managing forecast syncs and viewing forecasts from
three federal agency sources:
- AG (GSA Acquisition Gateway)
- APFS (DHS Acquisition Planning Forecast System)
- State Department

Endpoints:
    Forecast Syncs:
        GET /forecasts/syncs - List syncs
        POST /forecasts/syncs - Create sync
        GET /forecasts/syncs/{id} - Get sync details
        PATCH /forecasts/syncs/{id} - Update sync
        DELETE /forecasts/syncs/{id} - Delete sync
        POST /forecasts/syncs/{id}/pull - Trigger manual pull

    Forecasts (Unified):
        GET /forecasts - List all forecasts (unified view)
        GET /forecasts/stats - Dashboard statistics
        GET /forecasts/{source_type}/{source_id} - Get forecast detail

Security:
    - All endpoints require authentication
    - Syncs are organization-scoped
    - Only org_admin can create/delete syncs
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.connectors.dhs_apfs.apfs_forecast_service import apfs_forecast_service
from app.connectors.gsa_gateway.ag_forecast_service import ag_forecast_service
from app.connectors.state_forecast.state_forecast_service import state_forecast_service
from app.core.database.models import ForecastSync, Run, User
from app.core.shared.database_service import database_service
from app.core.shared.forecast_service import forecast_service
from app.core.shared.forecast_sync_service import forecast_sync_service
from app.core.shared.run_service import run_service
from app.core.tasks import forecast_sync_task
from app.dependencies import get_current_org_id, get_current_user, require_org_admin

# Initialize router
router = APIRouter(prefix="/forecasts", tags=["Acquisition Forecasts"])

# Initialize logger
logger = logging.getLogger("curatore.api.forecasts")


# =========================================================================
# REQUEST/RESPONSE MODELS
# =========================================================================


class ForecastSyncCreateRequest(BaseModel):
    """Request to create a forecast sync."""

    name: str = Field(..., min_length=1, max_length=255, description="Sync name")
    source_type: str = Field(
        ...,
        description="Data source: 'ag', 'apfs', or 'state'",
    )
    filter_config: Dict[str, Any] = Field(
        default_factory=dict,
        description="Source-specific filters (AG: agency_ids, naics_ids; APFS: organizations, fiscal_years)",
    )
    sync_frequency: str = Field(
        default="manual",
        description="Sync frequency (manual, hourly, daily)",
    )
    automation_config: Dict[str, Any] = Field(
        default_factory=dict,
        description="Post-sync automation (after_procedure_slug, after_procedure_params)",
    )


class ForecastSyncUpdateRequest(BaseModel):
    """Request to update a forecast sync."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    filter_config: Optional[Dict[str, Any]] = None
    status: Optional[str] = Field(None, description="active, paused, archived")
    is_active: Optional[bool] = None
    sync_frequency: Optional[str] = None
    automation_config: Optional[Dict[str, Any]] = None


class ForecastSyncResponse(BaseModel):
    """Forecast sync response."""

    id: str
    organization_id: str
    name: str
    slug: str
    source_type: str
    status: str
    is_active: bool
    sync_frequency: str
    filter_config: Dict[str, Any]
    automation_config: Dict[str, Any]
    last_sync_at: Optional[datetime]
    last_sync_status: Optional[str]
    last_sync_run_id: Optional[str] = None
    forecast_count: int
    created_at: datetime
    updated_at: datetime
    # Active sync tracking
    is_syncing: bool = False
    current_sync_status: Optional[str] = None


class ForecastSyncListResponse(BaseModel):
    """List of forecast syncs response."""

    items: List[ForecastSyncResponse]
    total: int
    limit: int
    offset: int


class ForecastResponse(BaseModel):
    """Unified forecast response."""

    id: str
    organization_id: str
    sync_id: Optional[str] = None
    source_type: str
    source_id: str
    title: str
    description: Optional[str]
    agency_name: Optional[str]
    naics_codes: Optional[List[Dict[str, Any]]]
    acquisition_phase: Optional[str]
    set_aside_type: Optional[str]
    contract_type: Optional[str]
    contract_vehicle: Optional[str]
    estimated_solicitation_date: Optional[datetime]
    fiscal_year: Optional[int]
    estimated_award_quarter: Optional[str]
    pop_start_date: Optional[datetime]
    pop_end_date: Optional[datetime]
    pop_city: Optional[str]
    pop_state: Optional[str]
    pop_country: Optional[str]
    poc_name: Optional[str]
    poc_email: Optional[str]
    sbs_name: Optional[str]
    sbs_email: Optional[str]
    incumbent_contractor: Optional[str]
    source_url: Optional[str]
    first_seen_at: datetime
    last_updated_at: datetime
    indexed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    history: Optional[List[Dict[str, Any]]] = None


class ForecastListResponse(BaseModel):
    """List of forecasts response."""

    items: List[ForecastResponse]
    total: int
    limit: int
    offset: int


class ForecastStatsResponse(BaseModel):
    """Forecast statistics response."""

    total_syncs: int
    active_syncs: int
    total_forecasts: int
    by_source: Dict[str, int]
    recent_changes: int
    last_sync_at: Optional[datetime]


# =========================================================================
# SYNC ENDPOINTS
# =========================================================================


@router.get("/syncs", response_model=ForecastSyncListResponse)
async def list_syncs(
    status: Optional[str] = Query(None, description="Filter by status"),
    source_type: Optional[str] = Query(None, description="Filter by source type"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    org_id: UUID = Depends(get_current_org_id),
):
    """List forecast syncs for the organization."""
    async with database_service.get_session() as session:
        syncs, total = await forecast_sync_service.list_syncs(
            session=session,
            organization_id=org_id,
            status=status,
            source_type=source_type,
            limit=limit,
            offset=offset,
        )

        # Check for active syncs
        items = []
        for sync in syncs:
            sync_response = await _sync_to_response(session, sync)
            items.append(sync_response)

        return ForecastSyncListResponse(
            items=items,
            total=total,
            limit=limit,
            offset=offset,
        )


@router.post("/syncs", response_model=ForecastSyncResponse, status_code=status.HTTP_201_CREATED)
async def create_sync(
    request: ForecastSyncCreateRequest,
    org_id: UUID = Depends(get_current_org_id),
    current_user: User = Depends(require_org_admin),
):
    """Create a new forecast sync."""
    # Validate source_type
    if request.source_type not in ("ag", "apfs", "state"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid source_type: {request.source_type}. Must be 'ag', 'apfs', or 'state'.",
        )

    async with database_service.get_session() as session:
        try:
            sync = await forecast_sync_service.create_sync(
                session=session,
                organization_id=org_id,
                name=request.name,
                source_type=request.source_type,
                filter_config=request.filter_config,
                sync_frequency=request.sync_frequency,
                automation_config=request.automation_config,
                created_by=current_user.id,
            )
            await session.commit()

            return await _sync_to_response(session, sync)

        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )


@router.get("/syncs/{sync_id}", response_model=ForecastSyncResponse)
async def get_sync(
    sync_id: UUID,
    org_id: UUID = Depends(get_current_org_id),
):
    """Get forecast sync details."""
    async with database_service.get_session() as session:
        sync = await forecast_sync_service.get_sync(
            session=session,
            sync_id=sync_id,
            organization_id=org_id,
        )

        if not sync:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Forecast sync {sync_id} not found",
            )

        return await _sync_to_response(session, sync)


@router.patch("/syncs/{sync_id}", response_model=ForecastSyncResponse)
async def update_sync(
    sync_id: UUID,
    request: ForecastSyncUpdateRequest,
    org_id: UUID = Depends(get_current_org_id),
    _admin: User = Depends(require_org_admin),
):
    """Update a forecast sync."""
    async with database_service.get_session() as session:
        sync = await forecast_sync_service.get_sync(
            session=session,
            sync_id=sync_id,
            organization_id=org_id,
        )

        if not sync:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Forecast sync {sync_id} not found",
            )

        # Build updates dict
        updates = {}
        if request.name is not None:
            updates["name"] = request.name
        if request.filter_config is not None:
            updates["filter_config"] = request.filter_config
        if request.status is not None:
            updates["status"] = request.status
        if request.is_active is not None:
            updates["is_active"] = request.is_active
        if request.sync_frequency is not None:
            updates["sync_frequency"] = request.sync_frequency
        if request.automation_config is not None:
            updates["automation_config"] = request.automation_config

        if updates:
            sync = await forecast_sync_service.update_sync(
                session=session,
                sync_id=sync_id,
                **updates,
            )
            await session.commit()

        return await _sync_to_response(session, sync)


@router.delete("/syncs/{sync_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sync(
    sync_id: UUID,
    org_id: UUID = Depends(get_current_org_id),
    _admin: User = Depends(require_org_admin),
):
    """Delete a forecast sync and all associated forecasts."""
    async with database_service.get_session() as session:
        sync = await forecast_sync_service.get_sync(
            session=session,
            sync_id=sync_id,
            organization_id=org_id,
        )

        if not sync:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Forecast sync {sync_id} not found",
            )

        await forecast_sync_service.delete_sync(session=session, sync_id=sync_id)
        await session.commit()


@router.post("/syncs/{sync_id}/pull")
async def trigger_sync_pull(
    sync_id: UUID,
    org_id: UUID = Depends(get_current_org_id),
):
    """Trigger a manual sync pull."""
    async with database_service.get_session() as session:
        sync = await forecast_sync_service.get_sync(
            session=session,
            sync_id=sync_id,
            organization_id=org_id,
        )

        if not sync:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Forecast sync {sync_id} not found",
            )

        if not sync.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot pull from an inactive sync",
            )

        # Check for existing active sync
        active_run = await _get_active_sync_run(session, sync_id)
        if active_run:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A sync is already in progress",
            )

        # Create run record
        run = await run_service.create_run(
            session=session,
            run_type="forecast_sync",
            organization_id=org_id,
            config={
                "sync_id": str(sync_id),
                "sync_name": sync.name,
                "source_type": sync.source_type,
                "triggered_by": "manual",
            },
        )
        await session.commit()

        # Queue Celery task (sync_id, organization_id, run_id)
        forecast_sync_task.delay(
            str(sync_id),
            str(org_id),
            str(run.id),
        )

        logger.info(
            f"Forecast sync triggered: sync={sync_id}, run={run.id}, source={sync.source_type}"
        )

        return {
            "run_id": str(run.id),
            "sync_id": str(sync_id),
            "status": "queued",
            "message": f"Sync pull queued for {sync.source_type.upper()} source",
        }


@router.post("/syncs/{sync_id}/clear")
async def clear_sync_forecasts(
    sync_id: UUID,
    org_id: UUID = Depends(get_current_org_id),
    _admin: User = Depends(require_org_admin),
):
    """
    Clear all forecasts for a sync (delete forecast data but keep sync config).

    This permanently deletes all forecast records associated with the sync.
    The sync configuration remains intact and can be re-synced.
    """
    async with database_service.get_session() as session:
        sync = await forecast_sync_service.get_sync(
            session=session,
            sync_id=sync_id,
            organization_id=org_id,
        )

        if not sync:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Forecast sync {sync_id} not found",
            )

        # Delete forecasts based on source type
        deleted_count = 0
        if sync.source_type == "ag":
            deleted_count = await ag_forecast_service.delete_by_sync(session, sync_id)
        elif sync.source_type == "apfs":
            deleted_count = await apfs_forecast_service.delete_by_sync(session, sync_id)
        elif sync.source_type == "state":
            deleted_count = await state_forecast_service.delete_by_sync(session, sync_id)

        # Note: Search index entries will be overwritten on next sync
        # No need to explicitly delete them - they'll be replaced

        # Reset sync stats
        await forecast_sync_service.update_forecast_count(session, sync_id, 0)
        await session.commit()

        logger.info(
            f"Cleared {deleted_count} forecasts from sync {sync_id} ({sync.source_type})"
        )

        return {
            "sync_id": str(sync_id),
            "deleted_count": deleted_count,
            "message": f"Cleared {deleted_count} forecasts from sync",
        }


# =========================================================================
# FORECAST ENDPOINTS (UNIFIED VIEW)
# =========================================================================


@router.get("", response_model=ForecastListResponse)
async def list_forecasts(
    source_type: Optional[str] = Query(None, description="Filter by source (ag, apfs, state)"),
    sync_id: Optional[UUID] = Query(None, description="Filter by sync ID"),
    agency_name: Optional[str] = Query(None, description="Filter by agency name (partial match)"),
    naics_code: Optional[str] = Query(None, description="Filter by NAICS code"),
    fiscal_year: Optional[int] = Query(None, description="Filter by fiscal year"),
    search: Optional[str] = Query(None, description="Search in title and description"),
    sort_by: Optional[str] = Query(
        None,
        description="Sort field (source_type, title, agency_name, naics, fiscal_year, award_quarter, last_updated_at)",
    ),
    sort_direction: Optional[str] = Query(
        None,
        description="Sort direction (asc, desc)",
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    org_id: UUID = Depends(get_current_org_id),
):
    """List forecasts from all sources (unified view)."""
    async with database_service.get_session() as session:
        # Convert singular source_type to list for service
        source_types = [source_type] if source_type else None

        forecasts, total = await forecast_service.list_forecasts(
            session=session,
            organization_id=org_id,
            source_types=source_types,
            sync_id=sync_id,
            agency_name=agency_name,
            fiscal_year=fiscal_year,
            search_query=search,
            sort_by=sort_by,
            sort_direction=sort_direction,
            limit=limit,
            offset=offset,
        )

        items = [_forecast_to_response(f) for f in forecasts]

        return ForecastListResponse(
            items=items,
            total=total,
            limit=limit,
            offset=offset,
        )


@router.get("/stats", response_model=ForecastStatsResponse)
async def get_forecast_stats(
    org_id: UUID = Depends(get_current_org_id),
):
    """Get forecast dashboard statistics."""
    async with database_service.get_session() as session:
        stats = await forecast_service.get_stats(
            session=session,
            organization_id=org_id,
        )

        sync_stats = await forecast_sync_service.get_stats(
            session=session,
            organization_id=org_id,
        )

        return ForecastStatsResponse(
            total_syncs=sync_stats.get("total_syncs", 0),
            active_syncs=sync_stats.get("active_syncs", 0),
            total_forecasts=stats.get("total", 0),
            by_source=stats.get("by_source", {}),
            recent_changes=stats.get("recent_changes", 0),
            last_sync_at=sync_stats.get("last_sync_at"),
        )


@router.get("/{forecast_id}", response_model=ForecastResponse)
async def get_forecast_by_id(
    forecast_id: UUID,
    org_id: UUID = Depends(get_current_org_id),
):
    """Get a specific forecast by UUID."""
    async with database_service.get_session() as session:
        forecast, source_type = await forecast_service.get_forecast_by_uuid(
            session=session,
            organization_id=org_id,
            forecast_id=forecast_id,
        )

        if not forecast:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Forecast not found: {forecast_id}",
            )

        # Convert model to unified dict format
        unified_dict = _model_to_unified_dict(forecast, source_type)
        return _forecast_to_response(unified_dict)


# =========================================================================
# HELPER FUNCTIONS
# =========================================================================


async def _get_active_sync_run(session, sync_id: UUID) -> Optional[Run]:
    """Check for an active sync run."""
    result = await session.execute(
        select(Run)
        .where(Run.run_type == "forecast_sync")
        .where(Run.config["sync_id"].astext == str(sync_id))
        .where(Run.status.in_(["pending", "submitted", "running"]))
        .order_by(Run.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _sync_to_response(session, sync: ForecastSync) -> ForecastSyncResponse:
    """Convert ForecastSync model to response."""
    # Check for active sync
    active_run = await _get_active_sync_run(session, sync.id)

    return ForecastSyncResponse(
        id=str(sync.id),
        organization_id=str(sync.organization_id),
        name=sync.name,
        slug=sync.slug,
        source_type=sync.source_type,
        status=sync.status,
        is_active=sync.is_active,
        sync_frequency=sync.sync_frequency,
        filter_config=sync.filter_config or {},
        automation_config=sync.automation_config or {},
        last_sync_at=sync.last_sync_at,
        last_sync_status=sync.last_sync_status,
        last_sync_run_id=str(sync.last_sync_run_id) if sync.last_sync_run_id else None,
        forecast_count=sync.forecast_count,
        created_at=sync.created_at,
        updated_at=sync.updated_at,
        is_syncing=active_run is not None,
        current_sync_status=active_run.status if active_run else None,
    )


def _model_to_unified_dict(model: Any, source_type: str) -> Dict[str, Any]:
    """
    Convert source-specific model to unified dict format.

    Handles mapping of source-specific fields (nid, apfs_number, row_hash)
    to the unified source_id field.
    """
    # Determine source_id based on source type
    if source_type == "ag":
        source_id = model.nid
        naics_codes = model.naics_codes  # Already JSONB
        agency_name = model.agency_name
        acquisition_phase = model.acquisition_phase
        set_aside_type = model.set_aside_type
        contract_type = None
        contract_vehicle = None
        pop_city = None
        pop_state = None
        pop_country = None
        incumbent_contractor = None
        source_url = getattr(model, "source_url", None)
    elif source_type == "apfs":
        source_id = model.apfs_number
        # Build naics_codes array from single code
        naics_codes = None
        if model.naics_code:
            naics_codes = [{"code": model.naics_code, "description": model.naics_description}]
        agency_name = "Department of Homeland Security"
        acquisition_phase = None
        set_aside_type = model.small_business_set_aside
        contract_type = model.contract_type
        contract_vehicle = model.contract_vehicle
        pop_city = None
        pop_state = None
        pop_country = None
        incumbent_contractor = None
        # Construct source_url from apfs_id
        source_url = None
        if model.apfs_id:
            source_url = f"https://apfs-cloud.dhs.gov/record/{model.apfs_id}/public-print/"
    elif source_type == "state":
        source_id = model.row_hash
        naics_codes = None
        if model.naics_code:
            naics_codes = [{"code": model.naics_code}]
        agency_name = "Department of State"
        acquisition_phase = model.acquisition_phase
        set_aside_type = model.set_aside_type
        contract_type = model.contract_type
        contract_vehicle = None
        pop_city = model.pop_city
        pop_state = model.pop_state
        pop_country = model.pop_country
        incumbent_contractor = model.incumbent_contractor
        source_url = None
    else:
        raise ValueError(f"Unknown source_type: {source_type}")

    return {
        "id": model.id,
        "organization_id": model.organization_id,
        "sync_id": model.sync_id,
        "source_type": source_type,
        "source_id": source_id,
        "title": model.title,
        "description": model.description,
        "agency_name": agency_name,
        "naics_codes": naics_codes,
        "acquisition_phase": acquisition_phase,
        "set_aside_type": set_aside_type,
        "contract_type": contract_type,
        "contract_vehicle": contract_vehicle,
        "estimated_solicitation_date": getattr(model, "estimated_solicitation_date", None),
        "fiscal_year": getattr(model, "fiscal_year", None) or getattr(model, "estimated_award_fy", None),
        "estimated_award_quarter": getattr(model, "estimated_award_quarter", None) or getattr(model, "award_quarter", None),
        "pop_start_date": getattr(model, "pop_start_date", None),
        "pop_end_date": getattr(model, "pop_end_date", None),
        "pop_city": pop_city,
        "pop_state": pop_state,
        "pop_country": pop_country,
        "poc_name": getattr(model, "poc_name", None),
        "poc_email": getattr(model, "poc_email", None),
        "sbs_name": getattr(model, "sbs_name", None),
        "sbs_email": getattr(model, "sbs_email", None),
        "incumbent_contractor": incumbent_contractor,
        "source_url": source_url,
        "first_seen_at": model.first_seen_at,
        "last_updated_at": model.last_updated_at,
        "indexed_at": model.indexed_at,
        "created_at": model.created_at,
        "updated_at": model.updated_at,
        "history": getattr(model, "history", None),
    }


def _forecast_to_response(forecast: Dict[str, Any]) -> ForecastResponse:
    """Convert unified forecast dict to response."""
    # Handle naics_codes (could be JSON string or already parsed)
    naics_codes = forecast.get("naics_codes")
    if isinstance(naics_codes, str):
        import json
        try:
            naics_codes = json.loads(naics_codes)
        except (json.JSONDecodeError, TypeError):
            naics_codes = None

    return ForecastResponse(
        id=str(forecast["id"]),
        organization_id=str(forecast["organization_id"]),
        sync_id=str(forecast["sync_id"]) if forecast.get("sync_id") else None,
        source_type=forecast["source_type"],
        source_id=forecast["source_id"],
        title=forecast["title"],
        description=forecast.get("description"),
        agency_name=forecast.get("agency_name"),
        naics_codes=naics_codes,
        acquisition_phase=forecast.get("acquisition_phase"),
        set_aside_type=forecast.get("set_aside_type"),
        contract_type=forecast.get("contract_type"),
        contract_vehicle=forecast.get("contract_vehicle"),
        estimated_solicitation_date=forecast.get("estimated_solicitation_date"),
        fiscal_year=forecast.get("fiscal_year"),
        estimated_award_quarter=forecast.get("estimated_award_quarter"),
        pop_start_date=forecast.get("pop_start_date"),
        pop_end_date=forecast.get("pop_end_date"),
        pop_city=forecast.get("pop_city"),
        pop_state=forecast.get("pop_state"),
        pop_country=forecast.get("pop_country"),
        poc_name=forecast.get("poc_name"),
        poc_email=forecast.get("poc_email"),
        sbs_name=forecast.get("sbs_name"),
        sbs_email=forecast.get("sbs_email"),
        incumbent_contractor=forecast.get("incumbent_contractor"),
        source_url=forecast.get("source_url"),
        first_seen_at=forecast["first_seen_at"],
        last_updated_at=forecast["last_updated_at"],
        indexed_at=forecast.get("indexed_at"),
        created_at=forecast["created_at"],
        updated_at=forecast["updated_at"],
        history=forecast.get("history"),
    )
