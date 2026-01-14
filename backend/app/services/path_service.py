# ============================================================================
# Curatore v2 - Path Service
# ============================================================================
"""
Unified path resolution service for hierarchical file organization.

This service provides organization-aware path management with support for:
- Multi-tenant isolation (organization-based folders)
- Batch and adhoc file grouping
- Backward compatibility with legacy flat structure
- Automatic directory creation
- Filename sanitization

Directory Structure:
    /app/files/
    ├── organizations/
    │   └── {organization_id}/
    │       ├── batches/{batch_id}/
    │       │   ├── uploaded/
    │       │   ├── processed/
    │       │   └── metadata.json
    │       └── adhoc/
    │           ├── uploaded/
    │           └── processed/
    ├── shared/  # For unauthenticated mode
    │   ├── batches/{batch_id}/...
    │   └── adhoc/...
    ├── dedupe/  # Content-addressable storage
    └── temp/    # Temporary processing files

Usage:
    from app.services.path_service import path_service

    # Get upload path for a document
    path = path_service.get_document_path(
        document_id="abc123",
        organization_id="org-uuid",
        batch_id="batch-uuid",
        file_type="uploaded",
        filename="document.pdf"
    )

    # Sanitize filenames
    safe_name = path_service.sanitize_filename("My Document (1).pdf")
    # Returns: "My_Document_1.pdf"
"""

import logging
import re
from pathlib import Path
from typing import Literal, Optional

from app.config import settings

logger = logging.getLogger(__name__)

FileType = Literal["uploaded", "processed"]


