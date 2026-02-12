#!/usr/bin/env python3
"""
Storage and Artifact Cleanup Utility.

This command cleans up object storage (MinIO/S3) and artifact records
during development when making breaking changes to the storage layer.

After cleanup, it automatically recreates buckets with proper lifecycle
policies and creates default organization folder structure.

DESTRUCTIVE OPERATION - USE WITH CAUTION

Usage:
    # Interactive mode with confirmation
    python -m app.commands.cleanup_storage

    # Force mode (no confirmation)
    python -m app.commands.cleanup_storage --force

    # Dry run (show what would be deleted)
    python -m app.commands.cleanup_storage --dry-run

    # Clean specific organization
    python -m app.commands.cleanup_storage --org-id <uuid>

    # Clean specific bucket (skips recreation)
    python -m app.commands.cleanup_storage --bucket curatore-uploads

    # Cleanup only (skip bucket recreation)
    python -m app.commands.cleanup_storage --skip-recreate

    # Also clean web scraping database records (ScrapedAssets, Assets, Runs)
    # Use this when storage path structure changes to re-crawl with new paths
    python -m app.commands.cleanup_storage --scrape
"""

import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional
from uuid import UUID

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import delete, select

from app.core.database.models import (
    Artifact,
    Asset,
    ExtractionResult,
    Run,
    ScrapeCollection,
    ScrapedAsset,
)
from app.core.shared.database_service import database_service
from app.core.storage.minio_service import get_minio_service

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def confirm_cleanup(org_id: Optional[UUID] = None, bucket: Optional[str] = None, include_scrape: bool = False) -> bool:
    """Prompt user for confirmation before destructive operation."""
    print("\n" + "=" * 70)
    print("⚠️  DESTRUCTIVE OPERATION - STORAGE CLEANUP")
    print("=" * 70)

    if bucket:
        print(f"  Scope: Bucket '{bucket}' only")
    elif org_id:
        print(f"  Scope: Organization {org_id}")
    else:
        print("  Scope: ALL organizations and buckets")

    print("\n  This will DELETE:")
    print("    • All objects in MinIO/S3 storage (within scope)")
    print("    • All artifact records from database")
    print("    • Asset file_hash values will be set to NULL")
    if include_scrape:
        print("    • All ScrapedAsset records (web scraping)")
        print("    • All Assets created by web scraping")
        print("    • All ExtractionResults for scraped content")
        print("    • All scrape/extraction Runs")
        print("    • Collection stats will be reset (collections preserved)")
    print("\n  This operation CANNOT be undone!")
    print("=" * 70)

    response = input("\n  Type 'DELETE' to confirm: ").strip()
    return response == "DELETE"


async def cleanup_minio_bucket(minio, bucket: str, org_id: Optional[UUID] = None, dry_run: bool = False) -> int:
    """
    Clean up objects in a specific MinIO bucket.

    Args:
        minio: MinIO service instance
        bucket: Bucket name
        org_id: Optional organization ID to limit scope
        dry_run: If True, only show what would be deleted

    Returns:
        Number of objects deleted (or would be deleted)
    """
    try:
        # List all objects in bucket
        prefix = f"{org_id}/" if org_id else None
        objects = minio.client.list_objects(bucket, prefix=prefix, recursive=True)

        deleted_count = 0
        for obj in objects:
            if dry_run:
                logger.info(f"  [DRY RUN] Would delete: {bucket}/{obj.object_name}")
            else:
                logger.info(f"  Deleting: {bucket}/{obj.object_name}")
                minio.client.remove_object(bucket, obj.object_name)
            deleted_count += 1

        return deleted_count

    except Exception as e:
        logger.error(f"Failed to clean bucket {bucket}: {e}")
        return 0


