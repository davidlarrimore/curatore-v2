# backend/app/api/v1/routers/search.py
"""
Search API Router for Hybrid Full-Text + Semantic Search.

Provides endpoints for searching assets across all sources using PostgreSQL
with pgvector for hybrid keyword + semantic search.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ....database.models import User
from ....dependencies import get_current_user, require_org_admin
from ....services.pg_search_service import pg_search_service
from ....services.pg_index_service import pg_index_service
from ....services.database_service import database_service
from ....services.config_loader import config_loader
from ....config import settings
from ....tasks import reindex_organization_task

logger = logging.getLogger("curatore.api.search")


def _is_search_enabled() -> bool:
    """Check if search is enabled via config.yml or environment variables."""
    search_config = config_loader.get_search_config()
    if search_config:
        return search_config.enabled
    return getattr(settings, "search_enabled", True)

router = APIRouter(prefix="/search", tags=["search"])


# =========================================================================
# REQUEST/RESPONSE MODELS
# =========================================================================


class SearchRequest(BaseModel):
    """Search request with query and optional filters."""

    query: str = Field(..., min_length=1, max_length=500, description="Search query")
    search_mode: Optional[str] = Field(
        "hybrid", description="Search mode: keyword, semantic, or hybrid"
    )
    semantic_weight: Optional[float] = Field(
        0.5, ge=0.0, le=1.0, description="Weight for semantic scores in hybrid mode (0-1)"
    )
    source_types: Optional[List[str]] = Field(
        None, description="Filter by source types (upload, sharepoint, web_scrape, sam_gov)"
    )
    content_types: Optional[List[str]] = Field(
        None, description="Filter by content/MIME types"
    )
    collection_ids: Optional[List[str]] = Field(
        None, description="Filter by collection IDs (for web scrapes)"
    )
    sync_config_ids: Optional[List[str]] = Field(
        None, description="Filter by SharePoint sync config IDs"
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
    keyword_score: Optional[float] = Field(None, description="Keyword/full-text match score")
    semantic_score: Optional[float] = Field(None, description="Semantic similarity score")


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

    enabled: bool = Field(..., description="Whether search is enabled")
    status: str = Field(..., description="Index status")
    index_name: Optional[str] = Field(None, description="Index name/description")
    document_count: Optional[int] = Field(None, description="Number of indexed documents")
    chunk_count: Optional[int] = Field(None, description="Number of indexed chunks")
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
    description="Hybrid full-text and semantic search across all indexed assets.",
)
async def search_assets(
    request: SearchRequest,
    current_user: User = Depends(get_current_user),
) -> SearchResponse:
    """
    Execute a hybrid search query combining keyword and semantic search.

    Searches across all indexed content including document text, titles,
    filenames, and URLs. Returns results with relevance scoring and
    highlighted text snippets.

    Search modes:
    - keyword: Full-text search only (fast, exact matches)
    - semantic: Vector similarity search only (finds related content)
    - hybrid: Combines both with configurable weighting (default, best quality)

    Filters can be applied by:
    - Source type (upload, sharepoint, web_scrape)
    - Content type (MIME type)
    - Collection ID (for web scrapes)
    - Date range
    """
    if not _is_search_enabled():
        raise HTTPException(
            status_code=503,
            detail="Search is not enabled. Enable SEARCH_ENABLED to use search.",
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

        # Convert sync_config_ids to UUIDs if provided
        sync_config_uuids = None
        if request.sync_config_ids:
            try:
                sync_config_uuids = [UUID(c) for c in request.sync_config_ids]
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid sync config ID format",
                )

        async with database_service.get_session() as session:
            # Use search_with_facets if facets are requested
            if request.include_facets:
                results = await pg_search_service.search_with_facets(
                    session=session,
                    organization_id=current_user.organization_id,
                    query=request.query,
                    search_mode=request.search_mode or "hybrid",
                    semantic_weight=request.semantic_weight or 0.5,
                    source_types=request.source_types,
                    content_types=request.content_types,
                    collection_ids=collection_uuids,
                    sync_config_ids=sync_config_uuids,
                    date_from=request.date_from,
                    date_to=request.date_to,
                    limit=request.limit,
                    offset=request.offset,
                )
            else:
                results = await pg_search_service.search(
                    session=session,
                    organization_id=current_user.organization_id,
                    query=request.query,
                    search_mode=request.search_mode or "hybrid",
                    semantic_weight=request.semantic_weight or 0.5,
                    source_types=request.source_types,
                    content_types=request.content_types,
                    collection_ids=collection_uuids,
                    sync_config_ids=sync_config_uuids,
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
                    keyword_score=hit.keyword_score,
                    semantic_score=hit.semantic_score,
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
    description="Hybrid search across all indexed assets using query parameters.",
)
async def search_assets_get(
    q: str = Query(..., min_length=1, max_length=500, description="Search query"),
    mode: Optional[str] = Query("hybrid", description="Search mode: keyword, semantic, hybrid"),
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
    Execute a hybrid search query using GET parameters.

    Simpler alternative to POST /search for basic queries.
    For advanced filtering, use POST /search with JSON body.
    """
    if not _is_search_enabled():
        raise HTTPException(
            status_code=503,
            detail="Search is not enabled. Enable SEARCH_ENABLED to use search.",
        )

    # Parse comma-separated filters
    source_type_list = source_types.split(",") if source_types else None
    content_type_list = content_types.split(",") if content_types else None

    try:
        async with database_service.get_session() as session:
            results = await pg_search_service.search(
                session=session,
                organization_id=current_user.organization_id,
                query=q,
                search_mode=mode or "hybrid",
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
                    keyword_score=hit.keyword_score,
                    semantic_score=hit.semantic_score,
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

    Returns information about the index including document count,
    chunk count, and storage size.
    """
    async with database_service.get_session() as session:
        health = await pg_index_service.get_index_health(session, current_user.organization_id)

    return IndexStatsResponse(
        enabled=health.get("enabled", False),
        status=health.get("status", "unknown"),
        index_name=health.get("index_name"),
        document_count=health.get("document_count"),
        chunk_count=health.get("chunk_count"),
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
    if not _is_search_enabled():
        raise HTTPException(
            status_code=503,
            detail="Search is not enabled. Enable SEARCH_ENABLED to use search.",
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
    description="Check PostgreSQL + pgvector search health and connectivity.",
)
async def check_search_health(
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Check search service health.

    Returns search system health status including pgvector availability.
    """
    if not _is_search_enabled():
        return {
            "enabled": False,
            "status": "disabled",
            "message": "Search is not enabled",
        }

    async with database_service.get_session() as session:
        is_healthy = await pg_search_service.health_check(session)

    # Get config from config.yml or fall back to settings
    search_config = config_loader.get_search_config()
    if search_config:
        embedding_model = search_config.embedding_model
        default_mode = search_config.default_mode
    else:
        embedding_model = getattr(settings, "embedding_model", "sentence-transformers/all-mpnet-base-v2")
        default_mode = getattr(settings, "search_default_mode", "hybrid")

    return {
        "enabled": True,
        "status": "healthy" if is_healthy else "unhealthy",
        "backend": "postgresql+pgvector",
        "embedding_model": embedding_model,
        "default_mode": default_mode,
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
    if not _is_search_enabled():
        raise HTTPException(
            status_code=503,
            detail="Search is not enabled. Enable SEARCH_ENABLED to use search.",
        )

    try:
        async with database_service.get_session() as session:
            results = await pg_search_service.search_sam(
                session=session,
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
                    keyword_score=hit.keyword_score,
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
    if not _is_search_enabled():
        raise HTTPException(
            status_code=503,
            detail="Search is not enabled. Enable SEARCH_ENABLED to use search.",
        )

    # Parse comma-separated filters
    source_type_list = source_types.split(",") if source_types else None
    notice_type_list = notice_types.split(",") if notice_types else None
    agency_list = agencies.split(",") if agencies else None

    try:
        async with database_service.get_session() as session:
            results = await pg_search_service.search_sam(
                session=session,
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
                    keyword_score=hit.keyword_score,
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
