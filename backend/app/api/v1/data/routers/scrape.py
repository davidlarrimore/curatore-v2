# backend/app/api/v1/routers/scrape.py
"""
Web Scraping Collection endpoints for Curatore v2 API (v1).

Provides endpoints for managing scrape collections, sources, and scraped assets.
Part of Phase 4: Web Scraping as Durable Data Source.

Endpoints:
    GET /scrape/collections - List scrape collections
    POST /scrape/collections - Create scrape collection
    GET /scrape/collections/{id} - Get collection details
    PUT /scrape/collections/{id} - Update collection
    DELETE /scrape/collections/{id} - Archive collection

    POST /scrape/collections/{id}/crawl - Start crawl
    GET /scrape/collections/{id}/crawl/status - Get crawl status

    GET /scrape/collections/{id}/sources - List sources
    POST /scrape/collections/{id}/sources - Add source
    DELETE /scrape/collections/{id}/sources/{source_id} - Delete source

    GET /scrape/collections/{id}/assets - List scraped assets
    GET /scrape/collections/{id}/assets/{asset_id} - Get scraped asset
    POST /scrape/collections/{id}/assets/{asset_id}/promote - Promote to record

    GET /scrape/collections/{id}/tree - Get hierarchical tree

Security:
    - All endpoints require authentication
    - Collections are organization-scoped
    - Only org_admin can create/delete collections
"""

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import PlainTextResponse

from app.api.v1.data.schemas import (
    CrawlCollectionRequest,
    CrawlCollectionResponse,
    CrawlStatusResponse,
    PathTreeNode,
    PathTreeResponse,
    PromoteToRecordResponse,
    ScrapeCollectionCreateRequest,
    ScrapeCollectionListResponse,
    ScrapeCollectionResponse,
    ScrapeCollectionUpdateRequest,
    ScrapedAssetListResponse,
    ScrapedAssetResponse,
    ScrapeSourceCreateRequest,
    ScrapeSourceListResponse,
    ScrapeSourceResponse,
)
from app.connectors.scrape.crawl_service import crawl_service
from app.connectors.scrape.scrape_service import scrape_service
from app.core.database.models import Run, ScrapeCollection, ScrapedAsset, User
from app.core.ingestion.extraction_result_service import extraction_result_service
from app.core.shared.database_service import database_service
from app.core.shared.run_service import run_service
from app.core.storage.minio_service import get_minio_service
from app.core.tasks import async_delete_scrape_collection_task
from app.dependencies import get_current_user, require_org_admin

# Initialize router
router = APIRouter(prefix="/scrape", tags=["Web Scraping"])

# Initialize logger
logger = logging.getLogger("curatore.api.scrape")


# =========================================================================
# HELPER FUNCTIONS
# =========================================================================


def _collection_to_response(collection: ScrapeCollection) -> ScrapeCollectionResponse:
    """Convert ScrapeCollection model to response."""
    return ScrapeCollectionResponse(
        id=str(collection.id),
        organization_id=str(collection.organization_id),
        name=collection.name,
        slug=collection.slug,
        description=collection.description,
        collection_mode=collection.collection_mode,
        root_url=collection.root_url,
        url_patterns=collection.url_patterns or [],
        crawl_config=collection.crawl_config or {},
        status=collection.status,
        last_crawl_at=collection.last_crawl_at,
        last_crawl_run_id=str(collection.last_crawl_run_id) if collection.last_crawl_run_id else None,
        stats=collection.stats or {},
        created_at=collection.created_at,
        updated_at=collection.updated_at,
        created_by=str(collection.created_by) if collection.created_by else None,
    )


def _scraped_asset_to_response(scraped: ScrapedAsset) -> ScrapedAssetResponse:
    """Convert ScrapedAsset model to response."""
    return ScrapedAssetResponse(
        id=str(scraped.id),
        asset_id=str(scraped.asset_id),
        collection_id=str(scraped.collection_id),
        source_id=str(scraped.source_id) if scraped.source_id else None,
        asset_subtype=scraped.asset_subtype,
        url=scraped.url,
        url_path=scraped.url_path,
        parent_url=scraped.parent_url,
        crawl_depth=scraped.crawl_depth,
        crawl_run_id=str(scraped.crawl_run_id) if scraped.crawl_run_id else None,
        is_promoted=scraped.is_promoted,
        promoted_at=scraped.promoted_at,
        promoted_by=str(scraped.promoted_by) if scraped.promoted_by else None,
        scrape_metadata=scraped.scrape_metadata or {},
        created_at=scraped.created_at,
        updated_at=scraped.updated_at,
        original_filename=scraped.asset.original_filename if scraped.asset else None,
        asset_status=scraped.asset.status if scraped.asset else None,
    )


