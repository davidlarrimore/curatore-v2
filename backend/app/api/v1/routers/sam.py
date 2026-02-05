# backend/app/api/v1/routers/sam.py
"""
SAM.gov Federal Opportunities API endpoints for Curatore v2 API (v1).

Provides endpoints for managing SAM.gov searches, solicitations, notices,
attachments, and LLM-powered summaries. Part of Phase 7: Native SAM.gov
Domain Integration.

Endpoints:
    Searches:
        GET /sam/searches - List SAM searches
        POST /sam/searches - Create search
        GET /sam/searches/{id} - Get search details
        PATCH /sam/searches/{id} - Update search
        DELETE /sam/searches/{id} - Archive search
        POST /sam/searches/{id}/pull - Trigger pull from SAM.gov
        GET /sam/searches/{id}/stats - Get search statistics

    Solicitations:
        GET /sam/solicitations - List solicitations
        GET /sam/solicitations/{id} - Get solicitation details
        GET /sam/solicitations/{id}/notices - List notices/versions
        GET /sam/solicitations/{id}/attachments - List attachments
        GET /sam/solicitations/{id}/summaries - List summaries
        POST /sam/solicitations/{id}/summarize - Generate summary
        POST /sam/solicitations/{id}/download-attachments - Download all attachments

    Notices:
        GET /sam/notices/{id} - Get notice details
        GET /sam/notices/{id}/attachments - List notice attachments
        POST /sam/notices/{id}/download-attachments - Download all notice attachments
        GET /sam/notices/{id}/description - Get full description
        POST /sam/notices/{id}/regenerate-summary - Regenerate AI summary
        POST /sam/notices/{id}/refresh - Refresh from SAM.gov
        GET /sam/notices/{id}/changes - Get change summary

    Attachments:
        GET /sam/attachments/{id} - Get attachment details
        POST /sam/attachments/{id}/download - Download attachment

    Summaries:
        GET /sam/summaries/{id} - Get summary details
        POST /sam/summaries/{id}/promote - Promote to canonical
        DELETE /sam/summaries/{id} - Delete experimental summary

    Agencies:
        GET /sam/agencies - List agencies

Security:
    - All endpoints require authentication
    - Searches are organization-scoped
    - Only org_admin can create/delete searches
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select, desc

from app.tasks import sam_pull_task, sam_refresh_solicitation_task, sam_refresh_notice_task
from app.services.run_service import run_service
from app.database.models import (
    Run,
    SamAttachment,
    SamNotice,
    SamSearch,
    SamSolicitation,
    SamSolicitationSummary,
    User,
)
from app.dependencies import get_current_user, require_org_admin
from app.services.database_service import database_service
from app.services.sam_api_usage_service import sam_api_usage_service
from app.services.sam_pull_service import sam_pull_service
from app.services.sam_service import sam_service
from app.services.sam_summarization_service import sam_summarization_service

# Initialize router
router = APIRouter(prefix="/sam", tags=["SAM.gov"])

# Initialize logger
logger = logging.getLogger("curatore.api.sam")


# =========================================================================
# REQUEST/RESPONSE MODELS
# =========================================================================


class SamSearchCreateRequest(BaseModel):
    """Request to create a SAM search."""

    name: str = Field(..., min_length=1, max_length=255, description="Search name")
    description: Optional[str] = Field(None, description="Search description")
    search_config: Dict[str, Any] = Field(
        default_factory=dict,
        description="Search filters (naics_codes, psc_codes, agencies, etc.)",
    )
    pull_frequency: str = Field(
        default="manual",
        description="Pull frequency (manual, hourly, daily)",
    )


class SamSearchUpdateRequest(BaseModel):
    """Request to update a SAM search."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    search_config: Optional[Dict[str, Any]] = None
    status: Optional[str] = Field(None, description="active, paused, archived")
    is_active: Optional[bool] = None
    pull_frequency: Optional[str] = None


class SamSearchResponse(BaseModel):
    """SAM search response."""

    id: str
    organization_id: str
    name: str
    slug: str
    description: Optional[str]
    search_config: Dict[str, Any]
    status: str
    is_active: bool
    last_pull_at: Optional[datetime]
    last_pull_status: Optional[str]
    last_pull_run_id: Optional[str] = None
    pull_frequency: str
    created_at: datetime
    updated_at: datetime
    # Active pull tracking
    is_pulling: bool = False  # True if a pull is currently running
    current_pull_status: Optional[str] = None  # pending, running, etc.


class SamSearchListResponse(BaseModel):
    """List of SAM searches response."""

    items: List[SamSearchResponse]
    total: int
    limit: int
    offset: int


class SamSolicitationResponse(BaseModel):
    """SAM solicitation response."""

    id: str
    organization_id: str
    notice_id: str
    solicitation_number: Optional[str]
    title: str
    description: Optional[str]
    notice_type: str
    naics_code: Optional[str]
    psc_code: Optional[str]
    set_aside_code: Optional[str]
    status: str
    posted_date: Optional[datetime]
    response_deadline: Optional[datetime]
    ui_link: Optional[str]
    contact_info: Optional[Any]  # Can be dict or list depending on API response
    # Organization hierarchy (parsed from fullParentPathName: AGENCY.BUREAU.OFFICE)
    agency_name: Optional[str]
    bureau_name: Optional[str]
    office_name: Optional[str]
    full_parent_path: Optional[str]
    notice_count: int
    attachment_count: int
    created_at: datetime
    updated_at: datetime


class SamSolicitationListResponse(BaseModel):
    """List of SAM solicitations response."""

    items: List[SamSolicitationResponse]
    total: int
    limit: int
    offset: int


class SamNoticeResponse(BaseModel):
    """SAM notice response.

    Supports both solicitation-linked notices and standalone notices (e.g., Special Notices).
    """

    id: str
    solicitation_id: Optional[str]  # Nullable for standalone notices
    organization_id: Optional[str]  # For standalone notices
    sam_notice_id: str
    notice_type: str
    version_number: int
    title: Optional[str]
    description: Optional[str]
    description_url: Optional[str] = None  # SAM.gov API URL for full description
    posted_date: Optional[datetime]
    response_deadline: Optional[datetime]
    changes_summary: Optional[str]
    created_at: datetime
    # Classification fields
    naics_code: Optional[str] = None
    psc_code: Optional[str] = None  # aka classification code
    set_aside_code: Optional[str] = None
    # Agency hierarchy
    agency_name: Optional[str] = None
    bureau_name: Optional[str] = None
    office_name: Optional[str] = None
    full_parent_path: Optional[str] = None
    # UI link for standalone notices
    ui_link: Optional[str] = None
    # Summary fields for standalone notices
    summary_status: Optional[str] = None  # pending, generating, ready, failed, no_llm
    summary_generated_at: Optional[datetime] = None
    # Is this a standalone notice?
    is_standalone: bool = False
    # Raw SAM.gov API response (for metadata tab)
    raw_data: Optional[Dict[str, Any]] = None


class SamAttachmentResponse(BaseModel):
    """SAM attachment response.

    Supports both solicitation-linked and notice-linked attachments.
    """

    id: str
    solicitation_id: Optional[str]  # Nullable for standalone notice attachments
    notice_id: Optional[str]
    asset_id: Optional[str]
    resource_id: str
    filename: str
    file_type: Optional[str]
    file_size: Optional[int]
    description: Optional[str]
    download_status: str
    downloaded_at: Optional[datetime]
    created_at: datetime


class SamSummaryResponse(BaseModel):
    """SAM solicitation summary response."""

    id: str
    solicitation_id: str
    summary_type: str
    is_canonical: bool
    model: str
    summary: str
    key_requirements: Optional[List[Dict[str, Any]]]
    compliance_checklist: Optional[List[Dict[str, Any]]]
    confidence_score: Optional[float]
    token_count: Optional[int]
    created_at: datetime
    promoted_at: Optional[datetime]


