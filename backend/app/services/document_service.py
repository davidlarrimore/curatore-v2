# ============================================================================
# backend/app/services/document_service.py
# ============================================================================
# Curatore v2 Document Service (extraction moved to external service)
#
# This version:
#   - Uses external Extraction Service for all conversion/OCR.
#   - conversion_feedback is a STRING (per model schema).
#   - Always includes word_count, char_count, processing_time in ConversionResult.
#   - Provides clear_all_files() for /system/reset and a private
#     _ensure_directories() helper (some routers call it directly).
#   - IMPORTANT: clear_all_files() preserves batch_dir (does NOT delete batch files).
# ============================================================================

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import List, Optional, Tuple

from ..config import settings
from ..models import (
    ConversionResult,
    LLMEvaluation,
    ProcessingOptions,
    ProcessingResult,
    ProcessingStatus,
    QualityThresholds,
)
from .llm_service import llm_service
from .storage_service import storage_service
from .zip_service import zip_service  # unchanged; used by routers
from .extraction_client import extraction_client, ExtractionError


SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
    ".txt",
    ".md",
    ".rtf",
    ".html",
    ".htm",
    ".csv",
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".bmp",
}


class DocumentService:
    """Main service coordinating file I/O, extraction, scoring, and LLM steps."""

    def __init__(self) -> None:
        self.upload_dir = Path(settings.upload_dir).resolve()
        self.processed_dir = Path(settings.processed_dir).resolve()
        self.batch_dir = Path(settings.batch_dir).resolve()
        self._ensure_directories()

    # ------------------------------- Helpers ---------------------------------

    def _ensure_directories(self) -> None:
        """Ensure upload/processed/batch directories exist (idempotent)."""
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        self.batch_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ IO/FS --

    def is_supported_file(self, filename: str) -> bool:
        return Path(filename).suffix.lower() in SUPPORTED_EXTENSIONS

    def get_supported_extensions(self) -> List[str]:
        return sorted(SUPPORTED_EXTENSIONS)

    def _safe_document_id(self, filename: str) -> str:
        base = Path(filename).name.replace(" ", "_")
        return f"{int(time.time() * 1000)}_{base}"

    async def save_uploaded_file(self, filename: str, content: bytes) -> Tuple[str, Path]:
        """
        Persist an uploaded file to UPLOAD_DIR.

        Returns (document_id, file_path).
        """
        if not self.is_supported_file(filename):
            raise ValueError(f"Unsupported file type for: {filename}")

        document_id = self._safe_document_id(filename)
        dest = self.upload_dir / f"{document_id}"
        dest.write_bytes(content)
        return document_id, dest

    def list_uploaded_files(self) -> List[dict]:
        items = []
        for p in sorted(self.upload_dir.iterdir()):
            if p.is_file():
                items.append(
                    {
                        "document_id": p.name,
                        "filename": p.name.split("_", 1)[-1],
                        "size": p.stat().st_size,
                        "created_at": int(p.stat().st_mtime),
                    }
                )
        return items

    def list_batch_files(self) -> List[dict]:
        items = []
        for p in sorted(self.batch_dir.glob("*.json")):
            items.append(
                {
                    "filename": p.name,
                    "size": p.stat().st_size,
                    "created_at": int(p.stat().st_mtime),
                }
            )
        return items

    def find_batch_file(self, filename: str) -> Optional[Path]:
        fp = self.batch_dir / filename
        return fp if fp.exists() else None

    def _find_document_file(self, document_id: str) -> Optional[Path]:
        fp = self.upload_dir / document_id
        return fp if fp.exists() else None

    # ----------------------------------------------------------- Core pipeline --

    async def _extract_to_markdown(self, file_path: Path) -> str:
        """
        Call the external extraction service and return Markdown text.
        """
        try:
            md = await extraction_client.extract_markdown(
                file_path=file_path,
                original_filename=file_path.name.split("_", 1)[-1],
                mime_type=None,
                extra_params=None,
            )
            return md
        except ExtractionError as e:
            raise RuntimeError(f"Extraction service failed: {e}") from e

    def _score_conversion(self, markdown_text: str) -> Tuple[int, str]:
        """
        Heuristic scoring of conversion quality (0-100) with human feedback (string).
        Deterministic and cheap; complements LLM eval.
        """
        feedback_parts: List[str] = []
        score = 0

        text = markdown_text.strip()

        if not text:
            return 0, "No content extracted"

        # Simple structure heuristics
        headings = sum(1 for line in text.splitlines() if line.lstrip().startswith("#"))
        bullets = sum(1 for line in text.splitlines() if line.lstrip().startswith(("-", "*")))
        tables = text.count("|")

        length = len(text)
        if length > 400:
            score += 25
        elif length > 120:
            score += 15
        else:
            feedback_parts.append("Content very short; may be incomplete")

        if headings >= 2:
            score += 25
        elif headings == 1:
            score += 15
            feedback_parts.append("Limited heading structure detected")
        else:
            feedback_parts.append("No headings detected")

        if bullets >= 3:
            score += 15
        elif bullets > 0:
            score += 8
            feedback_parts.append("Few list items detected")
        else:
            feedback_parts.append("No lists detected")

        if "�" in text:
            feedback_parts.append("Encoding artifacts detected")
            score -= 10

        score = max(0, min(100, score))
        if not feedback_parts:
            feedback_parts.append("Conversion looks structurally sound")

        return score, " | ".join(feedback_parts)

    def _stats(self, text: str) -> tuple[int, int]:
        """
        Return (word_count, char_count) for a given text.
        """
        s = text or ""
        words = [w for w in s.split() if w]
        return len(words), len(s)

    def _meets_thresholds(
        self,
        conversion_score: int,
        llm_eval: Optional[LLMEvaluation],
        thresholds: QualityThresholds,
    ) -> bool:
        """
        Check conversion score + optional LLM eval against configured thresholds.
        """
        if conversion_score < thresholds.conversion_threshold:
            return False
        if not llm_eval:
            return True
        return (
            llm_eval.clarity_score >= thresholds.clarity_threshold
            and llm_eval.completeness_score >= thresholds.completeness_threshold
            and llm_eval.relevance_score >= thresholds.relevance_threshold
            and llm_eval.markdown_score >= thresholds.markdown_threshold
        )

    async def process_document(
        self,
        document_id: str,
        file_path: Path,
        options: ProcessingOptions,
    ) -> Optional[ProcessingResult]:
        """
        Full pipeline for a single document:
          1) Extraction service -> Markdown
          2) Heuristic conversion score
          3) Optional LLM evaluation
          4) Optional vector optimization (via LLM)
          5) Save processed .md and return ProcessingResult
        """
        started = time.time()

        if not file_path.exists():
            return None

        try:
            # 1) Extract
            markdown = await self._extract_to_markdown(file_path)

            # 2) Score
            score, feedback = self._score_conversion(markdown)

            # 3) LLM evaluation (optional)
            llm_eval: Optional[LLMEvaluation] = None
            if options.run_llm_evaluation and llm_service.is_available:
                llm_eval = await llm_service.evaluate_document(markdown)

            # 4) Vector optimization (optional)
            vector_optimized = False
            final_content = markdown
            if options.apply_vector_optimization and llm_service.is_available:
                final_content = await llm_service.optimize_for_vector_db(markdown)
                vector_optimized = True

            # 5) Persist processed markdown
            processed_path = self.processed_dir / f"{int(time.time())}_{document_id}.md"
            processed_path.write_text(final_content, encoding="utf-8")

            elapsed = time.time() - started
            wc, cc = self._stats(final_content)

            passes_thresholds = self._meets_thresholds(
                conversion_score=score,
                llm_eval=llm_eval,
                thresholds=options.quality_thresholds,
            )

            result = ProcessingResult(
                document_id=document_id,
                filename=file_path.name.split("_", 1)[-1],
                status=ProcessingStatus.COMPLETED,
                success=True,
                original_path=str(file_path),
                markdown_path=str(processed_path),
                conversion_result=ConversionResult(
                    success=True,
                    markdown_content=final_content,
                    conversion_score=score,
                    conversion_feedback=feedback,  # STRING
                    conversion_note="Extracted via external extraction service",
                    word_count=wc,
                    char_count=cc,
                    processing_time=elapsed,
                ),
                llm_evaluation=llm_eval,
                vector_optimized=vector_optimized,
                pass_all_thresholds=passes_thresholds,
                processing_time=elapsed,
                processed_at=time.time(),
                thresholds_used=options.quality_thresholds,
            )

            storage_service.save_result(document_id, result)
            return result

        except Exception as e:
            elapsed = time.time() - started
            err_path = self.processed_dir / f"error_{document_id}.txt"
            err_path.write_text(f"{type(e).__name__}: {e}", encoding="utf-8")

            # On failure, ensure required fields exist and types are correct
            result = ProcessingResult(
                document_id=document_id,
                filename=file_path.name.split("_", 1)[-1],
                status=ProcessingStatus.FAILED,
                success=False,
                original_path=str(file_path),
                markdown_path=str(err_path),
                conversion_result=ConversionResult(
                    success=False,
                    markdown_content="",
                    conversion_score=0,
                    conversion_feedback=f"Processing error: {e}",  # STRING
                    conversion_note="Extraction failed",
                    word_count=0,
                    char_count=0,
                    processing_time=elapsed,
                ),
                llm_evaluation=None,
                vector_optimized=False,
                pass_all_thresholds=False,
                processing_time=elapsed,
                processed_at=time.time(),
                thresholds_used=options.quality_thresholds,
            )
            storage_service.save_result(document_id, result)
            return result

    async def process_batch(
        self,
        job_id: str,
        filenames: List[str],
        options: ProcessingOptions,
    ) -> dict:
        """
        Process a list of uploaded document_ids (filenames are document_ids in upload_dir)
        Returns a summary dictionary.
        """
        results: List[ProcessingResult] = []
        for document_id in filenames:
            src = self._find_document_file(document_id)
            if not src:
                continue
            res = await self.process_document(document_id, src, options)
            if res:
                results.append(res)

        storage_service.save_batch(job_id, results)

        ok = sum(1 for r in results if r.success)
        failed = sum(1 for r in results if not r.success)
        rag_ready = sum(1 for r in results if r.pass_all_thresholds)

        summary = {
            "job_id": job_id,
            "total": len(results),
            "succeeded": ok,
            "failed": failed,
            "rag_ready": rag_ready,
            "results": [r.model_dump() for r in results],
        }
        (self.batch_dir / f"{job_id}.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return summary

    def get_processed_content(self, document_id: str) -> Optional[str]:
        """
        Return the last processed markdown content for a document_id from disk.
        """
        for p in sorted(self.processed_dir.glob(f"*_{document_id}.md"), reverse=True):
            try:
                return p.read_text(encoding="utf-8")
            except Exception:
                continue
        return None

    async def update_document_content(
        self,
        document_id: str,
        content: str,
        options: ProcessingOptions,
        improvement_prompt: Optional[Optional[str]] = None,
        apply_vector_optimization: bool = False,
    ) -> Optional[ProcessingResult]:
        """
        Replace processed content with a new body (optionally LLM-improved),
        re-score and (optionally) re-evaluate.
        """
        processed_path: Optional[Path] = None
        for p in sorted(self.processed_dir.glob(f"*_{document_id}.md"), reverse=True):
            processed_path = p
            break
        if not processed_path:
            return None

        final_content = content

        if improvement_prompt and llm_service.is_available:
            final_content = await llm_service.improve_document(final_content, improvement_prompt)
        elif apply_vector_optimization and llm_service.is_available:
            final_content = await llm_service.optimize_for_vector_db(final_content)

        processed_path.write_text(final_content, encoding="utf-8")

        score, feedback = self._score_conversion(final_content)
        llm_eval: Optional[LLMEvaluation] = None
        if options.run_llm_evaluation and llm_service.is_available:
            llm_eval = await llm_service.evaluate_document(final_content)

        passes = self._meets_thresholds(score, llm_eval, options.quality_thresholds)
        original_file = self._find_document_file(document_id)
        wc, cc = self._stats(final_content)

        updated = ProcessingResult(
            document_id=document_id,
            filename=(original_file.name.split("_", 1)[-1] if original_file else processed_path.stem),
            status=ProcessingStatus.COMPLETED,
            success=True,
            original_path=str(original_file) if original_file else None,
            markdown_path=str(processed_path),
            conversion_result=ConversionResult(
                success=True,
                markdown_content=final_content,
                conversion_score=score,
                conversion_feedback=feedback,  # STRING
                conversion_note="Content updated by user/LLM",
                word_count=wc,
                char_count=cc,
                processing_time=0.0,  # update path is quick; keep simple
            ),
            llm_evaluation=llm_eval,
            vector_optimized=apply_vector_optimization,
            pass_all_thresholds=passes,
            processing_time=0.0,
            processed_at=time.time(),
            thresholds_used=options.quality_thresholds,
        )

        storage_service.save_result(document_id, updated)
        return updated

    # -------------------------------------------------------------- Reset/GC --

    def clear_all_files(self) -> dict:
        """
        Remove all uploaded and processed files on disk, preserve batch files,
        and clear in-memory stores (if supported by storage_service).
        Returns a summary counts dict for logging/UI.
        """
        def _wipe_dir(p: Path) -> int:
            count = 0
            if p.exists():
                for child in p.iterdir():
                    try:
                        if child.is_file() or child.is_symlink():
                            child.unlink(missing_ok=True)
                            count += 1
                        elif child.is_dir():
                            shutil.rmtree(child, ignore_errors=True)
                            count += 1
                    except Exception:
                        # best-effort; keep going
                        pass
            p.mkdir(parents=True, exist_ok=True)
            return count

        deleted_uploads = _wipe_dir(self.upload_dir)
        deleted_processed = _wipe_dir(self.processed_dir)

        # IMPORTANT: do NOT delete batch_dir contents
        deleted_batches = 0  # keep response shape stable

        # Try to clear any in-memory caches in storage_service
        cleared_memory = False
        for attr in ("clear_all", "clear", "reset"):
            fn = getattr(storage_service, attr, None)
            if callable(fn):
                try:
                    fn()
                    cleared_memory = True
                    break
                except Exception:
                    pass

        # Recreate dirs as safety (batch already preserved)
        self._ensure_directories()

        return {
            "deleted_uploads": deleted_uploads,
            "deleted_processed": deleted_processed,
            "deleted_batches": deleted_batches,
            "cleared_memory": cleared_memory,
        }


# Global instance preserved for router imports
document_service = DocumentService()
