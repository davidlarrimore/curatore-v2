"""
Cleanup script for duplicate SharePoint assets.

This script identifies and removes duplicate assets that were created due to
race conditions or transaction failures during SharePoint sync.

Duplicates are identified by matching `source_metadata.sharepoint_item_id`.
For each set of duplicates, we keep the OLDEST asset (first created) and
delete the newer duplicates along with their MinIO objects.

Usage:
    # Dry run (default) - shows what would be deleted
    python -m app.commands.cleanup_duplicate_sharepoint_assets

    # Actually delete duplicates
    python -m app.commands.cleanup_duplicate_sharepoint_assets --delete

    # Target a specific sync config
    python -m app.commands.cleanup_duplicate_sharepoint_assets --sync-config-id <uuid>
"""

import argparse
import asyncio
import logging
import sys
from collections import defaultdict
from typing import Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Setup path for imports
sys.path.insert(0, "/app")

from app.core.database.models import Asset, SharePointSyncedDocument
from app.core.shared.database_service import database_service
from app.core.storage.minio_service import get_minio_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def find_duplicate_sharepoint_assets(
    session: AsyncSession,
    sync_config_id: Optional[UUID] = None,
) -> Dict[str, List[Asset]]:
    """
    Find duplicate SharePoint assets grouped by sharepoint_item_id.

    Returns:
        Dict mapping sharepoint_item_id to list of duplicate assets
    """
    # Query all SharePoint assets
    query = select(Asset).where(Asset.source_type == "sharepoint")

    if sync_config_id:
        query = query.where(
            Asset.source_metadata["sync"]["config_id"].astext == str(sync_config_id)
        )

    result = await session.execute(query.order_by(Asset.created_at.asc()))
    assets = result.scalars().all()

    # Group by sharepoint_item_id
    grouped: Dict[str, List[Asset]] = defaultdict(list)
    for asset in assets:
        item_id = asset.source_metadata.get("sharepoint", {}).get("item_id")
        if item_id:
            grouped[item_id].append(asset)

    # Filter to only groups with duplicates
    duplicates = {k: v for k, v in grouped.items() if len(v) > 1}

    return duplicates


async def get_orphan_synced_documents(
    session: AsyncSession,
) -> List[SharePointSyncedDocument]:
    """
    Find SharePointSyncedDocument records pointing to non-existent assets.
    """
    # Find synced documents where asset doesn't exist
    result = await session.execute(
        select(SharePointSyncedDocument)
        .outerjoin(Asset, SharePointSyncedDocument.asset_id == Asset.id)
        .where(Asset.id.is_(None))
    )
    return list(result.scalars().all())


async def delete_asset_and_files(
    session: AsyncSession,
    asset: Asset,
    minio_service,
    dry_run: bool = True,
) -> bool:
    """
    Delete an asset and its associated MinIO files.

    Returns:
        True if deleted successfully, False otherwise
    """
    asset_id = asset.id
    filename = asset.original_filename
    raw_bucket = asset.raw_bucket
    raw_key = asset.raw_object_key

    if dry_run:
        logger.info(f"  [DRY RUN] Would delete asset {asset_id} ({filename})")
        logger.info(f"    - MinIO object: {raw_bucket}/{raw_key}")
        return True

    try:
        # Delete from MinIO
        if raw_bucket and raw_key:
            try:
                minio_service.remove_object(raw_bucket, raw_key)
                logger.info(f"    Deleted MinIO object: {raw_bucket}/{raw_key}")
            except Exception as e:
                logger.warning(f"    Failed to delete MinIO object: {e}")

        # Delete associated synced document records
        synced_docs_result = await session.execute(
            select(SharePointSyncedDocument).where(
                SharePointSyncedDocument.asset_id == asset_id
            )
        )
        for doc in synced_docs_result.scalars().all():
            await session.delete(doc)
            logger.info(f"    Deleted synced document record: {doc.id}")

        # Delete the asset (cascade will handle extraction results, versions, etc.)
        await session.delete(asset)
        logger.info(f"  Deleted asset {asset_id} ({filename})")

        return True

    except Exception as e:
        logger.error(f"  Failed to delete asset {asset_id}: {e}")
        return False