class SummarizeRequest(BaseModel):
    """Request to generate a summary."""

    summary_type: str = Field(
        default="executive",
        description="Summary type (executive, technical, compliance, full)",
    )
    model: Optional[str] = Field(None, description="LLM model to use")
    include_attachments: bool = Field(
        default=True, description="Include extracted attachment content"
    )


class PullRequest(BaseModel):
    """Request to pull data from SAM.gov."""

    max_pages: int = Field(default=10, ge=1, le=100, description="Max pages to fetch")
    page_size: int = Field(default=100, ge=1, le=1000, description="Results per page")
    download_attachments: bool = Field(default=True, description="Auto-download attachments after pull")


class AttachmentDownloadResult(BaseModel):
    """Result of attachment download operation."""

    total: int = 0
    downloaded: int = 0
    failed: int = 0
    errors: List[Dict[str, Any]] = []


class PullResponse(BaseModel):
    """Response from pull operation.

    Note: As of v2.4, pulls are executed asynchronously via Celery.
    The task_id can be used to check status via the jobs API.
    """

    search_id: str
    status: str = Field(description="'queued' for async tasks, or final status for sync")
    task_id: Optional[str] = Field(None, description="Celery task ID for tracking")
    run_id: Optional[str] = Field(None, description="Run ID for job tracking in the UI")
    message: str = Field(default="", description="Human-readable status message")
    # These fields are populated when the task completes (for backwards compat)
    total_fetched: int = 0
    new_solicitations: int = 0
    updated_solicitations: int = 0
    new_notices: int = 0
    new_attachments: int = 0
    errors: List[Dict[str, Any]] = []
    attachment_downloads: Optional[AttachmentDownloadResult] = None


class SamAgencyResponse(BaseModel):
    """SAM agency response."""

    id: str
    code: str
    name: str
    abbreviation: Optional[str]


class SamApiUsageResponse(BaseModel):
    """SAM.gov API usage response."""

    date: str
    search_calls: int
    detail_calls: int
    attachment_calls: int
    total_calls: int
    daily_limit: int
    remaining_calls: int
    usage_percent: float
    reset_at: str
    is_over_limit: bool


class SamApiUsageHistoryResponse(BaseModel):
    """SAM.gov API usage history response."""

    items: List[Dict[str, Any]]
    days: int


class SamApiImpactResponse(BaseModel):
    """Estimated API impact of a search configuration."""

    estimated_calls: int
    breakdown: Dict[str, int]
    current_usage: int
    remaining_before: int
    remaining_after: int
    will_exceed_limit: bool
    daily_limit: int


class SamQueueStatsResponse(BaseModel):
    """SAM.gov API queue statistics."""

    pending: int
    processing: int
    completed: int
    failed: int
    ready_to_process: int
    total: int


class SamApiStatusResponse(BaseModel):
    """Combined SAM.gov API status response for the dashboard."""

    usage: SamApiUsageResponse
    queue: SamQueueStatsResponse
    history: List[Dict[str, Any]]


class EstimateImpactRequest(BaseModel):
    """Request to estimate API impact."""

    search_config: Dict[str, Any] = Field(
        ..., description="Search configuration to estimate"
    )
    max_pages: int = Field(default=10, ge=1, le=100)
    page_size: int = Field(default=100, ge=1, le=1000)


class PreviewSearchRequest(BaseModel):
    """Request to preview/test a search configuration."""

    search_config: Dict[str, Any] = Field(
        ..., description="Search configuration to test"
    )
    limit: int = Field(default=10, ge=1, le=25, description="Number of sample results")


class PreviewSearchResult(BaseModel):
    """Individual preview result."""

    notice_id: str
    title: str
    solicitation_number: Optional[str]
    notice_type: str
    naics_code: Optional[str]
    psc_code: Optional[str]
    set_aside: Optional[str]
    posted_date: Optional[str]
    response_deadline: Optional[str]
    agency: Optional[str]
    ui_link: Optional[str]
    attachments_count: int


class PreviewSearchResponse(BaseModel):
    """Response from search preview."""

    success: bool
    total_matching: Optional[int] = None
    sample_count: Optional[int] = None
    sample_results: Optional[List[PreviewSearchResult]] = None
    search_config: Optional[Dict[str, Any]] = None
    message: str
    error: Optional[str] = None
    remaining_calls: Optional[int] = None
    is_multi_department: Optional[bool] = None
    departments_searched: Optional[int] = None


class SamDashboardStatsResponse(BaseModel):
    """Dashboard statistics response (Phase 7.6)."""

    total_notices: int
    total_solicitations: int
    recent_notices_7d: int
    new_solicitations_7d: int
    updated_solicitations_7d: int
    api_usage: Optional[SamApiUsageResponse] = None


class SamNoticeWithSolicitationResponse(BaseModel):
    """SAM notice response with solicitation context for org-wide listing."""

    id: str
    solicitation_id: Optional[str]  # Nullable for standalone notices (e.g., Special Notices)
    sam_notice_id: str
    notice_type: str
    version_number: int
    title: Optional[str]
    description: Optional[str]
    posted_date: Optional[datetime]
    response_deadline: Optional[datetime]
    changes_summary: Optional[str]
    created_at: datetime
    # Solicitation context
    solicitation_number: Optional[str] = None
    agency_name: Optional[str] = None
    bureau_name: Optional[str] = None
    office_name: Optional[str] = None


class SamNoticeListResponse(BaseModel):
    """List of SAM notices response."""

    items: List[SamNoticeWithSolicitationResponse]
    total: int
    limit: int
    offset: int


class SamSolicitationWithSummaryResponse(SamSolicitationResponse):
    """SAM solicitation response with summary status (Phase 7.6)."""

    summary_status: Optional[str] = None
    summary_generated_at: Optional[datetime] = None


# =========================================================================
# HELPER FUNCTIONS
# =========================================================================


def _search_to_response(search: SamSearch, run: Optional["Run"] = None) -> SamSearchResponse:
    """Convert SamSearch model to response.

    Args:
        search: The SamSearch model
        run: Optional Run model for the last pull (to check if pull is active)
    """
    # Determine if a pull is currently running
    is_pulling = False
    current_pull_status = None

    if run:
        current_pull_status = run.status
        is_pulling = run.status in ("pending", "running")

    return SamSearchResponse(
        id=str(search.id),
        organization_id=str(search.organization_id),
        name=search.name,
        slug=search.slug,
        description=search.description,
        search_config=search.search_config or {},
        status=search.status,
        is_active=search.is_active,
        last_pull_at=search.last_pull_at,
        last_pull_status=search.last_pull_status,
        last_pull_run_id=str(search.last_pull_run_id) if search.last_pull_run_id else None,
        pull_frequency=search.pull_frequency,
        created_at=search.created_at,
        updated_at=search.updated_at,
        is_pulling=is_pulling,
        current_pull_status=current_pull_status,
    )


def _solicitation_to_response(sol: SamSolicitation) -> SamSolicitationResponse:
    """Convert SamSolicitation model to response."""
    return SamSolicitationResponse(
        id=str(sol.id),
        organization_id=str(sol.organization_id),
        notice_id=sol.notice_id,
        solicitation_number=sol.solicitation_number,
        title=sol.title,
        description=sol.description,  # Full HTML description
        notice_type=sol.notice_type,
        naics_code=sol.naics_code,
        psc_code=sol.psc_code,
        set_aside_code=sol.set_aside_code,
        status=sol.status,
        posted_date=sol.posted_date,
        response_deadline=sol.response_deadline,
        ui_link=sol.ui_link,
        contact_info=sol.contact_info,
        agency_name=sol.agency_name,
        bureau_name=sol.bureau_name,
        office_name=sol.office_name,
        full_parent_path=sol.full_parent_path,
        notice_count=sol.notice_count,
        attachment_count=sol.attachment_count,
        created_at=sol.created_at,
        updated_at=sol.updated_at,
    )