class PathService:
    """
    Unified path resolution service for hierarchical file organization.

    This service centralizes all file path logic, providing:
    - Organization-aware path construction
    - Batch vs. adhoc distinction
    - Backward compatibility fallback
    - Automatic directory creation
    - Filename sanitization

    Attributes:
        settings: Application settings instance
    """

    def __init__(self):
        """Initialize the path service."""
        self.settings = settings

    def get_document_path(
        self,
        document_id: str,
        organization_id: Optional[str],
        batch_id: Optional[str],
        file_type: FileType,
        filename: str,
        create_dirs: bool = True,
    ) -> Path:
        """
        Get the full path for a document file in hierarchical storage.

        This method constructs the appropriate path based on organization,
        batch grouping, and file type. It automatically handles the
        organization/shared distinction and creates directories if needed.

        Args:
            document_id: Unique document identifier (UUID)
            organization_id: Organization UUID (None for shared)
            batch_id: Batch UUID (None for adhoc)
            file_type: Type of file ("uploaded" or "processed")
            filename: Original filename (will be sanitized)
            create_dirs: Whether to create parent directories

        Returns:
            Path object pointing to the document file location

        Example:
            >>> path_service.get_document_path(
            ...     document_id="doc-123",
            ...     organization_id="org-456",
            ...     batch_id="batch-789",
            ...     file_type="uploaded",
            ...     filename="report.pdf"
            ... )
            Path('/app/files/organizations/org-456/batches/batch-789/uploaded/doc-123_report.pdf')

            >>> path_service.get_document_path(
            ...     document_id="doc-abc",
            ...     organization_id=None,
            ...     batch_id=None,
            ...     file_type="processed",
            ...     filename="output.md"
            ... )
            Path('/app/files/shared/adhoc/processed/doc-abc_output.md')
        """
        if not self.settings.use_hierarchical_storage:
            # Fallback to legacy flat structure
            return self._get_legacy_path(document_id, file_type, filename)

        # Resolve organization path (organizations/{id} or shared)
        org_path = self.resolve_organization_path(organization_id)

        # Determine batch or adhoc
        if batch_id:
            group_path = org_path / "batches" / batch_id
        else:
            group_path = org_path / "adhoc"

        # Add file type subdirectory
        type_path = group_path / file_type

        # Create directories if requested
        if create_dirs:
            type_path.mkdir(parents=True, exist_ok=True)

        # Sanitize filename and prepend document ID
        safe_filename = self.sanitize_filename(filename)
        final_filename = f"{document_id}_{safe_filename}"

        return type_path / final_filename

    def resolve_organization_path(self, organization_id: Optional[str]) -> Path:
        """
        Resolve the organization-specific base path.

        Returns the organization folder for authenticated requests or
        the shared folder for unauthenticated/default organization mode.

        Args:
            organization_id: Organization UUID or None for shared

        Returns:
            Path to organization's base directory

        Example:
            >>> path_service.resolve_organization_path("org-123")
            Path('/app/files/organizations/org-123')

            >>> path_service.resolve_organization_path(None)
            Path('/app/files/shared')
        """
        base_path = self.settings.files_root_path

        if organization_id:
            return base_path / "organizations" / organization_id
        else:
            return base_path / "shared"

    def get_batch_metadata_path(
        self,
        batch_id: str,
        organization_id: Optional[str],
        create_dirs: bool = True,
    ) -> Path:
        """
        Get the path to a batch's metadata file.

        Args:
            batch_id: Batch UUID
            organization_id: Organization UUID (None for shared)
            create_dirs: Whether to create parent directories

        Returns:
            Path to metadata.json file

        Example:
            >>> path_service.get_batch_metadata_path("batch-123", "org-456")
            Path('/app/files/organizations/org-456/batches/batch-123/metadata.json')
        """
        org_path = self.resolve_organization_path(organization_id)
        batch_path = org_path / "batches" / batch_id

        if create_dirs:
            batch_path.mkdir(parents=True, exist_ok=True)

        return batch_path / "metadata.json"

    def get_temp_job_path(
        self,
        job_id: str,
        create_dirs: bool = True,
    ) -> Path:
        """
        Get the temporary processing directory for a job.

        Args:
            job_id: Job UUID
            create_dirs: Whether to create the directory

        Returns:
            Path to job's temp directory

        Example:
            >>> path_service.get_temp_job_path("job-789")
            Path('/app/files/temp/job-789')
        """
        temp_path = self.settings.temp_path / job_id

        if create_dirs:
            temp_path.mkdir(parents=True, exist_ok=True)

        return temp_path

    def sanitize_filename(self, filename: str) -> str:
        """
        Sanitize a filename for safe filesystem storage.

        This method:
        - Removes unsafe characters
        - Replaces spaces with underscores
        - Limits length to 255 characters
        - Preserves file extension
        - Handles edge cases (empty names, dots, etc.)

        Args:
            filename: Original filename

        Returns:
            Sanitized filename safe for filesystem

        Example:
            >>> path_service.sanitize_filename("My Document (1).pdf")
            'My_Document_1.pdf'

            >>> path_service.sanitize_filename("../../../etc/passwd")
            'etc_passwd'

            >>> path_service.sanitize_filename("file:with:colons.txt")
            'filewithcolons.txt'
        """
        if not filename:
            return "unnamed"

        # Remove path traversal attempts
        filename = filename.replace("..", "")

        # Remove or replace unsafe characters
        # Keep: letters, numbers, dots, hyphens, underscores
        filename = re.sub(r'[^\w\s\.-]', '', filename)

        # Replace spaces with underscores
        filename = filename.replace(' ', '_')

        # Remove leading/trailing dots and spaces
        filename = filename.strip('. ')

        # Handle empty result
        if not filename:
            return "unnamed"

        # Limit length (reserve space for extension)
        if len(filename) > 255:
            # Try to preserve extension
            parts = filename.rsplit('.', 1)
            if len(parts) == 2:
                name, ext = parts
                max_name_len = 255 - len(ext) - 1
                filename = f"{name[:max_name_len]}.{ext}"
            else:
                filename = filename[:255]

        return filename

    def find_file_with_fallback(
        self,
        document_id: str,
        organization_id: Optional[str],
        batch_id: Optional[str],
        file_type: FileType,
        filename: str,
    ) -> Optional[Path]:
        """
        Find a file in hierarchical storage with fallback to legacy structure.

        This method first checks the hierarchical path, then falls back to
        the legacy flat structure for backward compatibility. This allows
        gradual migration without breaking existing references.

        Args:
            document_id: Unique document identifier
            organization_id: Organization UUID (None for shared)
            batch_id: Batch UUID (None for adhoc)
            file_type: Type of file ("uploaded" or "processed")
            filename: Original filename

        Returns:
            Path to the file if found, None otherwise

        Example:
            >>> path = path_service.find_file_with_fallback(
            ...     document_id="doc-123",
            ...     organization_id="org-456",
            ...     batch_id=None,
            ...     file_type="uploaded",
            ...     filename="document.pdf"
            ... )
            >>> print(path)
            /app/files/organizations/org-456/adhoc/uploaded/doc-123_document.pdf
        """
        # Try hierarchical structure first
        if self.settings.use_hierarchical_storage:
            hierarchical_path = self.get_document_path(
                document_id=document_id,
                organization_id=organization_id,
                batch_id=batch_id,
                file_type=file_type,
                filename=filename,
                create_dirs=False,
            )

            if hierarchical_path.exists():
                logger.debug(f"Found file in hierarchical structure: {hierarchical_path}")
                return hierarchical_path

        # Fallback to legacy structure
        legacy_path = self._get_legacy_path(document_id, file_type, filename)
        if legacy_path.exists():
            logger.debug(f"Found file in legacy structure: {legacy_path}")
            return legacy_path

        logger.warning(
            f"File not found in hierarchical or legacy structure: "
            f"document_id={document_id}, file_type={file_type}, filename={filename}"
        )
        return None

    def _get_legacy_path(
        self,
        document_id: str,
        file_type: FileType,
        filename: str,
    ) -> Path:
        """
        Get the legacy flat structure path for backward compatibility.

        Args:
            document_id: Unique document identifier
            file_type: Type of file ("uploaded" or "processed")
            filename: Original filename

        Returns:
            Path in legacy flat structure
        """
        if file_type == "uploaded":
            base_dir = self.settings.upload_path
        else:  # processed
            base_dir = self.settings.processed_path

        safe_filename = self.sanitize_filename(filename)
        final_filename = f"{document_id}_{safe_filename}"

        return base_dir / final_filename

    def list_organization_files(
        self,
        organization_id: Optional[str],
        batch_id: Optional[str] = None,
        file_type: Optional[FileType] = None,
    ) -> list[Path]:
        """
        List all files for an organization, optionally filtered by batch and type.

        Args:
            organization_id: Organization UUID (None for shared)
            batch_id: Optional batch UUID filter
            file_type: Optional file type filter ("uploaded" or "processed")

        Returns:
            List of Path objects for matching files

        Example:
            >>> files = path_service.list_organization_files(
            ...     organization_id="org-123",
            ...     batch_id="batch-456",
            ...     file_type="uploaded"
            ... )
            >>> len(files)
            42
        """
        org_path = self.resolve_organization_path(organization_id)

        if not org_path.exists():
            return []

        files = []

        # Determine search scope
        if batch_id:
            search_paths = [org_path / "batches" / batch_id]
        else:
            # Search both batches and adhoc
            search_paths = [
                org_path / "batches",
                org_path / "adhoc",
            ]

        # Collect files
        for search_path in search_paths:
            if not search_path.exists():
                continue

            if file_type:
                # Search specific file type
                type_paths = [search_path / file_type]
            else:
                # Search all file types
                type_paths = [
                    search_path / "uploaded",
                    search_path / "processed",
                ]

            for type_path in type_paths:
                if type_path.exists():
                    files.extend(type_path.rglob("*"))

        # Filter out directories
        return [f for f in files if f.is_file()]


# Global path service instance
path_service = PathService()