async def cleanup_artifacts(
    session,
    org_id: Optional[UUID] = None,
    bucket: Optional[str] = None,
    dry_run: bool = False
) -> int:
    """
    Clean up artifact records from database.

    Args:
        session: Database session
        org_id: Optional organization ID to limit scope
        bucket: Optional bucket name to limit scope
        dry_run: If True, only count what would be deleted

    Returns:
        Number of artifacts deleted (or would be deleted)
    """
    try:
        # Build query
        stmt = select(Artifact)

        if org_id:
            stmt = stmt.where(Artifact.organization_id == org_id)

        if bucket:
            stmt = stmt.where(Artifact.bucket == bucket)

        result = await session.execute(stmt)
        artifacts = result.scalars().all()

        count = len(artifacts)

        if dry_run:
            logger.info(f"  [DRY RUN] Would delete {count} artifact records")
        else:
            # Delete artifacts
            delete_stmt = delete(Artifact)
            if org_id:
                delete_stmt = delete_stmt.where(Artifact.organization_id == org_id)
            if bucket:
                delete_stmt = delete_stmt.where(Artifact.bucket == bucket)

            await session.execute(delete_stmt)
            await session.commit()
            logger.info(f"  Deleted {count} artifact records")

        return count

    except Exception as e:
        logger.error(f"Failed to clean artifacts: {e}")
        await session.rollback()
        return 0


async def cleanup_scrape_records(
    session,
    org_id: Optional[UUID] = None,
    dry_run: bool = False
) -> dict:
    """
    Clean up web scraping database records.

    This removes ScrapedAssets, Assets (web_scrape type), ExtractionResults,
    and Runs related to web scraping. Collections and Sources are preserved.

    Args:
        session: Database session
        org_id: Optional organization ID to limit scope
        dry_run: If True, only count what would be deleted

    Returns:
        Dict with counts of deleted records
    """
    counts = {
        "scraped_assets": 0,
        "assets": 0,
        "extraction_results": 0,
        "runs": 0,
    }

    try:
        # Get collections to process
        stmt = select(ScrapeCollection)
        if org_id:
            stmt = stmt.where(ScrapeCollection.organization_id == org_id)
        result = await session.execute(stmt)
        collections = result.scalars().all()

        collection_ids = [c.id for c in collections]

        if not collection_ids:
            logger.info("  No scrape collections found")
            return counts

        # Count/delete ScrapedAssets
        stmt = select(ScrapedAsset).where(ScrapedAsset.collection_id.in_(collection_ids))
        result = await session.execute(stmt)
        scraped_assets = result.scalars().all()
        counts["scraped_assets"] = len(scraped_assets)

        # Get asset IDs for these scraped assets
        asset_ids = [sa.asset_id for sa in scraped_assets]

        if asset_ids:
            # Count/delete ExtractionResults for these assets
            stmt = select(ExtractionResult).where(ExtractionResult.asset_id.in_(asset_ids))
            result = await session.execute(stmt)
            extraction_results = result.scalars().all()
            counts["extraction_results"] = len(extraction_results)

            # Get run IDs from extraction results
            run_ids = list(set(er.run_id for er in extraction_results if er.run_id))

            if not dry_run:
                # Delete extraction results
                await session.execute(
                    delete(ExtractionResult).where(ExtractionResult.asset_id.in_(asset_ids))
                )

            # Count/delete Runs (scrape and extraction types for these assets)
            if run_ids:
                stmt = select(Run).where(Run.id.in_(run_ids))
                result = await session.execute(stmt)
                runs = result.scalars().all()
                counts["runs"] = len(runs)

                if not dry_run:
                    await session.execute(delete(Run).where(Run.id.in_(run_ids)))

            # Count/delete Assets
            stmt = select(Asset).where(Asset.id.in_(asset_ids))
            result = await session.execute(stmt)
            assets = result.scalars().all()
            counts["assets"] = len(assets)

            if not dry_run:
                # Delete scraped assets first (foreign key constraint)
                await session.execute(
                    delete(ScrapedAsset).where(ScrapedAsset.collection_id.in_(collection_ids))
                )
                # Then delete assets
                await session.execute(delete(Asset).where(Asset.id.in_(asset_ids)))

        # Also delete any orphaned scrape runs
        stmt = select(Run).where(
            Run.run_type == "scrape",
            Run.organization_id.in_([c.organization_id for c in collections])
        )
        result = await session.execute(stmt)
        scrape_runs = result.scalars().all()
        scrape_run_count = len(scrape_runs)

        if scrape_run_count > 0 and not dry_run:
            await session.execute(
                delete(Run).where(
                    Run.run_type == "scrape",
                    Run.organization_id.in_([c.organization_id for c in collections])
                )
            )
        counts["runs"] += scrape_run_count

        # Reset collection stats and last_crawl references
        if not dry_run:
            for collection in collections:
                collection.last_crawl_at = None
                collection.last_crawl_run_id = None
                collection.stats = {"page_count": 0, "record_count": 0, "promoted_count": 0}

            await session.commit()

        if dry_run:
            logger.info(f"  [DRY RUN] Would delete {counts['scraped_assets']} scraped assets")
            logger.info(f"  [DRY RUN] Would delete {counts['assets']} assets")
            logger.info(f"  [DRY RUN] Would delete {counts['extraction_results']} extraction results")
            logger.info(f"  [DRY RUN] Would delete {counts['runs']} runs")
        else:
            logger.info(f"  Deleted {counts['scraped_assets']} scraped assets")
            logger.info(f"  Deleted {counts['assets']} assets")
            logger.info(f"  Deleted {counts['extraction_results']} extraction results")
            logger.info(f"  Deleted {counts['runs']} runs")
            logger.info(f"  Reset {len(collections)} collection stats")

        return counts

    except Exception as e:
        logger.error(f"Failed to clean scrape records: {e}")
        await session.rollback()
        return counts


