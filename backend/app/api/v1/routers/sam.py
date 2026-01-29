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

from app.tasks import sam_pull_task
from app.database.models import (
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
    pull_frequency: str
    solicitation_count: int
    notice_count: int
    created_at: datetime
    updated_at: datetime


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
    search_id: str
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
    """SAM notice response."""

    id: str
    solicitation_id: str
    sam_notice_id: str
    notice_type: str
    version_number: int
    title: Optional[str]
    description: Optional[str]
    posted_date: Optional[datetime]
    response_deadline: Optional[datetime]
    changes_summary: Optional[str]
    created_at: datetime


class SamAttachmentResponse(BaseModel):
    """SAM attachment response."""

    id: str
    solicitation_id: str
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


# =========================================================================
# HELPER FUNCTIONS
# =========================================================================


def _search_to_response(search: SamSearch) -> SamSearchResponse:
    """Convert SamSearch model to response."""
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
        pull_frequency=search.pull_frequency,
        solicitation_count=search.solicitation_count,
        notice_count=search.notice_count,
        created_at=search.created_at,
        updated_at=search.updated_at,
    )


def _solicitation_to_response(sol: SamSolicitation) -> SamSolicitationResponse:
    """Convert SamSolicitation model to response."""
    return SamSolicitationResponse(
        id=str(sol.id),
        organization_id=str(sol.organization_id),
        search_id=str(sol.search_id),
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


def _notice_to_response(notice: SamNotice) -> SamNoticeResponse:
    """Convert SamNotice model to response."""
    return SamNoticeResponse(
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
    )


def _attachment_to_response(att: SamAttachment) -> SamAttachmentResponse:
    """Convert SamAttachment model to response."""
    return SamAttachmentResponse(
        id=str(att.id),
        solicitation_id=str(att.solicitation_id),
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
    async with database_service.get_session() as session:
        searches, total = await sam_service.list_searches(
            session=session,
            organization_id=current_user.organization_id,
            status=status,
            is_active=is_active,
            limit=limit,
            offset=offset,
        )

        return SamSearchListResponse(
            items=[_search_to_response(s) for s in searches],
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

        return _search_to_response(search)


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

        return _search_to_response(updated)


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
    """
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

        # Queue the pull task asynchronously via Celery
        task = sam_pull_task.delay(
            search_id=str(search_id),
            organization_id=str(current_user.organization_id),
            max_pages=request.max_pages,
            page_size=request.page_size,
            auto_download_attachments=request.download_attachments,
        )

        logger.info(f"Queued SAM pull task {task.id} for search {search_id}")

        return PullResponse(
            search_id=str(search_id),
            status="queued",
            task_id=task.id,
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


# =========================================================================
# SOLICITATION ENDPOINTS
# =========================================================================


@router.get(
    "/solicitations",
    response_model=SamSolicitationListResponse,
    summary="List solicitations",
    description="List SAM.gov solicitations with optional filters.",
)
async def list_solicitations(
    search_id: Optional[UUID] = Query(None, description="Filter by search"),
    status: Optional[str] = Query(None, description="Filter by status"),
    notice_type: Optional[str] = Query(None, description="Filter by notice type"),
    naics_code: Optional[str] = Query(None, description="Filter by NAICS code"),
    keyword: Optional[str] = Query(None, description="Search keyword"),
    limit: int = Query(50, ge=1, le=100, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    current_user: User = Depends(get_current_user),
) -> SamSolicitationListResponse:
    """List solicitations with filters."""
    async with database_service.get_session() as session:
        solicitations, total = await sam_service.list_solicitations(
            session=session,
            organization_id=current_user.organization_id,
            search_id=search_id,
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
    response_model=SamSolicitationResponse,
    summary="Get solicitation",
    description="Get details of a specific solicitation.",
)
async def get_solicitation(
    solicitation_id: UUID,
    current_user: User = Depends(get_current_user),
) -> SamSolicitationResponse:
    """Get solicitation by ID."""
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

        return _solicitation_to_response(sol)


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

        # Check access via solicitation
        sol = await sam_service.get_solicitation(session, notice.solicitation_id)
        if sol.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )

        return _notice_to_response(notice)


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
