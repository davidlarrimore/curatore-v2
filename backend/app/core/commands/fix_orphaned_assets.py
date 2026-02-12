#!/usr/bin/env python3
"""
Fix orphaned assets that are stuck in 'pending' status without extraction runs.

This command finds all assets with status='pending' that don't have an active
extraction run and queues extractions for them.

Usage:
    # Dry run (see what would be fixed)
    python -m app.commands.fix_orphaned_assets --dry-run

    # Actually fix the assets
    python -m app.commands.fix_orphaned_assets

    # Fix with a limit
    python -m app.commands.fix_orphaned_assets --limit 100
"""

import argparse
import asyncio
import logging

from sqlalchemy import and_, select

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def find_orphaned_assets(session, limit: int = 1000):
    """Find assets that are pending but have no active extraction run."""
    from ..database.models import Asset, Run

    # Get pending assets
    result = await session.execute(
        select(Asset.id, Asset.original_filename, Asset.organization_id)
        .where(Asset.status == "pending")
        .order_by(Asset.created_at.asc())
        .limit(limit)
    )
    pending_assets = result.fetchall()

    orphaned = []
    for asset_id, filename, org_id in pending_assets:
        asset_id_str = str(asset_id)

        # Check if there's an active extraction run for this asset
        # This is a bit slow but accurate
        run_result = await session.execute(
            select(Run.id)
            .where(and_(
                Run.run_type == "extraction",
                Run.status.in_(["pending", "submitted", "running"]),
            ))
        )

        found = False
        for (run_id,) in run_result.fetchall():
            run = await session.get(Run, run_id)
            if run and run.input_asset_ids:
                if asset_id_str in [str(x) for x in run.input_asset_ids]:
                    found = True
                    break

        if not found:
            orphaned.append((asset_id, filename, org_id))

    return orphaned


async def fix_orphaned_assets(dry_run: bool = True, limit: int = 1000):
    """Find and fix orphaned pending assets."""
    from ..services.database_service import database_service
    from ..services.upload_integration_service import upload_integration_service

    async with database_service.get_session() as session:
        logger.info("Finding orphaned pending assets...")
        orphaned = await find_orphaned_assets(session, limit)

        logger.info(f"Found {len(orphaned)} orphaned assets")

        if dry_run:
            logger.info("DRY RUN - not making any changes")
            for asset_id, filename, org_id in orphaned[:20]:
                logger.info(f"  Would fix: {asset_id} - {filename[:50]}")
            if len(orphaned) > 20:
                logger.info(f"  ... and {len(orphaned) - 20} more")
            return

        # Actually fix them
        fixed = 0
        errors = 0
        for asset_id, filename, org_id in orphaned:
            try:
                result = await upload_integration_service.trigger_extraction(
                    session=session,
                    asset_id=asset_id,
                )
                if result:
                    fixed += 1
                    logger.debug(f"Queued extraction for {asset_id}")
                else:
                    logger.warning(f"Extraction not triggered for {asset_id} (unsupported type?)")
            except Exception as e:
                errors += 1
                logger.error(f"Failed to queue extraction for {asset_id}: {e}")

        await session.commit()

        logger.info(f"Fixed {fixed} assets, {errors} errors")


def main():
    parser = argparse.ArgumentParser(description="Fix orphaned pending assets")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be fixed without making changes"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1000,
        help="Maximum number of assets to process (default: 1000)"
    )
    args = parser.parse_args()

    asyncio.run(fix_orphaned_assets(dry_run=args.dry_run, limit=args.limit))


if __name__ == "__main__":
    main()