# =========================================================================
# COLLECTION ENDPOINTS
# =========================================================================


@router.get(
    "/collections",
    response_model=ScrapeCollectionListResponse,
    summary="List scrape collections",
    description="List all scrape collections for the current organization."
)
async def list_collections(
    status: Optional[str] = Query(None, description="Filter by status (active, paused, archived)"),
    limit: int = Query(50, ge=1, le=100, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    current_user: User = Depends(get_current_user),
) -> ScrapeCollectionListResponse:
    """
    List scrape collections for the organization.

    Args:
        status: Filter by collection status
        limit: Maximum results to return
        offset: Pagination offset
        current_user: Current authenticated user

    Returns:
        ScrapeCollectionListResponse: Paginated list of collections
    """
    logger.info(f"Collections list requested by {current_user.email}")

    async with database_service.get_session() as session:
        collections, total = await scrape_service.list_collections(
            session=session,
            organization_id=current_user.organization_id,
            status=status,
            limit=limit,
            offset=offset,
        )

        return ScrapeCollectionListResponse(
            collections=[_collection_to_response(c) for c in collections],
            total=total,
            limit=limit,
            offset=offset,
        )


@router.post(
    "/collections",
    response_model=ScrapeCollectionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create scrape collection",
    description="Create a new scrape collection. Requires org_admin role."
)
async def create_collection(
    request: ScrapeCollectionCreateRequest,
    current_user: User = Depends(require_org_admin),
) -> ScrapeCollectionResponse:
    """
    Create a new scrape collection.

    Args:
        request: Collection creation details
        current_user: Current user (must be org_admin)

    Returns:
        ScrapeCollectionResponse: Created collection
    """
    logger.info(f"Collection creation requested by {current_user.email}: {request.name}")

    # Validate collection mode
    if request.collection_mode not in ("snapshot", "record_preserving"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="collection_mode must be 'snapshot' or 'record_preserving'"
        )

    async with database_service.get_session() as session:
        collection = await scrape_service.create_collection(
            session=session,
            organization_id=current_user.organization_id,
            name=request.name,
            root_url=request.root_url,
            collection_mode=request.collection_mode,
            description=request.description,
            url_patterns=request.url_patterns,
            crawl_config=request.crawl_config,
            created_by=current_user.id,
        )

        logger.info(f"Collection created: {collection.name} (id: {collection.id})")

        return _collection_to_response(collection)


@router.get(
    "/collections/{collection_id}",
    response_model=ScrapeCollectionResponse,
    summary="Get collection details",
    description="Get details of a specific scrape collection."
)
async def get_collection(
    collection_id: str,
    current_user: User = Depends(get_current_user),
) -> ScrapeCollectionResponse:
    """
    Get collection details.

    Args:
        collection_id: Collection UUID
        current_user: Current authenticated user

    Returns:
        ScrapeCollectionResponse: Collection details
    """
    logger.info(f"Collection details requested for {collection_id} by {current_user.email}")

    async with database_service.get_session() as session:
        collection = await scrape_service.get_collection(session, UUID(collection_id))

        if not collection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Collection not found"
            )

        # Verify organization access
        if collection.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Collection not found"
            )

        return _collection_to_response(collection)


