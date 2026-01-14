# ============================================================================
# Curatore v2 - Deduplication Service
# ============================================================================
"""
Content-based file deduplication service with reference counting.

This service provides:
- SHA-256 content hashing for duplicate detection
- Content-addressable storage (dedupe/)
- Reference counting for shared files
- Symlink or copy strategies for deduplication
- Storage savings metrics and reporting

Deduplication Flow:
    1. Calculate file hash on upload
    2. Check if hash exists in dedupe store
    3. If exists: Create symlink/reference to existing file (save storage)
    4. If new: Store in dedupe store and create initial reference
    5. Update reference count in refs.json
    6. On file deletion: Decrement ref count, delete dedupe file if refs = 0

Directory Structure:
    /app/files/dedupe/
    └── {hash[:2]}/                     # First 2 chars of SHA-256 (sharding)
        └── {hash}/                     # Full hash directory
            ├── content.ext             # Actual file content (stored once)
            └── refs.json               # Reference count and document IDs

Reference Tracking (refs.json):
    {
        "hash": "abc123...",
        "original_filename": "document.pdf",
        "file_size": 1048576,
        "created_at": "2026-01-13T10:00:00Z",
        "reference_count": 3,
        "references": [
            {
                "document_id": "doc1",
                "organization_id": "org1",
                "created_at": "2026-01-13T10:00:00Z"
            }
        ]
    }

Usage:
    from app.services.deduplication_service import deduplication_service

    # Calculate hash and check for duplicates
    hash_value = await deduplication_service.calculate_file_hash(file_path)
    existing = await deduplication_service.find_duplicate_by_hash(hash_value)

    # Store deduplicated file
    if existing:
        ref_path = await deduplication_service.add_reference(
            hash_value, document_id, organization_id
        )
    else:
        ref_path = await deduplication_service.store_deduplicated_file(
            file_path, hash_value, document_id, organization_id
        )
"""

import hashlib
import json
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from app.config import settings

logger = logging.getLogger(__name__)


