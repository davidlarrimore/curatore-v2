"""
Extraction Orchestrator Service for Automatic Extraction.

Orchestrates the automatic extraction process for Assets by delegating to the
standalone Document Service via the DocumentServiceAdapter. The Document Service
handles triage, engine selection, and content extraction internally.

Usage:
    from app.core.ingestion.extraction_orchestrator import extraction_orchestrator

    # Execute extraction for an asset
    result = await extraction_orchestrator.execute_extraction(
        session=session,
        asset_id=asset_id,
        run_id=run_id,
        extraction_id=extraction_id,
    )
"""

import logging
import tempfile
import time
from io import BytesIO
from pathlib import Path
from typing import Any, Dict
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.connectors.adapters.document_service_adapter import (
    DocumentServiceError,
    DocumentServiceResponse,
    document_service_adapter,
)
from app.core.shared.asset_service import asset_service
from app.core.shared.config_loader import config_loader
from app.core.shared.run_log_service import run_log_service
from app.core.shared.run_service import run_service
from app.core.storage.minio_service import get_minio_service
from app.core.storage.storage_path_service import storage_paths

from .extraction_result_service import extraction_result_service


class UnsupportedFileTypeError(Exception):
    """Exception raised when a file type is not supported by the configured extraction engine."""
    pass


# All formats supported by the document service
SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".xlsb",
    ".txt", ".md", ".csv", ".html", ".htm", ".xml", ".json",
    ".msg", ".eml",
}


def _is_search_enabled() -> bool:
    """Check if search is enabled via config.yml or environment variables."""
    search_config = config_loader.get_search_config()
    if search_config:
        return search_config.enabled
    return getattr(settings, "search_enabled", True)

logger = logging.getLogger("curatore.extraction_orchestrator")


