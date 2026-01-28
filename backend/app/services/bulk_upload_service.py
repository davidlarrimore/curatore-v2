"""
Bulk Upload Analysis Service for Phase 2.

This service provides functionality to analyze bulk file uploads and detect:
- Unchanged files (same filename + content hash)
- Updated files (same filename, different content hash)
- New files (filename not seen before in organization)
- Missing files (in database but not in upload batch)

The service enables efficient document collection updates without data loss.
"""

import hashlib
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import Asset, AssetVersion
from .asset_service import asset_service


logger = logging.getLogger("curatore.services.bulk_upload")


class BulkUploadAnalysis:
    """Result of analyzing a bulk upload against existing assets."""

    def __init__(self):
        self.unchanged: List[Dict] = []  # Files that match existing assets
        self.updated: List[Dict] = []  # Files with same name but different content
        self.new: List[Dict] = []  # Files not seen before
        self.missing: List[Dict] = []  # Assets in DB but not in upload

    def to_dict(self) -> Dict:
        """Convert analysis to dictionary format."""
        return {
            "unchanged": self.unchanged,
            "updated": self.updated,
            "new": self.new,
            "missing": self.missing,
            "counts": {
                "unchanged": len(self.unchanged),
                "updated": len(self.updated),
                "new": len(self.new),
                "missing": len(self.missing),
                "total_uploaded": len(self.unchanged) + len(self.updated) + len(self.new),
            },
        }


