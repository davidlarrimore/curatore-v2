#!/usr/bin/env python3
"""
Backfill extraction_status and extraction_tier into source_metadata.file namespace.

Existing assets have these values on the Asset model columns but not in
source_metadata, which means they are invisible to the search index and
facet filters. This command copies them into source_metadata.file so the
AssetPassthroughBuilder can propagate them to search chunks.

Usage:
    # Dry run (see what would change)
    python -m app.core.commands.backfill_extraction_metadata --dry-run

    # Run backfill
    python -m app.core.commands.backfill_extraction_metadata

    # Run backfill and trigger reindex for updated assets
    python -m app.core.commands.backfill_extraction_metadata --reindex

    # Limit batch size
    python -m app.core.commands.backfill_extraction_metadata --batch-size 200
"""

import argparse
import asyncio
import logging

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def backfill_extraction_metadata(
    dry_run: bool = False,
    batch_size: int = 500,
    reindex: bool = False,
):
    """Backfill extraction_status and extraction_tier into source_metadata.file."""
    from app.core.database.models import Asset
    from app.core.shared.database_service import database_service

    async with database_service.get_session() as session:
        # Count total assets
        total_result = await session.execute(select(func.count(Asset.id)))
        total = total_result.scalar() or 0
        logger.info(f"Total assets: {total}")

        if total == 0:
            logger.info("No assets to process")
            return

        # Process in batches
        offset = 0
        updated = 0
        skipped = 0
        errors = 0
        updated_ids = []

        while offset < total:
            result = await session.execute(
                select(Asset)
                .order_by(Asset.created_at.asc())
                .offset(offset)
                .limit(batch_size)
            )
            assets = list(result.scalars().all())

            if not assets:
                break

            for asset in assets:
                try:
                    sm = dict(asset.source_metadata or {})
                    file_ns = dict(sm.get("file", {}))

                    needs_update = False

                    # Check extraction_status
                    if file_ns.get("extraction_status") != asset.status:
                        file_ns["extraction_status"] = asset.status
                        needs_update = True

                    # Check extraction_tier (only if asset has one)
                    if asset.extraction_tier and file_ns.get("extraction_tier") != asset.extraction_tier:
                        file_ns["extraction_tier"] = asset.extraction_tier
                        needs_update = True

                    if needs_update:
                        if not dry_run:
                            sm["file"] = file_ns
                            asset.source_metadata = sm
                        updated += 1
                        updated_ids.append(asset.id)
                    else:
                        skipped += 1

                except Exception as e:
                    errors += 1
                    logger.error(f"Error processing asset {asset.id}: {e}")

            if not dry_run:
                await session.commit()

            offset += batch_size
            logger.info(
                f"Progress: {min(offset, total)}/{total} "
                f"(updated={updated}, skipped={skipped}, errors={errors})"
            )

        action = "Would update" if dry_run else "Updated"
        logger.info(
            f"Backfill complete: {action} {updated} assets, "
            f"skipped {skipped} (already current), {errors} errors"
        )

        # Trigger reindex if requested
        if reindex and not dry_run and updated_ids:
            logger.info(f"Triggering reindex for {len(updated_ids)} updated assets...")
            try:
                from app.core.tasks import index_asset_task

                queued = 0
                for asset_id in updated_ids:
                    index_asset_task.delay(asset_id=str(asset_id))
                    queued += 1

                logger.info(f"Queued {queued} assets for reindexing")
            except Exception as e:
                logger.error(f"Failed to queue reindex tasks: {e}")
                logger.info(
                    "You can manually reindex later with: "
                    "python -m app.core.commands.migrate_search"
                )


def main():
    parser = argparse.ArgumentParser(
        description="Backfill extraction_status and extraction_tier into source_metadata.file"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without making modifications",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Number of assets to process per batch (default: 500)",
    )
    parser.add_argument(
        "--reindex",
        action="store_true",
        help="Trigger search reindex for updated assets after backfill",
    )
    args = parser.parse_args()

    asyncio.run(
        backfill_extraction_metadata(
            dry_run=args.dry_run,
            batch_size=args.batch_size,
            reindex=args.reindex,
        )
    )


if __name__ == "__main__":
    main()