def _notice_to_response(notice: SamNotice, include_raw_data: bool = False) -> SamNoticeResponse:
    """Convert SamNotice model to response.

    Handles both solicitation-linked and standalone notices.
    """
    # Determine if this is a standalone notice
    is_standalone = notice.solicitation_id is None

    return SamNoticeResponse(
        id=str(notice.id),
        solicitation_id=str(notice.solicitation_id) if notice.solicitation_id else None,
        organization_id=str(notice.organization_id) if notice.organization_id else None,
        sam_notice_id=notice.sam_notice_id,
        notice_type=notice.notice_type,
        version_number=notice.version_number,
        title=notice.title,
        description=notice.description[:500] if notice.description else None,
        description_url=getattr(notice, 'description_url', None),
        posted_date=notice.posted_date,
        response_deadline=notice.response_deadline,
        changes_summary=notice.changes_summary,
        created_at=notice.created_at,
        # Classification fields
        naics_code=notice.naics_code,
        psc_code=notice.psc_code,
        set_aside_code=notice.set_aside_code,
        # Agency hierarchy (from notice itself for standalone)
        agency_name=notice.agency_name,
        bureau_name=notice.bureau_name,
        office_name=notice.office_name,
        full_parent_path=getattr(notice, 'full_parent_path', None),
        # UI link
        ui_link=notice.ui_link,
        # Summary fields
        summary_status=notice.summary_status,
        summary_generated_at=notice.summary_generated_at,
        # Standalone flag
        is_standalone=is_standalone,
        # Raw data (only when requested)
        raw_data=notice.raw_data if include_raw_data else None,
    )


def _notice_with_solicitation_to_response(
    notice: SamNotice, solicitation: SamSolicitation
) -> SamNoticeWithSolicitationResponse:
    """Convert SamNotice with solicitation context to response."""
    return SamNoticeWithSolicitationResponse(
        id=str(notice.id),
        solicitation_id=str(notice.solicitation_id),
        sam_notice_id=notice.sam_notice_id,
        notice_type=notice.notice_type,
        version_number=notice.version_number,
        title=notice.title,
        description=notice.description[:500] if notice.description else None,
        posted_date=notice.posted_date,
        response_deadline=notice.response_deadline,
        changes_summary=notice.changes_summary,
        created_at=notice.created_at,
        solicitation_number=solicitation.solicitation_number,
        agency_name=solicitation.agency_name,
        bureau_name=solicitation.bureau_name,
        office_name=solicitation.office_name,
    )


def _solicitation_with_summary_to_response(sol: SamSolicitation) -> SamSolicitationWithSummaryResponse:
    """Convert SamSolicitation with summary status to response."""
    return SamSolicitationWithSummaryResponse(
        id=str(sol.id),
        organization_id=str(sol.organization_id),
        notice_id=sol.notice_id,
        solicitation_number=sol.solicitation_number,
        title=sol.title,
        description=sol.description,
        notice_type=sol.notice_type,
        naics_code=sol.naics_code,
        psc_code=sol.psc_code,
        set_aside_code=sol.set_aside_code,
        status=sol.status,
        posted_date=sol.posted_date,
        response_deadline=sol.response_deadline,
        ui_link=sol.ui_link,
        contact_info=sol.contact_info,
        agency_name=sol.agency_name,
        bureau_name=sol.bureau_name,
        office_name=sol.office_name,
        full_parent_path=sol.full_parent_path,
        notice_count=sol.notice_count,
        attachment_count=sol.attachment_count,
        created_at=sol.created_at,
        updated_at=sol.updated_at,
        summary_status=sol.summary_status,
        summary_generated_at=sol.summary_generated_at,
    )


def _attachment_to_response(att: SamAttachment) -> SamAttachmentResponse:
    """Convert SamAttachment model to response.

    Handles both solicitation-linked and standalone notice attachments.
    """
    return SamAttachmentResponse(
        id=str(att.id),
        solicitation_id=str(att.solicitation_id) if att.solicitation_id else None,
        notice_id=str(att.notice_id) if att.notice_id else None,
        asset_id=str(att.asset_id) if att.asset_id else None,
        resource_id=att.resource_id,
        filename=att.filename,
        file_type=att.file_type,
        file_size=att.file_size,
        description=att.description,
        download_status=att.download_status,
        downloaded_at=att.downloaded_at,
        created_at=att.created_at,
    )


def _summary_to_response(summary: SamSolicitationSummary) -> SamSummaryResponse:
    """Convert SamSolicitationSummary model to response."""
    return SamSummaryResponse(
        id=str(summary.id),
        solicitation_id=str(summary.solicitation_id),
        summary_type=summary.summary_type,
        is_canonical=summary.is_canonical,
        model=summary.model,
        summary=summary.summary,
        key_requirements=summary.key_requirements,
        compliance_checklist=summary.compliance_checklist,
        confidence_score=summary.confidence_score,
        token_count=summary.token_count,
        created_at=summary.created_at,
        promoted_at=summary.promoted_at,
    )


# =========================================================================
# DASHBOARD ENDPOINTS (Phase 7.6)
# =========================================================================


@router.get(
    "/dashboard",
    response_model=SamDashboardStatsResponse,
    summary="Get SAM dashboard stats",
    description="Get dashboard statistics including totals and recent activity.",
)
async def get_dashboard_stats(
    current_user: User = Depends(get_current_user),
) -> SamDashboardStatsResponse:
    """
    Get dashboard statistics for the organization.

    Returns aggregate counts for notices, solicitations, and recent activity (7 days).
    Also includes current API usage.
    """
    async with database_service.get_session() as session:
        # Get dashboard stats
        stats = await sam_service.get_dashboard_stats(
            session=session,
            organization_id=current_user.organization_id,
        )

        # Get API usage
        usage = await sam_api_usage_service.get_usage(
            session, current_user.organization_id
        )

        return SamDashboardStatsResponse(
            total_notices=stats["total_notices"],
            total_solicitations=stats["total_solicitations"],
            recent_notices_7d=stats["recent_notices_7d"],
            new_solicitations_7d=stats["new_solicitations_7d"],
            updated_solicitations_7d=stats["updated_solicitations_7d"],
            api_usage=SamApiUsageResponse(**usage),
        )


@router.post(
    "/reindex",
    summary="Reindex SAM data to search",
    description="Trigger reindexing of all SAM.gov data to search index for unified search. Admin only.",
    status_code=202,
)
async def reindex_sam_data(
    current_user: User = Depends(require_org_admin),
):
    """
    Trigger reindexing of all SAM.gov data to search index.

    This queues a background task to index all existing SAM notices and
    solicitations for the organization. Useful for initial setup or after
    enabling search.

    Requires org_admin role.
    """
    from ....tasks import reindex_sam_organization_task
    from ....services.config_loader import config_loader

    # Check if search is enabled
    search_config = config_loader.get_search_config()
    if not search_config or not search_config.enabled:
        raise HTTPException(
            status_code=503,
            detail="Search is not enabled. Enable search to use SAM search.",
        )

    # Queue background task
    task = reindex_sam_organization_task.delay(
        organization_id=str(current_user.organization_id),
    )

    logger.info(
        f"Queued SAM reindex for org {current_user.organization_id}, task_id={task.id}"
    )

    return {
        "status": "queued",
        "message": "SAM reindex task has been queued. This may take several minutes.",
        "task_id": task.id,
    }


