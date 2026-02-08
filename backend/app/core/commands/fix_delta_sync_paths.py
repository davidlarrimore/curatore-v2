"""
Fix assets created by delta sync with incorrect storage paths.

The delta sync had a bug where it didn't properly extract the relative path
from Microsoft Graph's parentReference.path format. This resulted in paths like:
  org_id/sharepoint/sync-slug/drives/b!xyz.../root/actual/path/file.pdf

Instead of:
  org_id/sharepoint/sync-slug/actual/path/file.pdf

This script:
1. Finds assets with wrong paths (containing '/drives/' in raw_object_key)
2. Deletes the SharePointSyncedDocument tracking record
3. Deletes the file from MinIO
4. Deletes the asset and related records from the database

After running this script, run a sync to re-create the files with correct paths.

Usage:
    # Dry run (show what would be deleted)
    docker exec curatore-backend python -m app.commands.fix_delta_sync_paths --dry-run

    # Actually delete
    docker exec curatore-backend python -m app.commands.fix_delta_sync_paths
"""

import argparse
import asyncio
import logging
import sys

from sqlalchemy import select, delete

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


async def fix_delta_sync_paths(dry_run: bool = True):
    """Find and fix assets with incorrect delta sync paths."""
    from app.core.database.models import Asset, SharePointSyncedDocument, ExtractionResult
    from app.core.shared.database_service import database_service
    from app.core.storage.minio_service import get_minio_service

    minio = get_minio_service()
    if not minio:
        logger.error("MinIO service not available")
        return

    async with database_service.get_session() as session:
        # Find assets with wrong paths (containing '/drives/' in raw_object_key)
        result = await session.execute(
            select(Asset).where(
                Asset.source_type == "sharepoint",
                Asset.raw_object_key.contains("/drives/"),
            )
        )
        affected_assets = result.scalars().all()

        if not affected_assets:
            logger.info("No assets found with incorrect paths. Nothing to fix.")
            return

        logger.info(f"Found {len(affected_assets)} assets with incorrect paths")

        for asset in affected_assets:
            logger.info(f"\nAsset: {asset.id}")
            logger.info(f"  Filename: {asset.original_filename}")
            logger.info(f"  Wrong path: {asset.raw_object_key}")

            if dry_run:
                logger.info("  [DRY RUN] Would delete this asset and related records")
                continue

            try:
                # 1. Delete SharePointSyncedDocument record
                await session.execute(
                    delete(SharePointSyncedDocument).where(
                        SharePointSyncedDocument.asset_id == asset.id
                    )
                )
                logger.info("  Deleted SharePointSyncedDocument record")

                # 2. Delete ExtractionResult record
                await session.execute(
                    delete(ExtractionResult).where(
                        ExtractionResult.asset_id == asset.id
                    )
                )
                logger.info("  Deleted ExtractionResult record")

                # 3. Delete file from MinIO
                try:
                    minio.delete_object(asset.raw_bucket, asset.raw_object_key)
                    logger.info(f"  Deleted from MinIO: {asset.raw_object_key}")
                except Exception as e:
                    logger.warning(f"  Failed to delete from MinIO (may not exist): {e}")

                # 4. Delete asset record
                await session.delete(asset)
                logger.info("  Deleted Asset record")

            except Exception as e:
                logger.error(f"  Error processing asset {asset.id}: {e}")
                continue

        if not dry_run:
            await session.commit()
            logger.info(f"\nSuccessfully cleaned up {len(affected_assets)} assets")
            logger.info("Run a sync to re-create the files with correct paths")
        else:
            logger.info(f"\n[DRY RUN] Would clean up {len(affected_assets)} assets")
            logger.info("Run without --dry-run to actually delete")


def main():
    parser = argparse.ArgumentParser(
        description="Fix assets created by delta sync with incorrect storage paths"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without actually deleting",
    )
    args = parser.parse_args()

    asyncio.run(fix_delta_sync_paths(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
