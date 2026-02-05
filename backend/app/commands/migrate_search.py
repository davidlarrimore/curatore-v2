#!/usr/bin/env python
"""
Migrate Search Data to PostgreSQL + pgvector

This command migrates all existing assets to the new PostgreSQL-based search
system with pgvector for hybrid full-text and semantic search. Run this after
deploying the pgvector Alembic migration.

Embeddings are generated via OpenAI API (text-embedding-3-small by default).
Configure the embedding model in config.yml under llm.models.embedding.

Usage:
    docker exec curatore-backend python -m app.commands.migrate_search

    # With options:
    docker exec curatore-backend python -m app.commands.migrate_search --org-id <uuid>
    docker exec curatore-backend python -m app.commands.migrate_search --batch-size 100

What this does:
    1. Queries all assets with completed extractions
    2. For each asset:
       - Downloads markdown from MinIO
       - Splits content into chunks
       - Generates embeddings for each chunk
       - Inserts into search_chunks table
    3. Migrates SAM.gov notices and solicitations
"""

import asyncio
import argparse
import logging
import sys
from datetime import datetime
from typing import Optional
from uuid import UUID

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("migrate_search")


async def migrate_assets(
    organization_id: Optional[UUID] = None,
    batch_size: int = 50,
) -> dict:
    """
    Migrate all assets to the new search system.

    Args:
        organization_id: Optional specific org to migrate (all if None)
        batch_size: Number of assets to process per batch

    Returns:
        Dict with migration statistics
    """
    from sqlalchemy import select
    from app.services.database_service import database_service
    from app.services.pg_index_service import pg_index_service
    from app.database.models import Asset, Organization

    stats = {
        "total_assets": 0,
        "indexed": 0,
        "failed": 0,
        "errors": [],
        "organizations_processed": 0,
    }

    async with database_service.get_session() as session:
        # Get organizations to process
        if organization_id:
            org_query = select(Organization).where(Organization.id == organization_id)
        else:
            org_query = select(Organization).where(Organization.is_active == True)

        org_result = await session.execute(org_query)
        organizations = list(org_result.scalars().all())

        logger.info(f"Found {len(organizations)} organization(s) to migrate")

        for org in organizations:
            logger.info(f"Processing organization: {org.name} ({org.id})")

            # Get all ready assets for this org
            asset_query = (
                select(Asset)
                .where(Asset.organization_id == org.id)
                .where(Asset.status == "ready")
                .order_by(Asset.created_at)
            )
            asset_result = await session.execute(asset_query)
            assets = list(asset_result.scalars().all())

            org_total = len(assets)
            org_indexed = 0
            org_failed = 0

            logger.info(f"  Found {org_total} assets to index")
            stats["total_assets"] += org_total

            for i, asset in enumerate(assets):
                try:
                    success = await pg_index_service.index_asset(session, asset.id)
                    if success:
                        org_indexed += 1
                        stats["indexed"] += 1
                    else:
                        org_failed += 1
                        stats["failed"] += 1

                    if (i + 1) % batch_size == 0 or (i + 1) == org_total:
                        logger.info(
                            f"  Progress: {i + 1}/{org_total} "
                            f"(indexed: {org_indexed}, failed: {org_failed})"
                        )

                except Exception as e:
                    org_failed += 1
                    stats["failed"] += 1
                    error_msg = f"Asset {asset.id}: {str(e)}"
                    if len(stats["errors"]) < 20:
                        stats["errors"].append(error_msg)
                    logger.warning(f"  Failed to index {asset.id}: {e}")

            stats["organizations_processed"] += 1
            logger.info(
                f"  Completed {org.name}: {org_indexed}/{org_total} indexed, "
                f"{org_failed} failed"
            )

    return stats