@router.get(
    "/notices",
    response_model=SamNoticeListResponse,
    summary="List all notices",
    description="List all SAM.gov notices for the organization with optional filters.",
)
async def list_all_notices(
    agency: Optional[str] = Query(None, description="Filter by agency name"),
    sub_agency: Optional[str] = Query(None, description="Filter by sub-agency/bureau"),
    office: Optional[str] = Query(None, description="Filter by office"),
    notice_type: Optional[str] = Query(None, description="Filter by notice type (o, p, k, r, s, a)"),
    posted_from: Optional[datetime] = Query(None, description="Filter by posted date from"),
    posted_to: Optional[datetime] = Query(None, description="Filter by posted date to"),
    keyword: Optional[str] = Query(None, description="Search by title, description, or solicitation number"),
    limit: int = Query(50, ge=1, le=500, description="Maximum results (up to 500 for facet counting)"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    current_user: User = Depends(get_current_user),
) -> SamNoticeListResponse:
    """
    List all notices across all SAM searches for the organization.

    Returns notices with solicitation context (agency, solicitation number, etc.)
    for display in an org-wide notices table. Includes both solicitation-linked
    notices and standalone notices (e.g., Special Notices).

    Supports keyword search across title, description, and solicitation number.
    """
    async with database_service.get_session() as session:
        notices, total = await sam_service.list_all_notices(
            session=session,
            organization_id=current_user.organization_id,
            agency=agency,
            sub_agency=sub_agency,
            office=office,
            notice_type=notice_type,
            posted_from=posted_from,
            posted_to=posted_to,
            keyword=keyword,
            limit=limit,
            offset=offset,
        )

        # Get solicitation info for each notice (or use notice's own fields for standalone)
        items = []
        for notice in notices:
            if notice.solicitation_id:
                # Notice with parent solicitation
                solicitation = await sam_service.get_solicitation(session, notice.solicitation_id)
                if solicitation:
                    items.append(_notice_with_solicitation_to_response(notice, solicitation))
            else:
                # Standalone notice (e.g., Special Notice) - use notice's own fields
                items.append(SamNoticeWithSolicitationResponse(
                    id=str(notice.id),
                    solicitation_id=None,
                    sam_notice_id=notice.sam_notice_id,
                    notice_type=notice.notice_type,
                    version_number=notice.version_number,
                    title=notice.title,
                    description=notice.description[:500] if notice.description else None,
                    posted_date=notice.posted_date,
                    response_deadline=notice.response_deadline,
                    changes_summary=notice.changes_summary,
                    created_at=notice.created_at,
                    solicitation_number=notice.solicitation_number,  # Can have solnum even for standalone
                    agency_name=notice.agency_name,
                    bureau_name=notice.bureau_name,
                    office_name=notice.office_name,
                ))

        return SamNoticeListResponse(
            items=items,
            total=total,
            limit=limit,
            offset=offset,
        )


# =========================================================================
# SEARCH ENDPOINTS
# =========================================================================


@router.post(
    "/searches/preview",
    response_model=PreviewSearchResponse,
    summary="Preview search configuration",
    description="Test a search configuration without saving. Returns sample matching opportunities.",
)
async def preview_search(
    request: PreviewSearchRequest,
    current_user: User = Depends(get_current_user),
) -> PreviewSearchResponse:
    """
    Preview/test a search configuration before saving.

    This endpoint makes a live API call to SAM.gov to validate the
    search configuration and return sample matching opportunities.
    This allows users to verify their filters before creating a search.

    Note: This uses API quota (counts against daily limit).
    """
    async with database_service.get_session() as session:
        result = await sam_pull_service.preview_search(
            session=session,
            organization_id=current_user.organization_id,
            search_config=request.search_config,
            limit=request.limit,
            check_rate_limit=True,
        )

        if not result.get("success"):
            return PreviewSearchResponse(
                success=False,
                message=result.get("message", "Preview failed"),
                error=result.get("error"),
                remaining_calls=result.get("remaining_calls"),
            )

        # Convert sample results to proper response format
        sample_results = []
        for r in result.get("sample_results", []):
            sample_results.append(
                PreviewSearchResult(
                    notice_id=r.get("notice_id", ""),
                    title=r.get("title", ""),
                    solicitation_number=r.get("solicitation_number"),
                    notice_type=r.get("notice_type", ""),
                    naics_code=r.get("naics_code"),
                    psc_code=r.get("psc_code"),
                    set_aside=r.get("set_aside"),
                    posted_date=r.get("posted_date"),
                    response_deadline=r.get("response_deadline"),
                    agency=r.get("agency"),
                    ui_link=r.get("ui_link"),
                    attachments_count=r.get("attachments_count", 0),
                )
            )

        return PreviewSearchResponse(
            success=True,
            total_matching=result.get("total_matching"),
            sample_count=result.get("sample_count"),
            sample_results=sample_results,
            search_config=result.get("search_config"),
            message=result.get("message", "Preview successful"),
            is_multi_department=result.get("is_multi_department"),
            departments_searched=result.get("departments_searched"),
        )


@router.get(
    "/searches",
    response_model=SamSearchListResponse,
    summary="List SAM searches",
    description="List all SAM.gov searches for the current organization.",
)
async def list_searches(
    status: Optional[str] = Query(None, description="Filter by status"),
    is_active: Optional[bool] = Query(None, description="Filter by active state"),
    limit: int = Query(50, ge=1, le=100, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    current_user: User = Depends(get_current_user),
) -> SamSearchListResponse:
    """List SAM searches for the organization."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    async with database_service.get_session() as session:
        searches, total = await sam_service.list_searches(
            session=session,
            organization_id=current_user.organization_id,
            status=status,
            is_active=is_active,
            limit=limit,
            offset=offset,
        )

        # Load runs for all searches that have a last_pull_run_id
        run_ids = [s.last_pull_run_id for s in searches if s.last_pull_run_id]
        runs_by_id = {}
        if run_ids:
            result = await session.execute(
                select(Run).where(Run.id.in_(run_ids))
            )
            runs_by_id = {run.id: run for run in result.scalars().all()}

        return SamSearchListResponse(
            items=[
                _search_to_response(s, runs_by_id.get(s.last_pull_run_id))
                for s in searches
            ],
            total=total,
            limit=limit,
            offset=offset,
        )


@router.post(
    "/searches",
    response_model=SamSearchResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create SAM search",
    description="Create a new SAM.gov search configuration.",
)
async def create_search(
    request: SamSearchCreateRequest,
    current_user: User = Depends(require_org_admin),
) -> SamSearchResponse:
    """Create a new SAM search."""
    async with database_service.get_session() as session:
        search = await sam_service.create_search(
            session=session,
            organization_id=current_user.organization_id,
            name=request.name,
            description=request.description,
            search_config=request.search_config,
            pull_frequency=request.pull_frequency,
            created_by=current_user.id,
        )

        return _search_to_response(search)


@router.get(
    "/searches/{search_id}",
    response_model=SamSearchResponse,
    summary="Get SAM search",
    description="Get details of a specific SAM.gov search.",
)
async def get_search(
    search_id: UUID,
    current_user: User = Depends(get_current_user),
) -> SamSearchResponse:
    """Get SAM search by ID."""
    from sqlalchemy import select

    async with database_service.get_session() as session:
        search = await sam_service.get_search(session, search_id)

        if not search:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Search not found",
            )

        if search.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )

        # Load the run if there's a last_pull_run_id
        run = None
        if search.last_pull_run_id:
            result = await session.execute(
                select(Run).where(Run.id == search.last_pull_run_id)
            )
            run = result.scalar_one_or_none()

        return _search_to_response(search, run)


@router.patch(
    "/searches/{search_id}",
    response_model=SamSearchResponse,
    summary="Update SAM search",
    description="Update a SAM.gov search configuration.",
)
async def update_search(
    search_id: UUID,
    request: SamSearchUpdateRequest,
    current_user: User = Depends(require_org_admin),
) -> SamSearchResponse:
    """Update SAM search."""
    from sqlalchemy import select

    async with database_service.get_session() as session:
        search = await sam_service.get_search(session, search_id)

        if not search:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Search not found",
            )

        if search.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )

        updated = await sam_service.update_search(
            session=session,
            search_id=search_id,
            name=request.name,
            description=request.description,
            search_config=request.search_config,
            status=request.status,
            is_active=request.is_active,
            pull_frequency=request.pull_frequency,
        )

        # Load the run if there's a last_pull_run_id
        run = None
        if updated.last_pull_run_id:
            result = await session.execute(
                select(Run).where(Run.id == updated.last_pull_run_id)
            )
            run = result.scalar_one_or_none()

        return _search_to_response(updated, run)


@router.delete(
    "/searches/{search_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete SAM search",
    description="Archive a SAM.gov search (soft delete).",
)
async def delete_search(
    search_id: UUID,
    current_user: User = Depends(require_org_admin),
):
    """Archive SAM search."""
    async with database_service.get_session() as session:
        search = await sam_service.get_search(session, search_id)

        if not search:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Search not found",
            )

        if search.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )

        await sam_service.delete_search(session, search_id)


@router.post(
    "/searches/{search_id}/pull",
    response_model=PullResponse,
    summary="Pull from SAM.gov",
    description="Trigger a pull of opportunities from SAM.gov API. The pull runs asynchronously via Celery.",
)
async def pull_search(
    search_id: UUID,
    request: PullRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_org_admin),
) -> PullResponse:
    """Pull opportunities from SAM.gov.

    The pull is executed asynchronously via a Celery task to avoid blocking
    the API. The returned task_id can be used to monitor progress.

    Rate limited to one pull per minute per search to prevent duplicate jobs.
    """
    from datetime import timedelta
    from sqlalchemy import and_

    async with database_service.get_session() as session:
        search = await sam_service.get_search(session, search_id)

        if not search:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Search not found",
            )

        if search.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )

        # Check if there's already a pending/running pull for this search
        one_minute_ago = datetime.utcnow() - timedelta(minutes=1)
        existing_run_result = await session.execute(
            select(Run).where(
                and_(
                    Run.run_type == "sam_pull",
                    Run.config["search_id"].astext == str(search_id),
                    Run.status.in_(["pending", "running"]),
                )
            ).limit(1)
        )
        existing_run = existing_run_result.scalar_one_or_none()

        if existing_run:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="A pull is already in progress for this search. Please wait for it to complete.",
            )

        # Check if a pull was triggered within the last minute (rate limiting)
        recent_run_result = await session.execute(
            select(Run).where(
                and_(
                    Run.run_type == "sam_pull",
                    Run.config["search_id"].astext == str(search_id),
                    Run.created_at > one_minute_ago,
                )
            ).limit(1)
        )
        recent_run = recent_run_result.scalar_one_or_none()

        if recent_run:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="A pull was recently triggered for this search. Please wait at least 1 minute between pulls.",
            )

        # Create the Run record BEFORE dispatching the task
        # This ensures the frontend can see the "pulling" indicator immediately
        run = Run(
            organization_id=current_user.organization_id,
            run_type="sam_pull",
            origin="user",
            status="pending",
            config={
                "search_id": str(search_id),
                "max_pages": request.max_pages,
                "page_size": request.page_size,
                "auto_download_attachments": request.download_attachments,
            },
            created_by=current_user.id,
        )
        session.add(run)
        await session.flush()

        # Update the search with the new run_id so is_pulling shows correctly
        search.last_pull_run_id = run.id
        await session.commit()

        # Now dispatch the Celery task with the pre-created run_id
        task = sam_pull_task.delay(
            search_id=str(search_id),
            organization_id=str(current_user.organization_id),
            max_pages=request.max_pages,
            page_size=request.page_size,
            auto_download_attachments=request.download_attachments,
            run_id=str(run.id),
        )

        logger.info(f"Queued SAM pull task {task.id} for search {search_id} (run_id={run.id})")

        return PullResponse(
            search_id=str(search_id),
            status="queued",
            task_id=task.id,
            run_id=str(run.id),
            message=f"Pull task queued. Task ID: {task.id}. Check the search page for results.",
        )


@router.get(
    "/searches/{search_id}/stats",
    summary="Get search statistics",
    description="Get statistics for a SAM.gov search.",
)
async def get_search_stats(
    search_id: UUID,
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Get statistics for a search."""
    async with database_service.get_session() as session:
        search = await sam_service.get_search(session, search_id)

        if not search:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Search not found",
            )

        if search.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )

        return await sam_service.get_search_stats(session, search_id)


