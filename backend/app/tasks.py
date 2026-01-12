"""
Celery tasks wrapping the existing document processing pipeline.
"""
import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from celery import shared_task, Task

from .services.document_service import document_service
from .services.storage_service import storage_service
from .services.job_service import (
    record_job_status,
    clear_active_job,
    append_job_log,
)


class BaseTask(Task):
    def on_success(self, retval: Any, task_id: str, args: Any, kwargs: Any):
        try:
            # retval should be a dict with result payload
            record_job_status(task_id, {
                "job_id": task_id,
                "document_id": kwargs.get("document_id") or (args[0] if args else None),
                "status": "SUCCESS",
                "finished_at": datetime.utcnow().isoformat(),
                "result": retval,
            })
        finally:
            doc_id = kwargs.get("document_id") or (args[0] if args else None)
            if doc_id:
                clear_active_job(doc_id, task_id)

    def on_failure(self, exc: Exception, task_id: str, args: Any, kwargs: Any, einfo):
        try:
            record_job_status(task_id, {
                "job_id": task_id,
                "document_id": kwargs.get("document_id") or (args[0] if args else None),
                "status": "FAILURE",
                "finished_at": datetime.utcnow().isoformat(),
                "error": str(exc),
            })
        finally:
            doc_id = kwargs.get("document_id") or (args[0] if args else None)
            if doc_id:
                clear_active_job(doc_id, task_id)


