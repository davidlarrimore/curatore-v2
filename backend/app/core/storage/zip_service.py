# ============================================================================
# backend/app/services/zip_service.py
# ============================================================================
#
# ZIP Archive Service for Curatore v2
#
# This module provides comprehensive ZIP archive creation functionality for
# bulk document downloads and exports. It supports multiple archive types
# including individual files, combined documents, and detailed processing
# summaries with metadata.
#
# Key Features:
#   - Individual document ZIP archives with basic summaries
#   - Combined markdown exports with adjusted header hierarchy
#   - Detailed processing summaries with quality metrics
#   - Temporary file management with automatic cleanup
#   - Flexible archive naming with timestamp generation
#   - Processing result integration for metadata
#   - RAG-ready file filtering and organization
#
# Archive Types:
#   1. Standard Archive: Individual processed files + summary
#   2. Combined Archive: Individual files + merged document + detailed summary
#   3. RAG-Ready Archive: Only files meeting quality thresholds
#   4. Custom Selection: User-specified document collections
#
# Author: Curatore v2 Development Team
# Version: 2.0.0
# ============================================================================

import os
import re
import zipfile
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple
from datetime import datetime
from io import BytesIO

from .storage_service import storage_service
from .minio_service import get_minio_service
from app.core.shared.artifact_service import artifact_service
from app.core.models import ProcessingResult, DownloadType


