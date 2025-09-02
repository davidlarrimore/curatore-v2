"""
Celery tasks wrapping the existing document processing pipeline.
"""
import asyncio
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
