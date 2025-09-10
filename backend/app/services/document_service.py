# backend/app/services/document_service.py
from __future__ import annotations

import re
import json
import logging
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
    DocumentService is the core orchestrator for Curatore's document lifecycle.

    Responsibilities:
    - File management: upload, list, find, delete, and clear runtime artifacts.
    - Extraction: convert various input formats to Markdown (via Docling or the
      default extraction microservice), with automatic fallbacks and rich logging.
    - Processing: score conversion quality, optionally run LLM evaluation, and
      persist results for RAG readiness checks and downloads.

    Programming logic overview:
    1) File orchestration
       - Uploaded files are saved under a UUID-prefixed filename to avoid collisions.
       - Batch files live in a separate directory and are discoverable by name.
    2) Extraction dispatch
       - _extract_content() chooses an extractor based on `CONTENT_EXTRACTOR`.
         It calls _extract_via_docling() or _extract_via_extraction_service(),
         and sets `_last_extraction_info` for downstream reporting.
    3) Processing pipeline
       - process_document() invokes extraction, computes conversion metrics,
         optionally evaluates with an LLM, writes Markdown to `processed_dir`,
         and returns a ProcessingResult (also saved by Celery tasks).
    """

    DEFAULT_EXTS: Set[str] = {
        ".pdf", ".doc", ".docx", ".ppt", ".pptx",
        ".xls", ".xlsx", ".csv", ".txt", ".md",
        ".png", ".jpg", ".jpeg", ".gif", ".tif", ".tiff", ".bmp"
    }

    def __init__(self) -> None:
        """Initialize the service with configured paths and extractor settings.

        Sets up storage directories (upload, processed, batch) under an optional
        files_root, loads supported extensions, and reads extractor configuration
        for the Docling and default extraction-service clients. Also prepares a
        logger and a per-request diagnostic map (`_last_extraction_info`).
        """
        self._logger = logging.getLogger("curatore.api")
        files_root = getattr(settings, "files_root", None)
        self.files_root: Optional[Path] = Path(files_root) if files_root else None

        self.upload_dir: Path = Path(getattr(settings, "upload_dir", "files/uploaded_files"))
        self.processed_dir: Path = Path(getattr(settings, "processed_dir", "files/processed_files"))
        batch_dir_val = getattr(settings, "batch_dir", None)
        self.batch_dir: Optional[Path] = Path(batch_dir_val) if batch_dir_val else None

        self._normalize_under_root()
        self._ensure_directories()

        self._supported_extensions: Set[str] = self._load_supported_extensions()

        # Extractor selection and service configuration
        self.extractor_engine: str = getattr(settings, "content_extractor", "default").strip().lower()

        # Existing custom extraction service (legacy/default)
        self.extract_base: str = str(getattr(settings, "extraction_service_url", "")).rstrip("/")
        self.extract_timeout: float = float(getattr(settings, "extraction_service_timeout", 60))
        self.extract_api_key: Optional[str] = getattr(settings, "extraction_service_api_key", None)

        # Docling service (alternative extractor)
        self.docling_base: str = str(getattr(settings, "docling_service_url", "")).rstrip("/")
        # Docling extract endpoint is fixed per API spec: POST /v1/convert/file
        self.docling_extract_path: str = "/v1/convert/file"
        self.docling_timeout: float = float(getattr(settings, "docling_timeout", 60))
        # Last extraction info for observability
        self._last_extraction_info: Dict[str, Any] = {}
        try:
            self._logger.debug(
                "Extractor config: engine=%s, extraction_service_url=%s, docling_service_url=%s",
                self.extractor_engine,
                self.extract_base or "",
                self.docling_base or "",
            )
        except Exception:
            pass

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
        """Normalize directory paths under the configured files root, with local fallback.

        Behavior:
        - If `files_root` is set and exists, map relative paths under it.
        - If `files_root` is set but does not exist (common in local dev without Docker),
          fall back to using a project-local `files/` directory while preserving subpaths
          (e.g., `/app/files/uploaded_files` → `./files/uploaded_files`).
        - If `files_root` is not set, leave any relative paths as-is.
        """
        if not self.files_root:
            return

        root = self.files_root
        root_exists = root.exists()
        if not root_exists:
            # Local dev fallback: use ./files as the effective root
            local_root = Path.cwd() / "files"

            def rebase_abs(p: Path) -> Path:
                try:
                    # Only rebase when path starts with the (missing) files_root
                    p_str = str(p)
                    root_str = str(root)
                    if p_str.startswith(root_str.rstrip("/")):
                        rel = Path(p_str[len(root_str.rstrip("/")) :].lstrip("/"))
                        return local_root / rel
                except Exception:
                    pass
                return p

            # Rebase absolute paths like /app/files/... to ./files/...
            if self.upload_dir.is_absolute():
                self.upload_dir = rebase_abs(self.upload_dir)
            else:
                self.upload_dir = local_root / self.upload_dir

            if self.processed_dir.is_absolute():
                self.processed_dir = rebase_abs(self.processed_dir)
            else:
                self.processed_dir = local_root / self.processed_dir

            if self.batch_dir is not None:
                if self.batch_dir.is_absolute():
                    self.batch_dir = rebase_abs(self.batch_dir)
                else:
                    self.batch_dir = local_root / self.batch_dir
            # Update files_root to the local root to keep subsequent logic consistent
            self.files_root = local_root
            return

        # Normal mapping: honor files_root for relative paths
        def under_root(p: Path) -> Path:
            return p if p.is_absolute() else (root / p)

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

    async def extractor_health(self) -> Dict[str, Any]:
        """Check connectivity to the configured extraction engine (best-effort).

        Returns a lightweight status object containing:
          { engine, connected, endpoint, response|error }
        For Docling, probes /health with fallbacks to /v1/health or /healthz.
        For the default extraction-service, probes /api/v1/system/health.
        """
        engine = getattr(self, "extractor_engine", "default")
        try:
            if engine == "docling":
                base = getattr(self, "docling_base", "")
                if not base:
                    return {"engine": engine, "connected": False, "endpoint": None, "error": "not_configured"}
                # Docling commonly exposes /health; attempt /health then fallback to /v1/health or /healthz
                url = f"{base}/health"
                try:
                    async with httpx.AsyncClient(timeout=5.0, verify=getattr(settings, 'docling_verify_ssl', True)) as client:
                        resp = await client.get(url)
                        if resp.status_code >= 400:
                            # Try alternate health paths
                            alt = f"{base}/v1/health"
                            resp = await client.get(alt)
                            if resp.status_code >= 400:
                                alt = f"{base}/healthz"
                                resp = await client.get(alt)
                                url = alt
                        ok = resp.status_code == 200
                        data: Any
                        try:
                            data = resp.json()
                        except Exception:
                            data = {"status_code": resp.status_code}
                        result = {"engine": engine, "connected": ok, "endpoint": url, "response": data}
                        try:
                            self._logger.debug("Docling health: %s", result)
                        except Exception:
                            pass
                        return result
                except Exception as e:
                    err = {"engine": engine, "connected": False, "endpoint": url, "error": str(e)}
                    try:
                        self._logger.warning("Docling health check failed: %s", e)
                    except Exception:
                        pass
                    return err

            # Default/legacy extraction service check (only for expected engine values)
            if engine in {"default", "extraction", "auto", "legacy"}:
                base = getattr(self, 'extract_base', '')
                if not base:
                    return {"engine": engine, "connected": False, "endpoint": None, "error": "not_configured"}
                url = f"{base}/api/v1/system/health"
                async with httpx.AsyncClient(timeout=5.0, verify=getattr(settings, 'extraction_service_verify_ssl', True)) as client:
                    resp = await client.get(url)
                    ok = resp.status_code == 200
                    data = resp.json() if ok else {"status_code": resp.status_code}
                    result = {"engine": engine, "connected": ok, "endpoint": url, "response": data}
                    try:
                        self._logger.debug("Extraction-service health: %s", result)
                    except Exception:
                        pass
                    return result
        except Exception as e:
            return {"engine": engine, "connected": False, "endpoint": None, "error": str(e)}

    async def available_extraction_services(self) -> Dict[str, Any]:
        """Report availability of supported extraction services.

        Returns a dict with a list of services and the currently active engine:
          {
            "active": "docling"|"default",
            "services": [
               {"id": "default", "name": "Default Extraction Service", "url": str|None, "available": bool},
               {"id": "docling", "name": "Docling", "url": str|None, "available": bool}
            ]
          }
        """
        active = getattr(self, "extractor_engine", "default")

        # Default/legacy extraction-service status
        default_url = None
        default_ok = False
        try:
            base = getattr(self, 'extract_base', '')
            if base:
                default_url = f"{base}/api/v1/system/health"
                async with httpx.AsyncClient(timeout=5.0, verify=getattr(settings, 'extraction_service_verify_ssl', True)) as client:
                    resp = await client.get(default_url)
                    default_ok = resp.status_code == 200
        except Exception:
            default_ok = False

        # Docling status
        docling_url = None
        docling_ok = False
        try:
            base = getattr(self, 'docling_base', '')
            if base:
                # Probe /health then fallbacks
                for path in ("/health", "/v1/health", "/healthz"):
                    try:
                        candidate = f"{base}{path}"
                        async with httpx.AsyncClient(timeout=5.0, verify=getattr(settings, 'docling_verify_ssl', True)) as client:
                            resp = await client.get(candidate)
                            if resp.status_code == 200:
                                docling_url = candidate
                                docling_ok = True
                                break
                    except Exception:
                        continue
                # If none succeeded, still expose base URL
                if not docling_url:
                    docling_url = f"{base}/health"
        except Exception:
            docling_ok = False

        return {
            "active": active,
            "services": [
                {
                    "id": "default",
                    "name": "Default Extraction Service",
                    "url": default_url,
                    "available": bool(default_ok),
                },
                {
                    "id": "docling",
                    "name": "Docling",
                    "url": docling_url,
                    "available": bool(docling_ok),
                },
            ],
        }

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
            try:
                # Guard even is_file() since it can stat() under the hood
                if not entry.is_file():
                    continue

                ext = entry.suffix.lower()
                if self._supported_extensions and ext and ext not in self._supported_extensions:
                    continue

                stat = entry.stat()
                # Attempt to parse name as "<document_id>_<original>" ONLY for non-batch kinds
                parts = entry.name.split("_", 1)
                if kind != "batch" and len(parts) == 2:
                    prefix = parts[0]
                    # Consider it an id only if it looks like a UUID hex (32 chars, lowercase hex)
                    if len(prefix) == 32 and all(c in "0123456789abcdef" for c in prefix):
                        document_id = prefix
                        original_filename = parts[1]
                    else:
                        document_id = ""
                        original_filename = entry.name
                else:
                    document_id = ""
                    original_filename = entry.name

                # For batch files, use the full filename as the document_id (exact match)
                if kind == "batch":
                    document_id = original_filename

                # Convert datetime to Unix timestamp as integer (not ISO string)
                upload_time_timestamp = int(stat.st_mtime)
                
                # Include both filename and original_filename fields as required
                results.append({
                    # Required fields for FileInfo model
                    "document_id": document_id,
                    "filename": original_filename,
                    "original_filename": original_filename,
                    "file_size": int(stat.st_size),
                    "upload_time": upload_time_timestamp,
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

    def clear_runtime_files(self) -> Dict[str, int]:
        """
        Clear only runtime-generated files: uploaded and processed.

        This intentionally leaves any files in the batch directory untouched
        so that locally curated batch files remain available between runs or
        when using the "Start Over" action in the UI.
        """
        deleted = {"uploaded": 0, "processed": 0, "total": 0}
        for dir_path, key in (
            (self.upload_dir, "uploaded"),
            (self.processed_dir, "processed"),
        ):
            if not dir_path:
                continue
            count = self._safe_clear_dir(dir_path)
            deleted[key] += count
        deleted["total"] = deleted["uploaded"] + deleted["processed"]
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
        """Get processed markdown content for a document.

        Files are named as: {document_id}_{original_stem}.md
        """
        pattern = f"{document_id}_*.md"
        for file_path in self.processed_dir.glob(pattern):
            try:
                return file_path.read_text(encoding="utf-8")
            except Exception:
                continue
        return None

    def get_processed_markdown_path(self, document_id: str) -> Optional[Path]:
        """Find the processed markdown file path by document_id."""
        try:
            pattern = f"{document_id}_*.md"
            for file_path in self.processed_dir.glob(pattern):
                if file_path.is_file():
                    return file_path
        except Exception:
            pass
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
            try:
                self._logger.debug("find_uploaded_file: upload_dir missing or not exists: %s", self.upload_dir)
            except Exception:
                pass
            return None
            
        try:
            # Search for uploaded files with pattern: document_id_originalname.ext
            for file_path in self.upload_dir.glob(f"{document_id}_*.*"):
                if file_path.is_file() and self.is_supported_file(file_path.name):
                    try:
                        self._logger.debug("find_uploaded_file: matched %s", file_path)
                    except Exception:
                        pass
                    return file_path
            try:
                self._logger.debug("find_uploaded_file: no match for id=%s in %s", document_id, self.upload_dir)
            except Exception:
                pass
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
            try:
                self._logger.debug("find_batch_file_by_document_id: batch_dir missing or not exists: %s", self.batch_dir)
            except Exception:
                pass
            return None
            
        try:
            # Normalize incoming identifier
            doc_id = (document_id or "").strip().strip("/\\")
            # If a path-like value is passed, use the basename
            if "/" in doc_id or "\\" in doc_id:
                doc_id = doc_id.replace("\\", "/").split("/")[-1]
            # Case 1: document_id has 'batch_' prefix (legacy format)
            if doc_id.startswith("batch_"):
                stem = doc_id.replace("batch_", "")
                # Try to find by stem
                for file_path in self.batch_dir.glob(f"{stem}.*"):
                    if file_path.is_file() and self.is_supported_file(file_path.name):
                        try:
                            self._logger.debug("find_batch_file_by_document_id: matched legacy stem %s -> %s", stem, file_path)
                        except Exception:
                            pass
                        return file_path
                        
            # Case 2: document_id must be the exact filename (preferred for batch items)
            candidate_path = self.batch_dir / doc_id
            if candidate_path.exists() and candidate_path.is_file() and self.is_supported_file(candidate_path.name):
                try:
                    self._logger.debug("find_batch_file_by_document_id: matched filename %s", candidate_path)
                except Exception:
                    pass
                return candidate_path

            # Note: No fuzzy or case-insensitive matching to avoid ambiguity.

            try:
                # Best-effort directory listing snapshot for debugging
                names = []
                for p in self.batch_dir.iterdir():
                    try:
                        if p.is_file():
                            names.append(p.name)
                    except Exception:
                        continue
                self._logger.debug("find_batch_file_by_document_id: no match for id=%s. batch_dir contents: %s", doc_id, ", ".join(sorted(names))[:1000])
            except Exception:
                pass
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
        try:
            self._logger.debug("find_document_file_unified: id=%s upload_dir=%s batch_dir=%s", document_id, self.upload_dir, self.batch_dir)
        except Exception:
            pass

        uploaded_path = self.find_uploaded_file(document_id)
        if uploaded_path:
            try:
                self._logger.debug("find_document_file_unified: found in uploads -> %s", uploaded_path)
            except Exception:
                pass
            return uploaded_path
            
        # Then try batch files by document_id
        batch_path = self.find_batch_file_by_document_id(document_id)
        if batch_path:
            try:
                self._logger.debug("find_document_file_unified: found in batch -> %s", batch_path)
            except Exception:
                pass
            return batch_path
            
        # Finally, fall back to the existing _find_document_file method
        # which has its own logic for handling both locations
        fallback = self._find_document_file(document_id)
        if fallback:
            try:
                self._logger.debug("find_document_file_unified: found via legacy fallback -> %s", fallback)
            except Exception:
                pass
            return fallback
        try:
            self._logger.debug("find_document_file_unified: NOT FOUND for id=%s", document_id)
        except Exception:
            pass
        return None

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
        """Process a document end-to-end and return a ProcessingResult.

        Steps:
          1) Extract to Markdown via configured extractor(s).
          2) Score conversion quality using simple heuristics.
          3) Optionally evaluate with an LLM (if available and enabled).
          4) Persist Markdown to `processed_dir` and build the result object.

        Args:
            document_id: Stable identifier for the document being processed.
            file_path: Absolute path to the source file.
            options: Domain ProcessingOptions controlling thresholds, OCR hints,
                     and whether to apply vector optimization and LLM analysis.

        Returns:
            ProcessingResult containing:
              - conversion_result (scores and notes)
              - llm_evaluation (optional)
              - markdown_path and metadata (includes extractor diagnostics)
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
            
            # Step 4: LLM evaluation (gate on LLM availability and auto_improve intent)
            llm_evaluation = None
            if llm_service.is_available and getattr(options, 'auto_improve', True):
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
            if getattr(options, 'vector_optimize', False):
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
                    "options_used": options.model_dump(),
                    "extractor": getattr(self, "_last_extraction_info", {})
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
                    "processing_time": time.time() - start_time,
                    "extractor": getattr(self, "_last_extraction_info", {})
                }
            )
            raise Exception(f"Document processing failed: {e}") from e

    async def _extract_via_docling(self, file_path: Path) -> Optional[str]:
        """Extract content via Docling.

        High-level: Sends a multipart upload to Docling Serve's
        `POST /v1/convert/file` endpoint and requests Markdown output.
        It first uploads the file under the field name `files` (Docling's
        documented parameter); if the server responds that it expected `file`,
        it retries automatically. Additional options are provided to improve
        quality (image placeholders and OCR annotations).

        Args:
            file_path: Absolute path to the source document on disk.

        Returns:
            Markdown string on success; None if the Docling call fails or
            returns an empty body.

        Side effects:
            - Populates `self._last_extraction_info` with diagnostic info
              including engine, URL, status/errors, options, and outcome.
            - Emits structured logs for success/failure and response details.
        """
        if not getattr(self, 'docling_base', None):
            return None
        base = self.docling_base.rstrip('/')
        url = f"{base}{self.docling_extract_path if getattr(self, 'docling_extract_path', None) else '/v1/convert/file'}"
        try:
            self._logger.info("Using Docling extractor: %s", url)
        except Exception:
            pass
        import mimetypes
        headers = {"Accept": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=self.docling_timeout, verify=getattr(settings, 'docling_verify_ssl', True)) as client:
                # Docling Serve expects conversion options as query parameters (primitives only).
                # Ensure images are represented as placeholders and OCR annotations are included.
                params = {
                    "output_format": "markdown",
                    "image_export_mode": "placeholder",
                    "include_annotations": "true",        # ensures text appears at image positions
                    # Important toggles to prevent base64 embedding:
                    "generate_picture_images": "false",
                    "include_images": "false",
                }
                mime = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"

                async def _post_with(field_name: str) -> httpx.Response:
                    with file_path.open('rb') as f:
                        files = [(field_name, (file_path.name, f, mime))]
                        # Only send file via multipart; options go in query parameters per API spec.
                        return await client.post(url, headers=headers, files=files, data=params)

                resp = await _post_with('files')
                if resp.status_code == 422:
                    # retry with 'file' if server asked for it
                    try:
                        body = resp.json() or {}
                        needs_file = any(
                            any(str(x).lower() == 'file' for x in (d.get('loc') or []))
                            for d in (body.get('detail') or [])
                        )
                    except Exception:
                        needs_file = False
                    if needs_file:
                        resp = await _post_with('file')
                resp.raise_for_status()

                ctype = (resp.headers.get('content-type') or '').lower()
                if 'application/json' in ctype:
                    payload = resp.json()
                    doc = payload.get('document') if isinstance(payload, dict) else None
                    status_text = payload.get('status') if isinstance(payload, dict) else None
                    errors_list = payload.get('errors') if isinstance(payload, dict) else None
                    proc_time = payload.get('processing_time') if isinstance(payload, dict) else None
                    if isinstance(doc, dict):
                        md_val = doc.get('md_content')
                        if isinstance(md_val, str) and md_val.strip():
                            self._last_extraction_info = {
                                "engine": "docling",
                                "url": url,
                                "ok": True,
                                "status": status_text,
                                "errors": errors_list if isinstance(errors_list, list) else [],
                                "processing_time": proc_time,
                                "options": {"output_format": "markdown", "image_export_mode": "placeholder", "include_annotations": True},
                            }
                            return md_val
                        txt_val = doc.get('text_content')
                        if isinstance(txt_val, str) and txt_val.strip():
                            self._last_extraction_info = {
                                "engine": "docling",
                                "url": url,
                                "ok": True,
                                "status": status_text,
                                "errors": errors_list if isinstance(errors_list, list) else [],
                                "processing_time": proc_time,
                                "note": "md_content missing; used text_content",
                                "options": {"output_format": "markdown", "image_export_mode": "placeholder", "include_annotations": True},
                            }
                            return txt_val
                text = resp.text
                if text and text.strip():
                    self._last_extraction_info = {"engine": "docling", "url": url, "ok": True, "status": None, "errors": [], "options": {"output_format": "markdown", "image_export_mode": "placeholder", "include_annotations": True}}
                    return text
        except Exception as e:
            try:
                if 'resp' in locals() and hasattr(resp, 'text'):
                    self._logger.warning("Docling extraction failed for %s: %s | body: %s", file_path.name, e, (resp.text[:500] or '').replace('\n',' '))
                else:
                    self._logger.warning("Docling extraction failed for %s: %s", file_path.name, e)
            except Exception:
                pass
            self._last_extraction_info = {"engine": "docling", "url": url, "ok": False}
            return None

    async def _extract_via_extraction_service(self, file_path: Path, fallback_from_docling: bool = False) -> Optional[str]:
        """Extract content via the default extraction-service.

        High-level: Streams a multipart upload to the internal extraction
        microservice (`/api/v1/extract`) and parses its JSON or text response.

        Args:
            file_path: Absolute path to the source document on disk.
            fallback_from_docling: True when this invocation is a fallback
                after a Docling attempt failed; recorded in diagnostics.

        Returns:
            Markdown string on success; None if the service call fails or
            does not return usable content.

        Side effects:
            - Populates `self._last_extraction_info` with engine, URL, ok flag,
              and whether this was a fallback call.
            - Logs request target and warnings on error.
        """
        if not getattr(self, 'extract_base', None):
            return None
        url = f"{self.extract_base.rstrip('/')}/api/v1/extract"
        try:
            if fallback_from_docling:
                self._logger.info("Falling back to extraction-service: %s", url)
            else:
                self._logger.info("Using extraction-service: %s", url)
        except Exception:
            pass
        headers = {"Accept": "application/json"}
        if getattr(self, 'extract_api_key', None):
            headers["Authorization"] = f"Bearer {self.extract_api_key}"
        try:
            async with httpx.AsyncClient(timeout=self.extract_timeout, verify=getattr(settings, 'extraction_service_verify_ssl', True)) as client:
                files = {"file": (file_path.name, file_path.open('rb'), None)}
                resp = await client.post(url, headers=headers, files=files)
                resp.raise_for_status()
                ctype = (resp.headers.get('content-type') or '').lower()
                if 'application/json' in ctype:
                    data = resp.json()
                    md = data.get('content_markdown') or data.get('markdown') or ''
                    if isinstance(md, str) and md.strip():
                        self._last_extraction_info = {"engine": "extraction", "url": url, "ok": True, "fallback": fallback_from_docling}
                        return md
                text = resp.text
                if text and text.strip():
                    self._last_extraction_info = {"engine": "extraction", "url": url, "ok": True, "fallback": fallback_from_docling}
                    return text
        except Exception as e:
            try:
                self._logger.warning("Extraction-service failed for %s: %s", file_path.name, e)
            except Exception:
                pass
        return None

    async def _extract_content(self, file_path: Path) -> str:
        """Dispatch content extraction for a given file.

        Behavior:
          - For `.txt`, `.md`, or `.csv` files, reads the file as UTF-8.
          - Otherwise, routes to the configured extractor:
              - `CONTENT_EXTRACTOR=docling`: try Docling first; on failure,
                fall back to the default extraction-service when available.
              - `CONTENT_EXTRACTOR=default` (or legacy values): call the
                extraction-service directly.
          - If all extractors are unavailable or fail, returns a small
            placeholder Markdown indicating extraction is not implemented.

        Args:
            file_path: Absolute path to the source document on disk.

        Returns:
            Markdown content extracted or a placeholder string.

        Notes:
            This method updates `self._last_extraction_info` to reflect the
            attempt details (engine selection, outcome, etc.) so the caller can
            surface it in processing metadata and logs.
        """
        suffix = file_path.suffix.lower()
        if suffix in {'.txt', '.md', '.csv'}:
            return file_path.read_text(encoding='utf-8', errors='ignore')

        engine = getattr(self, "extractor_engine", "default")
        self._last_extraction_info = {"requested_engine": engine, "ok": False}

        # Route based on engine, with fallback behavior
        if engine == "docling":
            md = await self._extract_via_docling(file_path)
            if md:
                return md
            # fallback to extraction-service if configured
            md2 = await self._extract_via_extraction_service(file_path, fallback_from_docling=True)
            if md2:
                return md2
        else:
            md = await self._extract_via_extraction_service(file_path)
            if md:
                return md

        # Final fallback placeholder
        try:
            self._logger.info("No extractor configured or all failed; returning placeholder for %s", file_path.name)
        except Exception:
            pass
        self._last_extraction_info = {"engine": "none", "ok": False}
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
        # Use domain QualityThresholds field names
        conv_thresh = 70
        if getattr(options, 'quality_thresholds', None) and getattr(options.quality_thresholds, 'conversion_quality', None) is not None:
            conv_thresh = options.quality_thresholds.conversion_quality
        if conversion.conversion_score < conv_thresh:
            return False
        
        if llm_eval:
            clarity_thresh = 7
            comp_thresh = 7
            if getattr(options, 'quality_thresholds', None):
                if getattr(options.quality_thresholds, 'clarity_score', None) is not None:
                    clarity_thresh = options.quality_thresholds.clarity_score
                if getattr(options.quality_thresholds, 'completeness_score', None) is not None:
                    comp_thresh = options.quality_thresholds.completeness_score
            if (llm_eval.clarity_score or 0) < clarity_thresh:
                return False
            if (llm_eval.completeness_score or 0) < comp_thresh:
                return False
        
        return True


# Create singleton instance
document_service = DocumentService()