class BulkUploadService:
    """
    Service for analyzing and processing bulk file uploads.

    Provides functionality to detect changes in document collections and
    update assets accordingly while maintaining full version history.
    """

    @staticmethod
    def compute_file_hash(file_path: Path) -> str:
        """
        Compute SHA-256 hash of a file.

        Args:
            file_path: Path to file

        Returns:
            Hex-encoded SHA-256 hash
        """
        sha256_hash = hashlib.sha256()
        with file_path.open("rb") as f:
            # Read in chunks for memory efficiency
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    @staticmethod
    def compute_file_hash_from_bytes(file_bytes: bytes) -> str:
        """
        Compute SHA-256 hash from file bytes.

        Args:
            file_bytes: File content as bytes

        Returns:
            Hex-encoded SHA-256 hash
        """
        return hashlib.sha256(file_bytes).hexdigest()

    async def analyze_bulk_upload(
        self,
        session: AsyncSession,
        organization_id: UUID,
        files: List[Tuple[str, bytes]],  # List of (filename, content) tuples
        source_type: str = "upload",
    ) -> BulkUploadAnalysis:
        """
        Analyze bulk file upload against existing assets.

        Compares uploaded files with existing assets in the organization
        to detect unchanged, updated, new, and missing files.

        Args:
            session: Database session
            organization_id: Organization ID
            files: List of (filename, file_bytes) tuples
            source_type: Source type for filtering existing assets

        Returns:
            BulkUploadAnalysis with categorized files

        Example:
            >>> files = [("doc1.pdf", pdf_bytes), ("doc2.pdf", pdf_bytes2)]
            >>> analysis = await bulk_upload_service.analyze_bulk_upload(
            ...     session, org_id, files
            ... )
            >>> print(f"New: {analysis.counts['new']}, Updated: {analysis.counts['updated']}")
        """
        analysis = BulkUploadAnalysis()

        # Build index of uploaded files by filename
        uploaded_files = {}
        for filename, file_bytes in files:
            file_hash = self.compute_file_hash_from_bytes(file_bytes)
            file_size = len(file_bytes)
            uploaded_files[filename] = {
                "filename": filename,
                "file_hash": file_hash,
                "file_size": file_size,
                "file_bytes": file_bytes,
            }

        # Get all existing assets for this organization and source type
        stmt = select(Asset).where(
            Asset.organization_id == organization_id,
            Asset.source_type == source_type,
        )
        result = await session.execute(stmt)
        existing_assets = result.scalars().all()

        # Build index of existing assets by filename
        existing_by_filename = {}
        for asset in existing_assets:
            existing_by_filename[asset.original_filename] = {
                "asset_id": str(asset.id),
                "filename": asset.original_filename,
                "file_hash": asset.file_hash,
                "file_size": asset.file_size,
                "status": asset.status,
                "current_version": asset.current_version_number,
                "created_at": asset.created_at.isoformat(),
                "updated_at": asset.updated_at.isoformat(),
            }

        # Categorize uploaded files
        for filename, upload_info in uploaded_files.items():
            if filename not in existing_by_filename:
                # New file
                analysis.new.append({
                    "filename": filename,
                    "file_size": upload_info["file_size"],
                    "file_hash": upload_info["file_hash"],
                })
            else:
                existing_info = existing_by_filename[filename]
                if upload_info["file_hash"] == existing_info["file_hash"]:
                    # Unchanged file
                    analysis.unchanged.append({
                        "filename": filename,
                        "file_size": upload_info["file_size"],
                        "file_hash": upload_info["file_hash"],
                        "asset_id": existing_info["asset_id"],
                        "current_version": existing_info["current_version"],
                    })
                else:
                    # Updated file
                    analysis.updated.append({
                        "filename": filename,
                        "file_size": upload_info["file_size"],
                        "file_hash": upload_info["file_hash"],
                        "old_file_hash": existing_info["file_hash"],
                        "asset_id": existing_info["asset_id"],
                        "current_version": existing_info["current_version"],
                    })

        # Identify missing files (in DB but not in upload)
        uploaded_filenames = set(uploaded_files.keys())
        for filename, existing_info in existing_by_filename.items():
            if filename not in uploaded_filenames:
                analysis.missing.append({
                    "filename": filename,
                    "file_size": existing_info["file_size"],
                    "file_hash": existing_info["file_hash"],
                    "asset_id": existing_info["asset_id"],
                    "current_version": existing_info["current_version"],
                    "status": existing_info["status"],
                })

        logger.info(
            "Bulk upload analysis complete: %d unchanged, %d updated, %d new, %d missing",
            len(analysis.unchanged),
            len(analysis.updated),
            len(analysis.new),
            len(analysis.missing),
        )

        return analysis

    async def apply_bulk_upload(
        self,
        session: AsyncSession,
        organization_id: UUID,
        files: List[Tuple[str, bytes]],
        user_id: Optional[UUID],
        source_type: str = "upload",
        mark_missing_inactive: bool = True,
    ) -> Dict:
        """
        Apply bulk upload changes based on analysis.

        This method:
        1. Creates new assets for new files
        2. Creates new versions for updated files
        3. Optionally marks missing files as inactive
        4. Triggers automatic re-extraction for new/updated assets

        Args:
            session: Database session
            organization_id: Organization ID
            files: List of (filename, file_bytes) tuples
            user_id: User performing the upload
            source_type: Source type for new assets
            mark_missing_inactive: If True, mark missing assets as inactive

        Returns:
            Dict with summary of applied changes and asset IDs

        Example:
            >>> result = await bulk_upload_service.apply_bulk_upload(
            ...     session, org_id, files, user_id
            ... )
            >>> print(f"Created {result['created_count']} new assets")
        """
        # First analyze the upload
        analysis = await self.analyze_bulk_upload(
            session=session,
            organization_id=organization_id,
            files=files,
            source_type=source_type,
        )

        created_assets = []
        updated_assets = []
        marked_inactive = []

        # TODO: Actual file upload to object storage and asset creation
        # This will be implemented in the next step when we wire up the API endpoint
        # For now, we just return the analysis

        logger.info(
            "Bulk upload would create %d assets, update %d assets, mark %d inactive",
            len(analysis.new),
            len(analysis.updated),
            len(analysis.missing) if mark_missing_inactive else 0,
        )

        return {
            "analysis": analysis.to_dict(),
            "created_assets": created_assets,
            "updated_assets": updated_assets,
            "marked_inactive": marked_inactive,
            "summary": {
                "created_count": len(created_assets),
                "updated_count": len(updated_assets),
                "marked_inactive_count": len(marked_inactive),
            },
        }


# Global service instance
bulk_upload_service = BulkUploadService()