@shared_task(bind=True, base=BaseTask, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def process_document_task(self, document_id: str, options: Dict[str, Any], file_path: Optional[str] = None) -> Dict[str, Any]:
    # Mark started
    record_job_status(self.request.id, {
        "job_id": self.request.id,
        "document_id": document_id,
        "status": "STARTED",
        "started_at": datetime.utcnow().isoformat(),
    })

    append_job_log(self.request.id, "info", f"Job started for document '{document_id}'")
    logger = logging.getLogger("curatore.api")
    # Log which extraction engine will be used
    try:
        engine = (document_service.extractor_engine or "default").lower()
        has_docling = bool(getattr(document_service, "docling_base", None))
        has_extraction = bool(getattr(document_service, "extract_base", None))

        if engine == "auto":
            # Auto mode: prioritize Docling if available, then extraction-service
            if has_docling and has_extraction:
                docling_base = getattr(document_service, "docling_base", "").rstrip("/")
                extraction_base = getattr(document_service, "extract_base", "")
                docling_timeout = getattr(document_service, "docling_timeout", 60)
                append_job_log(self.request.id, "info", f"Extractor: Auto mode (Docling → extraction-service fallback)")
                try:
                    logger.info("Extractor selected: Auto mode - trying Docling first (%s), then extraction-service (%s)", docling_base, extraction_base)
                except Exception:
                    pass
            elif has_docling:
                base = getattr(document_service, "docling_base", "").rstrip("/")
                timeout = getattr(document_service, "docling_timeout", 60)
                append_job_log(self.request.id, "info", f"Extractor: Auto mode (Docling only) at {base} (timeout {timeout}s)")
                try:
                    logger.info("Extractor selected: Auto mode - Docling %s (timeout %ss)", base, timeout)
                except Exception:
                    pass
            elif has_extraction:
                base = getattr(document_service, "extract_base", "")
                timeout = getattr(document_service, "extract_timeout", 60)
                append_job_log(self.request.id, "info", f"Extractor: Auto mode (extraction-service only) at {base} (timeout {timeout}s)")
                try:
                    logger.info("Extractor selected: Auto mode - extraction-service %s (timeout %ss)", base, timeout)
                except Exception:
                    pass
            else:
                append_job_log(self.request.id, "info", "Extractor: Auto mode (no services configured)")
                try:
                    logger.info("Extractor selected: Auto mode (no services configured)")
                except Exception:
                    pass
        elif engine == "docling" and has_docling:
            base = getattr(document_service, "docling_base", "").rstrip("/")
            path = "/v1/convert/file"
            timeout = getattr(document_service, "docling_timeout", 60)
            if has_extraction:
                extraction_base = getattr(document_service, "extract_base", "")
                append_job_log(self.request.id, "info", f"Extractor: Docling at {base}{path} (→ extraction-service fallback if needed)")
            else:
                append_job_log(self.request.id, "info", f"Extractor: Docling at {base}{path} (timeout {timeout}s)")
            try:
                logger.info("Extractor selected: Docling %s%s (timeout %ss)", base, path, timeout)
            except Exception:
                pass
        elif engine in {"default", "extraction", "legacy"} and has_extraction:
            base = getattr(document_service, "extract_base", "")
            timeout = getattr(document_service, "extract_timeout", 60)
            if has_docling:
                docling_base = getattr(document_service, "docling_base", "").rstrip("/")
                append_job_log(self.request.id, "info", f"Extractor: Default extraction-service at {base} (→ Docling fallback if needed)")
            else:
                append_job_log(self.request.id, "info", f"Extractor: Default extraction-service at {base} (timeout {timeout}s)")
            try:
                logger.info("Extractor selected: extraction-service %s (timeout %ss)", base, timeout)
            except Exception:
                pass
        else:
            append_job_log(self.request.id, "info", "Extractor: none (using local/fallback behavior)")
            try:
                logger.info("Extractor selected: none (local/fallback)")
            except Exception:
                pass
    except Exception:
        # Non-fatal; continue processing
        pass
    # Prepare domain options from incoming API shape
    from .api.v1.models import V1ProcessingOptions, V1ProcessingResult
    domain_options = V1ProcessingOptions(**(options or {})).to_domain()

    # Locate file using provided path first, else unified resolver
    resolved_path = None
    try:
        if file_path:
            from pathlib import Path
            p = Path(file_path)
            if p.exists():
                resolved_path = p
    except Exception:
        resolved_path = None

    if not resolved_path:
        resolved_path = document_service.find_document_file_unified(document_id)

    if not resolved_path:
        append_job_log(self.request.id, "error", "Document file not found")
        raise RuntimeError("Document file not found")

    # Run the existing async pipeline
    try:
        append_job_log(self.request.id, "info", "Conversion started")
        result = asyncio.run(document_service.process_document(document_id, resolved_path, domain_options))
        # Post-extraction confirmation log: which extractor actually produced content
        try:
            meta = getattr(result, 'processing_metadata', {}) or {}
            ex = meta.get('extractor') if isinstance(meta, dict) else None
            if isinstance(ex, dict) and ex:
                eng = ex.get('engine') or ex.get('requested_engine') or 'unknown'
                primary = ex.get('primary_engine') or (ex.get('requested_engine') if ex.get('failover') else None)
                chain = f"{primary}→{eng}" if primary and primary != eng else eng
                url = ex.get('url') or ''
                fb = ex.get('failover') or ex.get('fallback')
                ok = ex.get('ok')
                err = ex.get('error')
                status_txt = "ok" if ok else f"failed{f': {err}' if err else ''}"
                msg = f"Extractor used: {chain}{' (fallback)' if fb else ''}{' - ' + url if url else ''} ({status_txt})"
                append_job_log(self.request.id, "info", msg)
                if err:
                    append_job_log(self.request.id, "warning", f"Extractor error detail: {err}")
                # Docling-specific status/error reporting for Processing Panel visibility
                if eng == 'docling':
                    status_txt = ex.get('status')
                    errors_list = ex.get('errors') or []
                    ptime = ex.get('processing_time')
                    if status_txt:
                        append_job_log(self.request.id, "info", f"Docling status: {status_txt}{f', time: {ptime:.2f}s' if isinstance(ptime, (int, float)) else ''}")
                    if isinstance(errors_list, list) and errors_list:
                        first_err = errors_list[0]
                        append_job_log(self.request.id, "warning", f"Docling reported {len(errors_list)} error(s); first: {first_err}")
        except Exception:
            pass
        if result and getattr(result, 'conversion_result', None):
            append_job_log(self.request.id, "success", f"Conversion complete (score {result.conversion_result.conversion_score}/100)")
        if getattr(result, 'vector_optimized', False):
            append_job_log(self.request.id, "success", "Optimization applied")
        else:
            append_job_log(self.request.id, "info", "Optimization skipped")
        if getattr(result, 'llm_evaluation', None):
            append_job_log(self.request.id, "success", "Quality analysis complete")
        if getattr(result, 'is_rag_ready', False) or getattr(result, 'pass_all_thresholds', False):
            append_job_log(self.request.id, "success", "File passed quality thresholds")
        else:
            append_job_log(self.request.id, "warning", "File did not meet quality thresholds")
        append_job_log(self.request.id, "success", "Completed processing")
    except Exception as e:
        append_job_log(self.request.id, "error", f"Processing error: {str(e)}")
        raise

    # Persist result via storage service (so existing endpoints work)
    storage_service.save_processing_result(result)

    # Return a JSON-serializable V1ProcessingResult dict
    return V1ProcessingResult.model_validate(result).model_dump()


@shared_task(bind=True, base=BaseTask, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def update_document_content_task(self, document_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    # payload: { content, options, improvement_prompt, apply_vector_optimization }
    record_job_status(self.request.id, {
        "job_id": self.request.id,
        "document_id": document_id,
        "status": "STARTED",
        "started_at": datetime.utcnow().isoformat(),
    })

    from .api.v1.models import V1ProcessingOptions, V1ProcessingResult

    options_dict = payload.get("options") or {}
    content = payload.get("content") or ""
    improvement_prompt = payload.get("improvement_prompt")
    apply_vector_optimization = bool(payload.get("apply_vector_optimization") or False)

    domain_options = V1ProcessingOptions(**options_dict).to_domain()

    try:
        append_job_log(self.request.id, "info", "Content update started")
        result = asyncio.run(
            document_service.update_document_content(
                document_id=document_id,
                content=content,
                options=domain_options,
                improvement_prompt=improvement_prompt,
                apply_vector_optimization=apply_vector_optimization,
            )
        )
        if not result:
            append_job_log(self.request.id, "error", "Document not found or update failed")
            raise RuntimeError("Document not found or update failed")
        append_job_log(self.request.id, "success", "Content saved and re-evaluated")
        if getattr(result, 'is_rag_ready', False) or getattr(result, 'pass_all_thresholds', False):
            append_job_log(self.request.id, "success", "File passed quality thresholds")
        else:
            append_job_log(self.request.id, "warning", "File did not meet quality thresholds")
        append_job_log(self.request.id, "success", "Update complete")
    except Exception as e:
        append_job_log(self.request.id, "error", f"Update failed: {str(e)}")
        raise

    storage_service.save_processing_result(result)
    return V1ProcessingResult.model_validate(result).model_dump()