async def reset_asset_hashes(
    session,
    org_id: Optional[UUID] = None,
    dry_run: bool = False
) -> int:
    """
    Reset file_hash to NULL for assets after storage cleanup.

    This allows assets to be reprocessed with new extraction methods
    without validation errors.

    Args:
        session: Database session
        org_id: Optional organization ID to limit scope
        dry_run: If True, only count what would be reset

    Returns:
        Number of assets updated
    """
    try:
        # Build query
        stmt = select(Asset)

        if org_id:
            stmt = stmt.where(Asset.organization_id == org_id)

        result = await session.execute(stmt)
        assets = result.scalars().all()

        count = 0
        for asset in assets:
            if asset.file_hash:  # Only reset if hash exists
                count += 1
                if not dry_run:
                    asset.file_hash = None

        if dry_run:
            logger.info(f"  [DRY RUN] Would reset file_hash for {count} assets")
        else:
            await session.commit()
            logger.info(f"  Reset file_hash for {count} assets")

        return count

    except Exception as e:
        logger.error(f"Failed to reset asset hashes: {e}")
        await session.rollback()
        return 0


async def create_org_folder_structure(minio, bucket_name: str, org_id: str, dry_run: bool = False):
    """
    Create organization folder structure in a bucket.

    Creates the standard folder hierarchy:
        {org_id}/
        ├── uploads/
        ├── scrape/
        ├── sharepoint/
        └── temp/

    Args:
        minio: MinIO service instance
        bucket_name: Bucket name
        org_id: Organization ID string
        dry_run: If True, only show what would be created
    """
    from io import BytesIO

    # Define subfolders based on storage path service structure
    subfolders = ["uploads", "scrape", "sharepoint", "temp"]

    for subfolder in subfolders:
        folder_path = f"{org_id}/{subfolder}/.keep"

        if dry_run:
            logger.info(f"  [DRY RUN] Would create: {bucket_name}/{org_id}/{subfolder}/")
        else:
            try:
                # MinIO/S3 doesn't have "folders" - create a .keep file to establish path
                minio.client.put_object(
                    bucket_name,
                    folder_path,
                    data=BytesIO(b""),
                    length=0,
                )
                logger.info(f"  ✓ Created: {bucket_name}/{org_id}/{subfolder}/")
            except Exception as e:
                logger.error(f"  ✗ Failed to create {bucket_name}/{org_id}/{subfolder}/: {e}")


