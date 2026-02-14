"""
Search Collections API Router.

Provides endpoints for managing named search collections and their
external vector store sync targets.

Endpoints:
    GET    /collections              - List search collections
    POST   /collections              - Create collection
    GET    /collections/{id}         - Get collection details
    PUT    /collections/{id}         - Update collection
    DELETE /collections/{id}         - Delete collection

    GET    /collections/{id}/syncs   - List vector sync targets
    POST   /collections/{id}/syncs   - Add vector sync target
    DELETE /collections/{id}/syncs/{sync_id} - Remove vector sync target

Security:
    - All endpoints require authentication
    - Collections are organization-scoped
    - Only org_admin can create/delete collections
"""

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.v1.data.schemas import (
    CollectionClearResponse,
    CollectionPopulateFreshRequest,
    CollectionPopulateFreshResponse,
    CollectionPopulateRequest,
    CollectionPopulateResponse,
    CollectionRemoveAssetsRequest,
    CollectionRemoveAssetsResponse,
    SearchCollectionCreateRequest,
    SearchCollectionListResponse,
    SearchCollectionResponse,
    SearchCollectionUpdateRequest,
    VectorSyncCreateRequest,
    VectorSyncResponse,
)
from app.core.database.models import SearchCollection, User
from app.core.search.collection_service import collection_service
from app.core.shared.database_service import database_service
from app.dependencies import get_current_org_id, get_current_user, require_org_admin_or_above

router = APIRouter(prefix="/collections", tags=["Search Collections"])

logger = logging.getLogger("curatore.api.collections")


# =========================================================================
# HELPERS
# =========================================================================


def _collection_to_response(collection: SearchCollection) -> SearchCollectionResponse:
    """Convert SearchCollection ORM model to response."""
    vector_syncs = None
    if hasattr(collection, "vector_syncs") and collection.vector_syncs:
        vector_syncs = [
            {
                "id": str(s.id),
                "connection_id": str(s.connection_id),
                "is_enabled": s.is_enabled,
                "sync_status": s.sync_status,
                "last_sync_at": s.last_sync_at.isoformat() if s.last_sync_at else None,
                "chunks_synced": s.chunks_synced,
            }
            for s in collection.vector_syncs
        ]

    return SearchCollectionResponse(
        id=str(collection.id),
        organization_id=str(collection.organization_id),
        name=collection.name,
        slug=collection.slug,
        description=collection.description,
        collection_type=collection.collection_type,
        query_config=collection.query_config,
        source_type=collection.source_type,
        source_id=str(collection.source_id) if collection.source_id else None,
        is_active=collection.is_active,
        item_count=collection.item_count,
        last_synced_at=collection.last_synced_at,
        vector_syncs=vector_syncs,
        created_at=collection.created_at,
        updated_at=collection.updated_at,
        created_by=str(collection.created_by) if collection.created_by else None,
    )


# =========================================================================
# COLLECTION ENDPOINTS
# =========================================================================


@router.get("", response_model=SearchCollectionListResponse)
async def list_collections(
    collection_type: Optional[str] = Query(None, description="Filter by type: static, dynamic, source_bound"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    org_id: UUID = Depends(get_current_org_id),
):
    """List search collections for the current organization."""
    async with database_service.get_session() as session:
        collections, total = await collection_service.list_collections(
            session=session,
            organization_id=org_id,
            collection_type=collection_type,
            is_active=is_active,
            limit=limit,
            offset=offset,
        )
        return SearchCollectionListResponse(
            collections=[_collection_to_response(c) for c in collections],
            total=total,
            limit=limit,
            offset=offset,
        )


@router.post("", response_model=SearchCollectionResponse, status_code=status.HTTP_201_CREATED)
async def create_collection(
    request: SearchCollectionCreateRequest,
    org_id: UUID = Depends(get_current_org_id),
    current_user: User = Depends(require_org_admin_or_above),
):
    """Create a new search collection."""
    async with database_service.get_session() as session:
        source_id = UUID(request.source_id) if request.source_id else None

        collection = await collection_service.create_collection(
            session=session,
            organization_id=org_id,
            name=request.name,
            description=request.description,
            collection_type=request.collection_type,
            query_config=request.query_config,
            source_type=request.source_type,
            source_id=source_id,
            created_by=current_user.id,
        )
        await session.commit()
        return _collection_to_response(collection)


@router.get("/{collection_id}", response_model=SearchCollectionResponse)
async def get_collection(
    collection_id: UUID,
    org_id: UUID = Depends(get_current_org_id),
):
    """Get a search collection by ID."""
    async with database_service.get_session() as session:
        collection = await collection_service.get_collection(
            session=session,
            collection_id=collection_id,
            organization_id=org_id,
        )
        if not collection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Collection {collection_id} not found",
            )
        return _collection_to_response(collection)