class ZipService:
    """
    Service for creating and managing ZIP archives of processed documents.

    This service provides multiple archive creation methods for different use cases,
    from simple individual file collections to complex combined exports with
    detailed processing summaries. All archives are created in the system
    temporary directory and include automatic cleanup mechanisms.

    Archive Organization:
        - Individual files are organized in subfolders (processed_documents/, individual_files/)
        - Combined exports include merged documents with adjusted header hierarchy
        - Summary files provide detailed processing statistics and quality metrics
        - Temporary files are automatically cleaned up after download

    Features:
        - Multiple archive types (individual, combined, RAG-ready)
        - Automatic filename generation with timestamps
        - Processing result integration for metadata
        - Header hierarchy adjustment for combined documents
        - Quality score integration and filtering
        - Comprehensive error handling and logging

    Attributes:
        minio: MinIO service instance for object storage access
    """

    def __init__(self):
        """
        Initialize the ZIP service with object storage access.

        Sets up the service to work with MinIO object storage for downloading
        processed markdown files. Files are downloaded from the processed bucket
        using artifact tracking from the database.
        """
        self.minio = get_minio_service()
        self._artifact_cache = {}  # Cache for artifacts by document_id

    def create_zip_archive(
        self,
        document_ids: List[str],
        zip_name: Optional[str] = None,
        include_summary: bool = True
    ) -> Tuple[str, int]:
        """
        Create a standard ZIP archive containing processed documents with optional summary.

        Creates a basic ZIP archive with processed markdown files organized in a
        'processed_documents' subfolder. Includes a basic processing summary if requested.
        This is the standard archive type for simple bulk downloads.

        Args:
            document_ids (List[str]): List of document IDs to include in the archive
            zip_name (Optional[str]): Custom name for the ZIP file. If None, generates
                                    timestamp-based name: curatore_export_{timestamp}.zip
            include_summary (bool): Whether to include a basic processing summary file

        Returns:
            Tuple[str, int]: Tuple containing:
                - str: Full path to the created ZIP file in temporary directory
                - int: Number of files successfully added to the archive

        Archive Structure:
            ```
            curatore_export_20250827_143022.zip
            +-- processed_documents/
            |   +-- document1.md
            |   +-- document2.md
            |   +-- document3.md
            +-- PROCESSING_SUMMARY_20250827_143022.md  # if include_summary=True
            ```

        File Naming:
            - Original filenames are restored by removing the document ID prefix
            - Example: "user_guide_abc123.md" becomes "user_guide.md" in archive
            - Preserves original file extensions and structure

        Error Handling:
            - Missing files are skipped with console logging
            - Invalid document IDs are ignored
            - Returns actual file count for verification

        Example:
            >>> zip_path, count = zip_service.create_zip_archive(
            >>>     document_ids=["doc1", "doc2", "doc3"],
            >>>     zip_name="my_export.zip",
            >>>     include_summary=True
            >>> )
            >>> print(f"Created archive with {count} files at {zip_path}")
        """
        if not zip_name:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            zip_name = f"curatore_export_{timestamp}.zip"
        elif not zip_name.endswith('.zip'):
            zip_name += '.zip'

        # Create temporary ZIP file
        temp_dir = tempfile.gettempdir()
        zip_path = os.path.join(temp_dir, zip_name)

        file_count = 0

        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # Add processed documents from MinIO
            for doc_id in document_ids:
                # Download file from object storage
                file_content, original_name = self._download_processed_file(doc_id)
                if file_content:
                    zipf.writestr(f"processed_documents/{original_name}", file_content)
                    file_count += 1

            # Add summary file if requested
            if include_summary and file_count > 0:
                summary_content = self._generate_zip_summary(document_ids, file_count)
                summary_filename = f"PROCESSING_SUMMARY_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
                zipf.writestr(summary_filename, summary_content)

        return zip_path, file_count

    def create_combined_markdown_zip(
        self,
        document_ids: List[str],
        results: List[ProcessingResult],
        zip_name: Optional[str] = None
    ) -> Tuple[str, int]:
        """
        Create a comprehensive ZIP archive with individual files, combined document, and detailed summary.

        Args:
            document_ids (List[str]): List of document IDs to include in the archive
            results (List[ProcessingResult]): Processing results for metadata and statistics
            zip_name (Optional[str]): Custom name for the ZIP file.

        Returns:
            Tuple[str, int]: Tuple containing:
                - str: Full path to the created ZIP file in temporary directory
                - int: Number of individual files successfully added to the archive
        """
        if not zip_name:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            zip_name = f"curatore_combined_export_{timestamp}.zip"
        elif not zip_name.endswith('.zip'):
            zip_name += '.zip'

        # Create temporary ZIP file
        temp_dir = tempfile.gettempdir()
        zip_path = os.path.join(temp_dir, zip_name)

        file_count = 0
        combined_sections = []

        # Generate combined markdown header
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        successful_results = [r for r in results if r.success]
        rag_flag = lambda r: getattr(r, 'pass_all_thresholds', getattr(r, 'is_rag_ready', False))
        rag_ready_results = [r for r in successful_results if rag_flag(r)]
        vector_optimized_results = [r for r in successful_results if r.vector_optimized]
        pass_rate = (len(rag_ready_results) / len(successful_results) * 100) if successful_results else 0

        combined_sections.extend([
            "# Curatore Processing Results - Combined Export",
            f"*Generated on {timestamp}*",
            "",
            "**Processing Summary:**",
            f"- Total Files: {len(successful_results)}",
            f"- RAG Ready: {len(rag_ready_results)} ({pass_rate:.1f}%)",
            f"- Vector Optimized: {len(vector_optimized_results)}",
            "",
            "---",
            ""
        ])

        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # Add individual processed documents from MinIO
            for doc_id in document_ids:
                # Download file from object storage
                file_content, original_name = self._download_processed_file(doc_id)
                if file_content:
                    try:
                        # Decode content for combined file
                        content = file_content if isinstance(file_content, str) else file_content.decode('utf-8')
                        result = next((r for r in results if r.document_id == doc_id), None)

                        # Add section header using result metadata when available
                        section_title = None
                        if result and getattr(result, 'filename', None):
                            section_title = result.filename
                        else:
                            # Use original filename as fallback
                            section_title = original_name
                        combined_sections.append(f"# {section_title}")

                        # Optional metadata when result is available
                        if result:
                            if result.document_summary:
                                combined_sections.extend(["", f"*{result.document_summary}*"])

                            status_emoji = "+" if rag_flag(result) else "!"
                            optimized_emoji = " *" if result.vector_optimized else ""

                            combined_sections.extend([
                                "",
                                f"**Processing Status:** {status_emoji} {'RAG Ready' if rag_flag(result) else 'Needs Improvement'}{optimized_emoji}",
                                f"**Conversion Score:** {result.conversion_score}/100",
                            ])

                            if result.llm_evaluation:
                                scores = [
                                    f"Clarity: {result.llm_evaluation.clarity_score or 'N/A'}/10",
                                    f"Completeness: {result.llm_evaluation.completeness_score or 'N/A'}/10",
                                    f"Relevance: {result.llm_evaluation.relevance_score or 'N/A'}/10",
                                    f"Markdown: {result.llm_evaluation.markdown_score or 'N/A'}/10",
                                ]
                                combined_sections.append(f"**Quality Scores:** {', '.join(scores)}")

                        combined_sections.extend(["", "---", ""])

                        # Adjust markdown hierarchy for combined document
                        adjusted_content = self._adjust_markdown_hierarchy(content)
                        combined_sections.extend([adjusted_content, "", "", "---", ""])

                    except Exception as e:
                        print(f"Error processing content for {doc_id}: {e}")

                    # Add to ZIP as individual file using original filename
                    zipf.writestr(f"individual_files/{original_name}", file_content)
                    file_count += 1

            # Add combined markdown file
            if combined_sections:
                combined_content = "\n".join(combined_sections)
                combined_filename = f"COMBINED_EXPORT_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
                zipf.writestr(combined_filename, combined_content)

            # Add summary file
            if file_count > 0:
                summary_content = self._generate_detailed_zip_summary(document_ids, results, file_count)
                summary_filename = f"PROCESSING_SUMMARY_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
                zipf.writestr(summary_filename, summary_content)

        return zip_path, file_count

    def _download_processed_file(self, doc_id: str) -> Tuple[Optional[str], str]:
        """
        Download the processed markdown file from object storage.

        Uses cached artifact information (populated by async caller) or falls back
        to storage service for in-memory results.

        Args:
            doc_id: The document ID to download the processed file for

        Returns:
            Tuple of (file_content, original_filename) where:
            - file_content: String content of the markdown file, or None if not found
            - original_filename: Original filename with .md extension
        """
        # Try to use cached artifact (populated by async caller)
        artifact = self._artifact_cache.get(doc_id)
        if artifact and self.minio and self.minio.enabled:
            try:
                # Download from MinIO using cached artifact
                file_obj = self.minio.get_object(artifact.bucket, artifact.object_key)
                if file_obj:
                    content = file_obj.read()
                    # Decode if bytes
                    if isinstance(content, bytes):
                        content = content.decode('utf-8')

                    # Get original filename
                    original_name = self._get_original_filename_from_artifact(doc_id, artifact)
                    return content, original_name
            except Exception as e:
                print(f"Error downloading from MinIO for {doc_id}: {e}")

        # Fallback: Try storage service for in-memory results
        result = storage_service.get_processing_result(doc_id)
        if result and result.markdown_content:
            filename = getattr(result, 'filename', f'{doc_id}.md')
            # Strip hash prefix and change extension
            clean_filename = self._strip_hash_prefix(filename)
            stem = Path(clean_filename).stem
            return result.markdown_content, f"{stem}.md"

        return None, f"{doc_id}.md"

    def _strip_hash_prefix(self, filename: str) -> str:
        """
        Strip the 32-character hex hash prefix from a filename.

        Backend stores files as {hash}_{original_name}. This method removes
        the hash prefix to restore the original filename for user-facing exports.

        Args:
            filename: Filename potentially containing a hash prefix

        Returns:
            Filename with hash prefix removed, or original if no prefix found

        Example:
            >>> self._strip_hash_prefix("abc123def456789012345678901234_My Document.pdf")
            "My Document.pdf"
            >>> self._strip_hash_prefix("regular_file.pdf")
            "regular_file.pdf"
        """
        if not filename:
            return filename

        # Match 32 hex characters followed by underscore at the start
        match = re.match(r'^[0-9a-f]{32}_(.+)$', filename, re.IGNORECASE)
        if match:
            return match.group(1)

        return filename

    def _get_original_filename_from_artifact(
        self,
        doc_id: str,
        artifact: "Artifact"
    ) -> str:
        """
        Get the original filename from an artifact record, with .md extension.

        Extracts the original filename from artifact metadata and cleans it.

        Args:
            doc_id: The document ID
            artifact: Artifact database record

        Returns:
            Original filename with .md extension (e.g., "My Report.md")
        """
        # Try to get original filename from artifact metadata
        original_filename = artifact.original_filename if hasattr(artifact, 'original_filename') else None

        # Try storage service if not found
        if not original_filename:
            stored_result = storage_service.get_processing_result(doc_id)
            if stored_result and getattr(stored_result, 'filename', None):
                original_filename = stored_result.filename

        # If we found an original filename, strip hash prefix and change extension to .md
        if original_filename:
            clean_filename = self._strip_hash_prefix(original_filename)
            stem = Path(clean_filename).stem
            return f"{stem}.md"

        # Fall back to document_id.md
        return f"{doc_id}.md"

    def _adjust_markdown_hierarchy(self, content: str) -> str:
        """
        Adjust markdown header hierarchy by adding one level of nesting.

        Modifies markdown headers to increase their nesting level by one (adds one #)
        to prevent conflicts when multiple documents are combined into a single file.

        Args:
            content (str): Original markdown content with existing headers

        Returns:
            str: Modified markdown content with adjusted header hierarchy
        """
        if not content:
            return content

        lines = content.split('\n')
        adjusted_lines = []

        for line in lines:
            # Check if line starts with markdown headers
            header_match = line.strip()
            if header_match.startswith('#') and not header_match.startswith('######'):
                # Find the header level
                header_level = 0
                for char in header_match:
                    if char == '#':
                        header_level += 1
                    else:
                        break

                if header_level < 6:  # Don't exceed maximum header depth
                    # Add one more # to increase nesting level
                    adjusted_line = '#' + line
                    adjusted_lines.append(adjusted_line)
                else:
                    adjusted_lines.append(line)
            else:
                adjusted_lines.append(line)

        return '\n'.join(adjusted_lines)

    def _generate_zip_summary(self, document_ids: List[str], file_count: int) -> str:
        """
        Generate a basic summary for standard ZIP archives.

        Args:
            document_ids (List[str]): List of document IDs included in the archive
            file_count (int): Number of files actually included in the archive

        Returns:
            str: Formatted markdown summary content
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        return f"""# Curatore Export Summary