@router.put(
    "/collections/{collection_id}",
    response_model=ScrapeCollectionResponse,
    summary="Update collection",
    description="Update scrape collection settings."
)
async def update_collection(
    collection_id: str,
    request: ScrapeCollectionUpdateRequest,
    current_user: User = Depends(require_org_admin),
) -> ScrapeCollectionResponse:
    """
    Update collection settings.

    Args:
        collection_id: Collection UUID
        request: Update details
        current_user: Current user (must be org_admin)

    Returns:
        ScrapeCollectionResponse: Updated collection
    """
    logger.info(f"Collection update requested for {collection_id} by {current_user.email}")

    async with database_service.get_session() as session:
        collection = await scrape_service.get_collection(session, UUID(collection_id))

        if not collection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Collection not found"
            )

        if collection.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Collection not found"
            )

        # Validate collection mode if provided
        if request.collection_mode and request.collection_mode not in ("snapshot", "record_preserving"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="collection_mode must be 'snapshot' or 'record_preserving'"
            )

        # Validate status if provided
        if request.status and request.status not in ("active", "paused", "archived"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="status must be 'active', 'paused', or 'archived'"
            )

        updated = await scrape_service.update_collection(
            session=session,
            collection_id=UUID(collection_id),
            name=request.name,
            description=request.description,
            collection_mode=request.collection_mode,
            url_patterns=request.url_patterns,
            crawl_config=request.crawl_config,
            status=request.status,
        )

        logger.info(f"Collection updated: {updated.name}")

        return _collection_to_response(updated)


@router.delete(
    "/collections/{collection_id}",
    summary="Delete collection",
    description="Initiate async deletion of a scrape collection with full cleanup."
)
async def delete_collection(
    collection_id: str,
    current_user: User = Depends(require_org_admin),
):
    """
    Initiate async deletion of a scrape collection.

    This endpoint returns immediately with a run_id that tracks the deletion progress.
    The actual cleanup happens asynchronously in a background task, performing:
    - Cancel pending extraction jobs
    - Delete files from MinIO storage (raw and extracted)
    - Hard delete Asset records from database
    - Remove documents from search index
    - Delete ScrapedAsset records
    - Delete ScrapeSource records
    - Delete related Run records (except the deletion tracking run)
    - Delete the collection itself

    Returns:
        message: Status message
        run_id: UUID of the run tracking the deletion
        status: "deleting"
    """
    logger.info(f"Collection deletion requested for {collection_id} by {current_user.email}")

    async with database_service.get_session() as session:
        collection = await scrape_service.get_collection(session, UUID(collection_id))

        if not collection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Collection not found"
            )

        if collection.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Collection not found"
            )

        # Check if deletion is already in progress
        if collection.status == "deleting":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Deletion already in progress for this collection"
            )

        # Set status to deleting
        collection.status = "deleting"
        await session.commit()

        # Create a run to track the deletion
        run = Run(
            organization_id=current_user.organization_id,
            run_type="scrape_delete",
            origin="user",
            status="pending",
            config={
                "collection_id": str(collection_id),
                "collection_name": collection.name,
                "action": "delete_collection",
            },
            created_by=current_user.id,
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)

        # Queue the async deletion task
        async_delete_scrape_collection_task.delay(
            collection_id=str(collection_id),
            organization_id=str(current_user.organization_id),
            run_id=str(run.id),
            collection_name=collection.name,
        )

        logger.info(
            f"Queued async deletion for scrape collection {collection_id} by user {current_user.id}, "
            f"run_id={run.id}"
        )

        return {
            "message": "Deletion initiated",
            "run_id": str(run.id),
            "status": "deleting",
        }


# =========================================================================
# CRAWL ENDPOINTS
# =========================================================================


@router.post(
    "/collections/{collection_id}/crawl",
    response_model=CrawlCollectionResponse,
    summary="Start crawl",
    description="Start a crawl for the collection."
)
async def start_crawl(
    collection_id: str,
    request: Optional[CrawlCollectionRequest] = None,
    current_user: User = Depends(get_current_user),
) -> CrawlCollectionResponse:
    """
    Start a crawl for the collection.

    Args:
        collection_id: Collection UUID
        request: Optional crawl options
        current_user: Current authenticated user

    Returns:
        CrawlCollectionResponse: Crawl run details
    """
    logger.info(f"Crawl start requested for {collection_id} by {current_user.email}")

    async with database_service.get_session() as session:
        collection = await scrape_service.get_collection(session, UUID(collection_id))

        if not collection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Collection not found"
            )

        if collection.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Collection not found"
            )

        if collection.status != "active":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot crawl collection with status '{collection.status}'"
            )

        # Create crawl run record
        run = await crawl_service.start_crawl(
            session=session,
            collection_id=UUID(collection_id),
            user_id=current_user.id,
        )

        # Queue Celery task
        from app.core.tasks import scrape_crawl_task

        max_pages = request.max_pages if request else None

        scrape_crawl_task.delay(
            collection_id=str(collection_id),
            organization_id=str(current_user.organization_id),
            run_id=str(run.id),
            user_id=str(current_user.id),
            max_pages=max_pages,
        )

        logger.info(f"Queued scrape crawl task for collection {collection_id}, run {run.id}")

        return CrawlCollectionResponse(
            run_id=str(run.id),
            collection_id=collection_id,
            status="pending",
            message="Crawl queued successfully"
        )


