# backend/app/api/v1/routers/search.py
"""
Search API Router for Native Full-Text Search (Phase 6).

Provides endpoints for searching assets across all sources using OpenSearch.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ....database.models import User
from ....dependencies import get_current_user, require_org_admin
from ....services.opensearch_service import opensearch_service
from ....services.index_service import index_service
from ....services.config_loader import config_loader
from ....config import settings
from ....tasks import reindex_organization_task

logger = logging.getLogger("curatore.api.search")


def _is_opensearch_enabled() -> bool:
    """Check if OpenSearch is enabled via config.yml or environment variables."""
    opensearch_config = config_loader.get_opensearch_config()
    if opensearch_config:
        return opensearch_config.enabled
    return settings.opensearch_enabled

router = APIRouter(prefix="/search", tags=["search"])


# =========================================================================
# REQUEST/RESPONSE MODELS
# =========================================================================


class SearchRequest(BaseModel):
    """Search request with query and optional filters."""

    query: str = Field(..., min_length=1, max_length=500, description="Search query")
    source_types: Optional[List[str]] = Field(
        None, description="Filter by source types (upload, sharepoint, web_scrape, sam_gov)"
    )
    content_types: Optional[List[str]] = Field(
        None, description="Filter by content/MIME types"
    )
    collection_ids: Optional[List[str]] = Field(
        None, description="Filter by collection IDs (for web scrapes)"
    )
    date_from: Optional[datetime] = Field(
        None, description="Filter by creation date >= (ISO format)"
    )
    date_to: Optional[datetime] = Field(
        None, description="Filter by creation date <= (ISO format)"
    )
    limit: int = Field(20, ge=1, le=100, description="Maximum results to return")
    offset: int = Field(0, ge=0, description="Offset for pagination")
    include_facets: bool = Field(True, description="Include faceted counts in response")


class SearchHitResponse(BaseModel):
    """Single search result."""

    asset_id: str = Field(..., description="Asset UUID")
    score: float = Field(..., description="Relevance score (0-100)")
    title: Optional[str] = Field(None, description="Document title")
    filename: Optional[str] = Field(None, description="Original filename")
    source_type: Optional[str] = Field(None, description="Source type")
    content_type: Optional[str] = Field(None, description="MIME type")
    url: Optional[str] = Field(None, description="URL for web scrapes")
    created_at: Optional[str] = Field(None, description="Creation timestamp")
    highlights: Dict[str, List[str]] = Field(
        default_factory=dict, description="Highlighted text snippets"
    )


class FacetBucketResponse(BaseModel):
    """Single bucket in a facet."""

    value: str = Field(..., description="Facet value")
    count: int = Field(..., description="Document count for this value")


class FacetResponse(BaseModel):
    """Facet aggregation result."""

    field: str = Field(..., description="Field name for this facet")
    buckets: List[FacetBucketResponse] = Field(..., description="Facet buckets")
    total_other: int = Field(0, description="Count of documents not in top buckets")


class SearchResponse(BaseModel):
    """Search results with metadata."""

    total: int = Field(..., description="Total matching results")
    limit: int = Field(..., description="Results limit")
    offset: int = Field(..., description="Results offset")
    query: str = Field(..., description="Original search query")
    hits: List[SearchHitResponse] = Field(..., description="Matching results")
    facets: Optional[Dict[str, FacetResponse]] = Field(
        None, description="Faceted counts for filtering"
    )


class IndexStatsResponse(BaseModel):
    """Index statistics."""

    enabled: bool = Field(..., description="Whether OpenSearch is enabled")
    status: str = Field(..., description="Index status")
    index_name: Optional[str] = Field(None, description="OpenSearch index name")
    document_count: Optional[int] = Field(None, description="Number of indexed documents")
    size_bytes: Optional[int] = Field(None, description="Index size in bytes")
    message: Optional[str] = Field(None, description="Additional status message")


class ReindexResponse(BaseModel):
    """Reindex operation response."""

    status: str = Field(..., description="Reindex status")
    message: str = Field(..., description="Status message")
    task_id: Optional[str] = Field(None, description="Background task ID")


# =========================================================================
# SEARCH ENDPOINTS
# =========================================================================


@router.post(
    "",
    response_model=SearchResponse,
    summary="Search assets",
    description="Full-text search across all indexed assets.",
)
async def search_assets(
    request: SearchRequest,
    current_user: User = Depends(get_current_user),
) -> SearchResponse:
    """
    Execute a full-text search query.

    Searches across all indexed content including document text, titles,
    filenames, and URLs. Returns results with relevance scoring and
    highlighted text snippets.

    Filters can be applied by:
    - Source type (upload, sharepoint, web_scrape)
    - Content type (MIME type)
    - Collection ID (for web scrapes)
    - Date range
    """
    if not _is_opensearch_enabled():
        raise HTTPException(
            status_code=503,
            detail="Search is not enabled. Enable OPENSEARCH_ENABLED to use search.",
        )

    try:
        # Convert collection_ids to UUIDs if provided
        collection_uuids = None
        if request.collection_ids:
            try:
                collection_uuids = [UUID(c) for c in request.collection_ids]
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid collection ID format",
                )

        # Use search_with_facets if facets are requested
        if request.include_facets:
            results = await opensearch_service.search_with_facets(
                organization_id=current_user.organization_id,
                query=request.query,
                source_types=request.source_types,
                content_types=request.content_types,
                collection_ids=collection_uuids,
                date_from=request.date_from,
                date_to=request.date_to,
                limit=request.limit,
                offset=request.offset,
            )
        else:
            results = await opensearch_service.search(
                organization_id=current_user.organization_id,
                query=request.query,
                source_types=request.source_types,
                content_types=request.content_types,
                collection_ids=collection_uuids,
                date_from=request.date_from,
                date_to=request.date_to,
                limit=request.limit,
                offset=request.offset,
            )

        # Build facets response if available
        facets_response = None
        if results.facets:
            facets_response = {}
            for field, facet in results.facets.items():
                facets_response[field] = FacetResponse(
                    field=facet.field,
                    buckets=[
                        FacetBucketResponse(value=b.value, count=b.count)
                        for b in facet.buckets
                    ],
                    total_other=facet.total_other,
                )

        return SearchResponse(
            total=results.total,
            limit=request.limit,
            offset=request.offset,
            query=request.query,
            hits=[
                SearchHitResponse(
                    asset_id=hit.asset_id,
                    score=hit.score,
                    title=hit.title,
                    filename=hit.filename,
                    source_type=hit.source_type,
                    content_type=hit.content_type,
                    url=hit.url,
                    created_at=hit.created_at,
                    highlights=hit.highlights,
                )
                for hit in results.hits
            ],
            facets=facets_response,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Search failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Search failed: {str(e)}",
        )


@router.get(
    "",
    response_model=SearchResponse,
    summary="Search assets (GET)",
    description="Full-text search across all indexed assets using query parameters.",
)
async def search_assets_get(
    q: str = Query(..., min_length=1, max_length=500, description="Search query"),
    source_types: Optional[str] = Query(
        None, description="Comma-separated source types (upload,sharepoint,web_scrape,sam_gov)"
    ),
    content_types: Optional[str] = Query(
        None, description="Comma-separated content types"
    ),
    limit: int = Query(20, ge=1, le=100, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    current_user: User = Depends(get_current_user),
) -> SearchResponse:
    """
    Execute a full-text search query using GET parameters.

    Simpler alternative to POST /search for basic queries.
    For advanced filtering, use POST /search with JSON body.
    """
    if not _is_opensearch_enabled():
        raise HTTPException(
            status_code=503,
            detail="Search is not enabled. Enable OPENSEARCH_ENABLED to use search.",
        )

    # Parse comma-separated filters
    source_type_list = source_types.split(",") if source_types else None
    content_type_list = content_types.split(",") if content_types else None

    try:
        results = await opensearch_service.search(
            organization_id=current_user.organization_id,
            query=q,
            source_types=source_type_list,
            content_types=content_type_list,
            limit=limit,
            offset=offset,
        )

        return SearchResponse(
            total=results.total,
            limit=limit,
            offset=offset,
            query=q,
            hits=[
                SearchHitResponse(
                    asset_id=hit.asset_id,
                    score=hit.score,
                    title=hit.title,
                    filename=hit.filename,
                    source_type=hit.source_type,
                    content_type=hit.content_type,
                    url=hit.url,
                    created_at=hit.created_at,
                    highlights=hit.highlights,
                )
                for hit in results.hits
            ],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Search failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Search failed: {str(e)}",
        )


@router.get(
    "/stats",
    response_model=IndexStatsResponse,
    summary="Get search index statistics",
    description="Get statistics about the search index for the organization.",
)
async def get_search_stats(
    current_user: User = Depends(get_current_user),
) -> IndexStatsResponse:
    """
    Get search index statistics.

    Returns information about the index including document count
    and storage size.
    """
    health = await index_service.get_index_health(current_user.organization_id)

    return IndexStatsResponse(
        enabled=health.get("enabled", False),
        status=health.get("status", "unknown"),
        index_name=health.get("index_name"),
        document_count=health.get("document_count"),
        size_bytes=health.get("size_bytes"),
        message=health.get("message"),
    )


@router.post(
    "/reindex",
    response_model=ReindexResponse,
    summary="Reindex all assets",
    description="Trigger a full reindex of all assets. Admin only.",
    status_code=202,
)
async def reindex_all_assets(
    current_user: User = Depends(require_org_admin),
) -> ReindexResponse:
    """
    Trigger a full reindex of all assets.

    This queues a background task to reindex all assets for the
    organization. Useful after enabling search or recovering
    from index issues.

    Requires org_admin role.
    """
    if not _is_opensearch_enabled():
        raise HTTPException(
            status_code=503,
            detail="Search is not enabled. Enable OPENSEARCH_ENABLED to use search.",
        )

    try:
        # Queue background task
        task = reindex_organization_task.delay(
            organization_id=str(current_user.organization_id),
        )

        logger.info(
            f"Queued reindex for org {current_user.organization_id}, task_id={task.id}"
        )

        return ReindexResponse(
            status="queued",
            message="Reindex task has been queued. This may take several minutes.",
            task_id=task.id,
        )

    except Exception as e:
        logger.error(f"Failed to queue reindex: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to queue reindex: {str(e)}",
        )


@router.get(
    "/health",
    summary="Check search health",
    description="Check OpenSearch cluster health and connectivity.",
)
async def check_search_health(
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Check search service health.

    Returns OpenSearch cluster health status and connectivity information.
    """
    if not _is_opensearch_enabled():
        return {
            "enabled": False,
            "status": "disabled",
            "message": "OpenSearch is not enabled",
        }

    is_healthy = await opensearch_service.health_check()

    # Get config from config.yml or fall back to settings
    opensearch_config = config_loader.get_opensearch_config()
    if opensearch_config:
        index_prefix = opensearch_config.index_prefix
        endpoint = opensearch_config.service_url
    else:
        index_prefix = settings.opensearch_index_prefix
        endpoint = settings.opensearch_endpoint

    return {
        "enabled": True,
        "status": "healthy" if is_healthy else "unhealthy",
        "index_prefix": index_prefix,
        "endpoint": endpoint,
    }


