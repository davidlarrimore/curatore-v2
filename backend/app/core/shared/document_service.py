# backend/app/services/document_service.py
from __future__ import annotations

import os
import re
import tempfile
import json
import logging
import uuid
import shutil
from pathlib import Path
from typing import Iterable, List, Optional, Set, Dict, Any, Tuple
from datetime import datetime
import time

import httpx

from app.config import settings
from app.core.models import (
    ProcessingResult,
    ConversionResult,
    ProcessingStatus,
    LLMEvaluation,
    OCRSettings,
    ProcessingOptions,
)
from app.core.llm.llm_service import llm_service
from .config_loader import config_loader
from app.core.utils.text_utils import clean_llm_response
from app.core.ingestion.extraction import ExtractionEngineFactory, BaseExtractionEngine


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
       - _extract_content() chooses an extractor via the extraction engine
         abstraction layer, then sets `_last_extraction_info`.
    3) Processing pipeline
       - process_document() invokes extraction, computes conversion metrics,
         optionally evaluates with an LLM, writes Markdown to `processed_dir`,
         and returns a ProcessingResult (also saved by Celery tasks).
    """

    DEFAULT_EXTS: Set[str] = {
        ".pdf", ".doc", ".docx", ".ppt", ".pptx",
        ".xls", ".xlsx", ".xlsb", ".csv", ".txt", ".md",
        ".png", ".jpg", ".jpeg", ".gif", ".tif", ".tiff", ".bmp",
        ".msg", ".eml"  # Email formats
    }

    def __init__(self) -> None:
        """Initialize the service with extractor settings.

        Loads supported extensions and reads extractor configuration
        for the Docling and default extraction-service clients. Also prepares a
        logger and a per-request diagnostic map (`_last_extraction_info`).

        Note: All file storage operations now use object storage (MinIO/S3).
        """
        self._logger = logging.getLogger("curatore.api")

        self._supported_extensions: Set[str] = self._load_supported_extensions()

        processed_dir_env = os.getenv("PROCESSED_DIR", "").strip()
        base_processed_dir = Path(processed_dir_env) if processed_dir_env else Path(tempfile.gettempdir()) / "curatore_processed"
        self.processed_dir = base_processed_dir
        try:
            self.processed_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self._logger.warning("Failed to create processed_dir %s: %s", self.processed_dir, e)

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



    def get_supported_extensions(self) -> List[str]:
        """Get list of supported file extensions."""
        return sorted(self._supported_extensions)

    def is_supported_file(self, filename: str) -> bool:
        """Check if a filename has a supported extension."""
        if not filename:
            return False
        ext = Path(filename).suffix.lower()
        return not self._supported_extensions or ext in self._supported_extensions




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

            # Step 4: LLM evaluation - DISABLED (not operationally used)
            # This feature is half-baked and disabled globally to avoid unnecessary LLM calls
            llm_evaluation = None
            # if llm_service.is_available and getattr(options, 'auto_improve', True):
            #     try:
            #         llm_evaluation = await self._evaluate_with_llm(
            #             markdown_content,
            #             options,
            #             organization_id=organization_id,
            #             session=session
            #         )
            #     except Exception as e:
            #         print(f"LLM evaluation failed: {e}")

            # Step 5: Save processed markdown file
            markdown_filename = f"{document_id}_{Path(file_path.name).stem}.md"
            markdown_path = self.processed_dir / markdown_filename
            markdown_path.parent.mkdir(parents=True, exist_ok=True)
            markdown_path.write_text(markdown_content, encoding='utf-8')

            # Step 6: Create final result
            processing_result = ProcessingResult(
                document_id=document_id,
                filename=file_path.name,
                original_path=file_path,
                markdown_path=markdown_path,
                conversion_result=conversion_result,
                llm_evaluation=llm_evaluation,
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
                processed_at=datetime.now(),
                processing_metadata={
                    "service_version": "2.0",
                    "error": str(e),
                    "processing_time": time.time() - start_time,
                    "extractor": getattr(self, "_last_extraction_info", {})
                }
            )
            raise Exception(f"Document processing failed: {e}") from e

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
        # Use default engine from config if no engine specified
        if not engine:
            from .config_loader import config_loader
            default_engine = config_loader.get_default_extraction_engine()
            if default_engine:
                self._logger.info(
                    "Using default extraction engine from config: %s (%s)",
                    default_engine.name, default_engine.engine_type
                )
                return ExtractionEngineFactory.from_config({
                    "engine_type": default_engine.engine_type,
                    "name": default_engine.name,
                    "service_url": default_engine.service_url,
                    "timeout": default_engine.timeout,
                    "verify_ssl": default_engine.verify_ssl,
                    "api_key": default_engine.api_key,
                    "options": default_engine.options
                })
            # Fallback to extraction-service if no config
            self._logger.warning("No default extraction engine in config, falling back to extraction-service")
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
                from app.core.database.models import Connection

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

    # _apply_vector_optimization and _is_rag_ready methods removed - features deprecated



# Create singleton instance
document_service = DocumentService()