class PullHistoryItem(BaseModel):
    """Individual pull history entry."""
    id: str
    run_type: str
    status: str
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    results_summary: Optional[Dict[str, Any]]
    error_message: Optional[str]


class PullHistoryResponse(BaseModel):
    """Pull history for a search."""
    items: List[PullHistoryItem]
    total: int


@router.get(
    "/searches/{search_id}/pulls",
    response_model=PullHistoryResponse,
    summary="Get pull history",
    description="Get the history of pulls executed for a SAM.gov search.",
)
async def get_pull_history(
    search_id: UUID,
    limit: int = Query(20, ge=1, le=100, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    current_user: User = Depends(get_current_user),
) -> PullHistoryResponse:
    """Get pull history for a search."""
    async with database_service.get_session() as session:
        search = await sam_service.get_search(session, search_id)

        if not search:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Search not found",
            )

        if search.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )

        search_id_str = str(search_id)

        # Fetch all sam_pull runs for this org and filter by search_id in Python
        # This ensures database compatibility (SQLite vs PostgreSQL have different JSON syntax)
        query = (
            select(Run)
            .where(Run.organization_id == current_user.organization_id)
            .where(Run.run_type == "sam_pull")
            .order_by(desc(Run.started_at))
        )

        result = await session.execute(query)
        all_runs = result.scalars().all()

        # Filter by search_id in config
        matching_runs = [
            run for run in all_runs
            if run.config and run.config.get("search_id") == search_id_str
        ]

        # Apply pagination
        total = len(matching_runs)
        runs = matching_runs[offset:offset + limit]

        return PullHistoryResponse(
            items=[
                PullHistoryItem(
                    id=str(run.id),
                    run_type=run.run_type,
                    status=run.status,
                    started_at=run.started_at,
                    completed_at=run.completed_at,
                    results_summary=run.results_summary,
                    error_message=run.error_message,
                )
                for run in runs
            ],
            total=total,
        )


# =========================================================================
# SOLICITATION ENDPOINTS
# =========================================================================


@router.get(
    "/solicitations",
    response_model=SamSolicitationListResponse,
    summary="List solicitations",
    description="List SAM.gov solicitations with optional filters. Solicitations are org-wide and not tied to specific searches.",
)
async def list_solicitations(
    status: Optional[str] = Query(None, description="Filter by status"),
    notice_type: Optional[str] = Query(None, description="Filter by notice type"),
    naics_code: Optional[str] = Query(None, description="Filter by NAICS code"),
    keyword: Optional[str] = Query(None, description="Search keyword"),
    limit: int = Query(50, ge=1, le=500, description="Maximum results (up to 500 for facet counting)"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    current_user: User = Depends(get_current_user),
) -> SamSolicitationListResponse:
    """List solicitations with filters."""
    async with database_service.get_session() as session:
        solicitations, total = await sam_service.list_solicitations(
            session=session,
            organization_id=current_user.organization_id,
            status=status,
            notice_type=notice_type,
            naics_code=naics_code,
            keyword=keyword,
            limit=limit,
            offset=offset,
        )

        return SamSolicitationListResponse(
            items=[_solicitation_to_response(s) for s in solicitations],
            total=total,
            limit=limit,
            offset=offset,
        )


@router.get(
    "/solicitations/{solicitation_id}",
    response_model=SamSolicitationWithSummaryResponse,
    summary="Get solicitation",
    description="Get details of a specific solicitation including summary status.",
)
async def get_solicitation(
    solicitation_id: UUID,
    current_user: User = Depends(get_current_user),
) -> SamSolicitationWithSummaryResponse:
    """Get solicitation by ID with summary status."""
    async with database_service.get_session() as session:
        sol = await sam_service.get_solicitation(
            session, solicitation_id, include_notices=True, include_attachments=True
        )

        if not sol:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Solicitation not found",
            )

        if sol.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )

        return _solicitation_with_summary_to_response(sol)


