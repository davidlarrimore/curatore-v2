"""
Scrape Service for Web Scraping Collection Management.

Provides CRUD operations and management for ScrapeCollection, ScrapeSource,
and ScrapedAsset models. This is the core service for Phase 4: Web Scraping
as Durable Data Source.

Key Features:
- Create and manage scrape collections with modes (snapshot/record_preserving)
- Manage URL sources within collections
- Track scraped assets with page/record distinction
- Promote pages to durable records
- Hierarchical path utilities for tree browsing
- Collection statistics and health

Usage:
    from app.connectors.scrape.scrape_service import scrape_service

    # Create a collection
    collection = await scrape_service.create_collection(
        session=session,
        organization_id=org_id,
        name="SAM.gov Opportunities",
        root_url="https://sam.gov/search",
        collection_mode="record_preserving",
    )

    # Add a source
    source = await scrape_service.add_source(
        session=session,
        collection_id=collection.id,
        url="https://sam.gov/search?status=active",
    )

    # Promote a page to record
    await scrape_service.promote_to_record(
        session=session,
        scraped_asset_id=asset.id,
        user_id=user.id,
    )
"""

import logging
import re
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import select, and_, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database.models import (
    ScrapeCollection,
    ScrapeSource,
    ScrapedAsset,
    Asset,
    Run,
)

logger = logging.getLogger("curatore.scrape_service")


