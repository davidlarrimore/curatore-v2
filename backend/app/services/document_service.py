# ============================================================================
# Curatore v2 - Document Service
# ============================================================================
#
# Responsibilities:
#   - Enforce canonical file layout via app.config.settings
#   - Handle uploads, listings, lookups
#   - Convert to Markdown (with graceful fallbacks)
#   - Save processed output into processed_files
#
# Canonical directories (inside the container):
#   /app/files/uploaded_files
#   /app/files/processed_files
#   /app/files/batch_files
#
# IMPORTANT:
# - Do not hardcode relative paths like "uploads" or "processed".
# - Use settings.*_path for all filesystem activity.
# - We create uploaded_files and processed_files if missing.
#   batch_files is operator-managed and may be just a bind mount.
# ============================================================================

import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from app.config import settings

# Optional conversion engine (MarkItDown)
try:
    from markitdown import MarkItDown
    _MD = MarkItDown(enable_plugins=False)
except Exception:
    _MD = None

# Models (minimal typing to avoid import cycles)
from app.models import ProcessingResult  # adjust if your models are split
from app.models import ProcessingStatus, ProcessingOptions  # enums/data classes


SUPPORTED_EXTENSIONS = {
    ".pdf", ".docx", ".txt", ".md",
    ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"
}


@dataclass
class ConversionResult:
    conversion_score: int
    conversion_note: str = ""