async def recreate_storage_structure(minio, org_id: Optional[UUID] = None, dry_run: bool = False):
    """
    Recreate buckets and default folder structure after cleanup.

    Args:
        minio: MinIO service instance
        org_id: Optional organization ID to create folders for
        dry_run: If True, only show what would be created
    """
    logger.info("\n" + "=" * 70)
    logger.info("Recreating storage structure...")
    logger.info("=" * 70 + "\n")

    # Define bucket configuration (name, retention_days, description)
    buckets = [
        (minio.bucket_uploads, 30, "Uploads bucket (30 day retention)"),
        (minio.bucket_processed, 90, "Processed files bucket (90 day retention)"),
        (minio.bucket_temp, 7, "Temporary files bucket (7 day retention)"),
    ]

    # Recreate buckets with lifecycle policies
    for bucket_name, retention_days, description in buckets:
        try:
            if dry_run:
                logger.info(f"[DRY RUN] Would create bucket: {bucket_name}")
                logger.info(f"[DRY RUN] Would set lifecycle policy: {retention_days} days")
            else:
                # Ensure bucket exists
                if not minio.client.bucket_exists(bucket_name):
                    logger.info(f"Creating bucket: {bucket_name}")
                    minio.ensure_bucket_exists(bucket_name)
                    logger.info(f"✓ Created bucket: {bucket_name}")
                else:
                    logger.info(f"✓ Bucket exists: {bucket_name}")

                # Set lifecycle policy
                logger.info(f"Setting lifecycle policy ({retention_days} days)...")
                minio.set_lifecycle_policy(bucket_name, expiration_days=retention_days)
                logger.info(f"✓ Lifecycle policy set: {description}")

        except Exception as e:
            logger.error(f"Failed to create/configure bucket {bucket_name}: {e}")

    # Create organization folders
    org_to_create = None

    if org_id:
        org_to_create = str(org_id)
        org_name = f"Organization {org_id}"
    elif not dry_run:
        # Get default organization if no org_id specified
        try:
            from sqlalchemy import select

            from app.config import settings
            from app.core.database.models import Organization

            async with database_service.get_session() as session:
                # Try to get default organization
                if settings.default_org_id:
                    result = await session.execute(
                        select(Organization).where(Organization.id == settings.default_org_id)
                    )
                    default_org = result.scalar_one_or_none()
                else:
                    # Get first organization
                    result = await session.execute(select(Organization).limit(1))
                    default_org = result.scalar_one_or_none()

                if default_org:
                    org_to_create = str(default_org.id)
                    org_name = default_org.name
                else:
                    logger.warning("\nNo default organization found. Skipping folder creation.")
                    logger.warning("Run 'python -m app.commands.seed --create-admin' to create one.")

        except Exception as e:
            logger.error(f"Failed to get default organization: {e}")

    # Create folders for the organization
    if org_to_create:
        logger.info(f"\nCreating folder structure for organization: {org_name} ({org_to_create})")

        # Create in uploads bucket (primary storage)
        logger.info(f"\n{minio.bucket_uploads}:")
        await create_org_folder_structure(minio, minio.bucket_uploads, org_to_create, dry_run)

        # Create in processed bucket (extracted content)
        logger.info(f"\n{minio.bucket_processed}:")
        await create_org_folder_structure(minio, minio.bucket_processed, org_to_create, dry_run)

        # Create in temp bucket (temporary files)
        logger.info(f"\n{minio.bucket_temp}:")
        await create_org_folder_structure(minio, minio.bucket_temp, org_to_create, dry_run)

    logger.info("\n✓ Storage structure recreated")