def slugify(text: str) -> str:
    """Convert text to URL-friendly slug."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '-', text)
    return text[:255]


def extract_url_path(url: str) -> str:
    """Extract the path component from a URL for hierarchical browsing."""
    parsed = urlparse(url)
    path = parsed.path or "/"
    # Normalize path
    if not path.startswith("/"):
        path = "/" + path
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    return path


class ScrapeService:
    """
    Service for managing scrape collections and related operations.

    Handles CRUD operations for collections, sources, and scraped assets,
    as well as promotion mechanics and hierarchical path utilities.
    """

    # =========================================================================
    # COLLECTION OPERATIONS
    # =========================================================================

    async def create_collection(
        self,
        session: AsyncSession,
        organization_id: UUID,
        name: str,
        root_url: str,
        collection_mode: str = "record_preserving",
        description: Optional[str] = None,
        url_patterns: Optional[List[Dict[str, str]]] = None,
        crawl_config: Optional[Dict[str, Any]] = None,
        created_by: Optional[UUID] = None,
    ) -> ScrapeCollection:
        """
        Create a new scrape collection.

        Args:
            session: Database session
            organization_id: Organization UUID
            name: Collection name
            root_url: Primary URL for this collection
            collection_mode: snapshot or record_preserving
            description: Optional description
            url_patterns: URL include/exclude patterns
            crawl_config: Crawl configuration
            created_by: User who created the collection

        Returns:
            Created ScrapeCollection instance
        """
        slug = slugify(name)

        # Ensure slug is unique within org
        existing = await session.execute(
            select(ScrapeCollection).where(
                and_(
                    ScrapeCollection.organization_id == organization_id,
                    ScrapeCollection.slug == slug,
                )
            )
        )
        if existing.scalar_one_or_none():
            # Append timestamp to make unique
            slug = f"{slug}-{int(datetime.utcnow().timestamp())}"

        collection = ScrapeCollection(
            organization_id=organization_id,
            name=name,
            slug=slug,
            description=description,
            collection_mode=collection_mode,
            root_url=root_url,
            url_patterns=url_patterns or [],
            crawl_config=crawl_config or {},
            created_by=created_by,
        )

        session.add(collection)
        await session.flush()  # Get the collection ID

        # Auto-create a seed source from root_url
        # This eliminates the need for manual source management
        source = ScrapeSource(
            organization_id=organization_id,
            collection_id=collection.id,
            url=root_url,
            source_type="seed",
            crawl_config=None,
        )
        session.add(source)

        await session.commit()
        await session.refresh(collection)

        logger.info(f"Created scrape collection {collection.id}: {name} (auto-added root_url as seed source)")

        return collection

    async def get_collection(
        self,
        session: AsyncSession,
        collection_id: UUID,
    ) -> Optional[ScrapeCollection]:
        """Get collection by ID."""
        result = await session.execute(
            select(ScrapeCollection)
            .options(selectinload(ScrapeCollection.sources))
            .where(ScrapeCollection.id == collection_id)
        )
        return result.scalar_one_or_none()

    async def get_collection_by_slug(
        self,
        session: AsyncSession,
        organization_id: UUID,
        slug: str,
    ) -> Optional[ScrapeCollection]:
        """Get collection by slug within organization."""
        result = await session.execute(
            select(ScrapeCollection)
            .options(selectinload(ScrapeCollection.sources))
            .where(
                and_(
                    ScrapeCollection.organization_id == organization_id,
                    ScrapeCollection.slug == slug,
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_collections(
        self,
        session: AsyncSession,
        organization_id: UUID,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[ScrapeCollection], int]:
        """
        List collections for an organization.

        Returns:
            Tuple of (collections list, total count)
        """
        query = select(ScrapeCollection).where(
            ScrapeCollection.organization_id == organization_id
        )

        if status:
            query = query.where(ScrapeCollection.status == status)

        # Get total count
        count_query = select(func.count(ScrapeCollection.id)).where(
            ScrapeCollection.organization_id == organization_id
        )
        if status:
            count_query = count_query.where(ScrapeCollection.status == status)

        count_result = await session.execute(count_query)
        total = count_result.scalar_one()

        # Get paginated results
        query = query.order_by(ScrapeCollection.created_at.desc())
        query = query.limit(limit).offset(offset)

        result = await session.execute(query)
        collections = list(result.scalars().all())

        return collections, total

    async def update_collection(
        self,
        session: AsyncSession,
        collection_id: UUID,
        name: Optional[str] = None,
        description: Optional[str] = None,
        collection_mode: Optional[str] = None,
        url_patterns: Optional[List[Dict[str, str]]] = None,
        crawl_config: Optional[Dict[str, Any]] = None,
        status: Optional[str] = None,
    ) -> Optional[ScrapeCollection]:
        """Update collection properties."""
        collection = await self.get_collection(session, collection_id)
        if not collection:
            return None

        if name is not None:
            collection.name = name
        if description is not None:
            collection.description = description
        if collection_mode is not None:
            collection.collection_mode = collection_mode
        if url_patterns is not None:
            collection.url_patterns = url_patterns
        if crawl_config is not None:
            collection.crawl_config = crawl_config
        if status is not None:
            collection.status = status

        await session.commit()
        await session.refresh(collection)

        logger.info(f"Updated collection {collection_id}")

        return collection

    async def delete_collection(
        self,
        session: AsyncSession,
        collection_id: UUID,
    ) -> bool:
        """Delete a collection (soft delete by setting status to archived)."""
        collection = await self.get_collection(session, collection_id)
        if not collection:
            return False

        collection.status = "archived"
        await session.commit()

        logger.info(f"Archived collection {collection_id}")

        return True

    async def update_collection_stats(
        self,
        session: AsyncSession,
        collection_id: UUID,
    ) -> Optional[ScrapeCollection]:
        """Update denormalized collection statistics."""
        collection = await self.get_collection(session, collection_id)
        if not collection:
            return None

        # Count pages, records, and documents
        page_count = await session.execute(
            select(func.count(ScrapedAsset.id)).where(
                and_(
                    ScrapedAsset.collection_id == collection_id,
                    ScrapedAsset.asset_subtype == "page",
                )
            )
        )
        record_count = await session.execute(
            select(func.count(ScrapedAsset.id)).where(
                and_(
                    ScrapedAsset.collection_id == collection_id,
                    ScrapedAsset.asset_subtype == "record",
                )
            )
        )
        document_count = await session.execute(
            select(func.count(ScrapedAsset.id)).where(
                and_(
                    ScrapedAsset.collection_id == collection_id,
                    ScrapedAsset.asset_subtype == "document",
                )
            )
        )
        promoted_count = await session.execute(
            select(func.count(ScrapedAsset.id)).where(
                and_(
                    ScrapedAsset.collection_id == collection_id,
                    ScrapedAsset.is_promoted == True,
                )
            )
        )

        collection.stats = {
            "page_count": page_count.scalar_one(),
            "record_count": record_count.scalar_one(),
            "document_count": document_count.scalar_one(),
            "promoted_count": promoted_count.scalar_one(),
            "last_updated": datetime.utcnow().isoformat(),
        }

        await session.commit()
        await session.refresh(collection)

        return collection

    # =========================================================================
    # SOURCE OPERATIONS
    # =========================================================================

    async def add_source(
        self,
        session: AsyncSession,
        organization_id: UUID,
        collection_id: UUID,
        url: str,
        source_type: str = "seed",
        crawl_config: Optional[Dict[str, Any]] = None,
    ) -> ScrapeSource:
        """Add a URL source to a collection."""
        source = ScrapeSource(
            organization_id=organization_id,
            collection_id=collection_id,
            url=url,
            source_type=source_type,
            crawl_config=crawl_config,
        )

        session.add(source)
        await session.commit()
        await session.refresh(source)

        logger.info(f"Added source {source.id} to collection {collection_id}: {url[:50]}...")

        return source

    async def get_source(
        self,
        session: AsyncSession,
        source_id: UUID,
    ) -> Optional[ScrapeSource]:
        """Get source by ID."""
        result = await session.execute(
            select(ScrapeSource).where(ScrapeSource.id == source_id)
        )
        return result.scalar_one_or_none()

    async def list_sources(
        self,
        session: AsyncSession,
        collection_id: UUID,
        is_active: Optional[bool] = None,
    ) -> List[ScrapeSource]:
        """List sources for a collection."""
        query = select(ScrapeSource).where(
            ScrapeSource.collection_id == collection_id
        )

        if is_active is not None:
            query = query.where(ScrapeSource.is_active == is_active)

        query = query.order_by(ScrapeSource.created_at)

        result = await session.execute(query)
        return list(result.scalars().all())

    async def update_source(
        self,
        session: AsyncSession,
        source_id: UUID,
        is_active: Optional[bool] = None,
        crawl_config: Optional[Dict[str, Any]] = None,
    ) -> Optional[ScrapeSource]:
        """Update source properties."""
        source = await self.get_source(session, source_id)
        if not source:
            return None

        if is_active is not None:
            source.is_active = is_active
        if crawl_config is not None:
            source.crawl_config = crawl_config

        await session.commit()
        await session.refresh(source)

        return source

    async def delete_source(
        self,
        session: AsyncSession,
        source_id: UUID,
    ) -> bool:
        """Delete a source."""
        source = await self.get_source(session, source_id)
        if not source:
            return False

        await session.delete(source)
        await session.commit()

        logger.info(f"Deleted source {source_id}")

        return True

    # =========================================================================
    # SCRAPED ASSET OPERATIONS
    # =========================================================================

    async def create_scraped_asset(
        self,
        session: AsyncSession,
        organization_id: UUID,
        asset_id: UUID,
        collection_id: UUID,
        url: str,
        asset_subtype: str = "page",
        source_id: Optional[UUID] = None,
        url_path: Optional[str] = None,
        parent_url: Optional[str] = None,
        crawl_depth: int = 0,
        crawl_run_id: Optional[UUID] = None,
        scrape_metadata: Optional[Dict[str, Any]] = None,
    ) -> ScrapedAsset:
        """
        Create a scraped asset record linking an asset to a collection.

        Args:
            organization_id: Organization UUID for multi-tenant isolation
            asset_id: Asset UUID
            collection_id: Collection UUID
            url: Original URL
            asset_subtype: page or record
            source_id: Optional source that discovered this
            url_path: Hierarchical path (auto-extracted if not provided)
            parent_url: URL of parent page
            crawl_depth: Depth from seed URL
            crawl_run_id: Run that discovered this
            scrape_metadata: Additional metadata

        Returns:
            Created ScrapedAsset instance
        """
        if url_path is None:
            url_path = extract_url_path(url)

        scraped = ScrapedAsset(
            organization_id=organization_id,
            asset_id=asset_id,
            collection_id=collection_id,
            source_id=source_id,
            asset_subtype=asset_subtype,
            url=url,
            url_path=url_path,
            parent_url=parent_url,
            crawl_depth=crawl_depth,
            crawl_run_id=crawl_run_id,
            scrape_metadata=scrape_metadata or {},
        )

        session.add(scraped)
        await session.commit()
        await session.refresh(scraped)

        logger.info(f"Created scraped asset {scraped.id} ({asset_subtype}) for {url[:50]}...")

        return scraped

    async def get_scraped_asset(
        self,
        session: AsyncSession,
        scraped_asset_id: UUID,
    ) -> Optional[ScrapedAsset]:
        """Get scraped asset by ID."""
        result = await session.execute(
            select(ScrapedAsset)
            .options(selectinload(ScrapedAsset.asset))
            .where(ScrapedAsset.id == scraped_asset_id)
        )
        return result.scalar_one_or_none()

    async def get_scraped_asset_by_url(
        self,
        session: AsyncSession,
        collection_id: UUID,
        url: str,
    ) -> Optional[ScrapedAsset]:
        """Get scraped asset by URL within a collection."""
        result = await session.execute(
            select(ScrapedAsset)
            .options(selectinload(ScrapedAsset.asset))
            .where(
                and_(
                    ScrapedAsset.collection_id == collection_id,
                    ScrapedAsset.url == url,
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_scraped_assets(
        self,
        session: AsyncSession,
        collection_id: UUID,
        asset_subtype: Optional[str] = None,
        url_path_prefix: Optional[str] = None,
        is_promoted: Optional[bool] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Tuple[List[ScrapedAsset], int]:
        """
        List scraped assets in a collection with filtering.

        Args:
            collection_id: Collection UUID
            asset_subtype: Filter by page or record
            url_path_prefix: Filter by path prefix (for tree browsing)
            is_promoted: Filter by promotion status
            limit: Max results
            offset: Results offset

        Returns:
            Tuple of (assets list, total count)
        """
        query = select(ScrapedAsset).where(
            ScrapedAsset.collection_id == collection_id
        )

        count_query = select(func.count(ScrapedAsset.id)).where(
            ScrapedAsset.collection_id == collection_id
        )

        if asset_subtype:
            query = query.where(ScrapedAsset.asset_subtype == asset_subtype)
            count_query = count_query.where(ScrapedAsset.asset_subtype == asset_subtype)

        if url_path_prefix:
            query = query.where(ScrapedAsset.url_path.startswith(url_path_prefix))
            count_query = count_query.where(ScrapedAsset.url_path.startswith(url_path_prefix))

        if is_promoted is not None:
            query = query.where(ScrapedAsset.is_promoted == is_promoted)
            count_query = count_query.where(ScrapedAsset.is_promoted == is_promoted)

        # Get total count
        count_result = await session.execute(count_query)
        total = count_result.scalar_one()

        # Get paginated results
        query = query.options(selectinload(ScrapedAsset.asset))
        query = query.order_by(ScrapedAsset.url_path, ScrapedAsset.created_at)
        query = query.limit(limit).offset(offset)

        result = await session.execute(query)
        assets = list(result.scalars().all())

        return assets, total

    async def promote_to_record(
        self,
        session: AsyncSession,
        scraped_asset_id: UUID,
        user_id: Optional[UUID] = None,
    ) -> Optional[ScrapedAsset]:
        """
        Promote a page to a durable record.

        Records are never auto-deleted, even if the source page disappears.

        Args:
            scraped_asset_id: ScrapedAsset UUID
            user_id: User performing the promotion

        Returns:
            Updated ScrapedAsset instance
        """
        scraped = await self.get_scraped_asset(session, scraped_asset_id)
        if not scraped:
            return None

        if scraped.asset_subtype == "record":
            return scraped  # Already a record

        scraped.asset_subtype = "record"
        scraped.is_promoted = True
        scraped.promoted_at = datetime.utcnow()
        scraped.promoted_by = user_id

        await session.commit()
        await session.refresh(scraped)

        logger.info(f"Promoted scraped asset {scraped_asset_id} to record")

        # Update collection stats
        await self.update_collection_stats(session, scraped.collection_id)

        return scraped

    async def demote_to_page(
        self,
        session: AsyncSession,
        scraped_asset_id: UUID,
    ) -> Optional[ScrapedAsset]:
        """
        Demote a record back to a page.

        This makes the asset eligible for garbage collection.
        """
        scraped = await self.get_scraped_asset(session, scraped_asset_id)
        if not scraped:
            return None

        if scraped.asset_subtype == "page":
            return scraped  # Already a page

        scraped.asset_subtype = "page"
        # Keep is_promoted=True to track history

        await session.commit()
        await session.refresh(scraped)

        logger.info(f"Demoted scraped asset {scraped_asset_id} to page")

        return scraped

    # =========================================================================
    # HIERARCHICAL BROWSING
    # =========================================================================

    async def get_path_tree(
        self,
        session: AsyncSession,
        collection_id: UUID,
        path_prefix: str = "/",
        depth: int = 1,
    ) -> List[Dict[str, Any]]:
        """
        Get hierarchical tree structure for browsing.

        Returns immediate children of the given path prefix.

        Args:
            collection_id: Collection UUID
            path_prefix: Parent path to list children from
            depth: How many levels to include

        Returns:
            List of tree nodes with path, count, and type info
        """
        # Normalize prefix
        if not path_prefix.startswith("/"):
            path_prefix = "/" + path_prefix
        if not path_prefix.endswith("/"):
            path_prefix = path_prefix + "/"

        # Get all paths starting with prefix
        query = select(
            ScrapedAsset.url_path,
            ScrapedAsset.asset_subtype,
            func.count(ScrapedAsset.id).label("count"),
        ).where(
            and_(
                ScrapedAsset.collection_id == collection_id,
                ScrapedAsset.url_path.startswith(path_prefix),
            )
        ).group_by(
            ScrapedAsset.url_path,
            ScrapedAsset.asset_subtype,
        )

        result = await session.execute(query)
        rows = result.all()

        # Build tree structure
        tree_nodes: Dict[str, Dict[str, Any]] = {}

        for row in rows:
            path = row.url_path or "/"
            # Get the next segment after prefix
            remainder = path[len(path_prefix):]
            if not remainder:
                continue

            segments = remainder.split("/")
            if not segments:
                continue

            # First segment is the immediate child
            child_segment = segments[0]
            child_path = path_prefix + child_segment

            if child_path not in tree_nodes:
                tree_nodes[child_path] = {
                    "path": child_path,
                    "name": child_segment,
                    "page_count": 0,
                    "record_count": 0,
                    "has_children": len(segments) > 1,
                }

            if row.asset_subtype == "page":
                tree_nodes[child_path]["page_count"] += row.count
            else:
                tree_nodes[child_path]["record_count"] += row.count

        return list(tree_nodes.values())

    async def get_path_assets(
        self,
        session: AsyncSession,
        collection_id: UUID,
        path: str,
        include_children: bool = False,
    ) -> List[ScrapedAsset]:
        """
        Get assets at a specific path.

        Args:
            collection_id: Collection UUID
            path: Exact path or prefix
            include_children: If True, include all descendants

        Returns:
            List of ScrapedAsset instances
        """
        query = select(ScrapedAsset).where(
            ScrapedAsset.collection_id == collection_id
        ).options(selectinload(ScrapedAsset.asset))

        if include_children:
            query = query.where(ScrapedAsset.url_path.startswith(path))
        else:
            query = query.where(ScrapedAsset.url_path == path)

        query = query.order_by(ScrapedAsset.url_path)

        result = await session.execute(query)
        return list(result.scalars().all())


# Singleton instance
scrape_service = ScrapeService()
