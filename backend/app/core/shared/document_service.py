# backend/app/services/document_service.py
from __future__ import annotations

import logging
import os
import re
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from app.config import settings
from app.core.llm.llm_service import llm_service
from app.core.models import (
    ConversionResult,
    LLMEvaluation,
    ProcessingOptions,
    ProcessingResult,
)


class ExtractionFailureError(Exception):
    """Exception raised when document extraction fails permanently (non-retryable)."""
    pass


class DocumentService:
    """
    DocumentService is the core orchestrator for Curatore's document lifecycle.

    Responsibilities:
    - File management: upload, list, find, delete, and clear runtime artifacts.
    - Extraction: delegates to the standalone Document Service via adapter.
    - Processing: score conversion quality, optionally run LLM evaluation, and
      persist results for RAG readiness checks and downloads.
    """

    DEFAULT_EXTS: Set[str] = {
        ".pdf", ".doc", ".docx", ".ppt", ".pptx",
        ".xls", ".xlsx", ".xlsb", ".csv", ".txt", ".md",
        ".png", ".jpg", ".jpeg", ".gif", ".tif", ".tiff", ".bmp",
        ".msg", ".eml"  # Email formats
    }

    def __init__(self) -> None:
        self._logger = logging.getLogger("curatore.api")

        self._supported_extensions: Set[str] = self._load_supported_extensions()

        processed_dir_env = os.getenv("PROCESSED_DIR", "").strip()
        base_processed_dir = Path(processed_dir_env) if processed_dir_env else Path(tempfile.gettempdir()) / "curatore_processed"
        self.processed_dir = base_processed_dir
        try:
            self.processed_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self._logger.warning("Failed to create processed_dir %s: %s", self.processed_dir, e)

        # Last extraction info for observability
        self._last_extraction_info: Dict[str, Any] = {}

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
        """Check connectivity to the document service."""
        from app.connectors.adapters.document_service_adapter import document_service_adapter

        health_data = await document_service_adapter.health()
        is_healthy = health_data.get("status") == "ok"

        return {
            "engine": "document-service",
            "connected": is_healthy,
            "endpoint": f"{document_service_adapter.base_url}/api/v1/system/health" if document_service_adapter.base_url else None,
            "response": health_data if is_healthy else None,
            "error": None if is_healthy else health_data.get("error", "unhealthy"),
        }

    async def available_extraction_services(self) -> Dict[str, Any]:
        """Report availability of the document service."""
        from app.connectors.adapters.document_service_adapter import document_service_adapter

        caps = await document_service_adapter.capabilities()
        health_data = await document_service_adapter.health()
        is_healthy = health_data.get("status") == "ok"
        docling_available = caps.get("docling_available", False)

        services = [
            {
                "id": "document-service",
                "name": "Document Service",
                "url": document_service_adapter.base_url,
                "available": is_healthy,
            },
        ]

        if docling_available:
            services.append({
                "id": "docling",
                "name": "Docling (via Document Service)",
                "url": None,
                "available": True,
            })

        return {
            "active": "document-service" if is_healthy else None,
            "services": services,
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

        score = 50  # Base score
        notes = []

        if len(markdown_text) > 100:
            score += 20
            notes.append("Good content length")

        if any(marker in markdown_text for marker in ["#", "##", "###"]):
            score += 15
            notes.append("Contains headers")

        if any(marker in markdown_text for marker in ["- ", "* ", "1. "]):
            score += 10
            notes.append("Contains lists")

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
          1) Extract to Markdown via Document Service.
          2) Score conversion quality using simple heuristics.
          3) Optionally evaluate with an LLM (if available and enabled).
          4) Persist Markdown to `processed_dir` and build the result object.
        """
        if not file_path.exists():
            raise FileNotFoundError(f"Document file not found: {file_path}")

        start_time = time.time()

        try:
            # Step 1: Extract text/markdown from the document
            markdown_content = await self._extract_content(
                file_path,
                engine=getattr(options, "extraction_engine", None),
            )

            # Step 2: Score the conversion quality
            original_text = file_path.read_text(encoding='utf-8', errors='ignore') if file_path.suffix.lower() == '.txt' else None
            conversion_score, conversion_notes = self._score_conversion(markdown_content, original_text)

            extraction_info = getattr(self, '_last_extraction_info', {})
            engine_used = extraction_info.get('engine', extraction_info.get('requested_engine', 'unknown'))
            extraction_attempts = extraction_info.get('attempts', 1)

            conversion_result = ConversionResult(
                conversion_score=conversion_score,
                content_coverage=0.85,
                structure_preservation=0.80,
                readability_score=0.90,
                total_characters=len(original_text) if original_text else len(markdown_content),
                extracted_characters=len(markdown_content),
                processing_time=time.time() - start_time,
                conversion_notes=[conversion_notes],
                extraction_engine=engine_used,
                extraction_attempts=extraction_attempts,
                extraction_failover=None
            )

            # Step 3: LLM evaluation - DISABLED (not operationally used)
            llm_evaluation = None

            # Step 4: Save processed markdown file
            markdown_filename = f"{document_id}_{Path(file_path.name).stem}.md"
            markdown_path = self.processed_dir / markdown_filename
            markdown_path.parent.mkdir(parents=True, exist_ok=True)
            markdown_path.write_text(markdown_content, encoding='utf-8')

            # Step 5: Create final result
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

    async def _extract_content(
        self,
        file_path: Path,
        engine: Optional[str] = None,
    ) -> str:
        """Dispatch content extraction for a given file via the Document Service.

        For .txt, .md, or .csv files, reads directly. Otherwise delegates to
        the document service adapter.

        Args:
            file_path: Absolute path to the source document on disk.
            engine: Engine hint to pass to document service (auto, fast_pdf, markitdown, docling).

        Returns:
            Markdown content extracted.

        Raises:
            ExtractionFailureError: If extraction fails permanently.
        """
        suffix = file_path.suffix.lower()
        if suffix in {'.txt', '.md', '.csv'}:
            self._last_extraction_info = {"engine": "text-file", "ok": True}
            return file_path.read_text(encoding='utf-8', errors='ignore')

        from app.connectors.adapters.document_service_adapter import document_service_adapter

        if not document_service_adapter.is_available:
            self._last_extraction_info = {
                "requested_engine": engine,
                "engine": "none",
                "ok": False,
                "error": "not_configured"
            }
            raise ExtractionFailureError("No document service configured")

        # Map legacy engine names to document service engine hints
        engine_hint = None
        if engine:
            engine_lower = str(engine).lower()
            if engine_lower in ("docling", "docling-internal", "docling-external"):
                engine_hint = "docling"
            elif engine_lower in ("extraction-service", "markitdown", "default", "extraction"):
                engine_hint = "markitdown"
            elif engine_lower in ("fast_pdf",):
                engine_hint = "fast_pdf"
            elif engine_lower == "auto":
                engine_hint = "auto"
            else:
                # Could be a config.yml engine name - try to resolve the engine_type
                try:
                    from app.core.shared.config_loader import config_loader
                    config_engine = config_loader.get_extraction_engine_by_name(engine)
                    if config_engine:
                        et = config_engine.engine_type
                        if et == "docling":
                            engine_hint = "docling"
                        elif et == "extraction-service":
                            engine_hint = "markitdown"
                        else:
                            engine_hint = "auto"
                except Exception:
                    engine_hint = "auto"

        self._last_extraction_info = {
            "requested_engine": engine,
            "engine_hint": engine_hint,
            "ok": False,
        }

        try:
            result = await document_service_adapter.extract(
                file_path=file_path,
                engine=engine_hint,
            )

            self._last_extraction_info = {
                "engine": result.triage_engine or result.method,
                "engine_name": result.method,
                "url": document_service_adapter.base_url,
                "ok": True,
                "method": result.method,
                "ocr_used": result.ocr_used,
                "page_count": result.page_count,
            }
            return result.content_markdown

        except Exception as e:
            self._last_extraction_info = {
                "engine": "document-service",
                "engine_name": "Document Service",
                "url": document_service_adapter.base_url,
                "ok": False,
                "error": str(e),
            }
            self._logger.error(
                "Extraction failed for %s via document service: %s",
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
        """Evaluate document quality using LLM."""
        try:
            return await llm_service.evaluate_document(
                content,
                organization_id=organization_id,
                session=session
            )
        except Exception as e:
            self._logger.error(f"LLM evaluation failed: {e}")
            return None



# Create singleton instance
document_service = DocumentService()