@router.post(
    "/solicitations/{solicitation_id}/refresh",
    summary="Refresh solicitation from SAM.gov",
    description="Re-fetch solicitation data from SAM.gov API to update descriptions and other fields. Queues a background job.",
)
async def refresh_solicitation(
    solicitation_id: UUID,
    download_attachments: bool = Query(True, description="Download attachments after refresh"),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Refresh a solicitation by re-fetching data from SAM.gov.

    This queues a background job to refresh solicitation data and optionally
    download attachments. Returns a run_id that can be used to track progress.
    """
    async with database_service.get_session() as session:
        # Verify solicitation exists and belongs to user's org
        sol = await sam_service.get_solicitation(session, solicitation_id)
        if not sol:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Solicitation not found",
            )
        if sol.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )

        # Create Run record for tracking
        run = await run_service.create_run(
            session=session,
            run_type="sam_refresh",
            organization_id=current_user.organization_id,
            config={
                "solicitation_id": str(solicitation_id),
                "solicitation_number": sol.solicitation_number,
                "download_attachments": download_attachments,
            },
        )
        await session.commit()

        # Queue the background task
        sam_refresh_solicitation_task.delay(
            solicitation_id=str(solicitation_id),
            organization_id=str(current_user.organization_id),
            download_attachments=download_attachments,
            run_id=str(run.id),
        )

        logger.info(
            f"Queued SAM refresh job for solicitation {sol.solicitation_number} "
            f"(run_id={run.id}, download_attachments={download_attachments})"
        )

        return {
            "run_id": str(run.id),
            "status": "queued",
            "solicitation_id": str(solicitation_id),
            "download_attachments": download_attachments,
        }


@router.get(
    "/solicitations/{solicitation_id}/notices",
    response_model=List[SamNoticeResponse],
    summary="List notices",
    description="List all notices/versions for a solicitation.",
)
async def list_solicitation_notices(
    solicitation_id: UUID,
    current_user: User = Depends(get_current_user),
) -> List[SamNoticeResponse]:
    """List notices for a solicitation."""
    async with database_service.get_session() as session:
        sol = await sam_service.get_solicitation(session, solicitation_id)

        if not sol:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Solicitation not found",
            )

        if sol.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )

        notices = await sam_service.list_notices(session, solicitation_id)
        return [_notice_to_response(n) for n in notices]


@router.get(
    "/solicitations/{solicitation_id}/attachments",
    response_model=List[SamAttachmentResponse],
    summary="List attachments",
    description="List all attachments for a solicitation.",
)
async def list_solicitation_attachments(
    solicitation_id: UUID,
    download_status: Optional[str] = Query(None, description="Filter by download status"),
    current_user: User = Depends(get_current_user),
) -> List[SamAttachmentResponse]:
    """List attachments for a solicitation."""
    async with database_service.get_session() as session:
        sol = await sam_service.get_solicitation(session, solicitation_id)

        if not sol:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Solicitation not found",
            )

        if sol.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )

        attachments = await sam_service.list_attachments(
            session, solicitation_id, download_status
        )
        return [_attachment_to_response(a) for a in attachments]


@router.get(
    "/solicitations/{solicitation_id}/summaries",
    response_model=List[SamSummaryResponse],
    summary="List summaries",
    description="List all summaries for a solicitation.",
)
async def list_solicitation_summaries(
    solicitation_id: UUID,
    summary_type: Optional[str] = Query(None, description="Filter by summary type"),
    current_user: User = Depends(get_current_user),
) -> List[SamSummaryResponse]:
    """List summaries for a solicitation."""
    async with database_service.get_session() as session:
        sol = await sam_service.get_solicitation(session, solicitation_id)

        if not sol:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Solicitation not found",
            )

        if sol.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )

        summaries = await sam_service.list_summaries(
            session, solicitation_id, summary_type
        )
        return [_summary_to_response(s) for s in summaries]


@router.post(
    "/solicitations/{solicitation_id}/summarize",
    response_model=SamSummaryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate summary",
    description="Generate an LLM-powered summary for a solicitation.",
)
async def summarize_solicitation(
    solicitation_id: UUID,
    request: SummarizeRequest,
    current_user: User = Depends(get_current_user),
) -> SamSummaryResponse:
    """Generate summary for a solicitation."""
    async with database_service.get_session() as session:
        sol = await sam_service.get_solicitation(session, solicitation_id)

        if not sol:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Solicitation not found",
            )

        if sol.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )

        summary = await sam_summarization_service.summarize_solicitation(
            session=session,
            solicitation_id=solicitation_id,
            organization_id=current_user.organization_id,
            summary_type=request.summary_type,
            model=request.model,
            include_attachments=request.include_attachments,
        )

        if not summary:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to generate summary",
            )

        return _summary_to_response(summary)


@router.post(
    "/solicitations/{solicitation_id}/regenerate-summary",
    response_model=SamSolicitationWithSummaryResponse,
    summary="Regenerate auto-summary",
    description="Regenerate the auto-summary for a solicitation. Triggers async summary generation.",
)
async def regenerate_solicitation_summary(
    solicitation_id: UUID,
    current_user: User = Depends(get_current_user),
) -> SamSolicitationWithSummaryResponse:
    """
    Regenerate the auto-summary for a solicitation.

    This marks the solicitation summary_status as 'generating' and triggers
    an async task to regenerate the AI summary. The caller should poll
    the solicitation to check when summary_status becomes 'ready'.
    """
    from app.tasks import sam_auto_summarize_task

    async with database_service.get_session() as session:
        sol = await sam_service.get_solicitation(session, solicitation_id)

        if not sol:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Solicitation not found",
            )

        if sol.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )

        # Update status to generating
        await sam_service.update_solicitation_summary_status(
            session, solicitation_id, "generating"
        )

        # Trigger async summary generation
        sam_auto_summarize_task.delay(
            solicitation_id=str(solicitation_id),
            organization_id=str(current_user.organization_id),
        )

        # Refresh and return
        sol = await sam_service.get_solicitation(session, solicitation_id)
        return _solicitation_with_summary_to_response(sol)


@router.post(
    "/solicitations/{solicitation_id}/download-attachments",
    summary="Download all attachments",
    description="Download all pending attachments for a solicitation.",
)
async def download_solicitation_attachments(
    solicitation_id: UUID,
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Download all pending attachments."""
    async with database_service.get_session() as session:
        sol = await sam_service.get_solicitation(session, solicitation_id)

        if not sol:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Solicitation not found",
            )

        if sol.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )

        result = await sam_pull_service.download_all_attachments(
            session=session,
            solicitation_id=solicitation_id,
            organization_id=current_user.organization_id,
        )

        return result


# =========================================================================
# NOTICE ENDPOINTS
# =========================================================================


@router.get(
    "/notices/{notice_id}",
    response_model=SamNoticeResponse,
    summary="Get notice",
    description="Get details of a specific notice.",
)
async def get_notice(
    notice_id: UUID,
    include_metadata: bool = Query(False, description="Include raw SAM.gov API response"),
    current_user: User = Depends(get_current_user),
) -> SamNoticeResponse:
    """Get notice by ID."""
    async with database_service.get_session() as session:
        notice = await sam_service.get_notice(session, notice_id)

        if not notice:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Notice not found",
            )

        # Check access - either via solicitation or via organization (standalone notices)
        if notice.solicitation_id:
            sol = await sam_service.get_solicitation(session, notice.solicitation_id)
            if sol.organization_id != current_user.organization_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied",
                )
            # For non-standalone notices, get agency info from solicitation if not on notice
            if not notice.agency_name and sol.agency_name:
                notice.agency_name = sol.agency_name
                notice.bureau_name = sol.bureau_name
                notice.office_name = sol.office_name
                notice.full_parent_path = sol.full_parent_path
            # Get raw_data from solicitation if not on notice
            if include_metadata and not notice.raw_data and sol.raw_data:
                notice.raw_data = sol.raw_data
        elif notice.organization_id:
            # Standalone notice - check organization directly
            if notice.organization_id != current_user.organization_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied",
                )
        else:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied - notice has no associated organization",
            )

        return _notice_to_response(notice, include_raw_data=include_metadata)


