#!/usr/bin/env python3
"""
Orphaned file cleanup script for MinIO object storage.

This script identifies and optionally deletes files in MinIO buckets that don't
have corresponding artifact records in the database. This helps recover storage
space from orphaned files left behind by failed operations or deleted records.

Usage:
    # Dry run (list orphaned files without deleting)
    python scripts/cleanup_orphaned_files.py

    # Delete orphaned files
    python scripts/cleanup_orphaned_files.py --delete

    # Specific bucket only
    python scripts/cleanup_orphaned_files.py --bucket curatore-uploads

Exit codes:
    0 - Success
    1 - Error occurred
    2 - Configuration error

Buckets checked:
    - curatore-uploads
    - curatore-processed
    - curatore-temp (always safe to clean up)
"""

import asyncio
import argparse
import sys
from pathlib import Path
from typing import Set, List, Tuple
from datetime import datetime

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from sqlalchemy import select
from app.services.database_service import database_service
from app.services.minio_service import get_minio_service
from app.database.models import Artifact


class OrphanedFileCleaner:
    """Clean up orphaned files in MinIO storage."""

    def __init__(self, dry_run: bool = True, bucket_filter: str = None):
        """
        Initialize cleaner.

        Args:
            dry_run: If True, only report orphaned files without deleting
            bucket_filter: If provided, only check this bucket
        """
        self.dry_run = dry_run
        self.bucket_filter = bucket_filter
        self.minio = get_minio_service()

        if not self.minio:
            raise RuntimeError("MinIO service not available. Check configuration.")

    async def get_artifact_keys(self) -> Set[Tuple[str, str]]:
        """
        Get all (bucket, object_key) pairs from artifacts table.

        Returns:
            Set of (bucket, object_key) tuples
        """
        print("\n📊 Loading artifact records from database...")

        artifact_keys = set()

        async with database_service.get_session() as session:
            result = await session.execute(
                select(Artifact.bucket, Artifact.object_key)
                .where(Artifact.status != "deleted")
            )
            artifacts = result.all()

            for bucket, object_key in artifacts:
                artifact_keys.add((bucket, object_key))

        print(f"   Found {len(artifact_keys)} artifact records")
        return artifact_keys

    def get_storage_objects(self, bucket: str) -> List[str]:
        """
        Get all object keys from a MinIO bucket.

        Args:
            bucket: Bucket name

        Returns:
            List of object keys
        """
        if not self.minio.bucket_exists(bucket):
            print(f"   ⚠️  Bucket '{bucket}' does not exist")
            return []

        objects = self.minio.list_objects(bucket, recursive=True)
        return [obj.object_name for obj in objects]

    async def find_orphaned_files(self) -> List[Tuple[str, str, int]]:
        """
        Find orphaned files in MinIO.

        Returns:
            List of (bucket, object_key, size) tuples for orphaned files
        """
        # Get artifact keys from database
        artifact_keys = await self.get_artifact_keys()

        # Determine which buckets to check
        if self.bucket_filter:
            buckets_to_check = [self.bucket_filter]
        else:
            buckets_to_check = [
                "curatore-uploads",
                "curatore-processed",
                "curatore-temp",
            ]

        orphaned = []

        for bucket in buckets_to_check:
            print(f"\n🔍 Scanning bucket '{bucket}'...")

            # Get all objects in bucket
            try:
                storage_objects = self.get_storage_objects(bucket)
                print(f"   Found {len(storage_objects)} objects in storage")

                # Find orphaned objects
                for object_key in storage_objects:
                    if (bucket, object_key) not in artifact_keys:
                        # Get object size
                        try:
                            stat = self.minio.stat_object(bucket, object_key)
                            size = stat.size
                        except Exception:
                            size = 0

                        orphaned.append((bucket, object_key, size))

                if orphaned:
                    bucket_orphaned = [o for o in orphaned if o[0] == bucket]
                    print(f"   ⚠️  Found {len(bucket_orphaned)} orphaned objects")
                else:
                    print(f"   ✓ No orphaned objects")

            except Exception as e:
                print(f"   ❌ Error scanning bucket: {e}")
                continue

        return orphaned

    def delete_orphaned_files(self, orphaned: List[Tuple[str, str, int]]) -> int:
        """
        Delete orphaned files from MinIO.

        Args:
            orphaned: List of (bucket, object_key, size) tuples

        Returns:
            Number of successfully deleted files
        """
        print(f"\n🗑️  Deleting {len(orphaned)} orphaned files...")

        deleted_count = 0
        failed_count = 0

        for bucket, object_key, size in orphaned:
            try:
                self.minio.delete_object(bucket, object_key)
                deleted_count += 1
                print(f"   ✓ Deleted: {bucket}/{object_key} ({format_size(size)})")
            except Exception as e:
                failed_count += 1
                print(f"   ❌ Failed to delete {bucket}/{object_key}: {e}")

        print(f"\n✅ Deleted: {deleted_count}")
        if failed_count > 0:
            print(f"❌ Failed: {failed_count}")

        return deleted_count

    async def run(self):
        """Run the cleanup process."""
        print("=" * 70)
        print("Orphaned File Cleanup for MinIO Storage")
        print("=" * 70)

        if self.dry_run:
            print("\n🔍 DRY RUN MODE - No files will be deleted")
        else:
            print("\n⚠️  DELETE MODE - Orphaned files will be permanently deleted")

        # Find orphaned files
        orphaned = await self.find_orphaned_files()

        if not orphaned:
            print("\n✅ SUCCESS: No orphaned files found!")
            return 0

        # Calculate total size
        total_size = sum(size for _, _, size in orphaned)

        print("\n" + "=" * 70)
        print(f"📋 Summary:")
        print(f"   Orphaned files: {len(orphaned)}")
        print(f"   Total size: {format_size(total_size)}")
        print("=" * 70)

        # Show sample of orphaned files
        print("\n🗂️  Sample orphaned files:")
        for bucket, object_key, size in orphaned[:10]:
            print(f"   - {bucket}/{object_key} ({format_size(size)})")

        if len(orphaned) > 10:
            print(f"   ... and {len(orphaned) - 10} more")

        if self.dry_run:
            print("\n💡 To delete these files, run with --delete flag")
            return 0
        else:
            # Delete orphaned files
            deleted_count = self.delete_orphaned_files(orphaned)

            if deleted_count == len(orphaned):
                print(f"\n✅ SUCCESS: All {deleted_count} orphaned files deleted")
                return 0
            else:
                print(f"\n⚠️  WARNING: Only {deleted_count}/{len(orphaned)} files deleted")
                return 1


def format_size(size_bytes: int) -> str:
    """Format byte size as human-readable string."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} PB"


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Clean up orphaned files in MinIO storage"
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Actually delete orphaned files (default is dry run)"
    )
    parser.add_argument(
        "--bucket",
        type=str,
        help="Only check specific bucket (e.g., curatore-uploads)"
    )

    args = parser.parse_args()

    try:
        cleaner = OrphanedFileCleaner(
            dry_run=not args.delete,
            bucket_filter=args.bucket
        )
        return await cleaner.run()

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
