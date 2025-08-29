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
import zipfile
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple
from datetime import datetime

from ..config import settings
from .storage_service import storage_service
from ..models import ProcessingResult


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
        processed_dir (Path): Directory containing processed markdown files
    """
    
    def __init__(self):
        """
        Initialize the ZIP service with processed files directory.
        
        Sets up the service to work with the processed files directory from
        application settings. This directory should contain all successfully
        processed markdown files with the naming pattern: {original_name}_{document_id}.md
        """
        self.processed_dir = Path(settings.processed_dir)
    
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
            ├── processed_documents/
            │   ├── document1.md
            │   ├── document2.md
            │   └── document3.md
            └── PROCESSING_SUMMARY_20250827_143022.md  # if include_summary=True
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
            # Add processed documents
            for doc_id in document_ids:
                # Prefer manifest path from storage; fallback to glob
                manifest_path = storage_service.get_processed_path(doc_id) if hasattr(storage_service, 'get_processed_path') else None
                candidate_paths = []
                if manifest_path:
                    candidate_paths.append(Path(manifest_path))
                candidate_paths.extend(self.processed_dir.glob(f"*_{doc_id}.md"))
                for file_path in candidate_paths:
                    if file_path.exists():
                        original_name = file_path.name.split('_', 1)[-1] if '_' in file_path.name else file_path.name
                        zipf.write(file_path, f"processed_documents/{original_name}")
                        file_count += 1
                        break
            
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
        
        Creates the most comprehensive archive type, including individual processed files,
        a merged document with all content combined and hierarchy adjusted, and a detailed
        processing summary with quality metrics and statistics.
        
        Args:
            document_ids (List[str]): List of document IDs to include in the archive
            results (List[ProcessingResult]): Processing results for metadata and statistics
            zip_name (Optional[str]): Custom name for the ZIP file. If None, generates
                                    timestamp-based name: curatore_combined_export_{timestamp}.zip
        
        Returns:
            Tuple[str, int]: Tuple containing:
                - str: Full path to the created ZIP file in temporary directory  
                - int: Number of individual files successfully added to the archive
        
        Archive Structure:
            ```
            curatore_combined_export_20250827_143022.zip
            ├── individual_files/              # Original processed files
            │   ├── document1.md
            │   ├── document2.md
            │   └── document3.md
            ├── COMBINED_EXPORT_20250827_143022.md    # All documents merged
            └── PROCESSING_SUMMARY_20250827_143022.md # Detailed statistics
            ```
        
        Combined Document Features:
            - Header hierarchy adjustment to prevent conflicts
            - Document summaries and quality scores at the top of each section
            - Processing status indicators (✅ RAG Ready, ⚠️ Needs Improvement, 🎯 Vector Optimized)
            - Quality scores for all evaluation dimensions
            - Clear document separation with horizontal rules
        
        Combined Document Structure:
            ```markdown
            # Curatore Processing Results - Combined Export
            *Generated on 2025-08-27 14:30:22*
            
            **Processing Summary:**
            - Total Files: 3
            - RAG Ready: 2 (66.7%)
            - Vector Optimized: 1
            
            ---
            
            # document1.pdf
            *Technical documentation for software installation and configuration.*
            
            **Processing Status:** ✅ RAG Ready 🎯
            **Conversion Score:** 95/100
            **Quality Scores:** Clarity: 9/10, Completeness: 8/10, Relevance: 9/10, Markdown: 8/10
            
            ## Installation Guide  # <- Headers adjusted (+1 level)
            ...document content...
            ```
        
        Error Handling:
            - Missing files are skipped with error logging
            - Content reading errors are logged and skipped
            - Empty combined sections are handled gracefully
            - Missing processing results are handled with default values
        
        Example:
            >>> zip_path, count = zip_service.create_combined_markdown_zip(
            >>>     document_ids=["doc1", "doc2", "doc3"],
            >>>     results=processing_results,
            >>>     zip_name="comprehensive_export.zip"
            >>> )
            >>> print(f"Created combined archive with {count} files at {zip_path}")
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
            # Add individual processed documents
            for doc_id in document_ids:
                # Prefer manifest path from storage; fallback to glob
                manifest_path = storage_service.get_processed_path(doc_id) if hasattr(storage_service, 'get_processed_path') else None
                candidate_paths = []
                if manifest_path:
                    candidate_paths.append(Path(manifest_path))
                candidate_paths.extend(self.processed_dir.glob(f"*_{doc_id}.md"))
                for file_path in candidate_paths:
                    if file_path.exists():
                        # Read content for combined file
                        try:
                            content = file_path.read_text(encoding="utf-8")
                            result = next((r for r in results if r.document_id == doc_id), None)
                            
                            if result:
                                # Add section to combined markdown
                                combined_sections.append(f"# {result.filename}")

                                if result.document_summary:
                                    combined_sections.extend(["", f"*{result.document_summary}*"])

                                status_emoji = "✅" if rag_flag(result) else "⚠️"
                                optimized_emoji = " 🎯" if result.vector_optimized else ""

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
                            print(f"Error reading {file_path}: {e}")
                        
                        # Add to ZIP as individual file
                        original_name = file_path.name.split('_', 1)[-1] if '_' in file_path.name else file_path.name
                        zipf.write(file_path, f"individual_files/{original_name}")
                        file_count += 1
                        break
            
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
    
    def _adjust_markdown_hierarchy(self, content: str) -> str:
        """
        Adjust markdown header hierarchy by adding one level of nesting.
        
        Modifies markdown headers to increase their nesting level by one (adds one #)
        to prevent conflicts when multiple documents are combined into a single file.
        This ensures proper document structure and prevents header level collisions.
        
        Args:
            content (str): Original markdown content with existing headers
        
        Returns:
            str: Modified markdown content with adjusted header hierarchy
        
        Adjustment Rules:
            - # becomes ##
            - ## becomes ###
            - ### becomes ####
            - #### becomes #####
            - ##### becomes ######
            - ###### remains ###### (maximum depth)
        
        Edge Cases:
            - Empty content returns empty string
            - Lines without headers remain unchanged
            - Headers at maximum depth (######) are not modified
            - Lines starting with # but not headers (e.g., in code blocks) may be affected
        
        Example:
            >>> content = "# Main Title\n## Subtitle\n### Section"
            >>> adjusted = self._adjust_markdown_hierarchy(content)
            >>> print(adjusted)
            # Output: "## Main Title\n### Subtitle\n#### Section"
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
        
        Creates a simple summary file with basic export information for standard
        ZIP archives. Used for simple bulk downloads without detailed processing
        statistics or quality metrics.
        
        Args:
            document_ids (List[str]): List of document IDs included in the archive
            file_count (int): Number of files actually included in the archive
        
        Returns:
            str: Formatted markdown summary content
        
        Summary Contents:
            - Export generation timestamp
            - Number of documents included
            - Document IDs for reference
            - Basic usage instructions
            - Curatore v2 branding
        
        Format:
            Standard markdown with clear sections and professional formatting
            suitable for display in markdown viewers or text editors.
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
        
        Creates a detailed processing report with comprehensive statistics, quality
        metrics, and usage guidelines. Used for combined archives and detailed
        exports where users need complete processing information.
        
        Args:
            document_ids (List[str]): List of document IDs included in the archive
            results (List[ProcessingResult]): Processing results with quality metrics
            file_count (int): Number of files actually included in the archive
        
        Returns:
            str: Formatted markdown summary with detailed processing information
        
        Summary Contents:
            - Export overview with statistics and pass rates
            - Archive contents description
            - Individual document processing results with quality scores
            - Usage guidelines for RAG systems and manual review
            - Professional formatting with emojis for visual clarity
        
        Quality Indicators:
            - ✅ RAG Ready: Documents meeting all quality thresholds
            - ⚠️ Needs Improvement: Documents requiring review or reprocessing
            - 🎯 Vector Optimized: Documents with enhanced structure for RAG
        
        Metrics Included:
            - Conversion scores (0-100)
            - LLM evaluation scores (1-10) for clarity, completeness, relevance, markdown
            - Document summaries when available
            - Processing status and optimization flags
        
        Example Output:
            ```markdown
            # Curatore Export Summary
            **Generated:** 2025-08-27 14:30:22
            
            ## Export Overview
            - Total Files Included: 3
            - Successfully Processed: 3
            - RAG Ready Files: 2
            - Vector Optimized Files: 1
            - Overall Pass Rate: 66.7%
            
            ## Processing Results
            
            ### user_guide.pdf
            - **Status:** RAG Ready ✅
            - **Processing:** Vector Optimized 🎯
            - **Conversion Score:** 95/100
            - **Quality Scores:**
              - Clarity: 9/10
              - Completeness: 8/10
              - Relevance: 9/10
              - Markdown: 8/10
            - **Summary:** Technical documentation for software installation and configuration.
            ```
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
            status = "RAG Ready ✅" if rag_flag(result) else "Needs Improvement ⚠️"
            optimization = "Vector Optimized 🎯" if result.vector_optimized else "Standard Processing"
            
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
            "1. Import RAG-ready files (marked with ✅) directly into your vector database",
            "2. Use the combined export for bulk import operations",
            "3. Files marked as 'Vector Optimized' have enhanced chunking structure",
            "",
            "### For Manual Review:",
            "1. Review files marked with ⚠️ before production use",
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
        
        Removes the temporary ZIP file from the system temporary directory
        after it has been downloaded by the user. This is typically called
        as a background task after the FastAPI FileResponse completes.
        
        Args:
            zip_path (str): Full path to the ZIP file to be deleted
        
        Returns:
            bool: True if file was successfully deleted, False if deletion failed
        
        Error Handling:
            - File not found: Returns False, no error raised
            - Permission errors: Returns False, logs error details
            - Other OS errors: Returns False, logs error details
        
        Usage:
            This method is typically used as a background task in FastAPI
            responses to clean up temporary files after download:
            
            >>> return FileResponse(
            >>>     path=zip_path,
            >>>     filename=zip_name,
            >>>     media_type="application/zip",
            >>>     background=lambda: zip_service.cleanup_zip_file(zip_path)
            >>> )
        
        Example:
            >>> success = zip_service.cleanup_zip_file("/tmp/export_12345.zip")
            >>> if not success:
            >>>     print("Warning: Failed to clean up temporary file")
        """
        try:
            if os.path.exists(zip_path):
                os.unlink(zip_path)
                return True
        except Exception as e:
            print(f"Error cleaning up ZIP file {zip_path}: {e}")
        return False


# ============================================================================
# Global ZIP Service Instance
# ============================================================================

# Create a single global instance of the ZIP service
# This ensures consistent file handling and temporary directory management
zip_service = ZipService()