@router.get(
    "/collections/{collection_id}/crawl/status",
    response_model=CrawlStatusResponse,
    summary="Get crawl status",
    description="Get the status of the most recent crawl."
)
async def get_crawl_status(
    collection_id: str,
    current_user: User = Depends(get_current_user),
) -> CrawlStatusResponse:
    """
    Get status of the most recent crawl.

    Args:
        collection_id: Collection UUID
        current_user: Current authenticated user

    Returns:
        CrawlStatusResponse: Crawl status
    """
    async with database_service.get_session() as session:
        collection = await scrape_service.get_collection(session, UUID(collection_id))

        if not collection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Collection not found"
            )

        if collection.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Collection not found"
            )

        if not collection.last_crawl_run_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No crawl has been run for this collection"
            )

        run = await run_service.get_run(session, collection.last_crawl_run_id)

        if not run:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Crawl run not found"
            )

        return CrawlStatusResponse(
            run_id=str(run.id),
            status=run.status,
            progress=run.progress,
            results_summary=run.results_summary,
            error_message=run.error_message,
        )


# =========================================================================
# SOURCE ENDPOINTS
# =========================================================================


@router.get(
    "/collections/{collection_id}/sources",
    response_model=ScrapeSourceListResponse,
    summary="List sources",
    description="List URL sources for a collection."
)
async def list_sources(
    collection_id: str,
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    current_user: User = Depends(get_current_user),
) -> ScrapeSourceListResponse:
    """
    List sources for a collection.

    Args:
        collection_id: Collection UUID
        is_active: Filter by active status
        current_user: Current authenticated user

    Returns:
        ScrapeSourceListResponse: List of sources
    """
    async with database_service.get_session() as session:
        collection = await scrape_service.get_collection(session, UUID(collection_id))

        if not collection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Collection not found"
            )

        if collection.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Collection not found"
            )

        sources = await scrape_service.list_sources(
            session=session,
            collection_id=UUID(collection_id),
            is_active=is_active,
        )

        return ScrapeSourceListResponse(
            sources=[
                ScrapeSourceResponse(
                    id=str(s.id),
                    collection_id=str(s.collection_id),
                    url=s.url,
                    source_type=s.source_type,
                    is_active=s.is_active,
                    crawl_config=s.crawl_config,
                    last_crawl_at=s.last_crawl_at,
                    last_status=s.last_status,
                    discovered_pages=s.discovered_pages,
                    created_at=s.created_at,
                    updated_at=s.updated_at,
                )
                for s in sources
            ],
            total=len(sources),
        )


@router.post(
    "/collections/{collection_id}/sources",
    response_model=ScrapeSourceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add source",
    description="Add a URL source to the collection."
)
async def add_source(
    collection_id: str,
    request: ScrapeSourceCreateRequest,
    current_user: User = Depends(require_org_admin),
) -> ScrapeSourceResponse:
    """
    Add a source to a collection.

    Args:
        collection_id: Collection UUID
        request: Source creation details
        current_user: Current user (must be org_admin)

    Returns:
        ScrapeSourceResponse: Created source
    """
    logger.info(f"Source creation requested for collection {collection_id} by {current_user.email}")

    async with database_service.get_session() as session:
        collection = await scrape_service.get_collection(session, UUID(collection_id))

        if not collection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Collection not found"
            )

        if collection.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Collection not found"
            )

        source = await scrape_service.add_source(
            session=session,
            organization_id=current_user.organization_id,
            collection_id=UUID(collection_id),
            url=request.url,
            source_type=request.source_type,
            crawl_config=request.crawl_config,
        )

        logger.info(f"Source added: {source.url} (id: {source.id})")

        return ScrapeSourceResponse(
            id=str(source.id),
            collection_id=str(source.collection_id),
            url=source.url,
            source_type=source.source_type,
            is_active=source.is_active,
            crawl_config=source.crawl_config,
            last_crawl_at=source.last_crawl_at,
            last_status=source.last_status,
            discovered_pages=source.discovered_pages,
            created_at=source.created_at,
            updated_at=source.updated_at,
        )


