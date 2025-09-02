# backend/app/services/document_service.py
from __future__ import annotations

import re
import uuid
import shutil
from pathlib import Path
from typing import Iterable, List, Optional, Set, Dict, Any, Tuple
from datetime import datetime

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

    # ----------------------- Public FS API -----------------------

    def ensure_directories(self) -> None:
        self._ensure_directories()

    def clear_all_files(self) -> Dict[str, int]:
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
        return sorted(self._supported_extensions)

    def is_supported_file(self, filename: str) -> bool:
        if not filename:
            return False
        ext = Path(filename).suffix.lower()
        return not self._supported_extensions or ext in self._supported_extensions

    async def save_uploaded_file(self, filename: str, content: bytes) -> Tuple[str, str]:
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
        return self._list_files_for_api(self.upload_dir, kind="uploaded")

    def list_processed_files_with_metadata(self) -> List[Dict[str, Any]]:
        return self._list_files_for_api(self.processed_dir, kind="processed")

    def list_batch_files_with_metadata(self) -> List[Dict[str, Any]]:
        if not self.batch_dir:
            return []
        return self._list_files_for_api(self.batch_dir, kind="batch")

    # ---- Retrieval helpers ----

    def get_processed_content(self, document_id: str) -> Optional[str]:
        for file_path in self.processed_dir.glob(f"*_{document_id}.md"):
            try:
                return file_path.read_text(encoding="utf-8")
            except Exception:
                continue
        return None

    def find_batch_file(self, filename: str) -> Optional[Path]:
        if not self.batch_dir:
            return None
        try:
            cand = self.batch_dir / filename
            if cand.exists() and cand.is_file() and self.is_supported_file(cand.name):
                return cand
            stem = Path(filename).stem
            for p in self.batch_dir.glob(f"{stem}.*"):
                if p.is_file() and self.is_supported_file(p.name):
                    return p
        except Exception:
            pass
        return None

    # ----------------------- Processing via extraction service -----------------------

    async def convert_to_markdown(self, file_path: Path, ocr_settings: OCRSettings) -> ConversionResult:
        start = datetime.now()

        if file_path.suffix.lower() in {".txt", ".md"}:
            try:
                text = file_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                text = file_path.read_text(encoding="latin-1")
            score, feedback = self._score_conversion(text if file_path.suffix.lower() == ".md" else f"```\n{text}\n```")
            return ConversionResult(
                success=True,
                markdown_content=text if file_path.suffix.lower() == ".md" else f"```\n{text}\n```",
                conversion_score=score,
                conversion_feedback=feedback,
                word_count=len(text.split()),
                char_count=len(text),
                processing_time=(datetime.now() - start).total_seconds(),
                conversion_note="Loaded text/markdown directly.",
            )

        markdown, note = await self._extract_with_service(file_path, ocr_settings)
        if not markdown:
            return ConversionResult(
                success=False,
                markdown_content="",
                conversion_score=0,
                conversion_feedback="Extraction service failed to return content.",
                word_count=0,
                char_count=0,
                processing_time=(datetime.now() - start).total_seconds(),
                conversion_note=note or "No content.",
            )

        score, feedback = self._score_conversion(markdown)
        return ConversionResult(
            success=True,
            markdown_content=markdown,
            conversion_score=score,
            conversion_feedback=feedback,
            word_count=len(markdown.split()),
            char_count=len(markdown),
            processing_time=(datetime.now() - start).total_seconds(),
            conversion_note=note or "Converted via extraction service.",
        )

    async def process_document(
        self,
        document_id: str,
        file_path: Path,
        options: ProcessingOptions,
    ) -> ProcessingResult:
        start = datetime.now()
        filename = file_path.name.split("_", 1)[-1] if "_" in file_path.name else file_path.name

        try:
            conv = await self.convert_to_markdown(file_path, options.ocr_settings)
            if not conv.success or not conv.markdown_content:
                return ProcessingResult(
                    document_id=document_id,
                    filename=filename,
                    status=ProcessingStatus.FAILED,
                    success=False,
                    error_message=f"Conversion failed: {conv.conversion_feedback}",
                    original_path=str(file_path),
                    conversion_result=conv,
                    llm_evaluation=None,
                    is_rag_ready=False,
                    processing_time=(datetime.now() - start).total_seconds(),
                    processed_at=datetime.now(),
                    file_size=0,
                )

            markdown_content = conv.markdown_content

            document_summary = None
            if llm_service.is_available:
                try:
                    smry = await llm_service.summarize_document(markdown_content, filename)
                    document_summary = clean_llm_response(smry)
                except Exception as e:
                    document_summary = f"Summary generation failed: {str(e)[:120]}"

            out_path = self.processed_dir / f"{file_path.stem}_{document_id}.md"
            out_path.write_text(markdown_content, encoding="utf-8")

            llm_eval: Optional[LLMEvaluation] = None
            if llm_service.is_available:
                try:
                    llm_eval = await llm_service.evaluate_document(markdown_content)
                except Exception:
                    llm_eval = None

            passes = self._meets_thresholds(conv.conversion_score, llm_eval, options.quality_thresholds)

            return ProcessingResult(
                document_id=document_id,
                filename=filename,
                status=ProcessingStatus.COMPLETED,
                success=True,
                original_path=str(file_path),
                markdown_path=str(out_path),
                conversion_result=conv,
                llm_evaluation=llm_eval,
                document_summary=document_summary,
                conversion_score=conv.conversion_score,
                is_rag_ready=passes,
                vector_optimized=False,
                processing_time=(datetime.now() - start).total_seconds(),
                processed_at=datetime.now(),
                file_size=out_path.stat().st_size if out_path.exists() else 0,
            )

        except Exception as e:
            conv = ConversionResult(
                success=False,
                markdown_content="",
                conversion_score=0,
                conversion_feedback=f"Processing error: {e}",
                word_count=0,
                char_count=0,
                processing_time=(datetime.now() - start).total_seconds(),
                conversion_note="Processing pipeline error.",
            )
            return ProcessingResult(
                document_id=document_id,
                filename=filename,
                status=ProcessingStatus.FAILED,
                success=False,
                error_message=f"Processing error: {e}",
                original_path=str(file_path),
                conversion_result=conv,
                llm_evaluation=None,
                is_rag_ready=False,
                processing_time=(datetime.now() - start).total_seconds(),
                processed_at=datetime.now(),
                file_size=0,
            )

    async def process_batch(self, document_ids: List[str], options: ProcessingOptions) -> List[ProcessingResult]:
        results: List[ProcessingResult] = []
        for doc_id in document_ids:
            file_path = self._find_document_file(doc_id)
            if not file_path:
                conv = ConversionResult(
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
                    conversion_result=conv,
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
        apply_vector_optimization: bool = False,
    ) -> Optional[ProcessingResult]:
        processed_file = next(self.processed_dir.glob(f"*_{document_id}.md"), None)
        if not processed_file:
            return None

        final_content = content
        vector_optimized = False

        if improvement_prompt and llm_service.is_available:
            final_content = await llm_service.improve_document(content, improvement_prompt)
        elif apply_vector_optimization and llm_service.is_available:
            final_content = await llm_service.optimize_for_vector_db(content)
            vector_optimized = True

        final_content = clean_llm_response(final_content)
        processed_file.write_text(final_content, encoding="utf-8")

        score, feedback = self._score_conversion(final_content)
        llm_eval = await llm_service.evaluate_document(final_content) if llm_service.is_available else None
        passes = self._meets_thresholds(score, llm_eval, options.quality_thresholds)

        original_file = self._find_document_file(document_id)
        filename = (original_file.name.split("_", 1)[-1] if original_file else processed_file.stem.split("_", 1)[-1])

        return ProcessingResult(
            document_id=document_id,
            filename=filename,
            status=ProcessingStatus.COMPLETED,
            success=True,
            original_path=str(original_file) if original_file else None,
            markdown_path=str(processed_file),
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
            llm_evaluation=llm_eval,
            conversion_score=score,
            is_rag_ready=passes,
            vector_optimized=vector_optimized,
            processing_time=0.0,
            processed_at=datetime.now(),
            file_size=processed_file.stat().st_size if processed_file.exists() else 0,
        )

    # ----------------------- Internal helpers -----------------------

    def _load_supported_extensions(self) -> Set[str]:
        raw: Optional[Iterable[str]] = None
        if hasattr(settings, "supported_extensions"):
            raw = getattr(settings, "supported_extensions")
        elif hasattr(settings, "allowed_extensions"):
            raw = getattr(settings, "allowed_extensions")

        if not raw:
            return set(self.DEFAULT_EXTS)

        norm: Set[str] = set()
        for ext in raw:
            if not ext:
                continue
            e = str(ext).strip().lower()
            if not e.startswith("."):
                e = "." + e
            norm.add(e)
        return norm or set(self.DEFAULT_EXTS)

    def _normalize_under_root(self) -> None:
        if not self.files_root:
            return

        def under_root(p: Path) -> Path:
            return p if p.is_absolute() else (self.files_root / p)

        self.upload_dir = under_root(self.upload_dir)
        self.processed_dir = under_root(self.processed_dir)
        if self.batch_dir is not None:
            self.batch_dir = under_root(self.batch_dir)

    def _ensure_directories(self) -> None:
        if self.files_root is not None:
            self.files_root.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        if self.batch_dir is not None:
            self.batch_dir.mkdir(parents=True, exist_ok=True)

    def _safe_clear_dir(self, directory: Path) -> int:
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
        Returns list items shaped for FileListResponse:
          - original_filename (str)
          - file_size (int)
          - upload_time (ISO-8601 str)  [we use mtime]
          - file_path (str)             [relative to base_dir]
        Also includes helpful extras: document_id, ext.
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

                results.append({
                    # required by FileListResponse
                    "original_filename": original_filename,
                    "file_size": int(stat.st_size),
                    "upload_time": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "file_path": str(entry.relative_to(base_dir)),
                    # useful extras (safe to keep)
                    "document_id": document_id,
                    "ext": ext or "",
                })
            except Exception:
                continue

        return results

    def _find_document_file(self, document_id: str) -> Optional[Path]:
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
        name = name.replace("\\", "/").split("/")[-1]
        stem = Path(name).stem
        ext = Path(name).suffix
        safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-") or "file"
        return f"{safe_stem}{ext}"

    def _score_conversion(self, markdown_text: str, original_text: Optional[str] = None) -> Tuple[int, str]:
        if not markdown_text:
            return 0, "No markdown produced."

        content_score = 100
        if original_text:
            ow = original_text.split()
            mw = markdown_text.split()
            content_score = int(min(len(mw) / max(len(ow), 1), 1.0) * 100)

        import re as _re
        headings = len(_re.findall(r'^#{1,6}\s', markdown_text, flags=_re.MULTILINE))
        lists = len(_re.findall(r'^[\-\*]\s', markdown_text, flags=_re.MULTILINE))
        tables = markdown_text.count("|")

        structure_score = 0
        if headings > 0:
            structure_score += 30
        if lists > 0:
            structure_score += 30
        if tables > 3:
            structure_score += 20

        legibility_score = 0 if "�" in markdown_text else 20
        total = min(int(0.5 * content_score + structure_score + legibility_score), 100)

        fb = []
        if content_score < 100 and original_text:
            fb.append(f"Content preserved ~{content_score}%.")
        if structure_score < 60:
            fb.append("Formatting may be partially lost.")
        if legibility_score < 20:
            fb.append("Some readability issues.")
        if not fb:
            fb.append("High-fidelity conversion.")
        return total, " ".join(fb)

    def _meets_thresholds(
        self,
        conversion_score: int,
        llm_evaluation: Optional[LLMEvaluation],
        thresholds: Optional[QualityThresholds],
    ) -> bool:
        if not llm_evaluation:
            return False

        if thresholds is None:
            conv = settings.default_conversion_threshold
            clr = settings.default_clarity_threshold
            comp = settings.default_completeness_threshold
            rel = settings.default_relevance_threshold
            mdq = settings.default_markdown_threshold
        else:
            conv = getattr(thresholds, "conversion", getattr(thresholds, "conversion_quality", settings.default_conversion_threshold))
            clr = getattr(thresholds, "clarity", getattr(thresholds, "clarity_score", settings.default_clarity_threshold))
            comp = getattr(thresholds, "completeness", getattr(thresholds, "completeness_score", settings.default_completeness_threshold))
            rel = getattr(thresholds, "relevance", getattr(thresholds, "relevance_score", settings.default_relevance_threshold))
            mdq = getattr(thresholds, "markdown", getattr(thresholds, "markdown_quality", settings.default_markdown_threshold))

        try:
            return (
                conversion_score >= int(conv)
                and (llm_evaluation.clarity_score or 0) >= int(clr)
                and (llm_evaluation.completeness_score or 0) >= int(comp)
                and (llm_evaluation.relevance_score or 0) >= int(rel)
                and (llm_evaluation.markdown_score or 0) >= int(mdq)
            )
        except Exception:
            return False

    async def _extract_with_service(self, file_path: Path, ocr: OCRSettings) -> Tuple[Optional[str], str]:
        if not self.extract_base:
            return None, "extraction_service_url not configured."

        url_candidates = (
            f"{self.extract_base}/v1/extract",
            f"{self.extract_base}/extract",
        )
        headers: Dict[str, str] = {}
        if self.extract_api_key:
            headers["Authorization"] = f"Bearer {self.extract_api_key}"

        data = {
            "return_format": "markdown",
            "lang": getattr(ocr, "language", "eng"),
            "psm": str(getattr(ocr, "psm", 3)),
        }

        for url in url_candidates:
            try:
                async with httpx.AsyncClient(timeout=self.extract_timeout) as client:
                    with open(file_path, "rb") as fh:
                        files = {"file": (file_path.name, fh, "application/octet-stream")}
                        resp = await client.post(url, data=data, files=files, headers=headers)
                if resp.status_code != 200:
                    continue
                try:
                    js = resp.json()
                    md = js.get("markdown") or js.get("content") or js.get("text")
                    if md:
                        return str(md), f"Extraction service OK ({url})."
                except Exception:
                    pass
                txt = resp.text or ""
                if txt.strip():
                    return txt, f"Extraction service (text) OK ({url})."
            except Exception:
                continue

        return None, "All extraction endpoints failed."


# Singleton instance
document_service = DocumentService()
