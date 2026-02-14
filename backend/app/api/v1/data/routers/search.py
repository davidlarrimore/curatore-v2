# backend/app/api/v1/routers/search.py
"""
Search API Router for Hybrid Full-Text + Semantic Search.

Provides endpoints for searching assets across all sources using PostgreSQL
with pgvector for hybrid keyword + semantic search.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.config import settings
from app.core.database.models import User
from app.core.search.pg_index_service import pg_index_service
from app.core.search.pg_search_service import pg_search_service
from app.core.shared.config_loader import config_loader
from app.core.shared.database_service import database_service
from app.core.tasks import reindex_organization_task
from app.dependencies import get_current_org_id, get_current_user, require_org_admin_or_above

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
        None, description="Filter by source types (upload, sharepoint, web_scrape, sam_gov, salesforce)"
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
    metadata_filters: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "Raw namespaced JSONB containment filters (power-user). "
            'Example: {"sam": {"agency": "GSA"}, "custom": {"tags_llm_v1": {"tags": ["cyber"]}}}'
        ),
    )
    facet_filters: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "Cross-domain facet filters resolved via metadata registry. "
            'Example: {"agency": ["GSA", "DOD"], "naics_code": "541512", "fiscal_year": 2026}'
        ),
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


class MetadataFieldSchema(BaseModel):
    """Schema for a single metadata field."""

    type: str = Field(..., description="Field type (string, number, array, object)")
    sample_values: List[Any] = Field(default_factory=list, description="Sample values for enum-like fields")
    filterable: bool = Field(True, description="Whether this field supports containment filtering")


class MetadataNamespaceSchema(BaseModel):
    """Schema for a metadata namespace."""

    display_name: str = Field(..., description="Human-readable namespace name")
    source_types: List[str] = Field(default_factory=list, description="Source types using this namespace")
    doc_count: int = Field(0, description="Documents in this namespace")
    fields: Dict[str, MetadataFieldSchema] = Field(default_factory=dict, description="Fields in this namespace")


class MetadataSchemaResponse(BaseModel):
    """Response for metadata schema discovery."""

    namespaces: Dict[str, MetadataNamespaceSchema] = Field(
        default_factory=dict, description="Available metadata namespaces"
    )
    total_indexed_docs: int = Field(0, description="Total indexed documents")
    cached_at: Optional[str] = Field(None, description="When the schema was cached")


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
    org_id: UUID = Depends(get_current_org_id),
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
    - Source type (upload, sharepoint, web_scrape, sam_gov, salesforce)
    - Content type (MIME type)
    - Collection ID (for web scrapes)
    - Date range

    When filtering by "salesforce", results include Account, Contact, and Opportunity
    records with friendly type labels in the source_type field.
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
                    organization_id=org_id,
                    query=request.query,
                    search_mode=request.search_mode or "hybrid",
                    semantic_weight=request.semantic_weight or 0.5,
                    source_types=request.source_types,
                    content_types=request.content_types,
                    collection_ids=collection_uuids,
                    sync_config_ids=sync_config_uuids,
                    date_from=request.date_from,
                    date_to=request.date_to,
                    metadata_filters=request.metadata_filters,
                    facet_filters=request.facet_filters,
                    limit=request.limit,
                    offset=request.offset,
                )
            else:
                results = await pg_search_service.search(
                    session=session,
                    organization_id=org_id,
                    query=request.query,
                    search_mode=request.search_mode or "hybrid",
                    semantic_weight=request.semantic_weight or 0.5,
                    source_types=request.source_types,
                    content_types=request.content_types,
                    collection_ids=collection_uuids,
                    sync_config_ids=sync_config_uuids,
                    date_from=request.date_from,
                    date_to=request.date_to,
                    metadata_filters=request.metadata_filters,
                    facet_filters=request.facet_filters,
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
        None, description="Comma-separated source types (upload,sharepoint,web_scrape,sam_gov,salesforce)"
    ),
    content_types: Optional[str] = Query(
        None, description="Comma-separated content types"
    ),
    limit: int = Query(20, ge=1, le=100, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    org_id: UUID = Depends(get_current_org_id),
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
                organization_id=org_id,
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
    org_id: UUID = Depends(get_current_org_id),
) -> IndexStatsResponse:
    """
    Get search index statistics.

    Returns information about the index including document count,
    chunk count, and storage size.
    """
    async with database_service.get_session() as session:
        health = await pg_index_service.get_index_health(session, org_id)

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
    org_id: UUID = Depends(get_current_org_id),
    current_user: User = Depends(require_org_admin_or_above),
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
            organization_id=str(org_id),
        )

        logger.info(
            f"Queued reindex for org {org_id}, task_id={task.id}"
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
    org_id: UUID = Depends(get_current_org_id),
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
# METADATA SCHEMA ENDPOINT
# =========================================================================


@router.get(
    "/metadata-schema",
    response_model=MetadataSchemaResponse,
    summary="Discover metadata schema",
    description="Returns available metadata namespaces, fields, sample values, and document counts.",
)
async def get_metadata_schema(
    max_sample_values: int = Query(20, ge=1, le=50, description="Max sample values per field"),
    org_id: UUID = Depends(get_current_org_id),
) -> MetadataSchemaResponse:
    """
    Discover the metadata schema for the organization's search index.

    Returns a description of all available metadata namespaces, their fields,
    sample values for filterable fields, and document counts. This enables
    LLMs, procedures, and the frontend to know what metadata exists for
    building metadata_filters queries.

    Results are cached for 5 minutes and refreshed after index operations.
    """
    if not _is_search_enabled():
        raise HTTPException(
            status_code=503,
            detail="Search is not enabled.",
        )

    try:
        async with database_service.get_session() as session:
            schema = await pg_search_service.get_metadata_schema(
                session=session,
                organization_id=org_id,
                max_sample_values=max_sample_values,
            )

        return MetadataSchemaResponse(**schema)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get metadata schema: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get metadata schema: {str(e)}",
        )


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
    org_id: UUID = Depends(get_current_org_id),
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
                organization_id=org_id,
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


# =========================================================================
# SALESFORCE SEARCH ENDPOINTS
# =========================================================================


class SalesforceSearchRequest(BaseModel):
    """Salesforce search request with query and optional filters."""

    query: str = Field(..., min_length=1, max_length=500, description="Search query")
    entity_types: Optional[List[str]] = Field(
        None, description="Filter by entity type (account, contact, opportunity)"
    )
    account_types: Optional[List[str]] = Field(
        None, description="Filter by account types"
    )
    stages: Optional[List[str]] = Field(
        None, description="Filter by opportunity stages"
    )
    limit: int = Field(20, ge=1, le=100, description="Maximum results to return")
    offset: int = Field(0, ge=0, description="Offset for pagination")


@router.post(
    "/salesforce",
    response_model=SearchResponse,
    summary="Search Salesforce CRM data",
    description="Full-text search across Salesforce accounts, contacts, and opportunities.",
)
async def search_salesforce(
    request: SalesforceSearchRequest,
    org_id: UUID = Depends(get_current_org_id),
) -> SearchResponse:
    """
    Execute a full-text search across Salesforce CRM data.

    Searches across accounts, contacts, and opportunities including names,
    descriptions, titles, and other fields. Returns results with relevance
    scoring and highlighted text snippets.

    Results include a source_type field with friendly labels:
    - "Account" for Salesforce accounts
    - "Contact" for Salesforce contacts
    - "Opportunity" for Salesforce opportunities

    Filters can be applied by:
    - Entity type (account, contact, opportunity)
    - Account type
    - Opportunity stage
    """
    if not _is_search_enabled():
        raise HTTPException(
            status_code=503,
            detail="Search is not enabled. Enable SEARCH_ENABLED to use search.",
        )

    try:
        async with database_service.get_session() as session:
            results = await pg_search_service.search_salesforce(
                session=session,
                organization_id=org_id,
                query=request.query,
                entity_types=request.entity_types,
                account_types=request.account_types,
                stages=request.stages,
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
                    filename=hit.filename,  # Salesforce ID
                    source_type=hit.source_type,  # Account, Contact, or Opportunity
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
        logger.error(f"Salesforce search failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Salesforce search failed: {str(e)}",
        )


@router.get(
    "/salesforce",
    response_model=SearchResponse,
    summary="Search Salesforce CRM data (GET)",
    description="Full-text search across Salesforce data using query parameters.",
)
async def search_salesforce_get(
    q: str = Query(..., min_length=1, max_length=500, description="Search query"),
    entity_types: Optional[str] = Query(
        None, description="Comma-separated entity types (account,contact,opportunity)"
    ),
    account_types: Optional[str] = Query(
        None, description="Comma-separated account types"
    ),
    stages: Optional[str] = Query(
        None, description="Comma-separated opportunity stages"
    ),
    limit: int = Query(20, ge=1, le=100, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    org_id: UUID = Depends(get_current_org_id),
) -> SearchResponse:
    """
    Execute a full-text search across Salesforce data using GET parameters.

    Simpler alternative to POST /search/salesforce for basic queries.
    """
    if not _is_search_enabled():
        raise HTTPException(
            status_code=503,
            detail="Search is not enabled. Enable SEARCH_ENABLED to use search.",
        )

    # Parse comma-separated filters
    entity_type_list = entity_types.split(",") if entity_types else None
    account_type_list = account_types.split(",") if account_types else None
    stage_list = stages.split(",") if stages else None

    try:
        async with database_service.get_session() as session:
            results = await pg_search_service.search_salesforce(
                session=session,
                organization_id=org_id,
                query=q,
                entity_types=entity_type_list,
                account_types=account_type_list,
                stages=stage_list,
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
        logger.error(f"Salesforce search failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Salesforce search failed: {str(e)}",
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
    org_id: UUID = Depends(get_current_org_id),
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
                organization_id=org_id,
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
