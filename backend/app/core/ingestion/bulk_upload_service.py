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
from typing import Dict, List, Tuple
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database.models import Asset
from app.core.shared.asset_service import asset_service

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
            # Skip assets without file_hash (indicates storage inconsistency)
            if not asset.file_hash:
                logger.error(
                    f"Asset {asset.id} ({asset.original_filename}) has no file_hash. "
                    "Storage may be inconsistent. Consider running storage cleanup: "
                    "./scripts/cleanup_storage.sh --dry-run"
                )
                continue

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
                    # Unchanged file (content matches)
                    analysis.unchanged.append({
                        "filename": filename,
                        "file_size": upload_info["file_size"],
                        "file_hash": upload_info["file_hash"],
                        "asset_id": existing_info["asset_id"],
                        "current_version": existing_info["current_version"],
                    })
                else:
                    # Updated file (content changed)
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

    async def mark_assets_inactive(
        self,
        session: AsyncSession,
        asset_ids: List[UUID],
    ) -> List[UUID]:
        """
        Mark assets as inactive (non-destructive).

        Updates asset status to 'inactive' without deleting any data.
        Preserves full history and allows reactivation if needed.

        Args:
            session: Database session
            asset_ids: List of asset IDs to mark inactive

        Returns:
            List of successfully marked asset IDs
        """
        marked = []
        for asset_id in asset_ids:
            asset = await asset_service.get_asset(session=session, asset_id=asset_id)
            if asset:
                # Update status to inactive
                asset.status = "inactive"
                session.add(asset)
                marked.append(asset_id)
                logger.info(f"Marked asset {asset_id} as inactive")

        return marked


# Global service instance
bulk_upload_service = BulkUploadService()
