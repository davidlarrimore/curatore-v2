"""
Search Collection Service for managing named search collections.

Provides CRUD operations for SearchCollection and CollectionVectorSync models.
Collections group indexed content into logical sets that can be queried
independently and optionally synced to external vector stores.

Collection Types:
    - static: Manually curated sets of assets
    - dynamic: Query-based collections that auto-populate via saved filters
    - source_bound: Automatically linked to a data source (scrape, SharePoint, etc.)

Usage:
    from app.core.search.collection_service import collection_service

    # Create a collection
    coll = await collection_service.create_collection(
        session=session,
        organization_id=org_id,
        name="Federal Procurement Docs",
        collection_type="static",
    )

    # List collections
    collections = await collection_service.list_collections(
        session=session,
        organization_id=org_id,
    )
"""

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import and_, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database.models import (
    CollectionVectorSync,
    SearchCollection,
)

logger = logging.getLogger("curatore.search.collections")


def slugify(name: str) -> str:
    """Convert name to URL-friendly slug."""
    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[-\s]+", "-", slug)
    return slug[:255]


class SearchCollectionService:
    """Service for managing search collections and vector sync targets."""

    # =========================================================================
    # COLLECTION CRUD
    # =========================================================================

    async def create_collection(
        self,
        session: AsyncSession,
        organization_id: UUID,
        name: str,
        collection_type: str = "static",
        description: Optional[str] = None,
        query_config: Optional[Dict[str, Any]] = None,
        source_type: Optional[str] = None,
        source_id: Optional[UUID] = None,
        created_by: Optional[UUID] = None,
    ) -> SearchCollection:
        """Create a new search collection."""
        slug = slugify(name)

        # Ensure slug uniqueness within org
        existing = await session.execute(
            select(SearchCollection).where(
                and_(
                    SearchCollection.organization_id == organization_id,
                    SearchCollection.slug == slug,
                )
            )
        )
        if existing.scalar_one_or_none():
            # Append a suffix to make it unique
            count_result = await session.execute(
                select(func.count()).select_from(SearchCollection).where(
                    and_(
                        SearchCollection.organization_id == organization_id,
                        SearchCollection.slug.like(f"{slug}%"),
                    )
                )
            )
            count = count_result.scalar() or 0
            slug = f"{slug}-{count + 1}"

        collection = SearchCollection(
            organization_id=organization_id,
            name=name,
            slug=slug,
            description=description,
            collection_type=collection_type,
            query_config=query_config,
            source_type=source_type,
            source_id=source_id,
            created_by=created_by,
        )
        session.add(collection)
        await session.flush()
        logger.info(
            "Created search collection '%s' (slug=%s, type=%s) for org %s",
            name, slug, collection_type, organization_id,
        )
        return collection

    async def get_collection(
        self,
        session: AsyncSession,
        collection_id: UUID,
        organization_id: Optional[UUID] = None,
    ) -> Optional[SearchCollection]:
        """Get a collection by ID, optionally scoped to an organization."""
        query = select(SearchCollection).where(SearchCollection.id == collection_id)
        if organization_id:
            query = query.where(SearchCollection.organization_id == organization_id)
        result = await session.execute(query.options(selectinload(SearchCollection.vector_syncs)))
        return result.scalar_one_or_none()

    async def get_collection_by_slug(
        self,
        session: AsyncSession,
        organization_id: UUID,
        slug: str,
    ) -> Optional[SearchCollection]:
        """Get a collection by slug within an organization."""
        result = await session.execute(
            select(SearchCollection)
            .where(
                and_(
                    SearchCollection.organization_id == organization_id,
                    SearchCollection.slug == slug,
                )
            )
            .options(selectinload(SearchCollection.vector_syncs))
        )
        return result.scalar_one_or_none()

    async def list_collections(
        self,
        session: AsyncSession,
        organization_id: UUID,
        collection_type: Optional[str] = None,
        is_active: Optional[bool] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[SearchCollection], int]:
        """List collections with optional filtering. Returns (collections, total_count)."""
        filters = [SearchCollection.organization_id == organization_id]
        if collection_type:
            filters.append(SearchCollection.collection_type == collection_type)
        if is_active is not None:
            filters.append(SearchCollection.is_active == is_active)

        # Get total count
        count_query = select(func.count()).select_from(SearchCollection).where(and_(*filters))
        total = (await session.execute(count_query)).scalar() or 0

        # Get page
        query = (
            select(SearchCollection)
            .where(and_(*filters))
            .options(selectinload(SearchCollection.vector_syncs))
            .order_by(SearchCollection.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(query)
        collections = list(result.scalars().all())

        return collections, total

    async def update_collection(
        self,
        session: AsyncSession,
        collection_id: UUID,
        organization_id: UUID,
        **kwargs,
    ) -> Optional[SearchCollection]:
        """Update a collection. Only provided fields are updated."""
        collection = await self.get_collection(session, collection_id, organization_id)
        if not collection:
            return None

        allowed_fields = {
            "name", "description", "collection_type", "query_config",
            "source_type", "source_id", "is_active",
        }
        for key, value in kwargs.items():
            if key in allowed_fields and value is not None:
                setattr(collection, key, value)

        # Re-slug if name changed
        if "name" in kwargs and kwargs["name"]:
            collection.slug = slugify(kwargs["name"])

        collection.updated_at = datetime.utcnow()
        await session.flush()
        return collection

    async def delete_collection(
        self,
        session: AsyncSession,
        collection_id: UUID,
        organization_id: UUID,
    ) -> bool:
        """Delete a collection and its vector syncs (cascading)."""
        collection = await self.get_collection(session, collection_id, organization_id)
        if not collection:
            return False

        await session.delete(collection)
        await session.flush()
        logger.info("Deleted search collection %s", collection_id)
        return True

    async def get_collection_for_source(
        self,
        session: AsyncSession,
        organization_id: UUID,
        source_type: str,
        source_id: UUID,
    ) -> Optional[SearchCollection]:
        """Find a source_bound collection for a given source."""
        result = await session.execute(
            select(SearchCollection).where(
                and_(
                    SearchCollection.organization_id == organization_id,
                    SearchCollection.source_type == source_type,
                    SearchCollection.source_id == source_id,
                    SearchCollection.collection_type == "source_bound",
                )
            )
        )
        return result.scalar_one_or_none()

    async def update_item_count(
        self,
        session: AsyncSession,
        collection_id: UUID,
    ) -> int:
        """Recount chunks in a collection and update item_count. Returns new count."""
        result = await session.execute(
            text(
                "SELECT COUNT(*) FROM collection_chunks WHERE collection_id = :cid"
            ),
            {"cid": str(collection_id)},
        )
        count = result.scalar() or 0

        collection = await session.get(SearchCollection, collection_id)
        if collection:
            collection.item_count = count
            collection.updated_at = datetime.utcnow()
            await session.flush()

        return count

    # =========================================================================
    # VECTOR SYNC OPERATIONS
    # =========================================================================

    async def add_vector_sync(
        self,
        session: AsyncSession,
        collection_id: UUID,
        connection_id: UUID,
        sync_config: Optional[Dict[str, Any]] = None,
    ) -> CollectionVectorSync:
        """Add a vector store sync target to a collection."""
        sync = CollectionVectorSync(
            collection_id=collection_id,
            connection_id=connection_id,
            sync_config=sync_config or {},
        )
        session.add(sync)
        await session.flush()
        logger.info(
            "Added vector sync: collection=%s -> connection=%s",
            collection_id, connection_id,
        )
        return sync

    async def list_vector_syncs(
        self,
        session: AsyncSession,
        collection_id: UUID,
    ) -> List[CollectionVectorSync]:
        """List all vector sync targets for a collection."""
        result = await session.execute(
            select(CollectionVectorSync)
            .where(CollectionVectorSync.collection_id == collection_id)
            .order_by(CollectionVectorSync.created_at)
        )
        return list(result.scalars().all())

    async def remove_vector_sync(
        self,
        session: AsyncSession,
        sync_id: UUID,
    ) -> bool:
        """Remove a vector sync target."""
        sync = await session.get(CollectionVectorSync, sync_id)
        if not sync:
            return False
        await session.delete(sync)
        await session.flush()
        logger.info("Removed vector sync %s", sync_id)
        return True


# Module-level singleton
collection_service = SearchCollectionService()