class DeduplicationService:
    """
    Content-based file deduplication service.

    This service manages duplicate file detection and storage optimization
    using SHA-256 hashing and content-addressable storage. It maintains
    reference counts to ensure files are only deleted when all references
    are removed.

    Attributes:
        settings: Application settings instance
    """

    def __init__(self):
        """Initialize the deduplication service."""
        self.settings = settings

    async def calculate_file_hash(
        self,
        file_path: Path,
        algorithm: Optional[str] = None,
    ) -> str:
        """
        Calculate content hash of a file using streaming to handle large files.

        Args:
            file_path: Path to file
            algorithm: Hash algorithm (defaults to config setting)

        Returns:
            Hex digest of file content hash

        Raises:
            IOError: If file cannot be read

        Example:
            >>> hash_value = await deduplication_service.calculate_file_hash(
            ...     Path("/app/files/uploaded/doc-123_report.pdf")
            ... )
            >>> print(hash_value)
            'a1b2c3d4e5f6...'
        """
        if algorithm is None:
            algorithm = self.settings.dedupe_hash_algorithm

        hash_func = hashlib.new(algorithm)

        try:
            with open(file_path, "rb") as f:
                # Read in chunks to handle large files efficiently
                while chunk := f.read(8192):
                    hash_func.update(chunk)

            hex_digest = hash_func.hexdigest()
            logger.debug(f"Calculated {algorithm} hash for {file_path}: {hex_digest[:16]}...")
            return hex_digest

        except IOError as e:
            logger.error(f"Failed to calculate hash for {file_path}: {e}")
            raise

    def get_dedupe_path(self, hash_value: str) -> Path:
        """
        Get the content-addressable path for a file hash.

        Uses first 2 characters of hash for sharding to prevent
        too many files in a single directory.

        Args:
            hash_value: File content hash (hex string)

        Returns:
            Path to dedupe storage directory for this hash

        Example:
            >>> path = deduplication_service.get_dedupe_path("abc123...")
            >>> print(path)
            /app/files/dedupe/ab/abc123.../
        """
        shard = hash_value[:2]
        return self.settings.dedupe_path / shard / hash_value

    def get_dedupe_content_path(self, hash_value: str, extension: str = "") -> Path:
        """
        Get the path to the actual content file in dedupe storage.

        Args:
            hash_value: File content hash
            extension: File extension (e.g., ".pdf")

        Returns:
            Path to content file

        Example:
            >>> path = deduplication_service.get_dedupe_content_path(
            ...     "abc123...", ".pdf"
            ... )
            >>> print(path)
            /app/files/dedupe/ab/abc123.../content.pdf
        """
        dedupe_dir = self.get_dedupe_path(hash_value)
        filename = f"content{extension}"
        return dedupe_dir / filename

    def get_dedupe_refs_path(self, hash_value: str) -> Path:
        """
        Get the path to the reference tracking file.

        Args:
            hash_value: File content hash

        Returns:
            Path to refs.json file

        Example:
            >>> path = deduplication_service.get_dedupe_refs_path("abc123...")
            >>> print(path)
            /app/files/dedupe/ab/abc123.../refs.json
        """
        dedupe_dir = self.get_dedupe_path(hash_value)
        return dedupe_dir / "refs.json"

    async def find_duplicate_by_hash(self, hash_value: str) -> Optional[Path]:
        """
        Check if a file with this hash already exists in dedupe storage.

        Args:
            hash_value: File content hash

        Returns:
            Path to existing deduplicated file, or None if not found

        Example:
            >>> existing = await deduplication_service.find_duplicate_by_hash(
            ...     "abc123..."
            ... )
            >>> if existing:
            ...     print(f"Duplicate found: {existing}")
        """
        refs_path = self.get_dedupe_refs_path(hash_value)

        if not refs_path.exists():
            return None

        # Find the content file
        dedupe_dir = self.get_dedupe_path(hash_value)
        content_files = list(dedupe_dir.glob("content.*"))

        if content_files:
            logger.debug(f"Found existing deduplicated file: {content_files[0]}")
            return content_files[0]

        return None

    async def store_deduplicated_file(
        self,
        file_path: Path,
        hash_value: str,
        document_id: str,
        organization_id: Optional[str],
        original_filename: Optional[str] = None,
    ) -> Path:
        """
        Store a new file in dedupe storage and create initial reference.

        Args:
            file_path: Path to source file
            hash_value: Calculated file hash
            document_id: Document UUID
            organization_id: Organization UUID (None for shared)
            original_filename: Original filename for metadata

        Returns:
            Path to deduplicated content file

        Raises:
            IOError: If file cannot be stored

        Example:
            >>> content_path = await deduplication_service.store_deduplicated_file(
            ...     file_path=Path("/tmp/upload.pdf"),
            ...     hash_value="abc123...",
            ...     document_id="doc-456",
            ...     organization_id="org-789",
            ...     original_filename="report.pdf"
            ... )
        """
        # Create dedupe directory
        dedupe_dir = self.get_dedupe_path(hash_value)
        dedupe_dir.mkdir(parents=True, exist_ok=True)

        # Determine file extension
        extension = file_path.suffix
        content_path = self.get_dedupe_content_path(hash_value, extension)

        try:
            # Copy file to dedupe storage
            shutil.copy2(file_path, content_path)
            logger.info(f"Stored deduplicated file: {content_path}")

            # Create initial reference tracking
            file_size = file_path.stat().st_size
            refs_data = {
                "hash": hash_value,
                "original_filename": original_filename or file_path.name,
                "file_size": file_size,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "reference_count": 1,
                "references": [
                    {
                        "document_id": document_id,
                        "organization_id": organization_id,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    }
                ],
            }

            refs_path = self.get_dedupe_refs_path(hash_value)
            refs_path.write_text(json.dumps(refs_data, indent=2))
            logger.info(f"Created reference tracking: {refs_path}")

            return content_path

        except IOError as e:
            logger.error(f"Failed to store deduplicated file: {e}")
            raise

    async def add_reference(
        self,
        hash_value: str,
        document_id: str,
        organization_id: Optional[str],
    ) -> Optional[Path]:
        """
        Add a reference to an existing deduplicated file.

        Args:
            hash_value: File content hash
            document_id: Document UUID
            organization_id: Organization UUID (None for shared)

        Returns:
            Path to deduplicated content file, or None if not found

        Example:
            >>> content_path = await deduplication_service.add_reference(
            ...     hash_value="abc123...",
            ...     document_id="doc-new",
            ...     organization_id="org-789"
            ... )
        """
        refs_path = self.get_dedupe_refs_path(hash_value)

        if not refs_path.exists():
            logger.warning(f"Cannot add reference to non-existent dedupe file: {hash_value}")
            return None

        try:
            # Read existing references
            refs_data = json.loads(refs_path.read_text())

            # Check if reference already exists
            for ref in refs_data.get("references", []):
                if ref["document_id"] == document_id:
                    logger.debug(f"Reference already exists: {document_id}")
                    # Return existing content path
                    dedupe_dir = self.get_dedupe_path(hash_value)
                    content_files = list(dedupe_dir.glob("content.*"))
                    return content_files[0] if content_files else None

            # Add new reference
            refs_data["references"].append(
                {
                    "document_id": document_id,
                    "organization_id": organization_id,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            refs_data["reference_count"] = len(refs_data["references"])

            # Write updated references
            refs_path.write_text(json.dumps(refs_data, indent=2))
            logger.info(
                f"Added reference to deduplicated file: {document_id} "
                f"(total refs: {refs_data['reference_count']})"
            )

            # Return content path
            dedupe_dir = self.get_dedupe_path(hash_value)
            content_files = list(dedupe_dir.glob("content.*"))
            return content_files[0] if content_files else None

        except (IOError, json.JSONDecodeError) as e:
            logger.error(f"Failed to add reference: {e}")
            return None

    async def remove_reference(
        self,
        hash_value: str,
        document_id: str,
    ) -> bool:
        """
        Remove a reference to a deduplicated file.

        Returns True if the file should be deleted (no more references),
        False otherwise.

        Args:
            hash_value: File content hash
            document_id: Document UUID

        Returns:
            True if file has no more references and should be deleted

        Example:
            >>> should_delete = await deduplication_service.remove_reference(
            ...     hash_value="abc123...",
            ...     document_id="doc-456"
            ... )
            >>> if should_delete:
            ...     print("No more references, can delete dedupe file")
        """
        refs_path = self.get_dedupe_refs_path(hash_value)

        if not refs_path.exists():
            logger.debug(f"Reference file not found: {refs_path}")
            return True  # File doesn't exist, so it can be "deleted"

        try:
            # Read existing references
            refs_data = json.loads(refs_path.read_text())

            # Remove reference
            original_count = len(refs_data.get("references", []))
            refs_data["references"] = [
                ref for ref in refs_data.get("references", [])
                if ref["document_id"] != document_id
            ]
            new_count = len(refs_data["references"])
            refs_data["reference_count"] = new_count

            if new_count == 0:
                # No more references, delete everything
                logger.info(f"No more references for {hash_value}, deleting dedupe files")
                dedupe_dir = self.get_dedupe_path(hash_value)
                if dedupe_dir.exists():
                    shutil.rmtree(dedupe_dir)
                return True
            else:
                # Still have references, update refs file
                refs_path.write_text(json.dumps(refs_data, indent=2))
                logger.info(
                    f"Removed reference {document_id} from {hash_value} "
                    f"({new_count} refs remaining)"
                )
                return False

        except (IOError, json.JSONDecodeError) as e:
            logger.error(f"Failed to remove reference: {e}")
            return False

    async def get_file_references(self, hash_value: str) -> Optional[Dict[str, Any]]:
        """
        Get all references to a deduplicated file.

        Args:
            hash_value: File content hash

        Returns:
            Reference data dictionary or None if not found

        Example:
            >>> refs = await deduplication_service.get_file_references("abc123...")
            >>> print(f"Reference count: {refs['reference_count']}")
        """
        refs_path = self.get_dedupe_refs_path(hash_value)

        if not refs_path.exists():
            return None

        try:
            refs_data = json.loads(refs_path.read_text())
            return refs_data
        except (IOError, json.JSONDecodeError) as e:
            logger.error(f"Failed to read references: {e}")
            return None

    async def get_deduplication_stats(
        self,
        organization_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get storage savings statistics from deduplication.

        Args:
            organization_id: Optional organization filter

        Returns:
            Dictionary with deduplication statistics

        Example:
            >>> stats = await deduplication_service.get_deduplication_stats("org-123")
            >>> print(f"Storage saved: {stats['storage_saved_bytes']} bytes")
            >>> print(f"Savings percentage: {stats['savings_percentage']:.1f}%")
        """
        dedupe_base = self.settings.dedupe_path

        if not dedupe_base.exists():
            return {
                "unique_files": 0,
                "total_references": 0,
                "duplicate_references": 0,
                "storage_used_bytes": 0,
                "storage_saved_bytes": 0,
                "savings_percentage": 0.0,
            }

        unique_files = 0
        total_references = 0
        storage_used = 0
        storage_saved = 0

        # Scan dedupe directory
        for shard_dir in dedupe_base.iterdir():
            if not shard_dir.is_dir():
                continue

            for hash_dir in shard_dir.iterdir():
                if not hash_dir.is_dir():
                    continue

                refs_path = hash_dir / "refs.json"
                if not refs_path.exists():
                    continue

                try:
                    refs_data = json.loads(refs_path.read_text())

                    # Filter by organization if specified
                    references = refs_data.get("references", [])
                    if organization_id:
                        references = [
                            ref for ref in references
                            if ref.get("organization_id") == organization_id
                        ]

                    if not references:
                        continue

                    unique_files += 1
                    ref_count = len(references)
                    total_references += ref_count

                    file_size = refs_data.get("file_size", 0)
                    storage_used += file_size
                    storage_saved += file_size * (ref_count - 1)

                except (IOError, json.JSONDecodeError) as e:
                    logger.error(f"Error reading refs file {refs_path}: {e}")
                    continue

        duplicate_references = total_references - unique_files
        total_potential_storage = storage_used + storage_saved
        savings_percentage = (
            (storage_saved / total_potential_storage * 100)
            if total_potential_storage > 0
            else 0.0
        )

        return {
            "unique_files": unique_files,
            "total_references": total_references,
            "duplicate_references": duplicate_references,
            "storage_used_bytes": storage_used,
            "storage_saved_bytes": storage_saved,
            "savings_percentage": savings_percentage,
        }

    async def should_deduplicate_file(self, file_path: Path) -> bool:
        """
        Check if a file should be deduplicated based on size threshold.

        Args:
            file_path: Path to file

        Returns:
            True if file should be deduplicated

        Example:
            >>> if await deduplication_service.should_deduplicate_file(file_path):
            ...     # Proceed with deduplication
        """
        if not self.settings.file_deduplication_enabled:
            return False

        try:
            file_size = file_path.stat().st_size
            return file_size >= self.settings.dedupe_min_file_size
        except OSError:
            return False

    async def create_reference_link(
        self,
        content_path: Path,
        target_path: Path,
    ) -> None:
        """
        Create a symlink or copy to deduplicated content.

        The strategy (symlink vs copy) is controlled by the
        file_deduplication_strategy config setting.

        Args:
            content_path: Path to deduplicated content file
            target_path: Path where reference should be created

        Raises:
            IOError: If link/copy cannot be created

        Example:
            >>> await deduplication_service.create_reference_link(
            ...     content_path=Path("/app/files/dedupe/ab/abc123.../content.pdf"),
            ...     target_path=Path("/app/files/organizations/org-123/batches/batch-456/uploaded/doc-789_report.pdf")
            ... )
        """
        strategy = self.settings.file_deduplication_strategy

        # Ensure parent directory exists
        target_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            if strategy == "symlink":
                # Create symbolic link
                if target_path.exists() or target_path.is_symlink():
                    target_path.unlink()
                os.symlink(content_path, target_path)
                logger.debug(f"Created symlink: {target_path} -> {content_path}")

            elif strategy == "copy":
                # Create a copy
                shutil.copy2(content_path, target_path)
                logger.debug(f"Copied deduplicated file to: {target_path}")

            else:
                logger.warning(f"Unknown deduplication strategy: {strategy}, using copy")
                shutil.copy2(content_path, target_path)

        except (IOError, OSError) as e:
            logger.error(f"Failed to create reference link: {e}")
            raise


# Global deduplication service instance
deduplication_service = DeduplicationService()