async def migrate_sam_data(
    organization_id: Optional[UUID] = None,
) -> dict:
    """
    Migrate SAM.gov data to the new search system.

    Args:
        organization_id: Optional specific org to migrate

    Returns:
        Dict with migration statistics
    """
    from sqlalchemy import select
    from app.services.database_service import database_service
    from app.services.pg_index_service import pg_index_service
    from app.database.models import Organization, SamSolicitation, SamNotice

    stats = {
        "solicitations_indexed": 0,
        "notices_indexed": 0,
        "failed": 0,
        "errors": [],
    }

    async with database_service.get_session() as session:
        # Get organizations
        if organization_id:
            org_query = select(Organization).where(Organization.id == organization_id)
        else:
            org_query = select(Organization).where(Organization.is_active == True)

        org_result = await session.execute(org_query)
        organizations = list(org_result.scalars().all())

        for org in organizations:
            logger.info(f"Processing SAM data for: {org.name}")

            # Get solicitations
            sol_query = select(SamSolicitation).where(
                SamSolicitation.organization_id == org.id
            )
            sol_result = await session.execute(sol_query)
            solicitations = list(sol_result.scalars().all())

            logger.info(f"  Found {len(solicitations)} solicitations")

            for solicitation in solicitations:
                try:
                    success = await pg_index_service.index_sam_solicitation(
                        session=session,
                        organization_id=org.id,
                        solicitation_id=solicitation.id,
                        solicitation_number=solicitation.solicitation_number,
                        title=solicitation.title,
                        description=solicitation.description or "",
                        agency=solicitation.agency_name,
                        office=solicitation.office_name,
                        naics_code=solicitation.naics_code,
                        set_aside=solicitation.set_aside_code,
                        posted_date=solicitation.posted_date,
                        response_deadline=solicitation.response_deadline,
                        url=getattr(solicitation, "sam_url", None),
                    )
                    if success:
                        stats["solicitations_indexed"] += 1
                except Exception as e:
                    stats["failed"] += 1
                    if len(stats["errors"]) < 20:
                        stats["errors"].append(f"Solicitation {solicitation.id}: {e}")

            # Get notices - include both solicitation-linked AND standalone notices
            # Use outerjoin to get notices that may or may not have a solicitation
            from sqlalchemy import or_
            notice_query = (
                select(SamNotice)
                .outerjoin(SamSolicitation)
                .where(
                    or_(
                        # Notices linked to solicitations owned by this org
                        SamSolicitation.organization_id == org.id,
                        # Standalone notices (e.g., Special Notices) owned directly by this org
                        SamNotice.organization_id == org.id,
                    )
                )
            )
            notice_result = await session.execute(notice_query)
            notices = list(notice_result.scalars().all())

            logger.info(f"  Found {len(notices)} notices")

            for notice in notices:
                try:
                    success = await pg_index_service.index_sam_notice(
                        session=session,
                        organization_id=org.id,
                        notice_id=notice.id,
                        sam_notice_id=notice.sam_notice_id,
                        solicitation_id=notice.solicitation_id,
                        title=notice.title,
                        description=notice.description or "",
                        notice_type=notice.notice_type,
                        posted_date=notice.posted_date,
                        response_deadline=notice.response_deadline,
                        url=getattr(notice, "sam_url", None),
                    )
                    if success:
                        stats["notices_indexed"] += 1
                except Exception as e:
                    stats["failed"] += 1
                    if len(stats["errors"]) < 20:
                        stats["errors"].append(f"Notice {notice.id}: {e}")

    return stats


async def main(
    organization_id: Optional[str] = None,
    batch_size: int = 50,
    skip_assets: bool = False,
    skip_sam: bool = False,
):
    """Run the migration."""
    start_time = datetime.now()
    logger.info("=" * 60)
    logger.info("Starting Search Migration to PostgreSQL + pgvector")
    logger.info("=" * 60)

    org_uuid = UUID(organization_id) if organization_id else None

    total_stats = {}

    if not skip_assets:
        logger.info("\n[1/2] Migrating Assets...")
        asset_stats = await migrate_assets(org_uuid, batch_size)
        total_stats["assets"] = asset_stats
        logger.info(
            f"\nAsset migration complete: "
            f"{asset_stats['indexed']}/{asset_stats['total_assets']} indexed, "
            f"{asset_stats['failed']} failed"
        )
    else:
        logger.info("\n[1/2] Skipping asset migration")

    if not skip_sam:
        logger.info("\n[2/2] Migrating SAM.gov Data...")
        sam_stats = await migrate_sam_data(org_uuid)
        total_stats["sam"] = sam_stats
        logger.info(
            f"\nSAM migration complete: "
            f"{sam_stats['solicitations_indexed']} solicitations, "
            f"{sam_stats['notices_indexed']} notices indexed"
        )
    else:
        logger.info("\n[2/2] Skipping SAM migration")

    duration = datetime.now() - start_time
    logger.info("\n" + "=" * 60)
    logger.info(f"Migration completed in {duration}")
    logger.info("=" * 60)

    return total_stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Migrate search data to PostgreSQL + pgvector"
    )
    parser.add_argument(
        "--org-id",
        type=str,
        help="Specific organization ID to migrate (migrates all if not specified)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Number of assets to process per batch (default: 50)",
    )
    parser.add_argument(
        "--skip-assets",
        action="store_true",
        help="Skip asset migration",
    )
    parser.add_argument(
        "--skip-sam",
        action="store_true",
        help="Skip SAM.gov data migration",
    )

    args = parser.parse_args()

    try:
        asyncio.run(
            main(
                organization_id=args.org_id,
                batch_size=args.batch_size,
                skip_assets=args.skip_assets,
                skip_sam=args.skip_sam,
            )
        )
    except KeyboardInterrupt:
        logger.info("\nMigration interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"\nMigration failed: {e}")
        sys.exit(1)