**Export Details:**
- Generated: {timestamp}
- Documents Included: {file_count}
- Document IDs: {', '.join(document_ids)}

**Contents:**
- Individual processed markdown files in `processed_documents/` folder
- This summary file

**Usage:**
- Each `.md` file is ready for use in RAG systems
- Import into your vector database or knowledge base
- Files are optimized for semantic search and retrieval

---
*Generated by Curatore v2 - RAG Document Processing*
"""

    def _generate_detailed_zip_summary(
        self,
        document_ids: List[str],
        results: List[ProcessingResult],
        file_count: int
    ) -> str:
        """
        Generate a comprehensive summary with detailed processing results and quality metrics.

        Args:
            document_ids (List[str]): List of document IDs included in the archive
            results (List[ProcessingResult]): Processing results with quality metrics
            file_count (int): Number of files actually included in the archive

        Returns:
            str: Formatted markdown summary with detailed processing information
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        successful_results = [r for r in results if r.success]
        rag_flag = lambda r: getattr(r, 'pass_all_thresholds', getattr(r, 'is_rag_ready', False))
        rag_ready_results = [r for r in successful_results if rag_flag(r)]
        vector_optimized_results = [r for r in successful_results if r.vector_optimized]
        pass_rate = (len(rag_ready_results) / len(successful_results) * 100) if successful_results else 0

        summary_lines = [
            "# Curatore Export Summary",
            f"**Generated:** {timestamp}",
            "",
            "## Export Overview",
            f"- Total Files Included: {file_count}",
            f"- Successfully Processed: {len(successful_results)}",
            f"- RAG Ready Files: {len(rag_ready_results)}",
            f"- Vector Optimized Files: {len(vector_optimized_results)}",
            f"- Overall Pass Rate: {pass_rate:.1f}%",
            "",
            "## Archive Contents",
            "- `individual_files/` - Individual processed markdown files",
            "- `COMBINED_EXPORT_*.md` - All documents combined into single file",
            "- `PROCESSING_SUMMARY_*.md` - This summary file",
            "",
            "## Processing Results",
            ""
        ]

        # Add detailed results for each document
        for result in successful_results:
            status = "RAG Ready [OK]" if rag_flag(result) else "Needs Improvement [!]"
            optimization = "Vector Optimized [*]" if result.vector_optimized else "Standard Processing"

            summary_lines.extend([
                f"### {result.filename}",
                f"- **Status:** {status}",
                f"- **Processing:** {optimization}",
                f"- **Conversion Score:** {result.conversion_score}/100"
            ])

            if result.llm_evaluation:
                summary_lines.extend([
                    "- **Quality Scores:**",
                    f"  - Clarity: {result.llm_evaluation.clarity_score or 'N/A'}/10",
                    f"  - Completeness: {result.llm_evaluation.completeness_score or 'N/A'}/10",
                    f"  - Relevance: {result.llm_evaluation.relevance_score or 'N/A'}/10",
                    f"  - Markdown: {result.llm_evaluation.markdown_score or 'N/A'}/10"
                ])

            if result.document_summary:
                summary_lines.append(f"- **Summary:** {result.document_summary}")

            summary_lines.append("")

        summary_lines.extend([
            "## Usage Guidelines",
            "",
            "### For RAG Systems:",
            "1. Import RAG-ready files (marked with [OK]) directly into your vector database",
            "2. Use the combined export for bulk import operations",
            "3. Files marked as 'Vector Optimized' have enhanced chunking structure",
            "",
            "### For Manual Review:",
            "1. Review files marked with [!] before production use",
            "2. Check quality scores against your requirements",
            "3. Consider re-processing with adjusted thresholds if needed",
            "",
            "---",
            "*Generated by Curatore v2 - RAG Document Processing*"
        ])

        return "\n".join(summary_lines)

    def cleanup_zip_file(self, zip_path: str) -> bool:
        """
        Clean up temporary ZIP file after download completion.

        Args:
            zip_path (str): Full path to the ZIP file to be deleted

        Returns:
            bool: True if file was successfully deleted, False if deletion failed
        """
        try:
            if os.path.exists(zip_path):
                os.unlink(zip_path)
                return True
        except Exception as e:
            print(f"Error cleaning up ZIP file {zip_path}: {e}")
        return False

    def cleanup_all_temp_archives(self) -> int:
        """
        Remove Curatore-generated ZIP files from the system temporary directory.

        Returns:
            int: Number of ZIP files deleted.
        """
        temp_dir = Path(tempfile.gettempdir())
        patterns = [
            "curatore_export_*.zip",
            "curatore_combined_export_*.zip",
            "curatore_rag_ready_export*.zip",
            "curatore_selected_*.zip",
            "curatore_complete_*.zip",
        ]
        deleted = 0
        for pat in patterns:
            for p in temp_dir.glob(pat):
                try:
                    if p.is_file():
                        p.unlink()
                        deleted += 1
                except Exception:
                    continue
        return deleted

    # -------------------- v2 async helpers --------------------
    class ZipInfo:
        def __init__(self, zip_path: Path, file_count: int):
            self.zip_path = zip_path
            self.file_count = file_count

    async def create_bulk_download(
        self,
        document_ids: List[str],
        download_type: DownloadType,
        custom_filename: Optional[str] = None,
        include_summary: bool = True,
        include_combined: bool = False,
    ) -> "ZipService.ZipInfo":
        """
        v2-compatible bulk download helper that returns a ZipInfo with a Path.

        Supports 'individual', 'combined', and 'rag_ready' download types.
        """
        if not document_ids:
            raise ValueError("No document IDs provided")

        # Load artifacts for all documents into cache (for sync functions to use)
        from app.core.shared.database_service import database_service
        self._artifact_cache = {}
        try:
            async with database_service.get_session() as session:
                for doc_id in document_ids:
                    artifacts = await artifact_service.get_artifacts_by_document(
                        session, doc_id
                    )
                    # Filter for processed artifacts
                    processed = [a for a in artifacts if a.artifact_type == "processed"]
                    if processed:
                        self._artifact_cache[doc_id] = processed[0]  # Get first processed artifact
        except Exception as e:
            print(f"Failed to load artifacts: {e}")
            # Continue anyway - will fall back to storage service

        # Gather processing results for provided IDs
        results: List[ProcessingResult] = []
        for doc_id in document_ids:
            r = storage_service.get_processing_result(doc_id)
            if r and r.success:
                results.append(r)

        # Results may be empty when workers run in a different process.
        # We still allow archive creation using filesystem fallbacks.

        # Filter IDs based on type
        def is_rag_ready(r: ProcessingResult) -> bool:
            return bool(getattr(r, "is_rag_ready", getattr(r, "pass_all_thresholds", False)))

        if str(download_type) in {getattr(DownloadType, 'RAG_READY', 'rag_ready'), 'rag_ready'}:
            filtered_ids = [r.document_id for r in results if is_rag_ready(r)]
            if not filtered_ids:
                raise ValueError("No RAG-ready documents found")
        else:
            filtered_ids = [r.document_id for r in results] if results else list(document_ids)

        # Create archive (do not require results; filesystem fallback works)
        if str(download_type) in {getattr(DownloadType, 'COMBINED', 'combined'), 'combined'} or include_combined:
            zip_path_str, count = self.create_combined_markdown_zip(filtered_ids, results, custom_filename)
        else:
            zip_path_str, count = self.create_zip_archive(filtered_ids, custom_filename, include_summary)

        # Clear artifact cache after use
        self._artifact_cache = {}

        zip_path = Path(zip_path_str)
        return ZipService.ZipInfo(zip_path=zip_path, file_count=count)

    async def create_rag_ready_download(
        self,
        custom_filename: Optional[str] = None,
        include_summary: bool = True,
    ) -> "ZipService.ZipInfo":
        """
        v2-compatible helper to build an archive of all RAG-ready documents.
        """
        all_results: List[ProcessingResult] = list(storage_service.get_all_processing_results() or [])
        rag_ready = [r for r in all_results if r.success and getattr(r, "is_rag_ready", getattr(r, "pass_all_thresholds", False))]
        if not rag_ready:
            raise ValueError("No RAG-ready documents found")

        ids = [r.document_id for r in rag_ready]

        # Load artifacts for all documents into cache (for sync functions to use)
        from app.core.shared.database_service import database_service
        self._artifact_cache = {}
        try:
            async with database_service.get_session() as session:
                for doc_id in ids:
                    artifacts = await artifact_service.get_artifacts_by_document(
                        session, doc_id
                    )
                    # Filter for processed artifacts
                    processed = [a for a in artifacts if a.artifact_type == "processed"]
                    if processed:
                        self._artifact_cache[doc_id] = processed[0]  # Get first processed artifact
        except Exception as e:
            print(f"Failed to load artifacts: {e}")
            # Continue anyway - will fall back to storage service

        zip_path_str, count = self.create_zip_archive(ids, custom_filename or "curatore_rag_ready_export.zip", include_summary)

        # Clear artifact cache after use
        self._artifact_cache = {}

        return ZipService.ZipInfo(zip_path=Path(zip_path_str), file_count=count)


# ============================================================================
# Global ZIP Service Instance
# ============================================================================

# Create a single global instance of the ZIP service
# This ensures consistent file handling and temporary directory management
zip_service = ZipService()