@router.put("/{collection_id}", response_model=SearchCollectionResponse)
async def update_collection(
    collection_id: UUID,
    request: SearchCollectionUpdateRequest,
    org_id: UUID = Depends(get_current_org_id),
    current_user: User = Depends(require_org_admin_or_above),
):
    """Update a search collection."""
    async with database_service.get_session() as session:
        update_data = request.model_dump(exclude_unset=True)
        if "source_id" in update_data and update_data["source_id"]:
            update_data["source_id"] = UUID(update_data["source_id"])

        collection = await collection_service.update_collection(
            session=session,
            collection_id=collection_id,
            organization_id=org_id,
            **update_data,
        )
        if not collection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Collection {collection_id} not found",
            )
        await session.commit()
        return _collection_to_response(collection)


@router.delete("/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_collection(
    collection_id: UUID,
    org_id: UUID = Depends(get_current_org_id),
    current_user: User = Depends(require_org_admin_or_above),
):
    """Delete a search collection and its vector sync targets."""
    async with database_service.get_session() as session:
        deleted = await collection_service.delete_collection(
            session=session,
            collection_id=collection_id,
            organization_id=org_id,
        )
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Collection {collection_id} not found",
            )
        await session.commit()


# =========================================================================
# POPULATION ENDPOINTS
# =========================================================================


@router.post(
    "/{collection_id}/populate",
    response_model=CollectionPopulateResponse,
)
async def populate_collection(
    collection_id: UUID,
    request: CollectionPopulateRequest,
    org_id: UUID = Depends(get_current_org_id),
    current_user: User = Depends(require_org_admin_or_above),
):
    """
    Populate a collection by copying chunks from the core index.

    Fast path: reuses existing embeddings from search_chunks.
    """
    async with database_service.get_session() as session:
        collection = await collection_service.get_collection(
            session=session,
            collection_id=collection_id,
            organization_id=org_id,
        )
        if not collection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Collection {collection_id} not found",
            )

        from app.core.search.collection_population_service import (
            collection_population_service,
        )

        result = await collection_population_service.populate_from_index(
            session=session,
            collection_id=collection_id,
            organization_id=org_id,
            asset_ids=[UUID(a) for a in request.asset_ids],
        )
        await session.commit()
        return CollectionPopulateResponse(
            added=result.added,
            skipped=result.skipped,
            total=result.total,
        )


@router.post(
    "/{collection_id}/populate/fresh",
    response_model=CollectionPopulateFreshResponse,
)
async def populate_collection_fresh(
    collection_id: UUID,
    request: CollectionPopulateFreshRequest,
    org_id: UUID = Depends(get_current_org_id),
    current_user: User = Depends(require_org_admin_or_above),
):
    """
    Populate a collection with fresh chunking and embeddings.

    Async: dispatches a Celery task. Returns a run_id for tracking.
    """
    async with database_service.get_session() as session:
        collection = await collection_service.get_collection(
            session=session,
            collection_id=collection_id,
            organization_id=org_id,
        )
        if not collection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Collection {collection_id} not found",
            )

        from app.core.search.collection_population_service import (
            collection_population_service,
        )

        run_id = await collection_population_service.populate_fresh(
            session=session,
            collection_id=collection_id,
            organization_id=org_id,
            asset_ids=[UUID(a) for a in request.asset_ids],
            chunk_size=request.chunk_size,
            chunk_overlap=request.chunk_overlap,
        )
        await session.commit()
        return CollectionPopulateFreshResponse(
            run_id=run_id,
            message=f"Fresh population started for {len(request.asset_ids)} assets",
        )