@router.delete(
    "/collections/{collection_id}/sources/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete source",
    description="Delete a URL source from the collection."
)
async def delete_source(
    collection_id: str,
    source_id: str,
    current_user: User = Depends(require_org_admin),
) -> None:
    """
    Delete a source from a collection.

    Args:
        collection_id: Collection UUID
        source_id: Source UUID
        current_user: Current user (must be org_admin)
    """
    logger.info(f"Source deletion requested for {source_id} by {current_user.email}")

    async with database_service.get_session() as session:
        collection = await scrape_service.get_collection(session, UUID(collection_id))

        if not collection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Collection not found"
            )

        if collection.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Collection not found"
            )

        source = await scrape_service.get_source(session, UUID(source_id))

        if not source or str(source.collection_id) != collection_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Source not found"
            )

        await scrape_service.delete_source(session, UUID(source_id))

        logger.info(f"Source deleted: {source_id}")


# =========================================================================
# SCRAPED ASSET ENDPOINTS
# =========================================================================


@router.get(
    "/collections/{collection_id}/assets",
    response_model=ScrapedAssetListResponse,
    summary="List scraped assets",
    description="List scraped assets in a collection."
)
async def list_scraped_assets(
    collection_id: str,
    asset_subtype: Optional[str] = Query(None, description="Filter by type: page or record"),
    url_path_prefix: Optional[str] = Query(None, description="Filter by URL path prefix"),
    is_promoted: Optional[bool] = Query(None, description="Filter by promotion status"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    current_user: User = Depends(get_current_user),
) -> ScrapedAssetListResponse:
    """
    List scraped assets in a collection.

    Args:
        collection_id: Collection UUID
        asset_subtype: Filter by page or record
        url_path_prefix: Filter by path prefix
        is_promoted: Filter by promotion status
        limit: Maximum results
        offset: Pagination offset
        current_user: Current authenticated user

    Returns:
        ScrapedAssetListResponse: Paginated list of scraped assets
    """
    async with database_service.get_session() as session:
        collection = await scrape_service.get_collection(session, UUID(collection_id))

        if not collection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Collection not found"
            )

        if collection.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Collection not found"
            )

        assets, total = await scrape_service.list_scraped_assets(
            session=session,
            collection_id=UUID(collection_id),
            asset_subtype=asset_subtype,
            url_path_prefix=url_path_prefix,
            is_promoted=is_promoted,
            limit=limit,
            offset=offset,
        )

        return ScrapedAssetListResponse(
            assets=[_scraped_asset_to_response(a) for a in assets],
            total=total,
            limit=limit,
            offset=offset,
        )


@router.get(
    "/collections/{collection_id}/assets/{scraped_asset_id}",
    response_model=ScrapedAssetResponse,
    summary="Get scraped asset",
    description="Get details of a specific scraped asset."
)
async def get_scraped_asset(
    collection_id: str,
    scraped_asset_id: str,
    current_user: User = Depends(get_current_user),
) -> ScrapedAssetResponse:
    """
    Get scraped asset details.

    Args:
        collection_id: Collection UUID
        scraped_asset_id: ScrapedAsset UUID
        current_user: Current authenticated user

    Returns:
        ScrapedAssetResponse: Scraped asset details
    """
    async with database_service.get_session() as session:
        collection = await scrape_service.get_collection(session, UUID(collection_id))

        if not collection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Collection not found"
            )

        if collection.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Collection not found"
            )

        scraped = await scrape_service.get_scraped_asset(session, UUID(scraped_asset_id))

        if not scraped or str(scraped.collection_id) != collection_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Scraped asset not found"
            )

        return _scraped_asset_to_response(scraped)


