# ============================================================================
# backend/app/services/document_service.py
# ============================================================================
#
# Document Processing Service for Curatore v2
#
# This module provides the core document processing functionality for Curatore v2,
# a RAG document processing and optimization tool. It handles the complete
# document processing pipeline from file upload through conversion, optimization,
# quality evaluation, and output generation.
#
# Key Features:
#   - Multi-format document conversion (PDF, DOCX, images, text, markdown)
#   - Intelligent conversion chain with MarkItDown integration
#   - Advanced OCR processing with Tesseract
#   - Quality scoring and evaluation systems
#   - LLM-powered content optimization and evaluation
#   - Vector database optimization for RAG applications
#   - Batch processing capabilities
#   - File management and cleanup operations
#
# Supported Formats:
#   - Documents: PDF, DOCX
#   - Images: PNG, JPG, JPEG, BMP, TIF, TIFF (with OCR)
#   - Text: MD (Markdown), TXT (Plain text)
#
# Processing Pipeline:
#   1. File validation and format detection
#   2. Document conversion to markdown
#   3. Content quality scoring
#   4. LLM-powered evaluation (4 dimensions)
#   5. Vector database optimization (optional)
#   6. Quality threshold validation
#   7. File output and metadata generation
#
# Author: Curatore v2 Development Team
# Version: 2.0.0
# ============================================================================

import io
from datetime import datetime
import re
import time
import uuid
import shutil
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any

# Import from v1 pipeline logic - document conversion tools
try:
    from markitdown import MarkItDown
    MD_CONVERTER = MarkItDown(enable_plugins=False)
except Exception:
    MD_CONVERTER = None

from pdfminer.high_level import extract_text as pdf_extract_text
from PIL import Image
import pytesseract
from pytesseract import Output
import fitz  # PyMuPDF
import docx

from ..config import settings
from ..models import (
    ProcessingResult, ConversionResult, ProcessingStatus, LLMEvaluation,
    OCRSettings, QualityThresholds, ProcessingOptions
)


