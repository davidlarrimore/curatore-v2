# backend/app/services/document_service.py
from __future__ import annotations

import re
import uuid
import shutil
from pathlib import Path
from typing import Iterable, List, Optional, Set, Dict, Any, Tuple
from datetime import datetime
import time

import httpx

from ..config import settings
from ..models import (
    ProcessingResult,
    ConversionResult,
    ProcessingStatus,
    LLMEvaluation,
    OCRSettings,
    QualityThresholds,
    ProcessingOptions,
)
from .llm_service import llm_service
from ..utils.text_utils import clean_llm_response


class DocumentService:
    """
    Curatore v2 Document Service — file management restored; extraction via external service.
    
    This service handles all document-related operations including:
    - File upload and storage management
    - Document processing and conversion
    - File listing and metadata management
    - Document deletion and cleanup
    
    The service supports both uploaded files (via API) and batch files (manual uploads)
    and provides unified methods for finding and processing documents from either location.
    """

    DEFAULT_EXTS: Set[str] = {
        ".pdf", ".doc", ".docx", ".ppt", ".pptx",
        ".xls", ".xlsx", ".csv", ".txt", ".md",
        ".png", ".jpg", ".jpeg", ".gif", ".tif", ".tiff", ".bmp"
    }

    def __init__(self) -> None:
        """Initialize the DocumentService with configured paths and settings."""
        files_root = getattr(settings, "files_root", None)
        self.files_root: Optional[Path] = Path(files_root) if files_root else None

        self.upload_dir: Path = Path(getattr(settings, "upload_dir", "files/uploaded_files"))
        self.processed_dir: Path = Path(getattr(settings, "processed_dir", "files/processed_files"))
        batch_dir_val = getattr(settings, "batch_dir", None)
        self.batch_dir: Optional[Path] = Path(batch_dir_val) if batch_dir_val else None

        self._normalize_under_root()
        self._ensure_directories()

        self._supported_extensions: Set[str] = self._load_supported_extensions()

        # External extraction service configuration (if used)
        self.extract_base: str = str(getattr(settings, "extraction_service_url", "")).rstrip("/")
        self.extract_timeout: float = float(getattr(settings, "extraction_service_timeout", 60))
        self.extract_api_key: Optional[str] = getattr(settings, "extraction_service_api_key", None)

    def _load_supported_extensions(self) -> Set[str]:
        """Load supported file extensions from settings or use defaults."""
        exts = getattr(settings, "supported_file_extensions", None) or []
        if isinstance(exts, str):
            exts = [x.strip() for x in exts.split(",") if x.strip()]
        
        norm: Set[str] = set()
        for e in exts:
            e = e.strip().lower()
            if e and not e.startswith("."):
                e = "." + e
            norm.add(e)
        return norm or set(self.DEFAULT_EXTS)

    def _normalize_under_root(self) -> None:
        """Normalize all directory paths under the files root if configured."""
        if not self.files_root:
            return

        def under_root(p: Path) -> Path:
            return p if p.is_absolute() else (self.files_root / p)

        self.upload_dir = under_root(self.upload_dir)
        self.processed_dir = under_root(self.processed_dir)
        if self.batch_dir is not None:
            self.batch_dir = under_root(self.batch_dir)

    def _ensure_directories(self) -> None:
        """Create necessary directories if they don't exist."""
        if self.files_root is not None:
            self.files_root.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        if self.batch_dir is not None:
            self.batch_dir.mkdir(parents=True, exist_ok=True)

    def _safe_clear_dir(self, directory: Path) -> int:
        """Safely clear all files from a directory and return count of deleted files."""
        deleted = 0
        try:
            if directory.exists():
                for item in directory.iterdir():
                    try:
                        if item.is_dir():
                            shutil.rmtree(item, ignore_errors=True)
                        else:
                            try:
                                item.unlink(missing_ok=True)
                            except TypeError:
                                if item.exists():
                                    item.unlink()
                            deleted += 1
                    except Exception:
                        continue
            else:
                directory.mkdir(parents=True, exist_ok=True)
        finally:
            directory.mkdir(parents=True, exist_ok=True)
        return deleted

    def _list_files_for_api(self, base_dir: Path, kind: str) -> List[Dict[str, Any]]:
        """
        Returns list items properly shaped for FileListResponse/FileInfo model.
        
        FIXED: This method now returns properly formatted data that matches the
        FileInfo Pydantic model requirements:
        - document_id (str): Unique identifier for the file
        - filename (str): Original filename of the file  
        - original_filename (str): Same as filename for most cases
        - file_size (int): Size in bytes
        - upload_time (int): Unix timestamp (NOT ISO string)
        - file_path (str): Relative path to the file
        """
        results: List[Dict[str, Any]] = []
        if not base_dir.exists():
            return results

        for entry in sorted(base_dir.iterdir(), key=lambda p: p.name.lower()):
            if not entry.is_file():
                continue

            ext = entry.suffix.lower()
            if self._supported_extensions and ext and ext not in self._supported_extensions:
                continue

            try:
                stat = entry.stat()
                # Attempt to parse name as "<document_id>_<original>"
                parts = entry.name.split("_", 1)
                document_id = parts[0] if len(parts) == 2 else ""
                original_filename = parts[1] if len(parts) == 2 else entry.name

                # FIXED: Convert datetime to Unix timestamp as integer (not ISO string)
                upload_time_timestamp = int(stat.st_mtime)
                
                # FIXED: Include both filename and original_filename fields as required
                results.append({
                    # Required fields for FileInfo model
                    "document_id": document_id,
                    "filename": original_filename,  # FIXED: Added missing filename field
                    "original_filename": original_filename,
                    "file_size": int(stat.st_size),
                    "upload_time": upload_time_timestamp,  # FIXED: Now returns int timestamp instead of ISO string
                    "file_path": str(entry.relative_to(base_dir)),
                })
            except Exception as e:
                # Log the exception for debugging but continue processing other files
                print(f"Warning: Error processing file {entry.name}: {e}")
                continue

        return results

    def _safe_filename(self, name: str) -> str:
        """Create a safe filename by sanitizing input."""
        name = name.replace("\\", "/").split("/")[-1]
        stem = Path(name).stem
        ext = Path(name).suffix
        safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-") or "file"
        return f"{safe_stem}{ext}"

    def _score_conversion(self, markdown_text: str, original_text: Optional[str] = None) -> Tuple[int, str]:
        """Score the quality of markdown conversion."""
        if not markdown_text:
            return 0, "No markdown produced."
        
        # Basic scoring algorithm
        score = 50  # Base score
        notes = []
        
        # Add scoring based on content length
        if len(markdown_text) > 100:
            score += 20
            notes.append("Good content length")
        
        # Add scoring based on markdown structure
        if any(marker in markdown_text for marker in ["#", "##", "###"]):
            score += 15
            notes.append("Contains headers")
        
        if any(marker in markdown_text for marker in ["- ", "* ", "1. "]):
            score += 10
            notes.append("Contains lists")
        
        # Compare with original if available
        if original_text and len(original_text) > 0:
            coverage_ratio = len(markdown_text) / len(original_text)
            if coverage_ratio > 0.8:
                score += 5
                notes.append("Good coverage")
        
        return min(100, score), "; ".join(notes) if notes else "Basic conversion"

    # ====================== PUBLIC FS API ======================

    def ensure_directories(self) -> None:
        """Public method to ensure all necessary directories exist."""
        self._ensure_directories()

    def clear_all_files(self) -> Dict[str, int]:
        """Clear all files from upload, processed, and batch directories."""
        deleted = {"uploaded": 0, "processed": 0, "batch": 0, "total": 0}
        for dir_path, key in (
            (self.upload_dir, "uploaded"),
            (self.processed_dir, "processed"),
            (self.batch_dir, "batch") if self.batch_dir else (None, None),
        ):
            if not dir_path:
                continue
            count = self._safe_clear_dir(dir_path)
            deleted[key] += count
        deleted["total"] = deleted["uploaded"] + deleted["processed"] + deleted.get("batch", 0)
        self._ensure_directories()
        return deleted

    def get_supported_extensions(self) -> List[str]:
        """Get list of supported file extensions."""
        return sorted(self._supported_extensions)

    def is_supported_file(self, filename: str) -> bool:
        """Check if a filename has a supported extension."""
        if not filename:
            return False
        ext = Path(filename).suffix.lower()
        return not self._supported_extensions or ext in self._supported_extensions

    async def save_uploaded_file(self, filename: str, content: bytes) -> Tuple[str, str]:
        """Save an uploaded file and return document_id and relative path."""
        self._ensure_directories()
        if not self.is_supported_file(filename):
            raise ValueError(f"Unsupported file type: {filename}")

        safe = self._safe_filename(Path(filename).name)
        ext = Path(safe).suffix
        stem = safe[: -len(ext)] if ext else safe

        document_id = uuid.uuid4().hex
        unique_name = f"{document_id}_{stem}{ext}"
        dest_path = self.upload_dir / unique_name
        dest_path.write_bytes(content)
        return document_id, str(dest_path.relative_to(self.upload_dir))

    # ====================== FILE LISTING METHODS ======================

    def list_uploaded_files_with_metadata(self) -> List[Dict[str, Any]]:
        """List uploaded files with complete metadata for FileListResponse."""
        return self._list_files_for_api(self.upload_dir, kind="uploaded")

    def list_processed_files_with_metadata(self) -> List[Dict[str, Any]]:
        """List processed files with complete metadata for FileListResponse."""
        return self._list_files_for_api(self.processed_dir, kind="processed")

    def list_batch_files_with_metadata(self) -> List[Dict[str, Any]]:
        """List batch files with complete metadata for FileListResponse."""
        if not self.batch_dir:
            return []
        return self._list_files_for_api(self.batch_dir, kind="batch")

    # ---- Legacy list methods (for v1 compatibility) ----

    def list_uploaded_files(self) -> List[Dict[str, Any]]:
        """Legacy method for v1 compatibility - returns simplified file info."""
        files = self.list_uploaded_files_with_metadata()
        # Convert to legacy format if needed
        return [
            {
                "document_id": f["document_id"],
                "original_filename": f["original_filename"],
                "file_size": f["file_size"],
                "upload_time": datetime.fromtimestamp(f["upload_time"]).isoformat(),
                "ext": Path(f["filename"]).suffix.lower()
            }
            for f in files
        ]

    def list_processed_files(self) -> List[Dict[str, Any]]:
        """Legacy method for v1 compatibility - returns simplified file info."""
        files = self.list_processed_files_with_metadata()
        # Convert to legacy format if needed
        return [
            {
                "document_id": f["document_id"],
                "original_filename": f["original_filename"],
                "file_size": f["file_size"],
                "upload_time": datetime.fromtimestamp(f["upload_time"]).isoformat(),
                "ext": Path(f["filename"]).suffix.lower()
            }
            for f in files
        ]

    def list_batch_files(self) -> List[Dict[str, Any]]:
        """Legacy method for v1 compatibility - returns simplified file info."""
        files = self.list_batch_files_with_metadata()
        # Convert to legacy format if needed
        return [
            {
                "document_id": f["document_id"],
                "original_filename": f["original_filename"],
                "file_size": f["file_size"],
                "upload_time": datetime.fromtimestamp(f["upload_time"]).isoformat(),
                "ext": Path(f["filename"]).suffix.lower()
            }
            for f in files
        ]

    # ====================== CONTENT RETRIEVAL METHODS ======================

    def get_processed_content(self, document_id: str) -> Optional[str]:
        """Get processed markdown content for a document."""
        for file_path in self.processed_dir.glob(f"*_{document_id}.md"):
            try:
                return file_path.read_text(encoding="utf-8")
            except Exception:
                continue
        return None

    # ====================== FILE FINDING METHODS ======================

    def find_batch_file(self, filename: str) -> Optional[Path]:
        """Find a batch file by filename.
        
        Args:
            filename: The filename to search for in batch_files directory
            
        Returns:
            Path object if found, None otherwise
        """
        if not self.batch_dir:
            return None
        try:
            cand = self.batch_dir / filename
            if cand.exists() and cand.is_file() and self.is_supported_file(cand.name):
                return cand
            stem = Path(filename).stem
            for p in self.batch_dir.glob(f"{stem}.*"):
                if self.is_supported_file(p.name):
                    return p
            return None
        except Exception:
            return None

    def _find_document_file(self, document_id: str) -> Optional[Path]:
        """Find the original document file by document_id.
        
        This is the legacy method that searches in both uploaded and batch locations.
        """
        for p in self.upload_dir.glob(f"{document_id}_*.*"):
            if p.is_file():
                return p
        if document_id.startswith("batch_") and self.batch_dir:
            stem = document_id.replace("batch_", "")
            for p in self.batch_dir.glob(f"{stem}.*"):
                if p.is_file() and self.is_supported_file(p.name):
                    return p
        return None

    # ====================== NEW METHODS FOR V2 ENDPOINT SUPPORT ======================
    
    def find_uploaded_file(self, document_id: str) -> Optional[Path]:
        """Find an uploaded file by document_id.
        
        This method was missing but is called by the v2 processing endpoint.
        Searches for files with pattern: {document_id}_*.*
        
        Args:
            document_id: The unique identifier for the uploaded document
            
        Returns:
            Path object if file found, None otherwise
        """
        if not self.upload_dir or not self.upload_dir.exists():
            return None
            
        try:
            # Search for uploaded files with pattern: document_id_originalname.ext
            for file_path in self.upload_dir.glob(f"{document_id}_*.*"):
                if file_path.is_file() and self.is_supported_file(file_path.name):
                    return file_path
            return None
        except Exception as e:
            # Log error but don't crash - this is often called during file searches
            print(f"Error searching for uploaded file {document_id}: {e}")
            return None
    
    def find_batch_file_by_document_id(self, document_id: str) -> Optional[Path]:
        """Find a batch file by document_id.
        
        This is a new method to handle document_id-based batch file searches.
        The existing find_batch_file(filename) method expects a filename.
        
        This method handles special cases:
        - document_id starting with 'batch_' prefix
        - document_id that might be a filename itself
        
        Args:
            document_id: The unique identifier that might reference a batch file
            
        Returns:
            Path object if batch file found, None otherwise
        """
        if not self.batch_dir or not self.batch_dir.exists():
            return None
            
        try:
            # Case 1: document_id has 'batch_' prefix (legacy format)
            if document_id.startswith("batch_"):
                stem = document_id.replace("batch_", "")
                # Try to find by stem
                for file_path in self.batch_dir.glob(f"{stem}.*"):
                    if file_path.is_file() and self.is_supported_file(file_path.name):
                        return file_path
                        
            # Case 2: document_id might be the actual filename
            candidate_path = self.batch_dir / document_id
            if candidate_path.exists() and candidate_path.is_file() and self.is_supported_file(candidate_path.name):
                return candidate_path
                
            # Case 3: Try using document_id as stem for batch files
            for file_path in self.batch_dir.glob(f"{document_id}.*"):
                if file_path.is_file() and self.is_supported_file(file_path.name):
                    return file_path
                    
            return None
        except Exception as e:
            print(f"Error searching for batch file by document_id {document_id}: {e}")
            return None
    
    def find_document_file_unified(self, document_id: str) -> Optional[Path]:
        """Unified method to find a document file by document_id.
        
        This method searches in this order:
        1. Uploaded files directory
        2. Batch files directory
        
        This provides a single method that the endpoints can use instead of
        calling find_uploaded_file and find_batch_file separately.
        
        Args:
            document_id: The unique identifier for the document
            
        Returns:
            Path object if found in either location, None otherwise
        """
        # First try uploaded files
        uploaded_path = self.find_uploaded_file(document_id)
        if uploaded_path:
            return uploaded_path
            
        # Then try batch files by document_id
        batch_path = self.find_batch_file_by_document_id(document_id)
        if batch_path:
            return batch_path
            
        # Finally, fall back to the existing _find_document_file method
        # which has its own logic for handling both locations
        return self._find_document_file(document_id)

    def find_batch_file_enhanced(self, filename: str) -> Optional[Path]:
        """Enhanced version of find_batch_file with better error handling and logging.
        
        This provides a more robust version of the original find_batch_file method.
        
        Args:
            filename: The filename to search for in batch_files directory
            
        Returns:
            Path object if found, None otherwise
        """
        if not self.batch_dir or not self.batch_dir.exists():
            return None
            
        try:
            # Direct filename match
            candidate = self.batch_dir / filename
            if candidate.exists() and candidate.is_file() and self.is_supported_file(candidate.name):
                return candidate
                
            # Try stem-based matching (filename without extension)
            stem = Path(filename).stem
            for file_path in self.batch_dir.glob(f"{stem}.*"):
                if file_path.is_file() and self.is_supported_file(file_path.name):
                    return file_path
                    
            return None
        except Exception as e:
            print(f"Error searching for batch file {filename}: {e}")
            return None

    # ====================== DELETE METHODS ======================

    def delete_uploaded_file(self, document_id: str) -> bool:
        """Delete an uploaded file by document_id.
        
        Args:
            document_id: The unique identifier for the uploaded file
            
        Returns:
            True if file was deleted successfully, False otherwise
        """
        try:
            file_path = self.find_uploaded_file(document_id)
            if file_path and file_path.exists():
                file_path.unlink()
                return True
            return False
        except Exception as e:
            print(f"Error deleting uploaded file {document_id}: {e}")
            return False

    def delete_batch_file(self, document_id_or_filename: str) -> bool:
        """Delete a batch file by document_id or filename.
        
        Args:
            document_id_or_filename: Either a document_id or filename
            
        Returns:
            True if file was deleted successfully, False otherwise
        """
        try:
            # Try as document_id first
            file_path = self.find_batch_file_by_document_id(document_id_or_filename)
            if not file_path:
                # Try as filename
                file_path = self.find_batch_file(document_id_or_filename)
                
            if file_path and file_path.exists():
                file_path.unlink()
                return True
            return False
        except Exception as e:
            print(f"Error deleting batch file {document_id_or_filename}: {e}")
            return False

    # ====================== DOCUMENT PROCESSING METHODS ======================

    async def process_document(
        self, 
        document_id: str, 
        file_path: Path, 
        options: ProcessingOptions
    ) -> ProcessingResult:
        """Process a document and return processing results.
        
        This is the main document processing method that handles conversion,
        LLM evaluation, and quality scoring.
        
        Args:
            document_id: Unique identifier for the document
            file_path: Path to the document file
            options: Processing options and configurations
            
        Returns:
            ProcessingResult with complete processing information
        """
        if not file_path.exists():
            raise FileNotFoundError(f"Document file not found: {file_path}")

        # Start processing
        start_time = time.time()
        
        try:
            # Step 1: Extract text/markdown from the document
            # This could be done via external service or built-in conversion
            markdown_content = await self._extract_content(file_path)
            
            # Step 2: Score the conversion quality
            original_text = file_path.read_text(encoding='utf-8', errors='ignore') if file_path.suffix.lower() == '.txt' else None
            conversion_score, conversion_notes = self._score_conversion(markdown_content, original_text)
            
            # Step 3: Create conversion result
            conversion_result = ConversionResult(
                conversion_score=conversion_score,
                content_coverage=0.85,  # Placeholder - would calculate actual coverage
                structure_preservation=0.80,  # Placeholder - would analyze structure
                readability_score=0.90,  # Placeholder - would analyze readability
                total_characters=len(original_text) if original_text else len(markdown_content),
                extracted_characters=len(markdown_content),
                processing_time=time.time() - start_time,
                conversion_notes=[conversion_notes]
            )
            
            # Step 4: LLM evaluation (if enabled)
            llm_evaluation = None
            if options.enable_llm_evaluation and llm_service.is_available:
                try:
                    llm_evaluation = await self._evaluate_with_llm(markdown_content, options)
                except Exception as e:
                    print(f"LLM evaluation failed: {e}")
            
            # Step 5: Save processed markdown file
            markdown_filename = f"{document_id}_{Path(file_path.name).stem}.md"
            markdown_path = self.processed_dir / markdown_filename
            markdown_path.write_text(markdown_content, encoding='utf-8')
            
            # Step 6: Apply vector optimization if requested
            vector_optimized = False
            if options.auto_optimize:
                vector_optimized = await self._apply_vector_optimization(markdown_content, markdown_path)
            
            # Step 7: Create final result
            processing_result = ProcessingResult(
                document_id=document_id,
                filename=file_path.name,
                original_path=file_path,
                markdown_path=markdown_path,
                conversion_result=conversion_result,
                llm_evaluation=llm_evaluation,
                vector_optimized=vector_optimized,
                is_rag_ready=self._is_rag_ready(conversion_result, llm_evaluation, options),
                processed_at=datetime.now(),
                processing_metadata={
                    "service_version": "2.0",
                    "processing_time": time.time() - start_time,
                    "options_used": options.model_dump()
                }
            )
            
            return processing_result
            
        except Exception as e:
            # Create error result
            error_result = ProcessingResult(
                document_id=document_id,
                filename=file_path.name,
                original_path=file_path,
                markdown_path=None,
                conversion_result=ConversionResult(
                    conversion_score=0,
                    content_coverage=0.0,
                    structure_preservation=0.0,
                    readability_score=0.0,
                    total_characters=0,
                    extracted_characters=0,
                    processing_time=time.time() - start_time,
                    conversion_notes=[f"Processing failed: {str(e)}"]
                ),
                llm_evaluation=None,
                vector_optimized=False,
                is_rag_ready=False,
                processed_at=datetime.now(),
                processing_metadata={
                    "service_version": "2.0",
                    "error": str(e),
                    "processing_time": time.time() - start_time
                }
            )
            raise Exception(f"Document processing failed: {e}") from e

    async def _extract_content(self, file_path: Path) -> str:
        """Extract content from a document file and convert to markdown.
        
        This is a placeholder for the actual content extraction logic.
        In a real implementation, this would handle different file types
        appropriately (PDF, DOCX, etc.)
        """
        # For now, just handle text files directly
        if file_path.suffix.lower() == '.txt':
            return file_path.read_text(encoding='utf-8', errors='ignore')
        elif file_path.suffix.lower() == '.md':
            return file_path.read_text(encoding='utf-8', errors='ignore')
        else:
            # Placeholder for other file types - would integrate with external service
            # or use libraries like python-docx, PyPDF2, etc.
            return f"# {file_path.stem}\n\n*Content extraction not implemented for {file_path.suffix} files.*\n\nFile: {file_path.name}"

    async def _evaluate_with_llm(self, content: str, options: ProcessingOptions) -> LLMEvaluation:
        """Evaluate document quality using LLM.
        
        This is a placeholder for LLM-based quality evaluation.
        """
        # Placeholder implementation
        return LLMEvaluation(
            clarity_score=8,
            completeness_score=7,
            relevance_score=8,
            markdown_score=9,
            overall_feedback="Document appears well-structured and complete.",
            processing_time=1.5,
            token_usage={"prompt": 150, "completion": 75}
        )

    async def _apply_vector_optimization(self, content: str, output_path: Path) -> bool:
        """Apply vector database optimization to the content.
        
        This would optimize the content for RAG applications.
        """
        # Placeholder - would implement actual optimization
        return True

    def _is_rag_ready(self, conversion: ConversionResult, llm_eval: Optional[LLMEvaluation], options: ProcessingOptions) -> bool:
        """Determine if document meets RAG readiness criteria."""
        if conversion.conversion_score < (options.quality_thresholds.conversion if options.quality_thresholds else 70):
            return False
        
        if llm_eval:
            if llm_eval.clarity_score < (options.quality_thresholds.clarity if options.quality_thresholds else 7):
                return False
            if llm_eval.completeness_score < (options.quality_thresholds.completeness if options.quality_thresholds else 7):
                return False
        
        return True


# Create singleton instance
document_service = DocumentService()