async def cleanup_storage(
    org_id: Optional[UUID] = None,
    bucket: Optional[str] = None,
    force: bool = False,
    dry_run: bool = False,
    skip_recreate: bool = False,
    include_scrape: bool = False,
):
    """
    Clean up storage and artifacts, then recreate bucket structure.

    Args:
        org_id: Optional organization ID to limit scope
        bucket: Optional bucket name to limit scope
        force: Skip confirmation prompt
        dry_run: Show what would be deleted without actually deleting
        skip_recreate: Skip recreation of bucket structure (cleanup only)
        include_scrape: Also delete web scraping database records (ScrapedAssets, etc.)
    """

    # Get MinIO service
    minio = get_minio_service()
    if not minio or not minio.enabled:
        logger.error("MinIO is not enabled. Cannot cleanup storage.")
        return 1

    # Confirm operation (unless force or dry-run)
    if not dry_run and not force:
        if not confirm_cleanup(org_id, bucket, include_scrape):
            logger.info("Cleanup cancelled by user")
            return 0

    logger.info("\n" + "=" * 70)
    logger.info("Starting storage cleanup...")
    if include_scrape:
        logger.info("(Including web scraping database records)")
    logger.info("=" * 70 + "\n")

    total_objects = 0
    total_artifacts = 0
    total_assets = 0
    scrape_counts = {}

    # Determine which buckets to clean
    buckets_to_clean = []
    if bucket:
        buckets_to_clean.append(bucket)
    else:
        # Clean all standard buckets
        buckets_to_clean = [
            "curatore-uploads",
            "curatore-processed",
            "curatore-temp",
        ]

    # Clean MinIO buckets
    logger.info("Cleaning MinIO buckets...")
    for bucket_name in buckets_to_clean:
        try:
            logger.info(f"\nBucket: {bucket_name}")
            count = await cleanup_minio_bucket(minio, bucket_name, org_id, dry_run)
            total_objects += count
            logger.info(f"  {'Would delete' if dry_run else 'Deleted'} {count} objects")
        except Exception as e:
            logger.error(f"  Failed: {e}")

    # Clean database artifacts
    logger.info("\n\nCleaning artifact records...")
    async with database_service.get_session() as session:
        total_artifacts = await cleanup_artifacts(session, org_id, bucket, dry_run)

    # Clean up web scraping records if requested
    if include_scrape:
        logger.info("\nCleaning web scraping database records...")
        async with database_service.get_session() as session:
            scrape_counts = await cleanup_scrape_records(session, org_id, dry_run)

    # Reset asset hashes (only for non-scrape assets if scrape cleanup was done)
    logger.info("\nResetting asset file_hash values...")
    async with database_service.get_session() as session:
        total_assets = await reset_asset_hashes(session, org_id, dry_run)

    # Recreate storage structure (unless skipped or bucket-specific cleanup)
    if not skip_recreate and not bucket:
        await recreate_storage_structure(minio, org_id, dry_run)

    # Summary
    logger.info("\n" + "=" * 70)
    logger.info("Cleanup complete" if not dry_run else "Dry run complete")
    logger.info("=" * 70)
    logger.info(f"  Objects {'would be' if dry_run else ''} deleted: {total_objects}")
    logger.info(f"  Artifacts {'would be' if dry_run else ''} deleted: {total_artifacts}")
    logger.info(f"  Assets {'would be' if dry_run else ''} reset: {total_assets}")
    if include_scrape and scrape_counts:
        logger.info(f"  Scraped assets {'would be' if dry_run else ''} deleted: {scrape_counts.get('scraped_assets', 0)}")
        logger.info(f"  Scrape-related assets {'would be' if dry_run else ''} deleted: {scrape_counts.get('assets', 0)}")
    if not skip_recreate and not bucket:
        logger.info(f"  Buckets {'would be' if dry_run else ''} recreated: {len(buckets_to_clean)}")
    logger.info("=" * 70 + "\n")

    return 0


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Clean up object storage and artifact records (DESTRUCTIVE)"
    )
    parser.add_argument(
        "--org-id",
        type=UUID,
        help="Limit cleanup to specific organization"
    )
    parser.add_argument(
        "--bucket",
        type=str,
        help="Limit cleanup to specific bucket"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip confirmation prompt"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without actually deleting"
    )
    parser.add_argument(
        "--skip-recreate",
        action="store_true",
        help="Skip recreation of bucket structure (cleanup only)"
    )
    parser.add_argument(
        "--scrape",
        action="store_true",
        help="Also delete web scraping database records (ScrapedAssets, Assets, Runs)"
    )

    args = parser.parse_args()

    exit_code = asyncio.run(
        cleanup_storage(
            org_id=args.org_id,
            bucket=args.bucket,
            force=args.force,
            dry_run=args.dry_run,
            skip_recreate=args.skip_recreate,
            include_scrape=args.scrape,
        )
    )
    sys.exit(exit_code)