class DocumentService:
    """
    Core document processing service for Curatore v2.
    
    This service provides comprehensive document processing capabilities including
    file upload handling, multi-format conversion, quality assessment, LLM evaluation,
    and vector database optimization. It manages the complete document processing
    lifecycle from raw input to RAG-ready output.
    
    Architecture:
        - File Management: Upload, batch, and processed file handling
        - Conversion Engine: Multi-format document conversion with fallback chains
        - Quality Assessment: Conversion scoring and LLM-powered evaluation
        - Optimization: Vector database optimization for RAG applications
        - Batch Processing: Parallel processing of multiple documents
    
    Directory Structure:
        - upload_dir: User-uploaded files with UUID prefixes
        - processed_dir: Converted markdown files ready for use
        - batch_dir: Local files for batch processing operations
    
    Integration Points:
        - LLMService: For evaluation, improvement, and optimization
        - Settings: Configuration for paths, thresholds, and OCR
        - Storage: File system management with Docker volume support
    
    Attributes:
        SUPPORTED_EXTENSIONS (Set[str]): File extensions supported for processing
        upload_dir (Path): Directory for uploaded files
        processed_dir (Path): Directory for processed markdown files
        batch_dir (Path): Directory for batch processing files
    """
    
    SUPPORTED_EXTENSIONS = {".docx", ".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".md", ".txt"}
    
    def __init__(self):
        """
        Initialize the document service with directory management.
        
        Sets up the service with paths from application settings and ensures
        required directories exist. Designed to work with Docker volume mounts
        where the main files directory is mounted from the host system.
        
        Directory Setup:
            - Validates Docker volume mount availability
            - Creates required subdirectories if main directory exists
            - Logs directory status for debugging and monitoring
            - Gracefully handles missing volume mounts
        
        Error Handling:
            - Missing volume mounts are logged but don't prevent initialization
            - Directory creation failures are logged but service remains operational
            - Service degrades gracefully with limited functionality if directories unavailable
        """
        # Use absolute paths from settings - these should match Docker volume mount
        self.upload_dir = Path(settings.upload_dir)
        self.processed_dir = Path(settings.processed_dir)
        self.batch_dir = Path(settings.batch_dir)
        
        print(f"🔧 DocumentService initialized with:")
        print(f"   Upload dir: {self.upload_dir}")
        print(f"   Processed dir: {self.processed_dir}")
        print(f"   Batch dir: {self.batch_dir}")
        
        # Only ensure directories exist, don't create them if they don't
        self._ensure_directories()
    
    def _ensure_directories(self) -> None:
        """
        Ensure required directories exist, but only if the parent volume is mounted.
        
        Validates that the Docker volume mount is working correctly and creates
        required subdirectories. This method is defensive and won't create
        the main files directory if it doesn't exist (indicating volume mount issues).
        
        Validation Process:
            1. Checks if main files directory exists (Docker volume mount)
            2. Creates subdirectories only if main directory exists
            3. Logs directory creation status for monitoring
            4. Handles errors gracefully without service failure
        
        Error Handling:
            - Missing main directory: Logs warning, continues without creating
            - Permission errors: Logs error, continues with limited functionality
            - Other filesystem errors: Logs error, service remains operational
        
        Side Effects:
            - Creates upload_dir, processed_dir, batch_dir if they don't exist
            - Logs directory status for debugging
            - Does not raise exceptions on failure
        """
        try:
            # Check if the main files directory exists (should be mounted from Docker)
            files_root = Path(settings.files_root)
            
            if not files_root.exists():
                print(f"⚠️  Main files directory doesn't exist: {files_root}")
                print("   This suggests the Docker volume mount may not be working correctly.")
                # Don't create it - this should be mounted from the host
                return
            
            # Only create subdirectories if the main directory exists
            dirs_to_ensure = [
                (self.upload_dir, "uploaded_files"),
                (self.processed_dir, "processed_files"), 
                (self.batch_dir, "batch_files")
            ]
            
            for dir_path, name in dirs_to_ensure:
                if not dir_path.exists():
                    dir_path.mkdir(parents=True, exist_ok=True)
                    print(f"📁 Created {name} directory: {dir_path}")
                else:
                    print(f"✅ {name} directory exists: {dir_path}")
                    
        except Exception as e:
            print(f"❌ Error ensuring directories: {e}")
            # Don't raise the exception - let the app continue
    
    def clear_all_files(self) -> Dict[str, int]:
        """
        Clear all uploaded and processed files for system reset.
        
        Removes all files from upload and processed directories, typically used
        during application startup or system reset operations. This is a destructive
        operation that permanently deletes all processed documents and uploads.
        
        Returns:
            Dict[str, int]: Dictionary containing deletion counts:
                - "uploaded": Number of uploaded files deleted
                - "processed": Number of processed files deleted  
                - "total": Total number of files deleted
        
        File Deletion Process:
            1. Iterates through all files in upload_dir
            2. Iterates through all files in processed_dir
            3. Deletes each file individually
            4. Tracks deletion counts for reporting
            5. Logs completion status
        
        Error Handling:
            - Individual file deletion failures are logged but don't stop the process
            - Directory access errors are caught and re-raised
            - Returns actual deletion counts even if some files couldn't be deleted
        
        Use Cases:
            - Application startup cleanup
            - System reset functionality
            - Development environment cleanup
            - Testing setup/teardown
        
        Example:
            >>> counts = document_service.clear_all_files()
            >>> print(f"Deleted {counts['total']} files total")
        """
        deleted_counts = {
            "uploaded": 0,
            "processed": 0,
            "total": 0
        }
        
        try:
            # Clear uploaded files
            if self.upload_dir.exists():
                for file_path in self.upload_dir.glob("*"):
                    if file_path.is_file():
                        file_path.unlink()
                        deleted_counts["uploaded"] += 1
            
            # Clear processed files
            if self.processed_dir.exists():
                for file_path in self.processed_dir.glob("*"):
                    if file_path.is_file():
                        file_path.unlink()
                        deleted_counts["processed"] += 1
            
            deleted_counts["total"] = deleted_counts["uploaded"] + deleted_counts["processed"]
            print(f"✅ File cleanup complete: {deleted_counts['total']} files deleted")
            
        except Exception as e:
            print(f"⚠️ Error during file cleanup: {e}")
            raise
        
        return deleted_counts
    
    def get_supported_extensions(self) -> List[str]:
        """
        Get list of supported file extensions for document processing.
        
        Returns:
            List[str]: List of supported file extensions including:
                - .docx (Word documents)
                - .pdf (PDF documents)
                - .png, .jpg, .jpeg, .bmp, .tif, .tiff (Images with OCR)
                - .md (Markdown files)
                - .txt (Plain text files)
        
        Example:
            >>> extensions = document_service.get_supported_extensions()
            >>> print(f"Supported formats: {', '.join(extensions)}")
        """
        return list(self.SUPPORTED_EXTENSIONS)
    
    def is_supported_file(self, filename: str) -> bool:
        """
        Check if a file is supported for processing based on its extension.
        
        Args:
            filename (str): The filename to check (must include extension)
        
        Returns:
            bool: True if the file extension is supported, False otherwise
        
        Validation Process:
            - Extracts file extension using pathlib
            - Converts to lowercase for case-insensitive matching
            - Checks against SUPPORTED_EXTENSIONS set
        
        Example:
            >>> is_supported = document_service.is_supported_file("document.pdf")
            >>> if not is_supported:
            >>>     raise ValueError("Unsupported file type")
        """
        return Path(filename).suffix.lower() in self.SUPPORTED_EXTENSIONS
    
    async def save_uploaded_file(self, filename: str, content: bytes) -> Tuple[str, Path]:
        """
        Save uploaded file content to the upload directory with unique ID.
        
        Creates a unique document ID and saves the file with a prefixed filename
        for identification and organization. The file is saved with a sanitized
        filename to prevent filesystem issues.
        
        Args:
            filename (str): Original filename from the upload
            content (bytes): File content as bytes
        
        Returns:
            Tuple[str, Path]: Tuple containing:
                - str: Unique document ID (UUID4)
                - Path: Full path to the saved file
        
        File Naming Convention:
            - Format: {document_id}_{sanitized_filename}
            - Example: "a1b2c3d4-e5f6-7890-abcd-ef1234567890_user_guide.pdf"
            - Special characters in filename are replaced with underscores
        
        File Safety:
            - Filename sanitization removes problematic characters
            - UUID prevents filename collisions
            - Creates upload directory if it doesn't exist
        
        Error Handling:
            - File write errors are logged and re-raised
            - Directory creation errors are handled automatically
            - Logs successful saves for monitoring
        
        Example:
            >>> doc_id, file_path = await document_service.save_uploaded_file(
            >>>     "report.pdf", file_content
            >>> )
            >>> print(f"Saved as {doc_id} at {file_path}")
        """
        document_id = str(uuid.uuid4())
        safe_filename = re.sub(r'[^a-zA-Z0-9_.-]', '_', filename)
        file_path = self.upload_dir / f"{document_id}_{safe_filename}"
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            with open(file_path, "wb") as f:
                f.write(content)
            print(f"File saved successfully: {file_path}")
        except Exception as e:
            print(f"Error saving file {file_path}: {e}")
            raise
        
        return document_id, file_path
    
    def list_uploaded_files(self) -> List[Dict[str, Any]]:
        """
        List all uploaded files with metadata for the frontend.
        
        Scans the upload directory and returns detailed metadata for each
        uploaded file including size, upload time, and document ID extraction.
        
        Returns:
            List[Dict[str, Any]]: List of file metadata dictionaries containing:
                - document_id: Unique identifier extracted from filename
                - filename: Original filename (without UUID prefix)
                - original_filename: Full filename as stored
                - file_size: File size in bytes
                - upload_time: Upload timestamp in milliseconds
                - file_path: Full path to the file
        
        Filename Processing:
            - Extracts document ID from filename prefix
            - Restores original filename by removing UUID prefix
            - Handles files with and without proper UUID prefixes
        
        Error Handling:
            - Individual file processing errors are logged and skipped
            - Directory access errors are caught and logged
            - Returns partial results if some files can't be processed
            - Empty list returned on complete failure
        
        Example:
            >>> files = document_service.list_uploaded_files()
            >>> for file_info in files:
            >>>     print(f"File: {file_info['filename']} ({file_info['file_size']} bytes)")
        """
        files = []
        try:
            for file_path in self.upload_dir.glob("*"):
                if file_path.is_file() and file_path.suffix.lower() in self.SUPPORTED_EXTENSIONS:
                    stat = file_path.stat()
                    parts = file_path.name.split('_', 1)
                    document_id = parts[0]
                    original_filename = parts[1] if len(parts) > 1 else file_path.name
                    
                    files.append({
                        "document_id": document_id,
                        "filename": original_filename,
                        "original_filename": file_path.name,
                        "file_size": stat.st_size,
                        "upload_time": stat.st_mtime * 1000,  # Convert to milliseconds
                        "file_path": str(file_path)
                    })
        except Exception as e:
            print(f"Error listing files: {e}")
        
        return files
    
    def list_batch_files(self) -> List[Dict[str, Any]]:
        """
        List all files in the batch_files directory for local processing.
        
        Scans the batch files directory and returns metadata for files available
        for batch processing. These are typically files placed directly in the
        batch directory for processing without going through the upload flow.
        
        Returns:
            List[Dict[str, Any]]: List of file metadata dictionaries containing:
                - document_id: Generated ID with "batch_" prefix
                - filename: Original filename
                - original_filename: Same as filename (no UUID prefix)
                - file_size: File size in bytes
                - upload_time: File modification time in milliseconds
                - file_path: Full path to the file
                - source: "batch" marker for identification
        
        Document ID Generation:
            - Format: "batch_{filename_stem}"
            - Example: "report.pdf" becomes document ID "batch_report"
            - Allows frontend to distinguish batch files from uploads
        
        File Filtering:
            - Only includes files with supported extensions
            - Ignores directories and unsupported file types
            - Logs unsupported files for debugging
        
        Error Handling:
            - Directory not existing is handled gracefully
            - Individual file processing errors are logged and skipped
            - Returns partial results if some files can't be processed
            - Comprehensive error logging for debugging
        
        Example:
            >>> batch_files = document_service.list_batch_files()
            >>> print(f"Found {len(batch_files)} batch files available")
        """
        files = []
        try:
            print(f"🔍 Listing batch files from: {self.batch_dir}")
            
            if not self.batch_dir.exists():
                print(f"⚠️ Batch directory does not exist: {self.batch_dir}")
                return files
            
            file_count = 0
            for file_path in self.batch_dir.glob("*"):
                file_count += 1
                if file_path.is_file() and file_path.suffix.lower() in self.SUPPORTED_EXTENSIONS:
                    try:
                        stat = file_path.stat()
                        
                        # Generate a temporary document_id for frontend compatibility
                        document_id = f"batch_{file_path.stem}"
                        
                        file_info = {
                            "document_id": document_id,
                            "filename": file_path.name,
                            "original_filename": file_path.name,
                            "file_size": stat.st_size,
                            "upload_time": stat.st_mtime * 1000,  # Convert to milliseconds
                            "file_path": str(file_path),
                            "source": "batch"  # Mark as batch file
                        }
                        files.append(file_info)
                    except Exception as e:
                        print(f"⚠️ Error processing file {file_path}: {e}")
                        continue
                else:
                    if file_path.is_file():
                        print(f"❌ Unsupported file type: {file_path.name}")
            
            print(f"✅ Found {len(files)} valid batch files out of {file_count} total files")
            
        except Exception as e:
            print(f"❌ Error listing batch files: {e}")
            import traceback
            traceback.print_exc()
        
        return files

    def find_batch_file(self, filename: str) -> Optional[Path]:
        """
        Locate a file in the batch directory by filename or stem.

        Accepts a filename (including spaces or URL-decoded characters) and
        attempts to resolve it within the configured batch directory. If an
        exact match is not found, falls back to searching by stem.

        Args:
            filename (str): The filename to search for (e.g., "report.pdf").

        Returns:
            Optional[Path]: Full path if found, otherwise None.
        """
        try:
            # 1) Exact match
            candidate = self.batch_dir / filename
            if candidate.exists() and candidate.is_file() and candidate.suffix.lower() in self.SUPPORTED_EXTENSIONS:
                return candidate

            # 2) Stem match (handle cases where extension might differ)
            stem = Path(filename).stem
            for p in self.batch_dir.glob(f"{stem}.*"):
                if p.is_file() and p.suffix.lower() in self.SUPPORTED_EXTENSIONS:
                    return p
        except Exception as e:
            print(f"Error finding batch file '{filename}': {e}")
        return None
    
    def get_processed_content(self, document_id: str) -> Optional[str]:
        """
        Get processed markdown content for a document by ID.
        
        Retrieves the processed markdown content for a document that has been
        successfully processed through the conversion pipeline.
        
        Args:
            document_id (str): Unique document identifier
        
        Returns:
            Optional[str]: Processed markdown content, or None if not found
        
        File Location:
            - Searches processed_dir for files matching pattern: "*_{document_id}.md"
            - Handles files with various prefixes (original filename prefixes)
            - Returns content from first matching file found
        
        Error Handling:
            - File read errors are caught and skipped (tries next match)
            - Missing files return None
            - Encoding errors are handled by trying multiple files
        
        Example:
            >>> content = document_service.get_processed_content("doc123")
            >>> if content:
            >>>     print(f"Content length: {len(content)} characters")
        """
        for file_path in self.processed_dir.glob(f"*_{document_id}.md"):
            try:
                return file_path.read_text(encoding="utf-8")
            except Exception:
                continue
        return None
    
    def _find_document_file(self, document_id: str) -> Optional[Path]:
        """
        Find the uploaded or batch file for a document ID.
        
        Locates the original file associated with a document ID by searching
        upload and batch directories. Handles both regular uploads and batch files.
        
        Args:
            document_id (str): Document identifier to search for
        
        Returns:
            Optional[Path]: Path to the document file, or None if not found
        
        Search Process:
            1. Searches upload_dir for files with format: "{document_id}_*.*"
            2. For batch IDs (starting with "batch_"), searches batch_dir
            3. Returns first matching file found
        
        Batch File Handling:
            - Batch IDs have format: "batch_{filename_stem}"
            - Removes "batch_" prefix to get original filename stem
            - Searches for files matching the stem with any extension
        
        Example:
            >>> file_path = document_service._find_document_file("doc123")
            >>> if file_path:
            >>>     print(f"Found file: {file_path}")
        """
        # Look for files that start with the document_id in upload directory
        try:
            print(f"🔎 Finding file for document_id='{document_id}'")
        except Exception:
            pass
        for file_path in self.upload_dir.glob(f"{document_id}_*.*"):
            if file_path.is_file():
                return file_path
        
        # Look in batch files for batch_ prefixed IDs
        if document_id.startswith("batch_"):
            filename_stem = document_id.replace("batch_", "")
            try:
                pattern = f"{filename_stem}.*"
                print(f"🔎 Searching batch_dir='{self.batch_dir}' pattern='{pattern}'")
            except Exception:
                pass
            for file_path in self.batch_dir.glob(f"{filename_stem}.*"):
                if file_path.is_file() and file_path.suffix.lower() in self.SUPPORTED_EXTENSIONS:
                    try:
                        print(f"✅ Found batch file: {file_path}")
                    except Exception:
                        pass
                    return file_path
        
        try:
            print(f"❌ No file found for document_id='{document_id}'")
        except Exception:
            pass
        return None
    
    def _score_conversion(self, markdown_text: str, original_text: Optional[str] = None) -> Tuple[int, str]:
        """
        Score the quality of document conversion to markdown (0-100).
        
        Evaluates the conversion quality based on content coverage, structure
        preservation, and readability. This scoring system helps identify
        successful conversions and potential issues.
        
        Args:
            markdown_text (str): The converted markdown content
            original_text (Optional[str]): Original text for comparison (currently unused)
        
        Returns:
            Tuple[int, str]: Tuple containing:
                - int: Conversion score (0-100)
                - str: Human-readable feedback explaining the score
        
        Scoring Components:
            1. Content Coverage (0-100): Ratio of extracted vs original content
            2. Structure Score (0-80): Based on markdown structure elements
                - Headings: +30 points if present
                - Lists: +30 points if present  
                - Tables: +20 points if 3+ table markers present
            3. Legibility Score (0-20): Based on character encoding and line length
        
        Score Calculation:
            - Total = (0.5 × Content Score) + Structure Score + Legibility Score
            - Capped at 100 maximum
            - Weighted toward content preservation
        
        Feedback Generation:
            - Content preservation percentage
            - Formatting loss warnings
            - Readability issue indicators
            - High-fidelity conversion confirmation
        
        Example:
            >>> score, feedback = self._score_conversion(markdown_content)
            >>> print(f"Conversion score: {score}/100 - {feedback}")
        """
        if not markdown_text:
            return 0, "No markdown produced."

        # Content coverage
        content_score = 100
        if original_text:
            ow = original_text.split()
            mw = markdown_text.split()
            if len(ow) == 0:
                content_score = 0
            else:
                ratio = min(len(mw) / len(ow), 1.0)
                content_score = int(ratio * 100)

        # Structure markers
        headings = len(re.findall(r'^#{1,6}\s', markdown_text, flags=re.MULTILINE))
        lists = len(re.findall(r'^[\-\*]\s', markdown_text, flags=re.MULTILINE))
        tables = markdown_text.count('|')
        structure_score = 0
        if headings > 0: structure_score += 30
        if lists > 0:    structure_score += 30
        if tables > 3:   structure_score += 20

        # Legibility score
        if "�" in markdown_text:  # Check for replacement characters
            legibility_score = 0
        else:
            lines = markdown_text.splitlines() or [markdown_text]
            avg_len = sum(len(l) for l in lines) / len(lines) if lines else 0
            legibility_score = 20 if avg_len < 200 else 10

        # Combine scores with weighting
        total = int(0.5 * content_score + structure_score + legibility_score)
        total = min(total, 100)

        # Generate human-readable feedback
        fb = []
        if content_score < 100 and original_text:
            fb.append(f"Content preserved ~{content_score}%.")
        if structure_score < 60:
            fb.append("Formatting may be partially lost.")
        if legibility_score < 20:
            fb.append("Some readability issues (long lines or odd characters).")
        if not fb:
            fb.append("High-fidelity conversion.")
        return total, " ".join(fb)
    
    def _meets_thresholds(
        self,
        conversion_score: int,
        llm_evaluation: Optional[LLMEvaluation],
        thresholds: Optional[QualityThresholds],
    ) -> bool:
        """
        Check if document meets all quality thresholds for RAG readiness.
        
        Evaluates whether a document passes all configured quality thresholds
        based on conversion score and LLM evaluation results. This determines
        if a document is considered "RAG Ready" for production use.
        
        Args:
            conversion_score (int): Conversion quality score (0-100)
            llm_evaluation (Optional[LLMEvaluation]): LLM evaluation results
            thresholds (QualityThresholds): Quality threshold configuration
        
        Returns:
            bool: True if all thresholds are met, False otherwise
        
        Threshold Evaluation:
            - Conversion Score: Must meet or exceed conversion threshold
            - Clarity Score: Must meet or exceed clarity threshold (1-10)
            - Completeness Score: Must meet or exceed completeness threshold (1-10)
            - Relevance Score: Must meet or exceed relevance threshold (1-10)
            - Markdown Score: Must meet or exceed markdown threshold (1-10)
        
        Requirements:
            - All thresholds must be met (AND logic, not OR)
            - LLM evaluation must be available (None evaluation = False)
            - Missing LLM scores are treated as 0
        
        Error Handling:
            - Missing LLM evaluation returns False
            - None LLM scores are treated as 0 for comparison
            - Exception during evaluation returns False
        
        Example:
            >>> passes = self._meets_thresholds(85, llm_eval, thresholds)
            >>> if passes:
            >>>     print("Document is RAG Ready!")
        """
        if not llm_evaluation:
            return False

        # Normalize thresholds (support both v1 payload and domain model names)
        try:
            if thresholds is None:
                conv = settings.default_conversion_threshold
                clr = settings.default_clarity_threshold
                comp = settings.default_completeness_threshold
                rel = settings.default_relevance_threshold
                mdq = settings.default_markdown_threshold
            else:
                conv = getattr(thresholds, "conversion", None)
                if conv is None:
                    conv = getattr(thresholds, "conversion_quality", settings.default_conversion_threshold)
                clr = getattr(thresholds, "clarity", None)
                if clr is None:
                    clr = getattr(thresholds, "clarity_score", settings.default_clarity_threshold)
                comp = getattr(thresholds, "completeness", None)
                if comp is None:
                    comp = getattr(thresholds, "completeness_score", settings.default_completeness_threshold)
                rel = getattr(thresholds, "relevance", None)
                if rel is None:
                    rel = getattr(thresholds, "relevance_score", settings.default_relevance_threshold)
                mdq = getattr(thresholds, "markdown", None)
                if mdq is None:
                    mdq = getattr(thresholds, "markdown_quality", settings.default_markdown_threshold)

            return (
                conversion_score >= int(conv)
                and (llm_evaluation.clarity_score or 0) >= int(clr)
                and (llm_evaluation.completeness_score or 0) >= int(comp)
                and (llm_evaluation.relevance_score or 0) >= int(rel)
                and (llm_evaluation.markdown_score or 0) >= int(mdq)
            )
        except Exception:
            return False
    
    async def convert_to_markdown(
        self,
        file_path: Path,
        ocr_settings: OCRSettings
    ) -> ConversionResult:
        """
        Convert document to markdown format using intelligent conversion chain.
        
        Performs document conversion using a prioritized chain of conversion
        methods, starting with the best option and falling back to alternatives
        if needed. Includes quality scoring of the conversion result.
        
        Args:
            file_path (Path): Path to the document file to convert
            ocr_settings (OCRSettings): OCR configuration for image processing
        
        Returns:
            ConversionResult: Conversion result with content, score, and feedback
        
        Conversion Chain:
            1. MarkItDown: Primary converter for structured documents
            2. Format-specific converters: PDF, DOCX, image processors
            3. OCR fallback: For images and problem documents
            4. Direct text reading: For text and markdown files
        
        Quality Assessment:
            - Automatic scoring of conversion quality (0-100)
            - Feedback generation explaining conversion results
            - Success/failure determination based on content availability
        
        Error Handling:
            - Individual conversion method failures are caught
            - Falls back to next method in chain
            - Returns detailed error information in conversion notes
            - Comprehensive exception handling with informative messages
        
        Example:
            >>> result = await document_service.convert_to_markdown(file_path, ocr_settings)
            >>> if result.success:
            >>>     print(f"Converted successfully: {result.conversion_score}/100")
        """
        start = time.time()
        try:
            markdown_content, note = self._convert_file_to_text(file_path, ocr_settings)
            
            if markdown_content is None:
                return ConversionResult(
                    success=False,
                    markdown_content="",
                    conversion_score=0,
                    conversion_feedback="Conversion failed to produce text.",
                    word_count=0,
                    char_count=0,
                    processing_time=time.time() - start,
                    conversion_note=note,
                )

            score, feedback = self._score_conversion(markdown_content)
            
            return ConversionResult(
                success=bool(markdown_content),
                markdown_content=markdown_content,
                conversion_score=score,
                conversion_feedback=feedback,
                word_count=len(markdown_content.split()),
                char_count=len(markdown_content),
                processing_time=time.time() - start,
                conversion_note=note,
            )
            
        except Exception as e:
            return ConversionResult(
                success=False,
                markdown_content="",
                conversion_score=0,
                conversion_feedback=f"Conversion error: {e}",
                word_count=0,
                char_count=0,
                processing_time=time.time() - start,
                conversion_note=f"An unexpected error occurred during conversion: {e}",
            )
    
    def _convert_file_to_text(
        self,
        file_path: Path,
        ocr_settings: OCRSettings
    ) -> Tuple[Optional[str], str]:
        """
        Convert a document to text format using a prioritized chain of methods.
        
        Internal method that implements the actual conversion logic with multiple
        fallback strategies. Tries the best conversion method first and falls
        back to alternatives if needed. Returns both content and processing notes.
        
        Args:
            file_path (Path): Path to the document file to convert
            ocr_settings (OCRSettings): OCR configuration (language, PSM mode)
        
        Returns:
            Tuple[Optional[str], str]: Tuple containing:
                - Optional[str]: Converted text content (None if all methods fail)
                - str: Processing notes explaining what method was used
        
        Conversion Priority Chain:
            1. Direct text reading: For .md and .txt files
            2. MarkItDown: For structured documents (PDF, DOCX, etc.)
            3. Format-specific fallbacks:
               - PDF: pdfminer + PyMuPDF fallback
               - DOCX: python-docx library
               - Images: Tesseract OCR
            4. OCR fallback: For any file that previous methods failed on
        
        OCR Processing:
            - Uses Tesseract with configurable language and PSM settings
            - Handles various image formats
            - Provides confidence scoring for OCR results
            - Falls back to different OCR strategies if primary fails
        
        Error Handling:
            - Each conversion method is wrapped in try-catch
            - Failed methods log errors and continue to next method
            - Returns detailed notes about which methods were attempted
            - Graceful degradation through the conversion chain
        
        Example Result:
            >>> content, note = self._convert_file_to_text(path, ocr_settings)
            >>> print(f"Conversion note: {note}")
            >>> # Output: "Converted with MarkItDown."
        """
        ext = file_path.suffix.lower()
        note = ""
        md = None

        # 1) MD/TXT direct read
        if ext in {".md", ".txt"}:
            try:
                text = file_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                text = file_path.read_text(encoding="latin-1")
            md = text if ext == ".md" else f"```\n{text}\n```"
            note = "Loaded text/markdown directly."
            return md, note

        # 2) Try MarkItDown first (preserves structure for LLM)
        try:
            if MD_CONVERTER:
                res = MD_CONVERTER.convert(str(file_path))
                md = (res.text_content or "").strip()
                if md:
                    note = "Converted with MarkItDown."
                    return md, note
                note = "MarkItDown returned empty content; attempting fallbacks."
        except Exception as e:
            note = f"MarkItDown failed ({str(e)[:50]}...); trying fallbacks."

        # 3) Format-specific fallbacks
        if ext == ".pdf":
            # PDF fallback chain
            try:
                # Try pdfminer first
                text = pdf_extract_text(str(file_path))
                if text and text.strip():
                    md = text.strip()
                    note += " Used pdfminer for PDF extraction."
                    return md, note
            except Exception as e:
                note += f" pdfminer failed ({str(e)[:30]}...)."
            
            try:
                # Try PyMuPDF as backup
                doc = fitz.open(str(file_path))
                pages = []
                for page in doc:
                    pages.append(page.get_text())
                doc.close()
                text = "\n\n".join(pages)
                if text and text.strip():
                    md = text.strip()
                    note += " Used PyMuPDF for PDF extraction."
                    return md, note
            except Exception as e:
                note += f" PyMuPDF failed ({str(e)[:30]}...)."

        elif ext == ".docx":
            # DOCX fallback
            try:
                doc = docx.Document(str(file_path))
                paragraphs = []
                for para in doc.paragraphs:
                    if para.text.strip():
                        paragraphs.append(para.text.strip())
                text = "\n\n".join(paragraphs)
                if text and text.strip():
                    md = text.strip()
                    note += " Used python-docx for DOCX extraction."
                    return md, note
            except Exception as e:
                note += f" python-docx failed ({str(e)[:30]}...)."

        # 4) OCR fallback for images and any other format
        if ext in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"} or not md:
            try:
                # Load image
                image = Image.open(str(file_path))
                
                # Configure OCR
                config = f'--oem 3 --psm {ocr_settings.psm} -l {ocr_settings.language}'
                
                # Try OCR with detailed output first
                try:
                    ocr_data = pytesseract.image_to_data(image, config=config, output_type=Output.DICT)
                    confidences = [int(conf) for conf in ocr_data['conf'] if int(conf) > 0]
                    avg_confidence = sum(confidences) / len(confidences) if confidences else 0
                    
                    # Get text
                    text = pytesseract.image_to_string(image, config=config)
                    
                    if text and text.strip():
                        md = text.strip()
                        note += f" Used Tesseract OCR (avg confidence: {avg_confidence:.1f}%)."
                        return md, note
                    else:
                        note += f" OCR completed but no text extracted (confidence: {avg_confidence:.1f}%)."
                
                except Exception as e:
                    # Fallback to simple OCR
                    text = pytesseract.image_to_string(image)
                    if text and text.strip():
                        md = text.strip()
                        note += f" Used simple Tesseract OCR fallback."
                        return md, note
                    else:
                        note += f" Simple OCR fallback also failed: {str(e)[:50]}..."
                        
            except Exception as e:
                note += f" OCR processing failed: {str(e)[:50]}..."

        # If we get here, all methods failed
        if not md:
            note += " All conversion methods failed to extract text."
        
        return md, note
    
    async def process_document(
        self, 
        document_id: str, 
        file_path: Path, 
        options: ProcessingOptions
    ) -> ProcessingResult:
        """
        Process a single document through the complete processing pipeline.
        
        Executes the full document processing workflow from conversion through
        optimization and evaluation. This is the main processing method that
        coordinates all steps of the document processing pipeline.
        
        Args:
            document_id (str): Unique identifier for the document
            file_path (Path): Path to the original document file
            options (ProcessingOptions): Processing configuration and thresholds
        
        Returns:
            ProcessingResult: Complete processing results with all metadata
        
        Processing Pipeline:
            1. Document conversion to markdown
            2. Document summarization (if LLM available)
            3. Vector database optimization (if enabled and LLM available)
            4. File output and storage
            5. LLM evaluation (if LLM available)
            6. Quality threshold validation
            7. Result compilation and metadata generation
        
        Quality Assessment:
            - Conversion quality scoring
            - LLM evaluation across 4 dimensions
            - Threshold compliance checking
            - RAG readiness determination
        
        Optimization Features:
            - Vector database optimization for better chunking
            - Content structure enhancement
            - Keyword enrichment for semantic search
        
        Error Handling:
            - Comprehensive error catching at each pipeline stage
            - Graceful degradation when LLM is unavailable
            - Detailed error reporting in processing results
            - Processing time tracking for performance monitoring
        
        Example:
            >>> result = await document_service.process_document(
            >>>     doc_id, file_path, processing_options
            >>> )
            >>> print(f"Processing {'successful' if result.success else 'failed'}")
        """
        start_time = time.time()
        filename = file_path.name.split('_', 1)[-1] if '_' in file_path.name else file_path.name
        
        try:
            print(f"🔄 Processing document: {filename} (ID: {document_id})")
            
            # Step 1: Convert to markdown
            conversion_result = await self.convert_to_markdown(file_path, options.ocr_settings)
            
            if not conversion_result.success or not conversion_result.markdown_content:
                return ProcessingResult(
                    document_id=document_id,
                    filename=filename,
                    status=ProcessingStatus.FAILED,
                    success=False,
                    error_message=f"Conversion failed: {conversion_result.conversion_feedback}",
                    original_path=str(file_path),
                    conversion_result=conversion_result,
                    llm_evaluation=None,
                    is_rag_ready=False,
                    processing_time=time.time() - start_time,
                    processed_at=datetime.now(),
                    file_size=0,
                )
            
            markdown_content = conversion_result.markdown_content
            print(f"✅ Conversion successful: {len(markdown_content)} characters")
            
            # Step 2: Summary generation disabled while LLM processing is off
            document_summary = None

            # Step 3: Vector DB optimization disabled while LLM processing is off
            vector_optimized = False
            optimization_note = ""
            
            # Step 4: Save processed markdown
            output_path = self.processed_dir / f"{file_path.stem}_{document_id}.md"
            try:
                output_path.write_text(markdown_content, encoding="utf-8")
                print(f"💾 Saved processed content: {output_path}")
            except Exception as e:
                return ProcessingResult(
                    document_id=document_id,
                    filename=filename,
                    status=ProcessingStatus.FAILED,
                    success=False,
                    error_message=f"Failed to save processed content: {str(e)}",
                    original_path=str(file_path),
                    conversion_result=conversion_result,
                    llm_evaluation=None,
                    is_rag_ready=False,
                    processing_time=time.time() - start_time,
                    processed_at=datetime.now(),
                    file_size=0,
                )
            
            # Update conversion result with any optimization notes
            conversion_result.conversion_note = f"{optimization_note}{conversion_result.conversion_note}"
            
            # Step 5: LLM evaluation disabled while LLM processing is off
            llm_evaluation = None
            
            # Step 6: Check quality thresholds
            passes_thresholds = self._meets_thresholds(
                conversion_result.conversion_score,
                llm_evaluation,
                options.quality_thresholds
            )
            status = "✅ PASS" if passes_thresholds else "❌ FAIL"
            print(f"🎯 Quality check: {status}")
            
            processing_time = time.time() - start_time
            print(f"⏱️ Processing completed in {processing_time:.2f}s")
            
            return ProcessingResult(
                document_id=document_id,
                filename=filename,
                status=ProcessingStatus.COMPLETED,
                success=True,
                original_path=str(file_path),
                markdown_path=str(output_path),
                conversion_result=conversion_result,
                llm_evaluation=llm_evaluation,
                document_summary=document_summary,
                conversion_score=conversion_result.conversion_score,
                is_rag_ready=passes_thresholds,
                vector_optimized=vector_optimized,
                processing_time=processing_time,
                processed_at=datetime.now(),
                file_size=output_path.stat().st_size if output_path.exists() else 0,
            )
            
        except Exception as e:
            print(f"❌ Processing error for {filename}: {e}")
            import traceback
            traceback.print_exc()
            
            # Construct a minimal conversion_result for error context
            minimal_conv = ConversionResult(
                success=False,
                markdown_content="",
                conversion_score=0,
                conversion_feedback=f"Processing error: {str(e)}",
                word_count=0,
                char_count=0,
                processing_time=time.time() - start_time,
                conversion_note="Processing pipeline error",
            )

            return ProcessingResult(
                document_id=document_id,
                filename=filename,
                status=ProcessingStatus.FAILED,
                success=False,
                error_message=f"Processing error: {str(e)}",
                original_path=str(file_path),
                conversion_result=minimal_conv,
                llm_evaluation=None,
                is_rag_ready=False,
                processing_time=time.time() - start_time,
                processed_at=datetime.now(),
                file_size=0,
            )
    
    async def process_batch(
        self, 
        document_ids: List[str], 
        options: ProcessingOptions
    ) -> List[ProcessingResult]:
        """
        Process multiple documents in sequence.
        
        Processes a batch of documents using the same processing options.
        Each document is processed individually with the full pipeline,
        allowing for different outcomes per document.
        
        Args:
            document_ids (List[str]): List of document IDs to process
            options (ProcessingOptions): Shared processing configuration
        
        Returns:
            List[ProcessingResult]: List of processing results for each document
        
        Processing Strategy:
            - Sequential processing (not parallel) for resource management
            - Individual error handling per document
            - Missing files are handled gracefully with error results
            - Each document gets full pipeline treatment
        
        Error Handling:
            - Missing documents result in failed ProcessingResult
            - Individual document failures don't stop batch processing
            - Comprehensive error reporting per document
        
        Performance Considerations:
            - Sequential processing prevents resource contention
            - Memory usage scales with document size, not count
            - Processing time is sum of individual document times
        
        Example:
            >>> results = await document_service.process_batch(
            >>>     ["doc1", "doc2", "doc3"], processing_options
            >>> )
            >>> successful = [r for r in results if r.success]
            >>> print(f"Processed {len(successful)}/{len(results)} documents successfully")
        """
        results = []
        
        for doc_id in document_ids:
            # Find the file for this document ID
            file_path = self._find_document_file(doc_id)
            if not file_path:
                # Build a minimal-but-valid result object for missing files
                minimal_conv = ConversionResult(
                    success=False,
                    markdown_content="",
                    conversion_score=0,
                    conversion_feedback="Document file not found",
                    word_count=0,
                    char_count=0,
                    processing_time=0.0,
                    conversion_note="",
                )
                results.append(ProcessingResult(
                    document_id=doc_id,
                    filename=f"unknown_{doc_id}",
                    status=ProcessingStatus.FAILED,
                    success=False,
                    error_message="Document file not found",
                    original_path=None,
                    conversion_result=minimal_conv,
                    llm_evaluation=None,
                    is_rag_ready=False,
                    processing_time=0.0,
                    processed_at=datetime.now(),
                    file_size=0,
                ))
                continue
            
            result = await self.process_document(doc_id, file_path, options)
            results.append(result)
        
        return results
    
    async def update_document_content(
        self, 
        document_id: str, 
        content: str, 
        options: ProcessingOptions,
        improvement_prompt: Optional[str] = None,
        apply_vector_optimization: bool = False
    ) -> Optional[ProcessingResult]:
        """
        Update document content with optional LLM improvements and re-evaluation.
        
        Allows updating processed document content. LLM-based improvements and
        vector optimization are currently disabled. The updated content is
        re-scored to provide fresh quality metrics.
        
        Args:
            document_id (str): Document ID to update
            content (str): New content to save
            options (ProcessingOptions): Processing options for re-evaluation
            improvement_prompt (Optional[str]): Custom prompt for LLM improvement
            apply_vector_optimization (bool): Whether to apply vector DB optimization
        
        Returns:
            Optional[ProcessingResult]: Updated processing result, or None if document not found
        
        Update Process:
            1. Locates existing processed file
            2. Saves updated content to file
            3. Re-evaluates content quality
            5. Checks thresholds with new scores
            6. Returns updated ProcessingResult
        
        LLM Integration:
            - Disabled for document editing and optimization
        
        Re-evaluation:
            - Fresh conversion scoring
            - New LLM evaluation if available
            - Updated threshold compliance checking
            - Metadata refresh with current processing options
        
        Error Handling:
            - Missing documents return None
            - LLM failures fall back to original content
            - File write errors are logged and handled
            - Evaluation errors are caught and logged
        
        Example:
            >>> result = await document_service.update_document_content(
            >>>     "doc123", 
            >>>     updated_content,
            >>>     options,
            >>>     improvement_prompt="Make this more concise"
            >>> )
            >>> if result:
            >>>     print(f"Updated with score: {result.conversion_score}/100")
        """
        try:
            processed_file_path = next(self.processed_dir.glob(f"*_{document_id}.md"), None)
            if not processed_file_path:
                return None

            final_content = content
            vector_optimized = False
            processed_file_path.write_text(final_content, encoding="utf-8")
            
            # Re-evaluate
            score, feedback = self._score_conversion(final_content)
            llm_evaluation = None
            passes_thresholds = self._meets_thresholds(score, llm_evaluation, options.quality_thresholds)
            
            # Find original file to create a full result object
            original_file_path = self._find_document_file(document_id)
            filename = original_file_path.name.split('_', 1)[-1] if original_file_path else processed_file_path.stem.split('_', 1)[-1]

            return ProcessingResult(
                document_id=document_id,
                filename=filename,
                status=ProcessingStatus.COMPLETED,
                success=True,
                original_path=str(original_file_path) if original_file_path else None,
                markdown_path=str(processed_file_path),
                conversion_result=ConversionResult(
                    success=True,
                    markdown_content=final_content,
                    conversion_score=score,
                    conversion_feedback=feedback,
                    word_count=len(final_content.split()),
                    char_count=len(final_content),
                    processing_time=0.0,
                    conversion_note="Content updated and re-evaluated.",
                ),
                llm_evaluation=llm_evaluation,
                conversion_score=score,
                is_rag_ready=passes_thresholds,
                vector_optimized=vector_optimized,
                processing_time=0.0,  # Not a full process
                processed_at=datetime.now(),
                file_size=processed_file_path.stat().st_size if processed_file_path.exists() else 0,
            )
            
        except Exception as e:
            print(f"Error updating document {document_id}: {e}")
            return None


# ============================================================================
# Global Document Service Instance
# ============================================================================

# Create a single global instance of the document service
# This ensures consistent file handling and processing across the application
document_service = DocumentService()
