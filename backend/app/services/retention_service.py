# ============================================================================
# Curatore v2 - Retention Service
# ============================================================================
"""
Scheduled file cleanup service with deduplication awareness.

This service handles:
- Scheduled cleanup of expired files based on retention policies
- Respect for active job locks (never delete files with active jobs)
- Deduplication-aware cleanup (decrement ref counts, delete when refs = 0)
- Batch processing of deletions
- Dry-run mode for testing
- Comprehensive logging of all cleanup operations

Retention Policies:
    - Uploaded files: configurable days (default: 7)
    - Processed files: configurable days (default: 30)
    - Batch files: configurable days (default: 14)
    - Temp files: configurable hours (default: 24)

Usage:
    from app.services.retention_service import retention_service

    # Find expired files
    expired = await retention_service.find_expired_files()

    # Cleanup expired files
    result = await retention_service.cleanup_expired_files(dry_run=False)
    print(f"Deleted {result['deleted_count']} files")
"""

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import settings
from app.services.deduplication_service import deduplication_service
from app.services.metadata_service import metadata_service
from app.services.path_service import path_service

logger = logging.getLogger(__name__)


class RetentionService:
    """
    Scheduled file cleanup service with deduplication awareness.

    This service manages the lifecycle of files based on retention policies,
    ensuring expired files are deleted while respecting active jobs and
    properly handling deduplicated files with reference counting.

    Attributes:
        settings: Application settings instance
    """

    def __init__(self):
        """Initialize the retention service."""
        self.settings = settings

    async def find_expired_files(
        self,
        organization_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Find all files that have exceeded their retention period.

        Args:
            organization_id: Optional organization filter

        Returns:
            List of expired file metadata dictionaries

        Example:
            >>> expired = await retention_service.find_expired_files()
            >>> for file in expired:
            ...     print(f"Expired: {file['path']}, age: {file['age_days']} days")
        """
        expired_files = []
        now = datetime.now(timezone.utc)

        # Determine search scope
        if organization_id:
            org_paths = [path_service.resolve_organization_path(organization_id)]
        else:
            # Search all organizations
            base_path = self.settings.files_root_path
            org_base = base_path / "organizations"
            shared_base = base_path / "shared"

            org_paths = []
            if org_base.exists():
                org_paths.extend([p for p in org_base.iterdir() if p.is_dir()])
            if shared_base.exists():
                org_paths.append(shared_base)

        # Scan each organization
        for org_path in org_paths:
            if not org_path.exists():
                continue

            # Check batches
            batches_path = org_path / "batches"
            if batches_path.exists():
                for batch_dir in batches_path.iterdir():
                    if not batch_dir.is_dir():
                        continue

                    # Check if batch is expired based on metadata
                    metadata_file = batch_dir / "metadata.json"
                    if metadata_file.exists():
                        try:
                            import json
                            metadata = json.loads(metadata_file.read_text())
                            expires_at_str = metadata.get("expires_at")

                            if expires_at_str:
                                expires_at = datetime.fromisoformat(expires_at_str)
                                if expires_at < now:
                                    # Batch is expired, mark all files in it
                                    for file_type in ["uploaded", "processed"]:
                                        type_dir = batch_dir / file_type
                                        if type_dir.exists():
                                            for file_path in type_dir.iterdir():
                                                if file_path.is_file():
                                                    expired_files.append({
                                                        "path": file_path,
                                                        "type": file_type,
                                                        "batch_id": batch_dir.name,
                                                        "organization_id": org_path.name if org_path.name != "shared" else None,
                                                        "expires_at": expires_at_str,
                                                        "age_days": (now - expires_at).days,
                                                    })

                        except Exception as e:
                            logger.error(f"Error reading batch metadata {metadata_file}: {e}")

            # Check adhoc files
            adhoc_path = org_path / "adhoc"
            if adhoc_path.exists():
                for file_type in ["uploaded", "processed"]:
                    type_dir = adhoc_path / file_type
                    if not type_dir.exists():
                        continue

                    # Determine retention period based on file type
                    if file_type == "uploaded":
                        retention_days = self.settings.file_retention_uploaded_days
                    else:  # processed
                        retention_days = self.settings.file_retention_processed_days

                    # Check each file's age
                    for file_path in type_dir.iterdir():
                        if not file_path.is_file():
                            continue

                        try:
                            # Get file modification time
                            mtime = datetime.fromtimestamp(file_path.stat().st_mtime, tz=timezone.utc)
                            expires_at = mtime + timedelta(days=retention_days)

                            if expires_at < now:
                                expired_files.append({
                                    "path": file_path,
                                    "type": file_type,
                                    "batch_id": None,
                                    "organization_id": org_path.name if org_path.name != "shared" else None,
                                    "expires_at": expires_at.isoformat(),
                                    "age_days": (now - mtime).days,
                                })

                        except Exception as e:
                            logger.error(f"Error checking file {file_path}: {e}")

        # Check temp files
        temp_base = self.settings.temp_path
        if temp_base.exists():
            retention_hours = self.settings.file_retention_temp_hours

            for temp_dir in temp_base.iterdir():
                if not temp_dir.is_dir():
                    continue

                try:
                    mtime = datetime.fromtimestamp(temp_dir.stat().st_mtime, tz=timezone.utc)
                    expires_at = mtime + timedelta(hours=retention_hours)

                    if expires_at < now:
                        expired_files.append({
                            "path": temp_dir,
                            "type": "temp",
                            "batch_id": None,
                            "organization_id": None,
                            "expires_at": expires_at.isoformat(),
                            "age_hours": (now - mtime).total_seconds() / 3600,
                        })

                except Exception as e:
                    logger.error(f"Error checking temp directory {temp_dir}: {e}")

        logger.info(f"Found {len(expired_files)} expired files")
        return expired_files

    async def is_file_active(
        self,
        document_id: str,
    ) -> bool:
        """
        Check if a file has an active job running.

        Args:
            document_id: Document UUID

        Returns:
            True if file has active job, False otherwise

        Example:
            >>> is_active = await retention_service.is_file_active("doc-123")
            >>> if not is_active:
            ...     # Safe to delete
        """
        try:
            # Import here to avoid circular dependency
            from app.services.job_service import job_service

            # Check if there's an active job for this document
            job_status = job_service.get_job_by_document(document_id)
            if job_status:
                status = job_status.get("status", "")
                # Don't delete if job is PENDING or STARTED
                if status in ["PENDING", "STARTED"]:
                    logger.debug(f"Document {document_id} has active job: {status}")
                    return True

            return False

        except Exception as e:
            logger.error(f"Error checking active job for {document_id}: {e}")
            # Err on the side of caution - consider it active if we can't check
            return True

    async def cleanup_deduplicated_file(
        self,
        file_path: Path,
        document_id: Optional[str] = None,
    ) -> bool:
        """
        Handle cleanup of a deduplicated file with reference counting.

        Args:
            file_path: Path to file (may be symlink)
            document_id: Document UUID (extracted from filename if None)

        Returns:
            True if cleanup was successful

        Example:
            >>> success = await retention_service.cleanup_deduplicated_file(
            ...     file_path=Path("/app/files/organizations/org-123/adhoc/uploaded/doc-456_report.pdf"),
            ...     document_id="doc-456"
            ... )
        """
        try:
            # Extract document ID from filename if not provided
            if not document_id:
                filename = file_path.name
                if "_" in filename:
                    document_id = filename.split("_")[0]

            # Check if file is a symlink (deduplicated)
            if file_path.is_symlink():
                # Resolve to get hash from dedupe path
                resolved = file_path.resolve()

                if "dedupe" in str(resolved):
                    # Extract hash from path (parent directory name)
                    hash_value = resolved.parent.name

                    # Remove reference
                    should_delete_dedupe = await deduplication_service.remove_reference(
                        hash_value=hash_value,
                        document_id=document_id,
                    )

                    logger.info(
                        f"Removed deduplication reference for {document_id} "
                        f"(hash: {hash_value[:16]}..., delete_dedupe: {should_delete_dedupe})"
                    )

                # Delete the symlink
                file_path.unlink()
                logger.info(f"Deleted symlink: {file_path}")
                return True

            else:
                # Regular file, just delete
                file_path.unlink()
                logger.info(f"Deleted file: {file_path}")
                return True

        except Exception as e:
            logger.error(f"Error cleaning up deduplicated file {file_path}: {e}")
            return False

    async def cleanup_expired_files(
        self,
        dry_run: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        Delete all expired files with deduplication awareness.

        Args:
            dry_run: If True, only report what would be deleted (defaults to config)

        Returns:
            Dictionary with cleanup statistics

        Example:
            >>> result = await retention_service.cleanup_expired_files(dry_run=True)
            >>> print(f"Would delete {result['would_delete_count']} files")

            >>> result = await retention_service.cleanup_expired_files(dry_run=False)
            >>> print(f"Deleted {result['deleted_count']} files")
        """
        if dry_run is None:
            dry_run = self.settings.file_cleanup_dry_run

        if not self.settings.file_cleanup_enabled and not dry_run:
            logger.warning("File cleanup is disabled in settings")
            return {
                "enabled": False,
                "message": "File cleanup is disabled",
            }

        start_time = datetime.now(timezone.utc)
        logger.info(f"Starting file cleanup (dry_run={dry_run})")

        # Find expired files
        expired_files = await self.find_expired_files()

        deleted_count = 0
        skipped_count = 0
        error_count = 0
        batch_size = self.settings.file_cleanup_batch_size

        # Process in batches
        for i in range(0, len(expired_files), batch_size):
            batch = expired_files[i:i + batch_size]

            for file_info in batch:
                file_path = file_info["path"]
                document_id = None

                try:
                    # Extract document ID from filename
                    if file_path.is_file():
                        filename = file_path.name
                        if "_" in filename:
                            document_id = filename.split("_")[0]

                    # Check if file has active job
                    if document_id and await self.is_file_active(document_id):
                        logger.debug(f"Skipping active file: {file_path}")
                        skipped_count += 1
                        await self.log_cleanup_operation(
                            file_path=file_path,
                            reason="active_job",
                            deleted=False,
                        )
                        continue

                    if dry_run:
                        logger.info(f"[DRY RUN] Would delete: {file_path}")
                        deleted_count += 1
                    else:
                        # Handle deletion
                        if file_info["type"] == "temp":
                            # Temp directories - just remove the whole directory
                            import shutil
                            shutil.rmtree(file_path)
                            logger.info(f"Deleted temp directory: {file_path}")
                            deleted_count += 1
                        else:
                            # Regular files - handle deduplication
                            success = await self.cleanup_deduplicated_file(
                                file_path=file_path,
                                document_id=document_id,
                            )

                            if success:
                                deleted_count += 1
                                await self.log_cleanup_operation(
                                    file_path=file_path,
                                    reason="expired",
                                    deleted=True,
                                )
                            else:
                                error_count += 1

                except Exception as e:
                    logger.error(f"Error deleting file {file_path}: {e}")
                    error_count += 1

        # Cleanup expired batch metadata
        expired_batches = metadata_service.get_expired_batches()
        for batch_metadata in expired_batches:
            batch_id = batch_metadata.get("batch_id")
            organization_id = batch_metadata.get("organization_id")

            if batch_id and not dry_run:
                try:
                    metadata_service.delete_batch_metadata(
                        batch_id=batch_id,
                        organization_id=organization_id,
                    )
                    logger.info(f"Deleted expired batch metadata: {batch_id}")
                except Exception as e:
                    logger.error(f"Error deleting batch metadata {batch_id}: {e}")

        end_time = datetime.now(timezone.utc)
        duration = (end_time - start_time).total_seconds()

        result = {
            "dry_run": dry_run,
            "started_at": start_time.isoformat(),
            "completed_at": end_time.isoformat(),
            "duration_seconds": duration,
            "total_expired": len(expired_files),
            "deleted_count": deleted_count if not dry_run else 0,
            "would_delete_count": deleted_count if dry_run else 0,
            "skipped_count": skipped_count,
            "error_count": error_count,
            "expired_batches": len(expired_batches),
        }

        logger.info(
            f"Cleanup completed: deleted={result.get('deleted_count', 0)}, "
            f"skipped={skipped_count}, errors={error_count}, duration={duration:.2f}s"
        )

        return result

    async def log_cleanup_operation(
        self,
        file_path: Path,
        reason: str,
        deleted: bool,
    ) -> None:
        """
        Log a cleanup operation for audit purposes.

        Args:
            file_path: Path to file
            reason: Reason for cleanup (e.g., "expired", "active_job")
            deleted: Whether file was actually deleted

        Example:
            >>> await retention_service.log_cleanup_operation(
            ...     file_path=Path("/app/files/..."),
            ...     reason="expired",
            ...     deleted=True
            ... )
        """
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "file_path": str(file_path),
            "reason": reason,
            "deleted": deleted,
        }

        # Log to standard logger
        if deleted:
            logger.info(f"Cleanup: deleted {file_path} (reason: {reason})")
        else:
            logger.debug(f"Cleanup: skipped {file_path} (reason: {reason})")

        # Could also write to a cleanup audit log file here if needed


# Global retention service instance
retention_service = RetentionService()
