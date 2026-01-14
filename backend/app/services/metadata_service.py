# ============================================================================
# Curatore v2 - Metadata Service
# ============================================================================
"""
Batch metadata management service for tracking file ages and retention.

This service manages metadata.json files for batch processing operations:
- Create/read/update batch metadata
- Track file creation and expiration timestamps
- Calculate retention periods
- Query expired batches for cleanup

Metadata Structure:
    {
        "batch_id": "uuid",
        "organization_id": "uuid",
        "created_at": "2026-01-13T10:00:00Z",
        "expires_at": "2026-01-27T10:00:00Z",
        "created_by": "user_id",
        "document_count": 10,
        "documents": [
            {
                "document_id": "doc-123",
                "filename": "report.pdf",
                "uploaded_at": "2026-01-13T10:00:00Z",
                "file_hash": "abc123..."
            }
        ],
        "status": "processing",
        "last_updated": "2026-01-13T10:05:00Z"
    }

Usage:
    from app.services.metadata_service import metadata_service

    # Create batch metadata
    metadata_service.create_batch_metadata(
        batch_id="batch-123",
        organization_id="org-456",
        created_by="user-789",
        documents=[...]
    )

    # Get expired batches for cleanup
    expired = metadata_service.get_expired_batches()
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from app.config import settings
from app.services.path_service import path_service

logger = logging.getLogger(__name__)


class MetadataService:
    """
    Batch metadata management service.

    This service handles creation, reading, and updating of metadata.json
    files for batch processing operations. It tracks file ages, expiration
    dates, and document counts for retention policy enforcement.

    Attributes:
        settings: Application settings instance
        path_service: Path resolution service
    """

    def __init__(self):
        """Initialize the metadata service."""
        self.settings = settings
        self.path_service = path_service

    def create_batch_metadata(
        self,
        batch_id: str,
        organization_id: Optional[str],
        created_by: Optional[str] = None,
        documents: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        """
        Create metadata file for a new batch.

        Args:
            batch_id: Unique batch identifier (UUID)
            organization_id: Organization UUID (None for shared)
            created_by: User ID who created the batch
            documents: List of document metadata dicts

        Returns:
            Created metadata dictionary

        Raises:
            IOError: If metadata file cannot be written

        Example:
            >>> metadata = metadata_service.create_batch_metadata(
            ...     batch_id="batch-123",
            ...     organization_id="org-456",
            ...     created_by="user-789",
            ...     documents=[{
            ...         "document_id": "doc-abc",
            ...         "filename": "report.pdf",
            ...         "uploaded_at": datetime.now(timezone.utc).isoformat()
            ...     }]
            ... )
            >>> metadata["document_count"]
            1
        """
        now = datetime.now(timezone.utc)
        retention_days = self.settings.file_retention_batch_days
        expires_at = now + timedelta(days=retention_days)

        metadata = {
            "batch_id": batch_id,
            "organization_id": organization_id,
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "created_by": created_by,
            "document_count": len(documents) if documents else 0,
            "documents": documents or [],
            "status": "created",
            "last_updated": now.isoformat(),
        }

        # Write metadata file
        metadata_path = self.path_service.get_batch_metadata_path(
            batch_id=batch_id,
            organization_id=organization_id,
            create_dirs=True,
        )

        try:
            metadata_path.write_text(json.dumps(metadata, indent=2))
            logger.info(f"Created batch metadata: {metadata_path}")
        except IOError as e:
            logger.error(f"Failed to write batch metadata: {e}")
            raise

        return metadata

    def get_batch_metadata(
        self,
        batch_id: str,
        organization_id: Optional[str],
    ) -> Optional[dict[str, Any]]:
        """
        Read batch metadata from file.

        Args:
            batch_id: Unique batch identifier
            organization_id: Organization UUID (None for shared)

        Returns:
            Metadata dictionary or None if not found

        Example:
            >>> metadata = metadata_service.get_batch_metadata(
            ...     batch_id="batch-123",
            ...     organization_id="org-456"
            ... )
            >>> print(metadata["status"])
            'completed'
        """
        metadata_path = self.path_service.get_batch_metadata_path(
            batch_id=batch_id,
            organization_id=organization_id,
            create_dirs=False,
        )

        if not metadata_path.exists():
            logger.debug(f"Batch metadata not found: {metadata_path}")
            return None

        try:
            content = metadata_path.read_text()
            metadata = json.loads(content)
            return metadata
        except (IOError, json.JSONDecodeError) as e:
            logger.error(f"Failed to read batch metadata: {e}")
            return None

    def update_batch_metadata(
        self,
        batch_id: str,
        organization_id: Optional[str],
        updates: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """
        Update existing batch metadata.

        Args:
            batch_id: Unique batch identifier
            organization_id: Organization UUID (None for shared)
            updates: Dictionary of fields to update

        Returns:
            Updated metadata dictionary or None if batch not found

        Example:
            >>> metadata = metadata_service.update_batch_metadata(
            ...     batch_id="batch-123",
            ...     organization_id="org-456",
            ...     updates={"status": "completed", "document_count": 10}
            ... )
        """
        # Read existing metadata
        metadata = self.get_batch_metadata(batch_id, organization_id)
        if not metadata:
            logger.warning(f"Cannot update non-existent batch metadata: {batch_id}")
            return None

        # Apply updates
        metadata.update(updates)
        metadata["last_updated"] = datetime.now(timezone.utc).isoformat()

        # Write updated metadata
        metadata_path = self.path_service.get_batch_metadata_path(
            batch_id=batch_id,
            organization_id=organization_id,
            create_dirs=False,
        )

        try:
            metadata_path.write_text(json.dumps(metadata, indent=2))
            logger.info(f"Updated batch metadata: {metadata_path}")
        except IOError as e:
            logger.error(f"Failed to update batch metadata: {e}")
            return None

        return metadata

    def add_document_to_batch(
        self,
        batch_id: str,
        organization_id: Optional[str],
        document_metadata: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """
        Add a document to batch metadata.

        Args:
            batch_id: Unique batch identifier
            organization_id: Organization UUID (None for shared)
            document_metadata: Document metadata dict

        Returns:
            Updated metadata dictionary or None if batch not found

        Example:
            >>> metadata = metadata_service.add_document_to_batch(
            ...     batch_id="batch-123",
            ...     organization_id="org-456",
            ...     document_metadata={
            ...         "document_id": "doc-new",
            ...         "filename": "new-file.pdf",
            ...         "uploaded_at": datetime.now(timezone.utc).isoformat()
            ...     }
            ... )
        """
        metadata = self.get_batch_metadata(batch_id, organization_id)
        if not metadata:
            return None

        # Add document
        metadata["documents"].append(document_metadata)
        metadata["document_count"] = len(metadata["documents"])
        metadata["last_updated"] = datetime.now(timezone.utc).isoformat()

        # Write updated metadata
        metadata_path = self.path_service.get_batch_metadata_path(
            batch_id=batch_id,
            organization_id=organization_id,
            create_dirs=False,
        )

        try:
            metadata_path.write_text(json.dumps(metadata, indent=2))
            logger.info(f"Added document to batch metadata: {metadata_path}")
        except IOError as e:
            logger.error(f"Failed to update batch metadata: {e}")
            return None

        return metadata

    def get_expired_batches(
        self,
        organization_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """
        Get all batches that have exceeded their retention period.

        Args:
            organization_id: Optional organization filter (None for all orgs)

        Returns:
            List of expired batch metadata dictionaries

        Example:
            >>> expired = metadata_service.get_expired_batches()
            >>> for batch in expired:
            ...     print(f"Batch {batch['batch_id']} expired at {batch['expires_at']}")
        """
        now = datetime.now(timezone.utc)
        expired_batches = []

        # Determine search scope
        if organization_id:
            org_paths = [self.path_service.resolve_organization_path(organization_id)]
        else:
            # Search all organizations
            base_path = self.settings.files_root_path
            org_base = base_path / "organizations"
            shared_base = base_path / "shared"

            org_paths = []
            if org_base.exists():
                org_paths.extend(org_base.iterdir())
            if shared_base.exists():
                org_paths.append(shared_base)

        # Scan for metadata files
        for org_path in org_paths:
            if not org_path.exists() or not org_path.is_dir():
                continue

            batches_path = org_path / "batches"
            if not batches_path.exists():
                continue

            # Check each batch folder
            for batch_path in batches_path.iterdir():
                if not batch_path.is_dir():
                    continue

                metadata_file = batch_path / "metadata.json"
                if not metadata_file.exists():
                    continue

                try:
                    content = metadata_file.read_text()
                    metadata = json.loads(content)

                    # Check expiration
                    expires_at_str = metadata.get("expires_at")
                    if expires_at_str:
                        expires_at = datetime.fromisoformat(expires_at_str)
                        if expires_at < now:
                            expired_batches.append(metadata)
                            logger.debug(
                                f"Found expired batch: {metadata['batch_id']} "
                                f"(expired: {expires_at_str})"
                            )
                except (IOError, json.JSONDecodeError, ValueError) as e:
                    logger.error(f"Error reading metadata file {metadata_file}: {e}")
                    continue

        logger.info(f"Found {len(expired_batches)} expired batches")
        return expired_batches

    def is_batch_expired(
        self,
        batch_id: str,
        organization_id: Optional[str],
    ) -> bool:
        """
        Check if a batch has exceeded its retention period.

        Args:
            batch_id: Unique batch identifier
            organization_id: Organization UUID (None for shared)

        Returns:
            True if batch is expired, False otherwise

        Example:
            >>> if metadata_service.is_batch_expired("batch-123", "org-456"):
            ...     print("Batch is ready for cleanup")
        """
        metadata = self.get_batch_metadata(batch_id, organization_id)
        if not metadata:
            return False

        expires_at_str = metadata.get("expires_at")
        if not expires_at_str:
            return False

        try:
            expires_at = datetime.fromisoformat(expires_at_str)
            now = datetime.now(timezone.utc)
            return expires_at < now
        except ValueError as e:
            logger.error(f"Invalid expires_at format: {e}")
            return False

    def calculate_expiration_date(
        self,
        created_at: Optional[datetime] = None,
        retention_days: Optional[int] = None,
    ) -> datetime:
        """
        Calculate expiration date based on creation time and retention policy.

        Args:
            created_at: Creation timestamp (defaults to now)
            retention_days: Retention period (defaults to config setting)

        Returns:
            Expiration datetime

        Example:
            >>> expires = metadata_service.calculate_expiration_date(
            ...     created_at=datetime.now(timezone.utc),
            ...     retention_days=14
            ... )
        """
        if created_at is None:
            created_at = datetime.now(timezone.utc)

        if retention_days is None:
            retention_days = self.settings.file_retention_batch_days

        return created_at + timedelta(days=retention_days)

    def delete_batch_metadata(
        self,
        batch_id: str,
        organization_id: Optional[str],
    ) -> bool:
        """
        Delete batch metadata file.

        Args:
            batch_id: Unique batch identifier
            organization_id: Organization UUID (None for shared)

        Returns:
            True if deleted, False if not found

        Example:
            >>> success = metadata_service.delete_batch_metadata(
            ...     batch_id="batch-123",
            ...     organization_id="org-456"
            ... )
        """
        metadata_path = self.path_service.get_batch_metadata_path(
            batch_id=batch_id,
            organization_id=organization_id,
            create_dirs=False,
        )

        if not metadata_path.exists():
            logger.debug(f"Batch metadata not found for deletion: {metadata_path}")
            return False

        try:
            metadata_path.unlink()
            logger.info(f"Deleted batch metadata: {metadata_path}")
            return True
        except IOError as e:
            logger.error(f"Failed to delete batch metadata: {e}")
            return False


# Global metadata service instance
metadata_service = MetadataService()