@router.post(
    "/notices/{notice_id}/refresh",
    summary="Refresh notice from SAM.gov",
    description="Re-fetch notice data from SAM.gov API to update description and metadata.",
)
async def refresh_notice(
    notice_id: UUID,
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Refresh a notice by re-fetching data from SAM.gov.

    For notices with a parent solicitation, uses the solicitation refresh which
    searches by solicitation number to get full opportunity data including
    agency info and raw metadata.

    For standalone notices (e.g., Special Notices), fetches description only.
    """
    async with database_service.get_session() as session:
        notice = await sam_service.get_notice(session, notice_id)

        if not notice:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Notice not found",
            )

        # Check access
        org_id = notice.organization_id
        solicitation = None
        if notice.solicitation_id:
            solicitation = await sam_service.get_solicitation(session, notice.solicitation_id)
            org_id = solicitation.organization_id

        if org_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )

        try:
            # For notices with a parent solicitation, use the solicitation refresh
            # which searches by solicitation number and gets full metadata
            if solicitation:
                refresh_results = await sam_pull_service.refresh_solicitation(
                    session=session,
                    solicitation_id=solicitation.id,
                    organization_id=current_user.organization_id,
                )

                return {
                    "notice_id": str(notice_id),
                    "solicitation_id": str(solicitation.id),
                    "notice_updated": refresh_results.get("notices_updated", 0) > 0 or refresh_results.get("notices_created", 0) > 0,
                    "solicitation_updated": refresh_results.get("description_updated", False),
                    "opportunities_found": refresh_results.get("opportunities_found", 0),
                    "error": refresh_results.get("error"),
                }

            # Standalone notice - create a job to refresh from SAM.gov
            # Create Run record for tracking
            run = Run(
                organization_id=current_user.organization_id,
                run_type="sam_refresh",
                origin="user",
                status="pending",
                config={
                    "notice_id": str(notice_id),
                    "sam_notice_id": notice.sam_notice_id,
                },
                created_by=current_user.id,
            )
            session.add(run)
            await session.commit()

            # Dispatch the Celery task
            task = sam_refresh_notice_task.delay(
                notice_id=str(notice_id),
                organization_id=str(current_user.organization_id),
                run_id=str(run.id),
            )

            logger.info(f"Queued SAM notice refresh task {task.id} for notice {notice_id} (run_id={run.id})")

            return {
                "notice_id": str(notice_id),
                "run_id": str(run.id),
                "status": "queued",
                "message": "Refresh task queued. Check the job monitor for progress.",
            }

        except Exception as e:
            logger.error(f"Error refreshing notice {notice_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to refresh notice: {str(e)}",
            )


@router.post(
    "/notices/{notice_id}/regenerate-summary",
    summary="Regenerate notice summary",
    description="Regenerate AI summary for a notice (standalone or solicitation-linked).",
)
async def regenerate_notice_summary(
    notice_id: UUID,
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Trigger AI summary regeneration for any notice.

    Works for both standalone notices and solicitation-linked notices.
    Generates a notice-specific summary focused on what the notice is about.
    """
    async with database_service.get_session() as session:
        notice = await sam_service.get_notice(session, notice_id)

        if not notice:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Notice not found",
            )

        # Get organization_id from notice or its parent solicitation
        org_id = notice.organization_id
        if not org_id and notice.solicitation_id:
            solicitation = await sam_service.get_solicitation(session, notice.solicitation_id)
            if solicitation:
                org_id = solicitation.organization_id

        if not org_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot determine organization for notice",
            )

        if org_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )

        # Update status and trigger task
        notice.summary_status = "generating"
        await session.commit()

        from app.tasks import sam_auto_summarize_notice_task
        sam_auto_summarize_notice_task.delay(
            notice_id=str(notice_id),
            organization_id=str(org_id),
        )

        return {
            "notice_id": str(notice_id),
            "status": "generating",
            "message": "Summary generation started",
        }


@router.get(
    "/notices/{notice_id}/attachments",
    response_model=List[SamAttachmentResponse],
    summary="List notice attachments",
    description="List all attachments for a specific notice.",
)
async def list_notice_attachments(
    notice_id: UUID,
    download_status: Optional[str] = Query(None, description="Filter by download status"),
    current_user: User = Depends(get_current_user),
) -> List[SamAttachmentResponse]:
    """List attachments for a notice.

    Works for both solicitation-linked and standalone notices.
    """
    async with database_service.get_session() as session:
        notice = await sam_service.get_notice(session, notice_id)

        if not notice:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Notice not found",
            )

        # Check access - either via solicitation or organization for standalone
        if notice.solicitation_id:
            sol = await sam_service.get_solicitation(session, notice.solicitation_id)
            if sol.organization_id != current_user.organization_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied",
                )
        else:
            # Standalone notice - check organization_id directly
            if notice.organization_id != current_user.organization_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied",
                )

        attachments = await sam_service.list_notice_attachments(
            session, notice_id, download_status
        )
        return [_attachment_to_response(a) for a in attachments]


@router.post(
    "/notices/{notice_id}/download-attachments",
    summary="Download all notice attachments",
    description="Download all pending attachments for a notice (standalone or solicitation-linked).",
)
async def download_notice_attachments(
    notice_id: UUID,
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Download all pending attachments for a notice.

    Works for both standalone notices and solicitation-linked notices.
    """
    async with database_service.get_session() as session:
        notice = await sam_service.get_notice(session, notice_id)

        if not notice:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Notice not found",
            )

        # Check access - either via solicitation or organization for standalone
        if notice.solicitation_id:
            sol = await sam_service.get_solicitation(session, notice.solicitation_id)
            if sol.organization_id != current_user.organization_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied",
                )
        else:
            # Standalone notice - check organization_id directly
            if notice.organization_id != current_user.organization_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied",
                )

        result = await sam_pull_service.download_all_notice_attachments(
            session=session,
            notice_id=notice_id,
            organization_id=current_user.organization_id,
        )

        return result


@router.get(
    "/notices/{notice_id}/description",
    summary="Get notice full description",
    description="Get the full (non-truncated) description for a notice.",
)
async def get_notice_description(
    notice_id: UUID,
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Get full notice description (not truncated)."""
    async with database_service.get_session() as session:
        notice = await sam_service.get_notice(session, notice_id)

        if not notice:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Notice not found",
            )

        # Check access
        if notice.solicitation_id:
            sol = await sam_service.get_solicitation(session, notice.solicitation_id)
            if sol.organization_id != current_user.organization_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied",
                )
        else:
            if notice.organization_id != current_user.organization_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied",
                )

        return {
            "notice_id": str(notice_id),
            "description": notice.description,
        }