async def cleanup_duplicates(
    sync_config_id: Optional[UUID] = None,
    dry_run: bool = True,
):
    """
    Main cleanup function.
    """
    minio_service = get_minio_service()
    if not minio_service:
        logger.error("MinIO service is not available")
        return

    stats = {
        "duplicate_groups": 0,
        "assets_to_delete": 0,
        "assets_deleted": 0,
        "files_deleted": 0,
        "errors": 0,
    }

    async with database_service.get_session() as session:
        # Find duplicates
        logger.info("Scanning for duplicate SharePoint assets...")
        duplicates = await find_duplicate_sharepoint_assets(session, sync_config_id)

        if not duplicates:
            logger.info("No duplicate assets found!")
            return

        stats["duplicate_groups"] = len(duplicates)
        logger.info(f"Found {len(duplicates)} sets of duplicate assets")

        # Process each duplicate group
        for item_id, assets in duplicates.items():
            logger.info(f"\nSharePoint item ID: {item_id}")
            logger.info(f"  {len(assets)} duplicates found:")

            # Keep the oldest (first created), delete the rest
            keep_asset = assets[0]
            delete_assets = assets[1:]

            logger.info(f"  KEEP: {keep_asset.id} ({keep_asset.original_filename}) - created {keep_asset.created_at}")

            for asset in delete_assets:
                stats["assets_to_delete"] += 1
                logger.info(f"  DELETE: {asset.id} ({asset.original_filename}) - created {asset.created_at}")

                success = await delete_asset_and_files(
                    session=session,
                    asset=asset,
                    minio_service=minio_service,
                    dry_run=dry_run,
                )

                if success:
                    stats["assets_deleted"] += 1
                else:
                    stats["errors"] += 1

        # Also check for and cleanup orphan synced document records
        logger.info("\nScanning for orphan synced document records...")
        orphan_docs = await get_orphan_synced_documents(session)

        if orphan_docs:
            logger.info(f"Found {len(orphan_docs)} orphan synced document records")
            for doc in orphan_docs:
                if dry_run:
                    logger.info(f"  [DRY RUN] Would delete orphan doc {doc.id} (item_id: {doc.sharepoint_item_id})")
                else:
                    await session.delete(doc)
                    logger.info(f"  Deleted orphan doc {doc.id}")
        else:
            logger.info("No orphan synced document records found")

        # Commit changes if not dry run
        if not dry_run:
            await session.commit()
            logger.info("\nChanges committed to database")

        # Summary
        logger.info("\n" + "=" * 60)
        logger.info("CLEANUP SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Duplicate groups found: {stats['duplicate_groups']}")
        logger.info(f"Assets to delete: {stats['assets_to_delete']}")
        if dry_run:
            logger.info("[DRY RUN] No actual deletions performed")
            logger.info("Run with --delete flag to actually delete duplicates")
        else:
            logger.info(f"Assets deleted: {stats['assets_deleted']}")
            logger.info(f"Errors: {stats['errors']}")


def main():
    parser = argparse.ArgumentParser(
        description="Cleanup duplicate SharePoint assets"
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Actually delete duplicates (default is dry run)"
    )
    parser.add_argument(
        "--sync-config-id",
        type=str,
        help="Only process assets from this sync config"
    )

    args = parser.parse_args()

    sync_config_id = UUID(args.sync_config_id) if args.sync_config_id else None
    dry_run = not args.delete

    if dry_run:
        logger.info("=" * 60)
        logger.info("DRY RUN MODE - No changes will be made")
        logger.info("Use --delete flag to actually delete duplicates")
        logger.info("=" * 60)
    else:
        logger.warning("=" * 60)
        logger.warning("DELETE MODE - Duplicates will be permanently deleted!")
        logger.warning("=" * 60)

    asyncio.run(cleanup_duplicates(
        sync_config_id=sync_config_id,
        dry_run=dry_run,
    ))


if __name__ == "__main__":
    main()
