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
from .path_service import path_service
from .deduplication_service import deduplication_service
from .metadata_service import metadata_service
from .config_loader import config_loader
from ..utils.text_utils import clean_llm_response
from .extraction import ExtractionEngineFactory, BaseExtractionEngine


class ExtractionFailureError(Exception):
    """Exception raised when document extraction fails permanently (non-retryable)."""
    pass


class DocumentService:
    """
    DocumentService is the core orchestrator for Curatore's document lifecycle.

    Responsibilities:
    - File management: upload, list, find, delete, and clear runtime artifacts.
    - Extraction: convert various input formats to Markdown (via Docling or the
      default extraction microservice) based on per-job selection.
    - Processing: score conversion quality, optionally run LLM evaluation, and
      persist results for RAG readiness checks and downloads.

    Programming logic overview:
    1) File orchestration
       - Uploaded files are saved under a UUID-prefixed filename to avoid collisions.
       - Batch files live in a separate directory and are discoverable by name.
    2) Extraction dispatch
       - _extract_content() chooses an extractor based on the job's
         ProcessingOptions.extraction_engine, then calls _extract_via_docling()
         or _extract_via_extraction_service(), and sets `_last_extraction_info`.
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
                "Extractor config: extraction_service_url=%s, docling_service_url=%s",
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

    async def extractor_health(self, engine: Optional[str] = None) -> Dict[str, Any]:
        """Check connectivity to a specific extraction engine (best-effort).

        Returns a lightweight status object containing:
          { engine, connected, endpoint, response|error }
        For Docling, probes /health with fallbacks to /v1/health or /healthz.
        For the extraction-service, probes /api/v1/system/health.
        """
        engine = (engine or "").strip().lower()
        if not engine:
            if getattr(self, 'extract_base', ''):
                engine = "extraction-service"
            elif getattr(self, 'docling_base', ''):
                engine = "docling"
            else:
                engine = "none"
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
            if engine in {"default", "extraction", "extraction-service", "legacy"}:
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

        Returns a dict with a list of services and the default engine suggestion:
          {
            "active": "docling"|"extraction-service"|null,
            "services": [
               {"id": "default", "name": "Default Extraction Service", "url": str|None, "available": bool},
               {"id": "docling", "name": "Docling", "url": str|None, "available": bool}
            ]
          }
        """
        if getattr(self, 'extract_base', ''):
            active = "extraction-service"
        elif getattr(self, 'docling_base', ''):
            active = "docling"
        else:
            active = None

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

        When hierarchical storage is enabled, recursively scans subdirectories.
        """
        results: List[Dict[str, Any]] = []
        if not base_dir.exists():
            return results

        # Use recursive glob when hierarchical storage is enabled, otherwise list directory
        if settings.use_hierarchical_storage:
            # Recursively find all files in subdirectories
            entries = sorted(base_dir.rglob("*"), key=lambda p: p.name.lower())
        else:
            # Only list files in the immediate directory (legacy behavior)
            entries = sorted(base_dir.iterdir(), key=lambda p: p.name.lower())

        for entry in entries:
            try:
                # Guard even is_file() since it can stat() under the hood
                if not entry.is_file():
                    continue

                # Skip system files
                if entry.name.startswith('.') or entry.name in ['Thumbs.db', 'desktop.ini']:
                    continue

                # When using hierarchical storage, filter by parent directory to match kind
                if settings.use_hierarchical_storage and kind in ["uploaded", "processed"]:
                    # Only include files from directories matching the kind
                    parent_name = entry.parent.name
                    if parent_name != kind:
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

    async def save_uploaded_file(
        self,
        filename: str,
        content: bytes,
        organization_id: Optional[str] = None,
        batch_id: Optional[str] = None,
    ) -> Tuple[str, str, Optional[str]]:
        """
        Save an uploaded file with hierarchical storage and deduplication support.

        Returns: (document_id, relative_path, file_hash)
        """
        self._ensure_directories()
        if not self.is_supported_file(filename):
            raise ValueError(f"Unsupported file type: {filename}")

        safe = self._safe_filename(Path(filename).name)
        document_id = uuid.uuid4().hex

        # Use hierarchical storage if enabled
        if settings.use_hierarchical_storage:
            # Get hierarchical path
            dest_path = path_service.get_document_path(
                document_id=document_id,
                organization_id=organization_id,
                batch_id=batch_id,
                file_type="uploaded",
                filename=safe,
                create_dirs=True,
            )

            # Write content to temporary location first
            temp_path = Path(settings.temp_dir) / f"upload_{document_id}_{safe}"
            temp_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path.write_bytes(content)

            file_hash = None
            try:
                # Check if deduplication is enabled and file meets size threshold
                if (settings.file_deduplication_enabled and
                    await deduplication_service.should_deduplicate_file(temp_path)):

                    # Calculate file hash
                    file_hash = await deduplication_service.calculate_file_hash(temp_path)

                    # Check for existing duplicate
                    existing = await deduplication_service.find_duplicate_by_hash(file_hash)

                    if existing:
                        # File is a duplicate, create reference
                        self._logger.info(f"Duplicate file detected: {file_hash[:16]}...")
                        await deduplication_service.add_reference(
                            hash_value=file_hash,
                            document_id=document_id,
                            organization_id=organization_id,
                        )
                        # Create symlink or copy to target location
                        await deduplication_service.create_reference_link(
                            content_path=existing,
                            target_path=dest_path,
                        )
                    else:
                        # New file, store in dedupe storage
                        self._logger.info(f"Storing new file in dedupe storage: {file_hash[:16]}...")
                        await deduplication_service.store_deduplicated_file(
                            file_path=temp_path,
                            hash_value=file_hash,
                            document_id=document_id,
                            organization_id=organization_id,
                            original_filename=safe,
                        )
                        # Create reference link
                        dedupe_content = await deduplication_service.find_duplicate_by_hash(file_hash)
                        if dedupe_content:
                            await deduplication_service.create_reference_link(
                                content_path=dedupe_content,
                                target_path=dest_path,
                            )
                else:
                    # No deduplication, just copy file
                    shutil.copy2(temp_path, dest_path)

            finally:
                # Clean up temp file
                if temp_path.exists():
                    temp_path.unlink()

            # Get relative path from organization root
            org_path = path_service.resolve_organization_path(organization_id)
            relative_path = str(dest_path.relative_to(org_path))
            return document_id, relative_path, file_hash

        else:
            # Legacy flat storage
            ext = Path(safe).suffix
            stem = safe[: -len(ext)] if ext else safe
            unique_name = f"{document_id}_{stem}{ext}"
            dest_path = self.upload_dir / unique_name
            dest_path.write_bytes(content)
            return document_id, str(dest_path.relative_to(self.upload_dir)), None

    # ====================== FILE LISTING METHODS ======================

    def list_uploaded_files_with_metadata(self) -> List[Dict[str, Any]]:
        """List uploaded files with complete metadata for FileListResponse."""
        if settings.use_hierarchical_storage:
            # When hierarchical storage is enabled, scan from the root to include all org/shared files
            # Files are stored in: /files/shared/adhoc/uploaded/ and /files/organizations/*/adhoc/uploaded/
            base_path = Path(settings.files_root)
            return self._list_files_for_api(base_path, kind="uploaded")
        else:
            # Legacy flat storage
            return self._list_files_for_api(self.upload_dir, kind="uploaded")

    def list_processed_files_with_metadata(self) -> List[Dict[str, Any]]:
        """List processed files with complete metadata for FileListResponse."""
        if settings.use_hierarchical_storage:
            # When hierarchical storage is enabled, scan from the root to include all org/shared files
            # Files are stored in: /files/shared/adhoc/processed/ and /files/organizations/*/adhoc/processed/
            base_path = Path(settings.files_root)
            return self._list_files_for_api(base_path, kind="processed")
        else:
            # Legacy flat storage
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

            if settings.use_hierarchical_storage:
                # Search recursively from files root when hierarchical storage is enabled
                base_path = Path(settings.files_root)
                for file_path in base_path.rglob(pattern):
                    if file_path.is_file():
                        return file_path
            else:
                # Legacy flat storage - search only in processed_dir
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
            # Fallback: search recursively in batch subfolders
            for p in self.batch_dir.rglob(filename):
                if p.is_file() and self.is_supported_file(p.name):
                    return p
            for p in self.batch_dir.rglob(f"{stem}.*"):
                if p.is_file() and self.is_supported_file(p.name):
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
    
    def find_uploaded_file(
        self,
        document_id: str,
        organization_id: Optional[str] = None,
        batch_id: Optional[str] = None,
    ) -> Optional[Path]:
        """
        Find an uploaded file by document_id with hierarchical storage support.

        Searches in hierarchical structure first, then falls back to legacy flat structure.
        Resolves symlinks if file is deduplicated.

        Args:
            document_id: The unique identifier for the uploaded document
            organization_id: Organization UUID (for hierarchical search)
            batch_id: Batch UUID (for hierarchical search)

        Returns:
            Path object if file found, None otherwise
        """
        # Try hierarchical storage first
        if settings.use_hierarchical_storage:
            try:
                # Search in hierarchical structure
                org_path = path_service.resolve_organization_path(organization_id)

                # Determine search paths
                search_paths = []
                if batch_id:
                    # Specific batch
                    batch_path = org_path / "batches" / batch_id / "uploaded"
                    if batch_path.exists():
                        search_paths.append(batch_path)
                else:
                    # Search both adhoc and all batches
                    adhoc_path = org_path / "adhoc" / "uploaded"
                    if adhoc_path.exists():
                        search_paths.append(adhoc_path)

                    batches_path = org_path / "batches"
                    if batches_path.exists():
                        for batch_dir in batches_path.iterdir():
                            if batch_dir.is_dir():
                                uploaded_path = batch_dir / "uploaded"
                                if uploaded_path.exists():
                                    search_paths.append(uploaded_path)

                # Search for file
                for search_path in search_paths:
                    for file_path in search_path.glob(f"{document_id}_*.*"):
                        if file_path.is_file() and self.is_supported_file(file_path.name):
                            # Resolve symlink if deduplicated
                            if file_path.is_symlink():
                                resolved = file_path.resolve()
                                if resolved.exists():
                                    self._logger.debug(f"Found deduplicated file: {file_path} -> {resolved}")
                                    return file_path  # Return symlink path for consistency
                            self._logger.debug(f"Found file in hierarchical storage: {file_path}")
                            return file_path

            except Exception as e:
                self._logger.warning(f"Error searching hierarchical storage: {e}")

        # Fallback to legacy flat structure
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
        options: ProcessingOptions,
        organization_id: Optional[str] = None,
        session = None
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
            organization_id: Optional organization ID for database connection lookup.
            session: Optional database session for connection lookup.

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
            markdown_content = await self._extract_content(
                file_path,
                engine=getattr(options, "extraction_engine", None),
                organization_id=organization_id,
                session=session,
            )
            
            # Step 2: Score the conversion quality
            original_text = file_path.read_text(encoding='utf-8', errors='ignore') if file_path.suffix.lower() == '.txt' else None
            conversion_score, conversion_notes = self._score_conversion(markdown_content, original_text)

            # Extract metadata from _last_extraction_info
            extraction_info = getattr(self, '_last_extraction_info', {})
            engine_used = extraction_info.get('engine', extraction_info.get('requested_engine', 'unknown'))
            extraction_attempts = extraction_info.get('attempts', 1)

            # Step 3: Create conversion result with extraction metadata
            conversion_result = ConversionResult(
                conversion_score=conversion_score,
                content_coverage=0.85,  # Placeholder - would calculate actual coverage
                structure_preservation=0.80,  # Placeholder - would analyze structure
                readability_score=0.90,  # Placeholder - would analyze readability
                total_characters=len(original_text) if original_text else len(markdown_content),
                extracted_characters=len(markdown_content),
                processing_time=time.time() - start_time,
                conversion_notes=[conversion_notes],
                extraction_engine=engine_used,
                extraction_attempts=extraction_attempts,
                extraction_failover=None
            )
            
            # Step 4: LLM evaluation (gate on LLM availability and auto_improve intent)
            llm_evaluation = None
            if llm_service.is_available and getattr(options, 'auto_improve', True):
                try:
                    llm_evaluation = await self._evaluate_with_llm(
                        markdown_content,
                        options,
                        organization_id=organization_id,
                        session=session
                    )
                except Exception as e:
                    print(f"LLM evaluation failed: {e}")
            
            # Step 5: Save processed markdown file
            markdown_filename = f"{document_id}_{Path(file_path.name).stem}.md"
            markdown_path = self.processed_dir / markdown_filename
            markdown_path.write_text(markdown_content, encoding='utf-8')
            
            # Step 6: Apply vector optimization if requested
            vector_optimized = False
            if getattr(options, 'vector_optimize', False):
                vector_optimized = await self._apply_vector_optimization(
                    markdown_content,
                    markdown_path,
                    organization_id=organization_id,
                    session=session
                )
            
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

    # =========================================================================
    # DEPRECATED EXTRACTION METHODS
    # =========================================================================
    # The following methods (_extract_via_docling, _extract_via_extraction_service)
    # have been moved to the extraction engine abstraction layer:
    # - backend/app/services/extraction/docling.py (DoclingEngine class)
    # - backend/app/services/extraction/extraction_service.py (ExtractionServiceEngine class)
    #
    # These methods are kept for reference but are no longer called.
    # The new abstraction is used via _extract_content() -> _resolve_extraction_connection()
    # =========================================================================

    async def _extract_via_docling(
        self,
        file_path: Path,
        max_retries: int = 2,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        endpoint_path: Optional[str] = None
    ) -> Optional[str]:
        """[DEPRECATED] Extract content via Docling with retry logic.

        This method has been replaced by the DoclingEngine class in
        backend/app/services/extraction/docling.py

        High-level: Sends a multipart upload to Docling Serve's
        `POST /v1/convert/file` endpoint and requests Markdown output.
        It first uploads the file under the field name `files` (Docling's
        documented parameter); if the server responds that it expected `file`,
        it retries automatically. Additional options are provided to improve
        quality (image placeholders and OCR annotations).
        Implements retry logic with progressive timeout extensions.

        Args:
            file_path: Absolute path to the source document on disk.
            max_retries: Maximum number of retry attempts (default: 2)
            base_url: Override base URL for the service (optional)
            timeout: Override timeout in seconds (optional)
            endpoint_path: Override endpoint path (optional, defaults to /v1/convert/file)

        Returns:
            Markdown string on success; None if the Docling call fails or
            returns an empty body after all retries.

        Side effects:
            - Populates `self._last_extraction_info` with diagnostic info
              including engine, URL, status/errors, options, outcome, and retry metadata.
            - Emits structured logs for success/failure and response details.
        """
        # Use provided base_url or fallback to instance config
        if base_url:
            base = base_url.rstrip('/')
        elif getattr(self, 'docling_base', None):
            base = self.docling_base.rstrip('/')
        else:
            return None

        # Use custom endpoint_path if provided, otherwise use defaults
        if endpoint_path:
            path = endpoint_path if endpoint_path.startswith('/') else f'/{endpoint_path}'
        else:
            path = getattr(self, 'docling_extract_path', '/v1/convert/file')

        url = f"{base}{path}"

        # Use provided timeout or fallback to instance config
        base_timeout = float(timeout if timeout is not None else getattr(self, 'docling_timeout', 60))
        timeout_extension = 30.0  # 30 seconds per retry

        for attempt in range(max_retries + 1):
            current_timeout = base_timeout + (attempt * timeout_extension)

            try:
                if attempt == 0:
                    self._logger.info("Using Docling extractor: %s (timeout: %.0fs) for file: %s", url, current_timeout, file_path.name)
                else:
                    self._logger.info("Retrying Docling (attempt %d/%d, timeout: %.0fs): %s",
                                    attempt + 1, max_retries + 1, current_timeout, file_path.name)
            except Exception:
                pass

            import mimetypes
            headers = {"Accept": "application/json"}

            try:
                async with httpx.AsyncClient(timeout=current_timeout, verify=getattr(settings, 'docling_verify_ssl', True)) as client:
                    # Docling Serve expects conversion options as primitive query/form values.
                    # Request Markdown with placeholder images, standard pipeline, OCR enabled (auto engine), and accurate tables.
                    params = {
                        "output_format": "markdown",
                        "image_export_mode": "placeholder",
                        "pipeline_type": "standard",
                        "enable_ocr": "true",
                        "ocr_engine": "auto",
                        "table_mode": "accurate",
                        "include_annotations": "true",        # ensures text appears at image positions
                        # Important toggles to prevent base64 embedding:
                        "generate_picture_images": "false",
                        "include_images": "false",
                    }
                    options_log = {
                        "output_format": "markdown",
                        "image_export_mode": "placeholder",
                        "pipeline_type": "standard",
                        "enable_ocr": True,
                        "ocr_engine": "auto",
                        "table_mode": "accurate",
                        "include_annotations": True,
                        "generate_picture_images": False,
                        "include_images": False,
                    }
                    mime = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"

                    async def _post_with(field_name: str) -> httpx.Response:
                        with file_path.open('rb') as f:
                            files = [(field_name, (file_path.name, f, mime))]
                            # Only send file via multipart; mirror options in query + form for compatibility across Docling builds.
                            return await client.post(url, headers=headers, params=params, files=files, data=params)

                    resp = await _post_with('files')

                    # Handle specific error codes
                    if resp.status_code == 404:
                        # Endpoint not found - log and try with 'file' field
                        try:
                            self._logger.warning(
                                "Docling endpoint returned 404 for field 'files'. URL: %s. Retrying with 'file' field.",
                                url
                            )
                        except Exception:
                            pass
                        resp = await _post_with('file')
                    elif resp.status_code == 422:
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
                                    "attempts": attempt + 1,
                                    "timeout_used": current_timeout,
                                    "options": options_log,
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
                                    "attempts": attempt + 1,
                                    "timeout_used": current_timeout,
                                    "note": "md_content missing; used text_content",
                                    "options": options_log,
                                }
                                return txt_val
                    text = resp.text
                    if text and text.strip():
                        self._last_extraction_info = {
                            "engine": "docling",
                            "url": url,
                            "ok": True,
                            "status": None,
                            "errors": [],
                            "attempts": attempt + 1,
                            "timeout_used": current_timeout,
                            "options": options_log,
                        }
                        return text

            except httpx.TimeoutException as e:
                is_last_attempt = (attempt >= max_retries)
                try:
                    if is_last_attempt:
                        self._logger.warning("Docling timeout for %s after %d attempts (final timeout: %.0fs): %s",
                                           file_path.name, attempt + 1, current_timeout, e)
                    else:
                        self._logger.warning("Docling timeout for %s (attempt %d/%d, timeout: %.0fs), will retry: %s",
                                           file_path.name, attempt + 1, max_retries + 1, current_timeout, e)
                except Exception:
                    pass

                if is_last_attempt:
                    self._last_extraction_info = {
                        "engine": "docling",
                        "url": url,
                        "ok": False,
                        "error": "timeout",
                        "attempts": attempt + 1,
                        "timeout_used": current_timeout
                    }
                    break
                # Continue to next retry

            except httpx.RequestError as e:
                # Network / connection errors (non-timeout) – retry unless out of attempts
                is_last_attempt = (attempt >= max_retries)
                try:
                    if is_last_attempt:
                        self._logger.warning("Docling request error for %s after %d attempts: %s", file_path.name, attempt + 1, e)
                    else:
                        self._logger.warning("Docling request error for %s (attempt %d/%d), will retry: %s",
                                             file_path.name, attempt + 1, max_retries + 1, e)
                except Exception:
                    pass

                if is_last_attempt:
                    self._last_extraction_info = {
                        "engine": "docling",
                        "url": url,
                        "ok": False,
                        "error": str(e),
                        "attempts": attempt + 1
                    }
                    break
                # Continue to next retry

            except Exception as e:
                try:
                    if 'resp' in locals() and hasattr(resp, 'text'):
                        self._logger.warning("Docling extraction failed for %s (attempt %d/%d): %s | body: %s",
                                           file_path.name, attempt + 1, max_retries + 1, e, (resp.text[:500] or '').replace('\n',' '))
                    else:
                        self._logger.warning("Docling extraction failed for %s (attempt %d/%d): %s",
                                           file_path.name, attempt + 1, max_retries + 1, e)
                except Exception:
                    pass

                # For non-timeout errors, don't retry
                self._last_extraction_info = {
                    "engine": "docling",
                    "url": url,
                    "ok": False,
                    "error": str(e),
                    "attempts": attempt + 1
                }
                break

        return None

    async def _extract_via_extraction_service(
        self,
        file_path: Path,
        max_retries: int = 2,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        endpoint_path: Optional[str] = None
    ) -> Optional[str]:
        """[DEPRECATED] Extract content via the default extraction-service with retry logic.

        This method has been replaced by the ExtractionServiceEngine class in
        backend/app/services/extraction/extraction_service.py

        High-level: Streams a multipart upload to the internal extraction
        microservice (`/api/v1/extract`) and parses its JSON or text response.
        Implements retry logic with progressive timeout extensions.

        Args:
            file_path: Absolute path to the source document on disk.
            max_retries: Maximum number of retry attempts (default: 2)
            base_url: Override base URL for the service (optional)
            timeout: Override timeout in seconds (optional)
            endpoint_path: Override endpoint path (optional, defaults to /api/v1/extract)

        Returns:
            Markdown string on success; None if the service call fails or
            does not return usable content after all retries.

        Side effects:
            - Populates `self._last_extraction_info` with engine, URL, ok flag,
              and retry metadata.
            - Logs request target and warnings on error.
        """
        # Use provided base_url or fallback to instance config
        if base_url:
            base = base_url.rstrip('/')
        elif getattr(self, 'extract_base', None):
            base = self.extract_base.rstrip('/')
        else:
            return None

        # Use custom endpoint_path if provided, otherwise use defaults
        if endpoint_path:
            path = endpoint_path if endpoint_path.startswith('/') else f'/{endpoint_path}'
        else:
            path = '/api/v1/extract'

        url = f"{base}{path}"

        # Use provided timeout or fallback to instance config
        base_timeout = float(timeout if timeout is not None else getattr(self, 'extract_timeout', 60))
        timeout_extension = 30.0  # 30 seconds per retry

        for attempt in range(max_retries + 1):
            current_timeout = base_timeout + (attempt * timeout_extension)

            try:
                if attempt == 0:
                    self._logger.info("Using extraction-service: %s (timeout: %.0fs)", url, current_timeout)
                else:
                    self._logger.info("Retrying extraction-service (attempt %d/%d, timeout: %.0fs): %s",
                                    attempt + 1, max_retries + 1, current_timeout, file_path.name)
            except Exception:
                pass

            headers = {"Accept": "application/json"}
            if getattr(self, 'extract_api_key', None):
                headers["Authorization"] = f"Bearer {self.extract_api_key}"

            try:
                async with httpx.AsyncClient(timeout=current_timeout, verify=getattr(settings, 'extraction_service_verify_ssl', True)) as client:
                    files = {"file": (file_path.name, file_path.open('rb'), None)}
                    resp = await client.post(url, headers=headers, files=files)
                    resp.raise_for_status()
                    ctype = (resp.headers.get('content-type') or '').lower()
                    if 'application/json' in ctype:
                        data = resp.json()
                        md = data.get('content_markdown') or data.get('markdown') or ''
                        if isinstance(md, str) and md.strip():
                            self._last_extraction_info = {
                                "engine": "extraction-service",
                                "url": url,
                                "ok": True,
                                "attempts": attempt + 1,
                                "timeout_used": current_timeout
                            }
                            return md
                    text = resp.text
                    if text and text.strip():
                        self._last_extraction_info = {
                            "engine": "extraction-service",
                            "url": url,
                            "ok": True,
                            "attempts": attempt + 1,
                            "timeout_used": current_timeout
                        }
                        return text
            except httpx.TimeoutException as e:
                is_last_attempt = (attempt >= max_retries)
                try:
                    if is_last_attempt:
                        self._logger.warning("Extraction-service timeout for %s after %d attempts (final timeout: %.0fs): %s",
                                           file_path.name, attempt + 1, current_timeout, e)
                    else:
                        self._logger.warning("Extraction-service timeout for %s (attempt %d/%d, timeout: %.0fs), will retry: %s",
                                           file_path.name, attempt + 1, max_retries + 1, current_timeout, e)
                except Exception:
                    pass

                if is_last_attempt:
                    self._last_extraction_info = {
                        "engine": "extraction-service",
                        "url": url,
                        "ok": False,
                        "error": "timeout",
                        "attempts": attempt + 1,
                        "timeout_used": current_timeout
                    }
                    break
                # Continue to next retry

            except Exception as e:
                try:
                    self._logger.warning("Extraction-service failed for %s (attempt %d/%d): %s",
                                       file_path.name, attempt + 1, max_retries + 1, e)
                except Exception:
                    pass

                # For non-timeout errors, don't retry
                self._last_extraction_info = {
                    "engine": "extraction-service",
                    "url": url,
                    "ok": False,
                    "error": str(e),
                    "attempts": attempt + 1
                }
                break

        return None

    async def _resolve_extraction_connection(
        self,
        engine: Optional[str],
        organization_id: Optional[str] = None,
        session = None
    ) -> Optional[BaseExtractionEngine]:
        """Resolve extraction engine connection to an engine instance.

        Args:
            engine: Engine identifier (connection ID, name, or legacy string)
            organization_id: Organization ID for connection lookup
            session: Database session for connection lookup

        Returns:
            Instantiated extraction engine or None if not configured
        """
        # Default to extraction-service if no engine specified
        if not engine:
            return ExtractionEngineFactory.create_engine(
                engine_type="extraction-service",
                name="default",
                service_url=self.extract_base,
                timeout=int(self.extract_timeout)
            )

        engine_str = str(engine).strip()

        # Check if it's a UUID (connection ID)
        try:
            from uuid import UUID
            UUID(engine_str)
            is_uuid = True
        except (ValueError, AttributeError):
            is_uuid = False

        if is_uuid and organization_id and session:
            # Resolve connection from database
            try:
                from sqlalchemy import select
                from ..database.models import Connection

                result = await session.execute(
                    select(Connection)
                    .where(Connection.id == engine_str)
                    .where(Connection.organization_id == organization_id)
                    .where(Connection.is_active == True)
                )
                connection = result.scalar_one_or_none()

                if connection and connection.connection_type == "extraction":
                    config = connection.config
                    service_url = config.get("service_url", "").rstrip("/")

                    # Get engine_type from config, or infer from service URL
                    engine_type = config.get("engine_type")
                    if not engine_type:
                        # Infer engine type from service URL for backward compatibility
                        service_url_lower = service_url.lower()
                        if "docling" in service_url_lower or ":5001" in service_url:
                            engine_type = "docling"
                            self._logger.info(
                                "Inferred engine_type 'docling' from service URL: %s",
                                service_url
                            )
                        else:
                            engine_type = "extraction-service"
                            self._logger.info(
                                "Defaulting to engine_type 'extraction-service' for: %s",
                                service_url
                            )

                    options = config.get("options")
                    if engine_type == "docling":
                        docling_ocr_enabled = config.get("docling_ocr_enabled")
                        if docling_ocr_enabled is not None:
                            options = {**(options or {}), "enable_ocr": bool(docling_ocr_enabled)}

                    # Create engine from database connection config
                    return ExtractionEngineFactory.from_config({
                        "engine_type": engine_type,
                        "name": connection.name,
                        "service_url": service_url,
                        "timeout": int(config.get("timeout", 60)),
                        "verify_ssl": config.get("verify_ssl", True),
                        "api_key": config.get("api_key"),
                        "options": options
                    })
                else:
                    self._logger.warning(f"Connection {engine_str} not found or not an extraction type")
            except Exception as e:
                self._logger.error(f"Failed to resolve connection {engine_str}: {e}")
        else:
            # Not a UUID - check if it's a config.yml engine name
            try:
                config_engine = config_loader.get_extraction_engine_by_name(engine_str)
                if config_engine:
                    self._logger.info(f"Resolved engine '{engine_str}' from config.yml")

                    options = config_engine.options
                    if config_engine.engine_type == "docling":
                        docling_ocr_enabled = getattr(config_engine, "docling_ocr_enabled", None)
                        if docling_ocr_enabled is not None:
                            options = {**(options or {}), "enable_ocr": bool(docling_ocr_enabled)}

                    # Create engine from config.yml
                    return ExtractionEngineFactory.from_config({
                        "engine_type": config_engine.engine_type,
                        "name": config_engine.name,
                        "service_url": config_engine.service_url,
                        "timeout": config_engine.timeout,
                        "verify_ssl": config_engine.verify_ssl,
                        "api_key": config_engine.api_key,
                        "options": options
                    })
            except Exception as e:
                self._logger.debug(f"Engine '{engine_str}' not found in config.yml: {e}")

        # Legacy string-based engines (fallback to environment variables)
        engine_lower = engine_str.lower()
        if engine_lower == "docling":
            if not self.docling_base:
                self._logger.warning("Docling engine requested but not configured")
                return None
            return ExtractionEngineFactory.create_engine(
                engine_type="docling",
                name="legacy-docling",
                service_url=self.docling_base,
                timeout=int(self.docling_timeout)
            )
        elif engine_lower in {"default", "extraction", "extraction-service"}:
            return ExtractionEngineFactory.create_engine(
                engine_type="extraction-service",
                name="legacy-extraction-service",
                service_url=self.extract_base,
                timeout=int(self.extract_timeout)
            )
        elif engine_lower == "none":
            return None

        # Unknown engine, default to extraction-service
        self._logger.warning(f"Unknown engine '{engine_str}', defaulting to extraction-service")
        return ExtractionEngineFactory.create_engine(
            engine_type="extraction-service",
            name="default",
            service_url=self.extract_base,
            timeout=int(self.extract_timeout)
        )

    async def _extract_content(
        self,
        file_path: Path,
        engine: Optional[str] = None,
        organization_id: Optional[str] = None,
        session = None
    ) -> str:
        """Dispatch content extraction for a given file using the selected engine.

        Behavior:
          - For `.txt`, `.md`, or `.csv` files, reads the file as UTF-8.
          - Otherwise, uses the extraction engine abstraction layer with retry support.
          - If the selected extractor is unavailable or fails after retries, raises an exception.

        Args:
            file_path: Absolute path to the source document on disk.
            engine: Selected extraction engine (connection ID, name, or legacy string).
            organization_id: Organization ID for connection lookup.
            session: Database session for connection lookup.

        Returns:
            Markdown content extracted.

        Raises:
            ExtractionFailureError: If extraction fails permanently.

        Notes:
            This method updates `self._last_extraction_info` to reflect the
            attempt details (engine selection, outcome, retries) so the caller can
            surface it in processing metadata and logs.
        """
        suffix = file_path.suffix.lower()
        if suffix in {'.txt', '.md', '.csv'}:
            self._last_extraction_info = {"engine": "text-file", "ok": True}
            return file_path.read_text(encoding='utf-8', errors='ignore')

        # Resolve connection to get engine instance
        extraction_engine = await self._resolve_extraction_connection(
            engine, organization_id, session
        )

        if not extraction_engine:
            self._last_extraction_info = {
                "requested_engine": engine,
                "engine": "none",
                "ok": False,
                "error": "not_configured"
            }
            raise ExtractionFailureError("No extraction engine configured")

        # Log resolved engine
        self._last_extraction_info = {
            "requested_engine": engine,
            "resolved_engine": extraction_engine.engine_type,
            "engine_name": extraction_engine.name,
            "ok": False
        }

        try:
            # Use the engine's extract method
            result = await extraction_engine.extract(file_path)

            if result.success and result.content:
                # Update extraction info with success
                self._last_extraction_info = {
                    "engine": extraction_engine.engine_type,
                    "engine_name": extraction_engine.name,
                    "url": extraction_engine.full_url,
                    "ok": True,
                    "metadata": result.metadata
                }
                return result.content
            else:
                # Extraction failed
                self._last_extraction_info = {
                    "engine": extraction_engine.engine_type,
                    "engine_name": extraction_engine.name,
                    "url": extraction_engine.full_url,
                    "ok": False,
                    "error": result.error or "unknown error",
                    "metadata": result.metadata
                }
                raise ExtractionFailureError(f"Extraction failed: {result.error}")

        except ExtractionFailureError:
            # Re-raise extraction failures
            raise
        except Exception as e:
            # Catch any other exceptions and convert to extraction failure
            self._last_extraction_info = {
                "engine": extraction_engine.engine_type,
                "engine_name": extraction_engine.name,
                "url": extraction_engine.full_url,
                "ok": False,
                "error": str(e)
            }
            self._logger.error(
                "Unexpected error during extraction for %s: %s",
                file_path.name, str(e)
            )
            raise ExtractionFailureError(f"Extraction error: {str(e)}")

    async def _evaluate_with_llm(
        self,
        content: str,
        options: ProcessingOptions,
        organization_id: Optional[str] = None,
        session = None
    ) -> Optional[LLMEvaluation]:
        """Evaluate document quality using LLM.

        Args:
            content: Markdown content to evaluate
            options: Processing options (unused currently)
            organization_id: Optional organization ID for database connection lookup
            session: Optional database session for connection lookup

        Returns:
            LLMEvaluation if successful, None if evaluation fails
        """
        try:
            return await llm_service.evaluate_document(
                content,
                organization_id=organization_id,
                session=session
            )
        except Exception as e:
            self._logger.error(f"LLM evaluation failed: {e}")
            return None

    async def _apply_vector_optimization(
        self,
        content: str,
        output_path: Path,
        organization_id: Optional[str] = None,
        session = None
    ) -> bool:
        """Apply vector database optimization to the content.

        Args:
            content: Markdown content to optimize
            output_path: Path where optimized content will be written
            organization_id: Optional organization ID for database connection lookup
            session: Optional database session for connection lookup

        Returns:
            True if optimization succeeded, False otherwise
        """
        try:
            optimized_content = await llm_service.optimize_for_vector_db(
                content,
                organization_id=organization_id,
                session=session
            )
            if optimized_content and optimized_content != content:
                output_path.write_text(optimized_content, encoding='utf-8')
                return True
            return False
        except Exception as e:
            self._logger.error(f"Vector optimization failed: {e}")
            return False

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

    # ====================== HIERARCHICAL STORAGE HELPER METHODS ======================

    def create_temp_job_directory(self, job_id: str) -> Path:
        """
        Create a temporary processing directory for a job.

        Args:
            job_id: Job UUID

        Returns:
            Path to job's temp directory
        """
        return path_service.get_temp_job_path(job_id, create_dirs=True)

    def cleanup_temp_job_directory(self, job_id: str) -> bool:
        """
        Clean up temporary processing directory for a job.

        Args:
            job_id: Job UUID

        Returns:
            True if cleaned up successfully, False otherwise
        """
        try:
            temp_path = path_service.get_temp_job_path(job_id, create_dirs=False)
            if temp_path.exists():
                shutil.rmtree(temp_path)
                self._logger.info(f"Cleaned up temp directory: {temp_path}")
                return True
            return False
        except Exception as e:
            self._logger.error(f"Failed to cleanup temp directory for job {job_id}: {e}")
            return False

    async def get_file_hash(self, document_id: str, organization_id: Optional[str] = None, batch_id: Optional[str] = None) -> Optional[str]:
        """
        Retrieve the content hash for a document.

        Args:
            document_id: Document UUID
            organization_id: Organization UUID
            batch_id: Batch UUID

        Returns:
            File hash string or None if not found
        """
        file_path = self.find_uploaded_file(document_id, organization_id, batch_id)
        if not file_path or not file_path.exists():
            return None

        try:
            # If file is a symlink, it's deduplicated - resolve to get hash from path
            if file_path.is_symlink():
                resolved = file_path.resolve()
                # Hash is the parent directory name in dedupe structure
                if "dedupe" in str(resolved):
                    return resolved.parent.name

            # Otherwise calculate hash
            return await deduplication_service.calculate_file_hash(file_path)
        except Exception as e:
            self._logger.error(f"Failed to get file hash for {document_id}: {e}")
            return None

    async def find_duplicates(self, organization_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Find all duplicate files in an organization.

        Args:
            organization_id: Organization UUID (None for all orgs)

        Returns:
            List of duplicate file groups with metadata
        """
        duplicates = []
        dedupe_base = settings.dedupe_path

        if not dedupe_base.exists():
            return duplicates

        # Scan dedupe directory for files with multiple references
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
                    import json
                    refs_data = json.loads(refs_path.read_text())

                    # Filter by organization if specified
                    references = refs_data.get("references", [])
                    if organization_id:
                        references = [
                            ref for ref in references
                            if ref.get("organization_id") == organization_id
                        ]

                    # Only include if there are multiple references (duplicates)
                    if len(references) > 1:
                        duplicates.append({
                            "hash": refs_data.get("hash"),
                            "original_filename": refs_data.get("original_filename"),
                            "file_size": refs_data.get("file_size"),
                            "reference_count": len(references),
                            "references": references,
                            "storage_saved": refs_data.get("file_size", 0) * (len(references) - 1),
                        })

                except Exception as e:
                    self._logger.error(f"Error reading refs file {refs_path}: {e}")
                    continue

        return duplicates


# Create singleton instance
document_service = DocumentService()