@router.post(
    "/notices/{notice_id}/generate-changes",
    summary="Generate change summary",
    description="Generate an LLM-powered summary of changes from previous version.",
)
async def generate_notice_changes(
    notice_id: UUID,
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Generate change summary for a notice."""
    async with database_service.get_session() as session:
        notice = await sam_service.get_notice(session, notice_id)

        if not notice:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Notice not found",
            )

        # Check access via solicitation
        sol = await sam_service.get_solicitation(session, notice.solicitation_id)
        if sol.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )

        summary = await sam_summarization_service.generate_change_summary(
            session=session,
            notice_id=notice_id,
            organization_id=current_user.organization_id,
        )

        return {
            "notice_id": str(notice_id),
            "changes_summary": summary,
        }


# =========================================================================
# ATTACHMENT ENDPOINTS
# =========================================================================


@router.get(
    "/attachments/{attachment_id}",
    response_model=SamAttachmentResponse,
    summary="Get attachment",
    description="Get details of a specific attachment.",
)
async def get_attachment(
    attachment_id: UUID,
    current_user: User = Depends(get_current_user),
) -> SamAttachmentResponse:
    """Get attachment by ID."""
    async with database_service.get_session() as session:
        attachment = await sam_service.get_attachment(session, attachment_id)

        if not attachment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Attachment not found",
            )

        # Check access via solicitation
        sol = await sam_service.get_solicitation(session, attachment.solicitation_id)
        if sol.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )

        return _attachment_to_response(attachment)


@router.post(
    "/attachments/{attachment_id}/download",
    summary="Download attachment",
    description="Download a specific attachment from SAM.gov.",
)
async def download_attachment(
    attachment_id: UUID,
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Download a specific attachment."""
    async with database_service.get_session() as session:
        attachment = await sam_service.get_attachment(session, attachment_id)

        if not attachment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Attachment not found",
            )

        # Check access via solicitation
        sol = await sam_service.get_solicitation(session, attachment.solicitation_id)
        if sol.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )

        asset = await sam_pull_service.download_attachment(
            session=session,
            attachment_id=attachment_id,
            organization_id=current_user.organization_id,
        )

        if asset:
            return {
                "attachment_id": str(attachment_id),
                "asset_id": str(asset.id),
                "status": "downloaded",
            }
        else:
            return {
                "attachment_id": str(attachment_id),
                "status": "failed",
                "error": attachment.download_error,
            }


# =========================================================================
# SUMMARY ENDPOINTS
# =========================================================================


@router.get(
    "/summaries/{summary_id}",
    response_model=SamSummaryResponse,
    summary="Get summary",
    description="Get details of a specific summary.",
)
async def get_summary(
    summary_id: UUID,
    current_user: User = Depends(get_current_user),
) -> SamSummaryResponse:
    """Get summary by ID."""
    async with database_service.get_session() as session:
        summary = await sam_service.get_summary(session, summary_id)

        if not summary:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Summary not found",
            )

        # Check access via solicitation
        sol = await sam_service.get_solicitation(session, summary.solicitation_id)
        if sol.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )

        return _summary_to_response(summary)


@router.post(
    "/summaries/{summary_id}/promote",
    response_model=SamSummaryResponse,
    summary="Promote summary",
    description="Promote an experimental summary to canonical status.",
)
async def promote_summary(
    summary_id: UUID,
    current_user: User = Depends(require_org_admin),
) -> SamSummaryResponse:
    """Promote summary to canonical."""
    async with database_service.get_session() as session:
        summary = await sam_service.get_summary(session, summary_id)

        if not summary:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Summary not found",
            )

        # Check access via solicitation
        sol = await sam_service.get_solicitation(session, summary.solicitation_id)
        if sol.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )

        promoted = await sam_service.promote_summary(session, summary_id)
        return _summary_to_response(promoted)


@router.delete(
    "/summaries/{summary_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete summary",
    description="Delete an experimental summary (cannot delete canonical).",
)
async def delete_summary(
    summary_id: UUID,
    current_user: User = Depends(require_org_admin),
):
    """Delete experimental summary."""
    async with database_service.get_session() as session:
        summary = await sam_service.get_summary(session, summary_id)

        if not summary:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Summary not found",
            )

        # Check access via solicitation
        sol = await sam_service.get_solicitation(session, summary.solicitation_id)
        if sol.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )

        if summary.is_canonical:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete canonical summary",
            )

        await sam_service.delete_summary(session, summary_id)


# =========================================================================
# AGENCY ENDPOINTS
# =========================================================================


@router.get(
    "/agencies",
    response_model=List[SamAgencyResponse],
    summary="List agencies",
    description="List all SAM.gov agencies.",
)
async def list_agencies(
    current_user: User = Depends(get_current_user),
) -> List[SamAgencyResponse]:
    """List all agencies."""
    async with database_service.get_session() as session:
        agencies = await sam_service.list_agencies(session, include_sub_agencies=False)
        return [
            SamAgencyResponse(
                id=str(a.id),
                code=a.code,
                name=a.name,
                abbreviation=a.abbreviation,
            )
            for a in agencies
        ]


# =========================================================================
# API USAGE & RATE LIMIT ENDPOINTS
# =========================================================================


@router.get(
    "/usage",
    response_model=SamApiUsageResponse,
    summary="Get API usage",
    description="Get today's SAM.gov API usage statistics.",
)
async def get_api_usage(
    current_user: User = Depends(get_current_user),
) -> SamApiUsageResponse:
    """Get today's API usage for the organization."""
    async with database_service.get_session() as session:
        usage = await sam_api_usage_service.get_usage(
            session, current_user.organization_id
        )
        return SamApiUsageResponse(**usage)


@router.get(
    "/usage/history",
    response_model=SamApiUsageHistoryResponse,
    summary="Get API usage history",
    description="Get historical API usage for the past N days.",
)
async def get_api_usage_history(
    days: int = Query(default=30, ge=1, le=90, description="Number of days"),
    current_user: User = Depends(get_current_user),
) -> SamApiUsageHistoryResponse:
    """Get API usage history."""
    async with database_service.get_session() as session:
        history = await sam_api_usage_service.get_usage_history(
            session, current_user.organization_id, days
        )
        return SamApiUsageHistoryResponse(items=history, days=days)


@router.post(
    "/usage/estimate",
    response_model=SamApiImpactResponse,
    summary="Estimate API impact",
    description="Estimate the API call impact of a search configuration.",
)
async def estimate_api_impact(
    request: EstimateImpactRequest,
    current_user: User = Depends(get_current_user),
) -> SamApiImpactResponse:
    """Estimate API impact of a search configuration."""
    async with database_service.get_session() as session:
        # Build full params including max_pages and page_size
        search_params = {
            **request.search_config,
            "max_pages": request.max_pages,
            "page_size": request.page_size,
        }
        impact = await sam_api_usage_service.estimate_impact(
            session, current_user.organization_id, search_params
        )
        return SamApiImpactResponse(**impact)


@router.get(
    "/usage/status",
    response_model=SamApiStatusResponse,
    summary="Get full API status",
    description="Get combined API usage, queue status, and history for dashboard.",
)
async def get_api_status(
    history_days: int = Query(default=7, ge=1, le=30, description="Days of history"),
    current_user: User = Depends(get_current_user),
) -> SamApiStatusResponse:
    """Get full API status for dashboard display."""
    async with database_service.get_session() as session:
        # Get today's usage
        usage = await sam_api_usage_service.get_usage(
            session, current_user.organization_id
        )

        # Get queue stats
        queue = await sam_api_usage_service.get_queue_stats(
            session, current_user.organization_id
        )

        # Get recent history
        history = await sam_api_usage_service.get_usage_history(
            session, current_user.organization_id, history_days
        )

        return SamApiStatusResponse(
            usage=SamApiUsageResponse(**usage),
            queue=SamQueueStatsResponse(**queue),
            history=history,
        )


@router.get(
    "/queue",
    response_model=SamQueueStatsResponse,
    summary="Get queue stats",
    description="Get statistics about queued API requests.",
)
async def get_queue_stats(
    current_user: User = Depends(get_current_user),
) -> SamQueueStatsResponse:
    """Get queue statistics for the organization."""
    async with database_service.get_session() as session:
        stats = await sam_api_usage_service.get_queue_stats(
            session, current_user.organization_id
        )
        return SamQueueStatsResponse(**stats)
