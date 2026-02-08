"""
Re-extract all documents with the new triage-based extraction system.

This script:
1. Finds all assets with completed extractions
2. Resets their status to 'pending'
3. Queues them for re-extraction via the extraction queue service
4. The triage system will analyze each document and select the optimal engine

Usage:
    python -m app.commands.reextract_all [--dry-run] [--limit N] [--batch-size N]

Options:
    --dry-run       Show what would be done without making changes
    --limit N       Limit to N assets (default: no limit)
    --batch-size N  Process N assets per batch (default: 50)
"""

import argparse
import asyncio
import logging
import sys
from datetime import datetime
from typing import List
from uuid import UUID

from sqlalchemy import select, and_

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("reextract_all")


async def get_assets_for_reextraction(session, limit: int = None) -> List:
    """Get all assets that need re-extraction."""
    from ..database.models import Asset

    # Get assets that are ready (have been extracted before)
    # Skip deleted and failed assets
    query = (
        select(Asset)
        .where(and_(
            Asset.status.in_(["ready", "pending"]),
        ))
        .order_by(Asset.created_at.asc())
    )

    if limit:
        query = query.limit(limit)

    result = await session.execute(query)
    return list(result.scalars().all())


async def reset_asset_for_reextraction(session, asset) -> bool:
    """Reset an asset for re-extraction."""
    from ..database.models import ExtractionResult

    # Reset asset status to pending
    asset.status = "pending"
    asset.updated_at = datetime.utcnow()

    # Clear the indexed_at field so it gets re-indexed after extraction
    asset.indexed_at = None

    await session.flush()
    return True


async def queue_extraction(session, asset) -> dict:
    """Queue extraction for an asset."""
    from ..services.extraction_queue_service import extraction_queue_service

    run, extraction, status = await extraction_queue_service.queue_extraction_for_asset(
        session=session,
        asset_id=asset.id,
        priority=0,  # Normal priority
        skip_content_type_check=True,  # Force re-extraction
    )

    return {
        "asset_id": str(asset.id),
        "status": status,
        "run_id": str(run.id) if run else None,
    }


async def main(dry_run: bool = False, limit: int = None, batch_size: int = 50):
    """Main re-extraction function."""
    from ..services.database_service import database_service

    logger.info("=" * 60)
    logger.info("Re-extract All Documents with New Triage System")
    logger.info("=" * 60)

    if dry_run:
        logger.info("DRY RUN MODE - No changes will be made")

    async with database_service.get_session() as session:
        # Get all assets needing re-extraction
        logger.info("Fetching assets for re-extraction...")
        assets = await get_assets_for_reextraction(session, limit)

        total = len(assets)
        logger.info(f"Found {total} assets to re-extract")

        if total == 0:
            logger.info("No assets found for re-extraction")
            return

        if dry_run:
            logger.info("Dry run - would process the following assets:")
            for asset in assets[:10]:
                logger.info(f"  - {asset.id}: {asset.original_filename} ({asset.status})")
            if total > 10:
                logger.info(f"  ... and {total - 10} more")
            return

        # Process in batches
        queued = 0
        skipped = 0
        errors = 0

        for i in range(0, total, batch_size):
            batch = assets[i:i + batch_size]
            batch_num = (i // batch_size) + 1
            total_batches = (total + batch_size - 1) // batch_size

            logger.info(f"Processing batch {batch_num}/{total_batches} ({len(batch)} assets)...")

            for asset in batch:
                try:
                    # Reset asset for re-extraction
                    await reset_asset_for_reextraction(session, asset)

                    # Queue extraction
                    result = await queue_extraction(session, asset)

                    if result["status"] == "queued":
                        queued += 1
                        logger.debug(f"Queued: {asset.original_filename} -> run={result['run_id']}")
                    elif result["status"] == "already_pending":
                        skipped += 1
                        logger.debug(f"Skipped (already pending): {asset.original_filename}")
                    else:
                        skipped += 1
                        logger.debug(f"Skipped ({result['status']}): {asset.original_filename}")

                except Exception as e:
                    errors += 1
                    logger.error(f"Error processing {asset.id}: {e}")

            # Commit batch
            await session.commit()
            logger.info(f"Batch {batch_num} complete: {queued} queued, {skipped} skipped, {errors} errors")

        logger.info("=" * 60)
        logger.info("Re-extraction complete!")
        logger.info(f"  Total assets: {total}")
        logger.info(f"  Queued: {queued}")
        logger.info(f"  Skipped: {skipped}")
        logger.info(f"  Errors: {errors}")
        logger.info("=" * 60)
        logger.info("Extraction queue will now process documents using the new triage system.")
        logger.info("Monitor progress at: /admin/queue")


def cli():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Re-extract all documents with new triage-based extraction system"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit to N assets (default: no limit)"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Process N assets per batch (default: 50)"
    )

    args = parser.parse_args()

    asyncio.run(main(
        dry_run=args.dry_run,
        limit=args.limit,
        batch_size=args.batch_size,
    ))


if __name__ == "__main__":
    cli()