class DocumentService:
    """
    Core document processing and storage helper.

    Public API:
        - save_uploaded_file(filename, content) -> (document_id, path)
        - list_uploaded_files() -> [str]
        - list_batch_files() -> [str]
        - find_uploaded_file(document_id) -> Path | None
        - find_batch_file(filename) -> Path | None
        - process_document(document_id, file_path, options) -> ProcessingResult
    """

    def __init__(self) -> None:
        # Ensure canonical directories exist (except batch_files)
        settings.upload_path.mkdir(parents=True, exist_ok=True)
        settings.processed_path.mkdir(parents=True, exist_ok=True)
        # We do NOT create batch_path; it’s managed externally (bind-mounted)

        print("[DocumentService] Using directories:")
        print(f"  uploads   -> {settings.upload_path}")
        print(f"  processed -> {settings.processed_path}")
        print(f"  batch     -> {settings.batch_path} (operator-managed)")

    # ------------------- Listing -------------------

    def get_supported_extensions(self) -> List[str]:
        return sorted(SUPPORTED_EXTENSIONS)

    def list_uploaded_files(self) -> List[str]:
        return sorted(p.name for p in settings.upload_path.glob("*") if p.is_file())

    def list_batch_files(self) -> List[str]:
        if not settings.batch_path.exists():
            return []
        return sorted(p.name for p in settings.batch_path.glob("*") if p.is_file())

    # ------------------- Upload & Lookup -------------------

    async def save_uploaded_file(self, filename: str, content: bytes) -> Tuple[str, Path]:
        """
        Persist an upload into /app/files/uploaded_files with a UUID prefix.
        Returns (document_id, absolute_path).
        """
        document_id = str(uuid.uuid4())

        # sanitize filename (naive but effective)
        safe = filename.replace("../", "").replace("..\\", "")
        safe = safe.replace("/", "_").replace("\\", "_")

        out_path = settings.upload_path / f"{document_id}_{safe}"
        out_path.write_bytes(content)
        return document_id, out_path

    def find_uploaded_file(self, document_id: str) -> Optional[Path]:
        """Find the uploaded file by its UUID prefix."""
        for p in settings.upload_path.glob(f"{document_id}_*"):
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS:
                return p
        # Legacy fallback: {name}_{uuid}.{ext}
        for p in settings.upload_path.glob("*"):
            if p.is_file() and p.stem.endswith(f"_{document_id}"):
                return p
        return None

    def find_batch_file(self, filename: str) -> Optional[Path]:
        """Locate a file inside /app/files/batch_files by exact filename."""
        candidate = settings.batch_path / filename
        return candidate if candidate.exists() and candidate.is_file() else None

    # ------------------- Processing -------------------

    def _convert_to_markdown(self, file_path: Path) -> Tuple[Optional[str], ConversionResult]:
        """
        Convert input file to Markdown using MarkItDown where available.
        Falls back to passthrough for .txt/.md when MarkItDown isn't present.
        """
        try:
            if _MD:
                md = _MD.convert(file_path.as_posix()).text_content  # type: ignore[attr-defined]
            else:
                if file_path.suffix.lower() in {".md", ".txt"}:
                    md = file_path.read_text(encoding="utf-8", errors="ignore")
                else:
                    raise RuntimeError("Conversion engine unavailable")
            score = 80 if md and md.strip() else 0
            return md, ConversionResult(conversion_score=score, conversion_note="Converted to Markdown")
        except Exception as e:
            return None, ConversionResult(conversion_score=0, conversion_note=f"Conversion failed: {e}")

    def _passes_thresholds(self, conv_score: int, thresholds: Dict[str, int]) -> bool:
        return conv_score >= int(thresholds.get("conversion", 70))

    async def process_document(
        self,
        document_id: str,
        file_path: Path,
        options: ProcessingOptions,
    ) -> ProcessingResult:
        """
        Convert the file to Markdown and save the output into processed_files.

        Output naming: {original_stem}_{document_id}.md
        """
        start = time.time()
        filename = file_path.name

        try:
            # Step 1: Convert
            markdown, conv = self._convert_to_markdown(file_path)
            if not markdown:
                return ProcessingResult(
                    document_id=document_id,
                    filename=filename,
                    status=ProcessingStatus.FAILED,
                    success=False,
                    message=conv.conversion_note,
                    original_path=str(file_path),
                    processing_time=time.time() - start,
                    thresholds_used=options.quality_thresholds,
                )

            # Step 2: Optional vector optimization via LLM (best-effort)
            vector_optimized = False
            try:
                from app.services.llm_service import llm_service  # lazy import
                if getattr(options, "auto_optimize", False) and llm_service.is_available:
                    optimized = await llm_service.optimize_for_vector_db(markdown)
                    if optimized and optimized.strip():
                        markdown = optimized
                        vector_optimized = True
                        conv.conversion_note = "Vector-optimized. " + conv.conversion_note
            except Exception as e:
                conv.conversion_note = f"Optimization skipped/failed ({str(e)[:60]}...). " + conv.conversion_note

            # Step 3: Write output
            out_path = settings.processed_path / f"{file_path.stem}_{document_id}.md"
            out_path.write_text(markdown, encoding="utf-8")

            # Step 4: Optional LLM evaluation (do not fail the pipeline on error)
            llm_eval = None
            try:
                from app.services.llm_service import llm_service  # lazy import
                if llm_service.is_available:
                    llm_eval = await llm_service.evaluate_document(markdown)
            except Exception:
                llm_eval = None

            # Step 5: Thresholds
            passes = self._passes_thresholds(conv.conversion_score, options.quality_thresholds)

            return ProcessingResult(
                document_id=document_id,
                filename=filename,
                status=ProcessingStatus.COMPLETED,
                success=True,
                original_path=str(file_path),
                markdown_path=str(out_path),
                conversion_result=conv,
                llm_evaluation=llm_eval,
                conversion_score=conv.conversion_score,
                pass_all_thresholds=passes,
                vector_optimized=vector_optimized,
                processing_time=time.time() - start,
                processed_at=time.time(),
                thresholds_used=options.quality_thresholds,
            )

        except Exception as e:
            return ProcessingResult(
                document_id=document_id,
                filename=filename,
                status=ProcessingStatus.FAILED,
                success=False,
                message=f"Processing error: {e}",
                original_path=str(file_path),
                processing_time=time.time() - start,
                thresholds_used=options.quality_thresholds,
            )

    # ------------------- Dev helpers -------------------

    def clear_all_files(self) -> None:
        """Dangerous: DEBUG/dev only. Clears uploaded/processed files."""
        if not settings.debug:
            return
        for p in settings.upload_path.glob("*"):
            try:
                if p.is_file():
                    p.unlink()
            except Exception:
                pass
        for p in settings.processed_path.glob("*"):
            try:
                if p.is_file():
                    p.unlink()
            except Exception:
                pass


# Singleton instance
document_service = DocumentService()
