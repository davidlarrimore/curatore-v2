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
    """

    DEFAULT_EXTS: Set[str] = {
        ".pdf", ".doc", ".docx", ".ppt", ".pptx",
        ".xls", ".xlsx", ".csv", ".txt", ".md",
        ".png", ".jpg", ".jpeg", ".gif", ".tif", ".tiff", ".bmp"
    }

    def __init__(self) -> None:
        files_root = getattr(settings, "files_root", None)
        self.files_root: Optional[Path] = Path(files_root) if files_root else None

        self.upload_dir: Path = Path(getattr(settings, "upload_dir", "files/uploaded_files"))
        self.processed_dir: Path = Path(getattr(settings, "processed_dir", "files/processed_files"))
        batch_dir_val = getattr(settings, "batch_dir", None)
        self.batch_dir: Optional[Path] = Path(batch_dir_val) if batch_dir_val else None

        self._normalize_under_root()
        self._ensure_directories()

        self._supported_extensions: Set[str] = self._load_supported_extensions()

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

    # ----------------------- Public FS API -----------------------

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

    # ---- Lists used by the UI (now matching FileListResponse expectations) ----

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

    # ---- Retrieval helpers ----

    def get_processed_content(self, document_id: str) -> Optional[str]:
        """Get processed markdown content for a document."""
        for file_path in self.processed_dir.glob(f"*_{document_id}.md"):
            try:
                return file_path.read_text(encoding="utf-8")
            except Exception:
                continue
        return None

    def find_batch_file(self, filename: str) -> Optional[Path]:
        """Find a batch file by filename."""
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
        """Find the original document file by document_id."""
        for p in self.upload_dir.glob(f"{document_id}_*.*"):
            if p.is_file():
                return p
        if document_id.startswith("batch_") and self.batch_dir:
            stem = document_id.replace("batch_", "")
            for p in self.batch_dir.glob(f"{stem}.*"):
                if p.is_file() and self.is_supported_file(p.name):
                    return p
        return None

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
        
        # Basic scoring logic - can be enhanced later
        score = 50  # Base score
        
        # Check for common markdown elements
        if "# " in markdown_text or "## " in markdown_text:
            score += 20  # Has headers
        
        if len(markdown_text.strip()) > 100:
            score += 15  # Has substantial content
        
        if "**" in markdown_text or "*" in markdown_text:
            score += 10  # Has emphasis
            
        if "[" in markdown_text and "](" in markdown_text:
            score += 5  # Has links
            
        score = min(score, 100)  # Cap at 100
        
        feedback = f"Conversion score: {score}/100"
        if score >= 80:
            feedback += " - Excellent conversion quality"
        elif score >= 60:
            feedback += " - Good conversion quality"
        elif score >= 40:
            feedback += " - Fair conversion quality"
        else:
            feedback += " - Poor conversion quality"
            
        return score, feedback


# Singleton instance
document_service = DocumentService()