class ExtractionOrchestrator:
    """
    Service for orchestrating automatic document extraction.

    Delegates extraction to the standalone Document Service, then handles
    Run/ExtractionResult tracking, structured logging, and Asset status management.
    """

    async def prepare_extraction(
        self,
        session: AsyncSession,
        asset_id: UUID,
        run_id: UUID,
        extraction_id: UUID,
    ) -> Dict[str, Any]:
        """
        Phase 1: Setup for extraction.

        Loads models, validates state, starts the run, and downloads the file
        to a temp directory. Designed to run in a short-lived DB session that
        closes before the long document service HTTP call.

        Args:
            session: Database session (will be committed/closed by caller)
            asset_id: Asset UUID to extract
            run_id: Run UUID tracking this extraction
            extraction_id: ExtractionResult UUID to update

        Returns:
            Dict with either:
            - {"phase": "early_return", "result": {...}} for already-done/unsupported
            - {"phase": "ready_for_extraction", "temp_file_path": str, "temp_dir": str,
               "start_time": float, "is_restart": bool}
        """
        start_time = time.time()

        # Get models
        asset = await asset_service.get_asset(session, asset_id)
        run = await run_service.get_run(session, run_id)
        extraction = await extraction_result_service.get_extraction_result(session, extraction_id)

        if not asset or not run or not extraction:
            error = f"Asset, Run, or Extraction not found: {asset_id}, {run_id}, {extraction_id}"
            logger.error(error)
            raise ValueError(error)

        # =====================================================================
        # RESTART RESILIENCE: Check if extraction already completed or failed
        # =====================================================================
        if extraction.status == "completed":
            logger.info(
                f"[Run {run_id}] Extraction already completed, skipping re-execution "
                f"(idempotency check)"
            )
            return {
                "phase": "early_return",
                "result": {
                    "status": "already_completed",
                    "asset_id": str(asset_id),
                    "run_id": str(run_id),
                    "extraction_id": str(extraction_id),
                    "message": "Extraction was already completed (task re-delivered after restart)",
                },
            }

        if run.status == "completed":
            logger.info(
                f"[Run {run_id}] Run already completed, skipping re-execution"
            )
            return {
                "phase": "early_return",
                "result": {
                    "status": "already_completed",
                    "asset_id": str(asset_id),
                    "run_id": str(run_id),
                    "extraction_id": str(extraction_id),
                    "message": "Run was already completed (task re-delivered after restart)",
                },
            }

        if run.status in ("timed_out", "failed", "cancelled"):
            logger.info(
                f"[Run {run_id}] Run already in terminal state '{run.status}', skipping re-execution"
            )
            return {
                "phase": "early_return",
                "result": {
                    "status": f"already_{run.status}",
                    "asset_id": str(asset_id),
                    "run_id": str(run_id),
                    "extraction_id": str(extraction_id),
                    "message": f"Run was already {run.status} (task re-delivered after restart)",
                },
            }

        is_restart = extraction.status == "running" or run.status == "running"
        if is_restart:
            logger.warning(
                f"[Run {run_id}] Found in 'running' state - likely interrupted by restart. "
                f"Resuming extraction..."
            )
            await run_log_service.log_event(
                session=session,
                run_id=run_id,
                level="WARN",
                event_type="restart",
                message="Extraction resumed after service restart",
                context={
                    "previous_run_status": run.status,
                    "previous_extraction_status": extraction.status,
                },
            )
        # =====================================================================

        minio = get_minio_service()
        if not minio:
            error = "MinIO service unavailable"
            logger.error(error)
            await self._fail_extraction(session, run_id, extraction_id, asset_id, error)
            raise RuntimeError(error)

        # =====================================================================
        # FILE TYPE VALIDATION
        # =====================================================================
        file_ext = Path(asset.original_filename).suffix.lower()
        is_supported, supported_formats, engine_name = self._check_file_type_support(file_ext)

        if not is_supported:
            error_message = (
                f"Unsupported file type: '{file_ext}'. "
                f"The document service supports: "
                f"{', '.join(sorted(supported_formats)[:10])}"
                f"{'...' if len(supported_formats) > 10 else ''}"
            )
            logger.warning(
                f"[Run {run_id}] Skipping extraction for unsupported file type: "
                f"{asset.original_filename} ({file_ext})"
            )
            await self._fail_extraction(
                session=session,
                run_id=run_id,
                extraction_id=extraction_id,
                asset_id=asset_id,
                error_message=error_message,
            )
            return {
                "phase": "early_return",
                "result": {
                    "status": "unsupported_file_type",
                    "asset_id": str(asset_id),
                    "run_id": str(run_id),
                    "extraction_id": str(extraction_id),
                    "file_extension": file_ext,
                    "supported_formats": list(supported_formats),
                    "engine_name": engine_name,
                    "error": error_message,
                },
            }
        # =====================================================================

        # Start the run (skip if resuming after restart - already running)
        if not is_restart:
            await run_service.start_run(session, run_id)
            await extraction_result_service.update_extraction_status(session, extraction_id, "running")

        # Get current version for logging
        current_version = await asset_service.get_current_asset_version(session, asset_id)
        version_info = {
            "version_number": asset.current_version_number,
            "version_id": str(current_version.id) if current_version else None,
        }

        await run_log_service.log_event(
            session=session,
            run_id=run_id,
            level="INFO",
            event_type="progress",
            message=f"Starting extraction for {asset.original_filename} (version {asset.current_version_number or 1})",
            context={
                "asset_id": str(asset_id),
                "filename": asset.original_filename,
                "file_size": asset.file_size,
                **version_info,
            },
        )

        # Download asset from object storage to temp file
        await run_log_service.log_event(
            session=session,
            run_id=run_id,
            level="INFO",
            event_type="progress",
            message="Downloading file from storage...",
        )

        temp_dir = Path(tempfile.mkdtemp(prefix="curatore_extract_"))
        temp_input_file = temp_dir / asset.original_filename

        file_data = minio.get_object(asset.raw_bucket, asset.raw_object_key)
        temp_input_file.write_bytes(file_data.getvalue())

        logger.info(f"Downloaded {asset.original_filename} to {temp_input_file}")

        await run_log_service.log_event(
            session=session,
            run_id=run_id,
            level="INFO",
            event_type="progress",
            message="Sending to document service for extraction...",
        )

        return {
            "phase": "ready_for_extraction",
            "temp_file_path": str(temp_input_file),
            "temp_dir": str(temp_dir),
            "start_time": start_time,
            "is_restart": is_restart,
        }

    async def finalize_extraction(
        self,
        session: AsyncSession,
        asset_id: UUID,
        run_id: UUID,
        extraction_id: UUID,
        doc_result: DocumentServiceResponse,
        start_time: float,
    ) -> Dict[str, Any]:
        """
        Phase 3: Save extraction results.

        Re-reads models from the database (may be a different session than
        prepare_extraction used), processes the doc_result, uploads markdown
        to object storage, and updates all statuses.

        Args:
            session: Database session (fresh, not the same as Phase 1)
            asset_id: Asset UUID
            run_id: Run UUID
            extraction_id: ExtractionResult UUID
            doc_result: Response from the document service
            start_time: time.time() from Phase 1 start

        Returns:
            Dict with extraction result details
        """
        # Re-read models from this (fresh) session
        asset = await asset_service.get_asset(session, asset_id)
        run = await run_service.get_run(session, run_id)
        extraction = await extraction_result_service.get_extraction_result(session, extraction_id)

        if not asset or not run or not extraction:
            error = f"Asset, Run, or Extraction not found in finalize: {asset_id}, {run_id}, {extraction_id}"
            logger.error(error)
            raise ValueError(error)

        if not doc_result.content_markdown:
            raise ValueError("Extraction produced no markdown content")

        markdown_content = doc_result.content_markdown
        # Sanitize null bytes — some PDF engines emit \x00 which is
        # invalid in PostgreSQL TEXT columns and breaks search indexing.
        if "\x00" in markdown_content:
            markdown_content = markdown_content.replace("\x00", "")
            logger.info(f"Stripped null bytes from extracted content for asset {asset_id}")

        # Derive engine info from document service response
        triage_engine = doc_result.triage_engine or doc_result.method or "unknown"
        engine_name = doc_result.method or triage_engine
        warnings = []

        await run_log_service.log_event(
            session=session,
            run_id=run_id,
            level="INFO",
            event_type="triage",
            message=f"Document service selected engine: {triage_engine} (complexity={doc_result.triage_complexity})",
            context={
                "triage_engine": doc_result.triage_engine,
                "triage_complexity": doc_result.triage_complexity,
                "triage_needs_ocr": doc_result.triage_needs_ocr,
                "triage_needs_layout": doc_result.triage_needs_layout,
                "triage_duration_ms": doc_result.triage_duration_ms,
                "triage_reason": doc_result.triage_reason,
                "method": doc_result.method,
                "ocr_used": doc_result.ocr_used,
                "page_count": doc_result.page_count,
            },
        )

        await run_log_service.log_event(
            session=session,
            run_id=run_id,
            level="INFO",
            event_type="progress",
            message=f"Extraction complete using {engine_name}",
            context={
                "engine": triage_engine,
                "engine_name": engine_name,
                "content_length": len(markdown_content),
            },
        )

        # Upload extracted markdown to object storage
        minio = get_minio_service()
        if not minio:
            raise RuntimeError("MinIO service unavailable during finalize")

        await run_log_service.log_event(
            session=session,
            run_id=run_id,
            level="INFO",
            event_type="progress",
            message="Uploading extracted content...",
        )

        extracted_bucket = settings.minio_bucket_processed
        extracted_key = self._get_extracted_path(asset)

        minio.put_object(
            bucket=extracted_bucket,
            key=extracted_key,
            data=BytesIO(markdown_content.encode('utf-8')),
            length=len(markdown_content.encode('utf-8')),
            content_type="text/markdown",
        )

        logger.info(f"Uploaded extracted content to {extracted_bucket}/{extracted_key}")

        # Record successful extraction
        extraction_time = time.time() - start_time

        await extraction_result_service.record_extraction_success(
            session=session,
            extraction_id=extraction_id,
            bucket=extracted_bucket,
            key=extracted_key,
            extraction_time_seconds=extraction_time,
            warnings=warnings,
        )

        # Update extractor_version with engine info for Job Manager display
        extraction.extractor_version = engine_name

        # =====================================================================
        # TRIAGE-BASED EXTRACTION TIER AND METADATA
        # =====================================================================
        extraction.triage_engine = doc_result.triage_engine
        extraction.triage_needs_ocr = doc_result.triage_needs_ocr
        extraction.triage_needs_layout = doc_result.triage_needs_layout
        extraction.triage_complexity = doc_result.triage_complexity
        extraction.triage_duration_ms = doc_result.triage_duration_ms

        # Set extraction_tier based on triage engine
        if doc_result.triage_engine == "docling":
            extraction.extraction_tier = "enhanced"
            asset.extraction_tier = "enhanced"
        else:
            extraction.extraction_tier = "basic"
            asset.extraction_tier = "basic"

        # Write extraction_tier to source_metadata for search indexing
        sm = dict(asset.source_metadata or {})
        file_ns = dict(sm.get("file", {}))
        file_ns["extraction_tier"] = asset.extraction_tier
        sm["file"] = file_ns
        asset.source_metadata = sm

        # Update Asset status to ready
        await asset_service.update_asset_status(session, asset_id, "ready")

        # Complete the run
        await run_service.complete_run(
            session=session,
            run_id=run_id,
            results_summary={
                "status": "success",
                "extraction_time_seconds": extraction_time,
                "markdown_length": len(markdown_content),
                "warnings_count": len(warnings),
                "engine": triage_engine,
                "engine_name": engine_name,
            },
        )

        await run_log_service.log_summary(
            session=session,
            run_id=run_id,
            message=f"Extraction completed successfully in {extraction_time:.2f}s",
            context={
                "extraction_time_seconds": extraction_time,
                "markdown_length": len(markdown_content),
                "extracted_bucket": extracted_bucket,
                "extracted_key": extracted_key,
                "warnings": warnings,
            },
        )

        logger.info(
            f"Extraction successful for asset {asset_id}: "
            f"run={run_id}, time={extraction_time:.2f}s, engine={triage_engine}"
        )

        # Trigger search indexing if enabled
        if _is_search_enabled():
            try:
                await run_log_service.log_event(
                    session=session,
                    run_id=run_id,
                    level="INFO",
                    event_type="progress",
                    message="Queueing asset for search indexing...",
                )

                from ..tasks import index_asset_task
                index_asset_task.delay(asset_id=str(asset_id))

                logger.info(f"Queued asset {asset_id} for search indexing")
            except Exception as e:
                # Don't fail extraction if indexing queue fails
                logger.warning(f"Failed to queue asset {asset_id} for indexing: {e}")

        # Emit event for completed extraction
        try:
            from ..shared.event_service import event_service
            await event_service.emit(
                session=session,
                event_name="asset.extraction_completed",
                organization_id=asset.organization_id,
                payload={
                    "asset_id": str(asset_id),
                    "run_id": str(run_id),
                    "extraction_id": str(extraction_id),
                    "filename": asset.original_filename,
                    "source_type": asset.source_type,
                    "engine": triage_engine,
                    "extraction_tier": extraction.extraction_tier,
                    "markdown_length": len(markdown_content),
                },
                source_run_id=run_id,
            )
        except Exception as e:
            # Don't fail extraction if event emission fails
            logger.warning(f"Failed to emit asset.extraction_completed event: {e}")

        # Notify group service if this run is part of a parent-child group
        try:
            if run.group_id:
                from ..shared.run_group_service import run_group_service
                await run_group_service.child_completed(session, run_id)
                logger.debug(f"Notified group service of completed extraction for run {run_id}")
        except Exception as e:
            # Don't fail extraction if group notification fails
            logger.warning(f"Failed to notify group service of completion: {e}")

        return {
            "status": "success",
            "asset_id": str(asset_id),
            "run_id": str(run_id),
            "extraction_id": str(extraction_id),
            "extracted_bucket": extracted_bucket,
            "extracted_key": extracted_key,
            "extraction_time_seconds": extraction_time,
            "markdown_length": len(markdown_content),
            "warnings": warnings,
            "triage_engine": triage_engine,
            "triage_complexity": doc_result.triage_complexity,
        }

    async def execute_extraction(
        self,
        session: AsyncSession,
        asset_id: UUID,
        run_id: UUID,
        extraction_id: UUID,
    ) -> Dict[str, Any]:
        """
        Execute extraction for an Asset (backward-compatible wrapper).

        Calls prepare_extraction → document service → finalize_extraction
        within a single session. For production use in Celery tasks, prefer
        calling the phases separately with independent sessions to avoid
        holding a DB connection during the long document service call.

        Args:
            session: Database session
            asset_id: Asset UUID to extract
            run_id: Run UUID tracking this extraction
            extraction_id: ExtractionResult UUID to update

        Returns:
            Dict with extraction result details
        """
        prep = await self.prepare_extraction(session, asset_id, run_id, extraction_id)

        if prep.get("phase") == "early_return":
            return prep["result"]

        temp_dir = prep.get("temp_dir")
        try:
            doc_result = await document_service_adapter.extract(
                file_path=Path(prep["temp_file_path"]),
                request_id=str(run_id),
            )

            return await self.finalize_extraction(
                session, asset_id, run_id, extraction_id,
                doc_result, prep["start_time"],
            )

        except Exception as e:
            error_message = str(e)
            logger.error(f"Extraction failed for asset {asset_id}: {error_message}", exc_info=True)

            await self._fail_extraction(
                session=session,
                run_id=run_id,
                extraction_id=extraction_id,
                asset_id=asset_id,
                error_message=error_message,
            )

            # Re-raise DocumentServiceError connectivity errors for Celery retry
            if isinstance(e, DocumentServiceError) and e.status_code in (502, 503, 504):
                raise

            return {
                "status": "failed",
                "asset_id": str(asset_id),
                "run_id": str(run_id),
                "extraction_id": str(extraction_id),
                "error": error_message,
            }

        finally:
            if temp_dir:
                import shutil
                temp_dir_path = Path(temp_dir) if isinstance(temp_dir, str) else temp_dir
                if temp_dir_path.exists():
                    try:
                        shutil.rmtree(temp_dir_path)
                    except Exception as e:
                        logger.warning(f"Failed to cleanup temp directory {temp_dir}: {e}")

    def _get_extracted_path(self, asset) -> str:
        """
        Generate the appropriate storage path for extracted content based on asset source type.

        Args:
            asset: Asset instance

        Returns:
            Storage path for extracted markdown

        Path structures by source type:
            - upload: {org}/uploads/{asset_id}/{filename}.md
            - web_scrape_document: {org}/scrape/{collection}/documents/{filename}.md
            - sharepoint: {org}/sharepoint/{site}/{path}/{filename}.md
            - other: {org}/uploads/{asset_id}/{filename}.md (fallback)
        """
        org_id = str(asset.organization_id)
        asset_id = str(asset.id)
        filename = asset.original_filename

        if asset.source_type == "web_scrape_document":
            source_meta = asset.source_metadata or {}
            collection_slug = source_meta.get("scrape", {}).get("collection_name", "unknown").lower().replace(" ", "-")
            return storage_paths.scrape_document(org_id, collection_slug, filename, extracted=True)

        elif asset.source_type == "sharepoint":
            source_meta = asset.source_metadata or {}

            sync_slug = None
            if asset.raw_object_key:
                parts = asset.raw_object_key.split("/")
                if len(parts) >= 3 and parts[1] == "sharepoint":
                    sync_slug = parts[2]

            if not sync_slug:
                sync_config_name = source_meta.get("sync", {}).get("config_name")
                if sync_config_name:
                    sync_slug = sync_config_name.lower().replace(" ", "-")

            if not sync_slug:
                sync_slug = "unknown"

            folder_path = source_meta.get("sharepoint", {}).get("path", "")
            return storage_paths.sharepoint_sync(org_id, sync_slug, folder_path, filename, extracted=True)

        elif asset.source_type == "sam_gov":
            source_meta = asset.source_metadata or {}
            sam_meta = source_meta.get("sam", {})
            agency = sam_meta.get("agency", "unknown-agency")
            bureau = sam_meta.get("bureau", agency)
            notice_id = sam_meta.get("solicitation_number") or sam_meta.get("notice_id", "unknown")

            if asset.raw_object_key and (notice_id == "unknown" or agency == "unknown-agency"):
                parts = asset.raw_object_key.split("/")
                if len(parts) >= 7 and parts[1] == "sam" and parts[4] == "solicitations":
                    agency = parts[2]
                    bureau = parts[3]
                    notice_id = parts[5]

            return storage_paths.sam_attachment(org_id, agency, bureau, notice_id, filename, extracted=True)

        else:
            return storage_paths.upload(org_id, asset_id, filename, extracted=True)

    async def _fail_extraction(
        self,
        session: AsyncSession,
        run_id: UUID,
        extraction_id: UUID,
        asset_id: UUID,
        error_message: str,
    ):
        """Handle extraction failure by updating all related records."""
        try:
            await extraction_result_service.record_extraction_failure(
                session=session,
                extraction_id=extraction_id,
                errors=[error_message],
            )
            await asset_service.update_asset_status(session, asset_id, "failed")
            await run_service.fail_run(session, run_id, error_message)

            await run_log_service.log_error(
                session=session,
                run_id=run_id,
                message=f"Extraction failed: {error_message}",
                context={
                    "asset_id": str(asset_id),
                    "extraction_id": str(extraction_id),
                    "error": error_message,
                },
            )

            try:
                run = await run_service.get_run(session, run_id)
                if run and run.group_id:
                    from ..shared.run_group_service import run_group_service
                    await run_group_service.child_failed(session, run_id, error_message)
                    logger.debug(f"Notified group service of failed extraction for run {run_id}")
            except Exception as group_e:
                logger.warning(f"Failed to notify group service of failure: {group_e}")

        except Exception as e:
            logger.error(f"Failed to record extraction failure: {e}", exc_info=True)

    def _check_file_type_support(
        self,
        file_extension: str,
    ) -> tuple[bool, set[str], str]:
        """Check if a file type is supported by the document service."""
        ext = file_extension.lower()
        if not ext.startswith('.'):
            ext = f'.{ext}'

        engine_name = "Document Service"
        is_supported = ext in SUPPORTED_EXTENSIONS

        return (is_supported, SUPPORTED_EXTENSIONS, engine_name)


# Singleton instance
extraction_orchestrator = ExtractionOrchestrator()
