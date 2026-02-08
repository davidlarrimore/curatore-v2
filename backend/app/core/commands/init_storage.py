#!/usr/bin/env python3
# backend/app/commands/init_storage.py
"""
Object storage initialization command for Curatore v2.

Creates required MinIO/S3 buckets and sets lifecycle policies for automatic retention.
This should be run after starting MinIO to ensure buckets exist before document processing.

Usage:
    # Initialize storage (creates buckets and sets lifecycle policies)
    python -m app.commands.init_storage

    # Force re-initialization (recreates buckets even if they exist)
    python -m app.commands.init_storage --force

    # Or run directly
    python backend/app/commands/init_storage.py

Environment Variables Required:
    - USE_OBJECT_STORAGE=true
    - MINIO_ENDPOINT: MinIO server endpoint (e.g., minio:9000)
    - MINIO_ACCESS_KEY: MinIO access key
    - MINIO_SECRET_KEY: MinIO secret key
    - MINIO_BUCKET_UPLOADS: Uploads bucket name
    - MINIO_BUCKET_PROCESSED: Processed files bucket name
    - MINIO_BUCKET_TEMP: Temporary files bucket name

Example:
    export USE_OBJECT_STORAGE=true
    export MINIO_ENDPOINT=minio:9000
    export MINIO_ACCESS_KEY=admin
    export MINIO_SECRET_KEY=changeme
    python -m app.commands.init_storage

Note:
    - MinIO must be running and accessible before running this command
    - Lifecycle policies control automatic file deletion based on retention periods
    - Buckets will not be deleted if they already exist (safe to run multiple times)
"""

import argparse
import logging
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.config import settings
from app.core.storage.minio_service import get_minio_service

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)


def init_storage(force: bool = False) -> int:
    """
    Initialize object storage buckets and lifecycle policies.

    Args:
        force: If True, recreates buckets even if they exist

    Returns:
        0 on success, 1 on failure
    """
    logger.info("Initializing object storage...")

    # Check if object storage is enabled
    if not settings.use_object_storage:
        logger.error("ERROR: Object storage is not enabled")
        logger.error("Set USE_OBJECT_STORAGE=true in .env and configure MinIO/S3 settings")
        return 1

    # Get MinIO service
    try:
        minio = get_minio_service()
    except Exception as e:
        logger.error(f"ERROR: Failed to initialize MinIO service: {e}")
        logger.error("Check your MinIO configuration in .env")
        return 1

    if not minio or not minio.enabled:
        logger.error("ERROR: MinIO service is not enabled or configured")
        logger.error("Set USE_OBJECT_STORAGE=true and configure MinIO/S3 settings in .env")
        return 1

    # Check MinIO connectivity
    try:
        # Test connection by listing buckets
        minio.client.list_buckets()
        logger.info(f"✓ Connected to MinIO at {minio.endpoint}")
    except Exception as e:
        logger.error(f"ERROR: Cannot connect to MinIO at {minio.endpoint}")
        logger.error(f"Error: {e}")
        logger.error("Ensure MinIO is running and accessible")
        return 1

    # Create buckets
    buckets = [
        (minio.bucket_uploads, 30, "Uploads bucket (30 day retention)"),
        (minio.bucket_processed, 90, "Processed files bucket (90 day retention)"),
        (minio.bucket_temp, 7, "Temporary files bucket (7 day retention)"),
    ]

    for bucket_name, retention_days, description in buckets:
        try:
            # Check if bucket exists
            if minio.client.bucket_exists(bucket_name):
                if force:
                    logger.warning(f"Bucket {bucket_name} already exists, recreating (--force)")
                    # Note: We don't actually delete and recreate to avoid data loss
                    # Just update the lifecycle policy
                else:
                    logger.info(f"✓ Bucket {bucket_name} already exists")
            else:
                logger.info(f"Creating bucket: {bucket_name}")
                minio.ensure_bucket_exists(bucket_name)
                logger.info(f"✓ Created bucket: {bucket_name}")

            # Set lifecycle policy for automatic retention
            logger.info(f"Setting lifecycle policy ({retention_days} days) for {bucket_name}")
            minio.set_lifecycle_policy(bucket_name, expiration_days=retention_days)
            logger.info(f"✓ Lifecycle policy set: {description}")

        except Exception as e:
            logger.error(f"ERROR: Failed to create/configure bucket {bucket_name}: {e}")
            return 1

    # Success summary
    logger.info("\n" + "="*70)
    logger.info("Object storage initialized successfully!")
    logger.info("="*70)
    logger.info(f"  • Uploads bucket:   {minio.bucket_uploads} (30 day retention)")
    logger.info(f"  • Processed bucket: {minio.bucket_processed} (90 day retention)")
    logger.info(f"  • Temp bucket:      {minio.bucket_temp} (7 day retention)")
    logger.info("="*70)
    logger.info("\nYou can now upload and process documents using the object storage system.")

    return 0


def main():
    """Main entry point for the command."""
    parser = argparse.ArgumentParser(
        description="Initialize object storage for Curatore v2",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-initialization (updates lifecycle policies even if buckets exist)"
    )

    args = parser.parse_args()

    try:
        exit_code = init_storage(force=args.force)
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"ERROR: Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