@router.delete(
    "/{collection_id}/assets",
    response_model=CollectionRemoveAssetsResponse,
)
async def remove_assets_from_collection(
    collection_id: UUID,
    request: CollectionRemoveAssetsRequest,
    org_id: UUID = Depends(get_current_org_id),
    current_user: User = Depends(require_org_admin_or_above),
):
    """Remove specific assets' chunks from a collection."""
    async with database_service.get_session() as session:
        collection = await collection_service.get_collection(
            session=session,
            collection_id=collection_id,
            organization_id=org_id,
        )
        if not collection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Collection {collection_id} not found",
            )

        from app.core.search.collection_population_service import (
            collection_population_service,
        )

        removed = await collection_population_service.remove_assets(
            session=session,
            collection_id=collection_id,
            organization_id=org_id,
            asset_ids=[UUID(a) for a in request.asset_ids],
        )
        await session.commit()
        return CollectionRemoveAssetsResponse(removed=removed)


@router.post(
    "/{collection_id}/clear",
    response_model=CollectionClearResponse,
)
async def clear_collection(
    collection_id: UUID,
    org_id: UUID = Depends(get_current_org_id),
    current_user: User = Depends(require_org_admin_or_above),
):
    """Remove all chunks from a collection."""
    async with database_service.get_session() as session:
        collection = await collection_service.get_collection(
            session=session,
            collection_id=collection_id,
            organization_id=org_id,
        )
        if not collection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Collection {collection_id} not found",
            )

        from app.core.search.collection_population_service import (
            collection_population_service,
        )

        removed = await collection_population_service.clear_collection(
            session=session,
            collection_id=collection_id,
            organization_id=org_id,
        )
        await session.commit()
        return CollectionClearResponse(removed=removed)


# =========================================================================
# VECTOR SYNC ENDPOINTS
# =========================================================================


@router.get("/{collection_id}/syncs", response_model=List[VectorSyncResponse])
async def list_vector_syncs(
    collection_id: UUID,
    org_id: UUID = Depends(get_current_org_id),
):
    """List external vector store sync targets for a collection."""
    async with database_service.get_session() as session:
        # Verify collection exists and belongs to org
        collection = await collection_service.get_collection(
            session=session,
            collection_id=collection_id,
            organization_id=org_id,
        )
        if not collection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Collection {collection_id} not found",
            )

        syncs = await collection_service.list_vector_syncs(
            session=session,
            collection_id=collection_id,
        )
        return [
            VectorSyncResponse(
                id=str(s.id),
                collection_id=str(s.collection_id),
                connection_id=str(s.connection_id),
                is_enabled=s.is_enabled,
                sync_status=s.sync_status,
                last_sync_at=s.last_sync_at,
                error_message=s.error_message,
                chunks_synced=s.chunks_synced,
                sync_config=s.sync_config,
                created_at=s.created_at,
                updated_at=s.updated_at,
            )
            for s in syncs
        ]


@router.post(
    "/{collection_id}/syncs",
    response_model=VectorSyncResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_vector_sync(
    collection_id: UUID,
    request: VectorSyncCreateRequest,
    org_id: UUID = Depends(get_current_org_id),
    current_user: User = Depends(require_org_admin_or_above),
):
    """Add an external vector store sync target to a collection."""
    async with database_service.get_session() as session:
        # Verify collection exists
        collection = await collection_service.get_collection(
            session=session,
            collection_id=collection_id,
            organization_id=org_id,
        )
        if not collection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Collection {collection_id} not found",
            )

        sync = await collection_service.add_vector_sync(
            session=session,
            collection_id=collection_id,
            connection_id=UUID(request.connection_id),
            sync_config=request.sync_config,
        )
        await session.commit()
        return VectorSyncResponse(
            id=str(sync.id),
            collection_id=str(sync.collection_id),
            connection_id=str(sync.connection_id),
            is_enabled=sync.is_enabled,
            sync_status=sync.sync_status,
            last_sync_at=sync.last_sync_at,
            error_message=sync.error_message,
            chunks_synced=sync.chunks_synced,
            sync_config=sync.sync_config,
            created_at=sync.created_at,
            updated_at=sync.updated_at,
        )


@router.delete(
    "/{collection_id}/syncs/{sync_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_vector_sync(
    collection_id: UUID,
    sync_id: UUID,
    org_id: UUID = Depends(get_current_org_id),
    current_user: User = Depends(require_org_admin_or_above),
):
    """Remove an external vector store sync target."""
    async with database_service.get_session() as session:
        # Verify collection exists
        collection = await collection_service.get_collection(
            session=session,
            collection_id=collection_id,
            organization_id=org_id,
        )
        if not collection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Collection {collection_id} not found",
            )

        deleted = await collection_service.remove_vector_sync(
            session=session,
            sync_id=sync_id,
        )
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Vector sync {sync_id} not found",
            )
        await session.commit()