# =========================================================================
# SAM.gov SEARCH ENDPOINTS (Phase 7.6)
# =========================================================================


class SamSearchRequest(BaseModel):
    """SAM.gov search request with query and optional filters."""

    query: str = Field(..., min_length=1, max_length=500, description="Search query")
    source_types: Optional[List[str]] = Field(
        None, description="Filter by type (notices, solicitations)"
    )
    notice_types: Optional[List[str]] = Field(
        None, description="Filter by notice types"
    )
    agencies: Optional[List[str]] = Field(
        None, description="Filter by agencies"
    )
    date_from: Optional[datetime] = Field(
        None, description="Filter by posted date >= (ISO format)"
    )
    date_to: Optional[datetime] = Field(
        None, description="Filter by posted date <= (ISO format)"
    )
    limit: int = Field(20, ge=1, le=100, description="Maximum results to return")
    offset: int = Field(0, ge=0, description="Offset for pagination")


@router.post(
    "/sam",
    response_model=SearchResponse,
    summary="Search SAM.gov data",
    description="Full-text search across SAM.gov notices and solicitations.",
)
async def search_sam(
    request: SamSearchRequest,
    current_user: User = Depends(get_current_user),
) -> SearchResponse:
    """
    Execute a full-text search across SAM.gov data.

    Searches across notices and solicitations including titles, descriptions,
    solicitation numbers, and agency names. Returns results with relevance
    scoring and highlighted text snippets.

    Filters can be applied by:
    - Source type (notices, solicitations)
    - Notice type (Combined Synopsis/Solicitation, etc.)
    - Agency name
    - Date range
    """
    if not _is_opensearch_enabled():
        raise HTTPException(
            status_code=503,
            detail="Search is not enabled. Enable OPENSEARCH_ENABLED to use search.",
        )

    try:
        results = await opensearch_service.search_sam(
            organization_id=current_user.organization_id,
            query=request.query,
            source_types=request.source_types,
            notice_types=request.notice_types,
            agencies=request.agencies,
            date_from=request.date_from,
            date_to=request.date_to,
            limit=request.limit,
            offset=request.offset,
        )

        return SearchResponse(
            total=results.total,
            limit=request.limit,
            offset=request.offset,
            query=request.query,
            hits=[
                SearchHitResponse(
                    asset_id=hit.asset_id,
                    score=hit.score,
                    title=hit.title,
                    filename=hit.filename,  # Solicitation number
                    source_type=hit.source_type,  # sam_notice or sam_solicitation
                    content_type=hit.content_type,  # Notice type
                    url=hit.url,
                    created_at=hit.created_at,
                    highlights=hit.highlights,
                )
                for hit in results.hits
            ],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"SAM search failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"SAM search failed: {str(e)}",
        )