@router.get(
    "/collections/{collection_id}/assets/{scraped_asset_id}/content",
    response_class=PlainTextResponse,
    summary="Get scraped asset content",
    description="Get the extracted markdown content for a scraped asset."
)
async def get_scraped_asset_content(
    collection_id: str,
    scraped_asset_id: str,
    current_user: User = Depends(get_current_user),
) -> PlainTextResponse:
    """
    Get extracted markdown content for a scraped asset.

    Args:
        collection_id: Collection UUID
        scraped_asset_id: ScrapedAsset UUID
        current_user: Current authenticated user

    Returns:
        PlainTextResponse: Markdown content
    """
    async with database_service.get_session() as session:
        collection = await scrape_service.get_collection(session, UUID(collection_id))

        if not collection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Collection not found"
            )

        if collection.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Collection not found"
            )

        scraped = await scrape_service.get_scraped_asset(session, UUID(scraped_asset_id))

        if not scraped or str(scraped.collection_id) != collection_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Scraped asset not found"
            )

        # Get the associated asset's extraction result
        extraction = await extraction_result_service.get_latest_extraction_for_asset(
            session, scraped.asset_id
        )

        if not extraction:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No extraction result found for this asset"
            )

        if extraction.status != "completed":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Extraction not completed (status: {extraction.status})"
            )

        if not extraction.extracted_bucket or not extraction.extracted_object_key:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No extracted content available"
            )

        # Fetch content from MinIO
        try:
            minio_svc = get_minio_service()
            content_bytes = minio_svc.get_object(
                extraction.extracted_bucket,
                extraction.extracted_object_key
            )
            content = content_bytes.read().decode("utf-8")
            return PlainTextResponse(content=content, media_type="text/markdown")
        except Exception as e:
            logger.error(f"Failed to fetch content from MinIO: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve content"
            )


@router.post(
    "/collections/{collection_id}/assets/{scraped_asset_id}/promote",
    response_model=PromoteToRecordResponse,
    summary="Promote to record",
    description="Promote a page to a durable record (never auto-deleted)."
)
async def promote_to_record(
    collection_id: str,
    scraped_asset_id: str,
    current_user: User = Depends(get_current_user),
) -> PromoteToRecordResponse:
    """
    Promote a page to a durable record.

    Records are never auto-deleted, even if the source page disappears.

    Args:
        collection_id: Collection UUID
        scraped_asset_id: ScrapedAsset UUID
        current_user: Current authenticated user

    Returns:
        PromoteToRecordResponse: Updated scraped asset
    """
    logger.info(f"Promotion requested for {scraped_asset_id} by {current_user.email}")

    async with database_service.get_session() as session:
        collection = await scrape_service.get_collection(session, UUID(collection_id))

        if not collection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Collection not found"
            )

        if collection.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Collection not found"
            )

        scraped = await scrape_service.get_scraped_asset(session, UUID(scraped_asset_id))

        if not scraped or str(scraped.collection_id) != collection_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Scraped asset not found"
            )

        if scraped.asset_subtype == "record":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Asset is already a record"
            )

        promoted = await scrape_service.promote_to_record(
            session=session,
            scraped_asset_id=UUID(scraped_asset_id),
            user_id=current_user.id,
        )

        logger.info(f"Scraped asset promoted to record: {scraped_asset_id}")

        return PromoteToRecordResponse(
            scraped_asset=_scraped_asset_to_response(promoted),
            message="Successfully promoted to record"
        )


# =========================================================================
# TREE BROWSING ENDPOINTS
# =========================================================================


@router.get(
    "/collections/{collection_id}/tree",
    response_model=PathTreeResponse,
    summary="Get path tree",
    description="Get hierarchical tree structure for browsing scraped content."
)
async def get_path_tree(
    collection_id: str,
    path_prefix: str = Query("/", description="Parent path to list children from"),
    current_user: User = Depends(get_current_user),
) -> PathTreeResponse:
    """
    Get hierarchical tree structure for browsing.

    Args:
        collection_id: Collection UUID
        path_prefix: Parent path to list children from
        current_user: Current authenticated user

    Returns:
        PathTreeResponse: Tree nodes at the specified path
    """
    async with database_service.get_session() as session:
        collection = await scrape_service.get_collection(session, UUID(collection_id))

        if not collection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Collection not found"
            )

        if collection.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Collection not found"
            )

        nodes = await scrape_service.get_path_tree(
            session=session,
            collection_id=UUID(collection_id),
            path_prefix=path_prefix,
        )

        return PathTreeResponse(
            path_prefix=path_prefix,
            nodes=[PathTreeNode(**n) for n in nodes],
        )