@router.get(
    "/sam",
    response_model=SearchResponse,
    summary="Search SAM.gov data (GET)",
    description="Full-text search across SAM.gov data using query parameters.",
)
async def search_sam_get(
    q: str = Query(..., min_length=1, max_length=500, description="Search query"),
    source_types: Optional[str] = Query(
        None, description="Comma-separated types (notices,solicitations)"
    ),
    notice_types: Optional[str] = Query(
        None, description="Comma-separated notice types"
    ),
    agencies: Optional[str] = Query(
        None, description="Comma-separated agencies"
    ),
    limit: int = Query(20, ge=1, le=100, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    current_user: User = Depends(get_current_user),
) -> SearchResponse:
    """
    Execute a full-text search across SAM.gov data using GET parameters.

    Simpler alternative to POST /search/sam for basic queries.
    """
    if not _is_opensearch_enabled():
        raise HTTPException(
            status_code=503,
            detail="Search is not enabled. Enable OPENSEARCH_ENABLED to use search.",
        )

    # Parse comma-separated filters
    source_type_list = source_types.split(",") if source_types else None
    notice_type_list = notice_types.split(",") if notice_types else None
    agency_list = agencies.split(",") if agencies else None

    try:
        results = await opensearch_service.search_sam(
            organization_id=current_user.organization_id,
            query=q,
            source_types=source_type_list,
            notice_types=notice_type_list,
            agencies=agency_list,
            limit=limit,
            offset=offset,
        )

        return SearchResponse(
            total=results.total,
            limit=limit,
            offset=offset,
            query=q,
            hits=[
                SearchHitResponse(
                    asset_id=hit.asset_id,
                    score=hit.score,
                    title=hit.title,
                    filename=hit.filename,
                    source_type=hit.source_type,
                    content_type=hit.content_type,
                    url=hit.url,
                    created_at=hit.created_at,
                    highlights=hit.highlights,
                )
                for hit in results.hits
            ],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"SAM search failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"SAM search failed: {str(e)}",
        )
