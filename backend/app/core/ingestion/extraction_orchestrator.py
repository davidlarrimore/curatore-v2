"""
Extraction Orchestrator Service for Automatic Extraction.

Orchestrates the automatic extraction process for Assets using the existing
document_service extraction logic, wrapped with Phase 0 Run/ExtractionResult
tracking. This makes extraction automatic platform infrastructure.

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

import hashlib
import logging
import tempfile
import time
from io import BytesIO
from pathlib import Path
from typing import Optional, Dict, Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database.models import Asset, Run, ExtractionResult
from app.core.shared.asset_service import asset_service
from app.core.shared.run_service import run_service
from .extraction_result_service import extraction_result_service
from app.core.shared.run_log_service import run_log_service
from app.core.storage.minio_service import get_minio_service
from app.core.storage.storage_path_service import storage_paths
from app.core.shared.document_service import document_service
from app.core.shared.config_loader import config_loader
from .triage_service import triage_service, ExtractionPlan
from app.core.models import OCRSettings, ProcessingOptions
from app.config import settings
from .extraction import (
    ExtractionEngineFactory,
    ExtractionServiceEngine,
    DoclingEngine,
    FastPdfEngine,
)


class UnsupportedFileTypeError(Exception):
    """Exception raised when a file type is not supported by the configured extraction engine."""
    pass


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

    Wraps the existing document_service extraction logic with Phase 0
    Run/ExtractionResult tracking, structured logging, and Asset status
    management.
    """

    async def execute_extraction(
        self,
        session: AsyncSession,
        asset_id: UUID,
        run_id: UUID,
        extraction_id: UUID,
    ) -> Dict[str, Any]:
        """
        Execute extraction for an Asset.

        This is the main orchestration method that:
        1. Downloads asset from object storage
        2. Extracts to markdown using document_service
        3. Uploads result to object storage
        4. Updates Run, ExtractionResult, and Asset status
        5. Logs all steps via run_log_service

        Args:
            session: Database session
            asset_id: Asset UUID to extract
            run_id: Run UUID tracking this extraction
            extraction_id: ExtractionResult UUID to update

        Returns:
            Dict with extraction result details
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
        # This handles the case where a Celery task is re-delivered after restart
        # =====================================================================
        if extraction.status == "completed":
            logger.info(
                f"[Run {run_id}] Extraction already completed, skipping re-execution "
                f"(idempotency check)"
            )
            return {
                "status": "already_completed",
                "asset_id": str(asset_id),
                "run_id": str(run_id),
                "extraction_id": str(extraction_id),
                "message": "Extraction was already completed (task re-delivered after restart)",
            }

        if run.status == "completed":
            logger.info(
                f"[Run {run_id}] Run already completed, skipping re-execution"
            )
            return {
                "status": "already_completed",
                "asset_id": str(asset_id),
                "run_id": str(run_id),
                "extraction_id": str(extraction_id),
                "message": "Run was already completed (task re-delivered after restart)",
            }

        # Skip runs that are already in a terminal state (timed_out, failed, cancelled)
        # These can be redelivered by Celery after a restart but shouldn't be reprocessed
        if run.status in ("timed_out", "failed", "cancelled"):
            logger.info(
                f"[Run {run_id}] Run already in terminal state '{run.status}', skipping re-execution"
            )
            return {
                "status": f"already_{run.status}",
                "asset_id": str(asset_id),
                "run_id": str(run_id),
                "extraction_id": str(extraction_id),
                "message": f"Run was already {run.status} (task re-delivered after restart)",
            }

        # Handle restart scenario: if status is "running" but we're starting fresh,
        # this means the previous execution was interrupted (worker crash/restart)
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
        # FILE TYPE VALIDATION: Check if file type is supported before extraction
        # =====================================================================
        file_ext = Path(asset.original_filename).suffix.lower()
        is_supported, supported_formats, engine_name = await self._check_file_type_support(file_ext)

        if not is_supported:
            error_message = (
                f"Unsupported file type: '{file_ext}'. "
                f"The configured extraction engine ({engine_name}) supports: "
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
                "status": "unsupported_file_type",
                "asset_id": str(asset_id),
                "run_id": str(run_id),
                "extraction_id": str(extraction_id),
                "file_extension": file_ext,
                "supported_formats": list(supported_formats),
                "engine_name": engine_name,
                "error": error_message,
            }
        # =====================================================================

        temp_dir = None

        try:
            # Start the run (skip if resuming after restart - already running)
            if not is_restart:
                await run_service.start_run(session, run_id)
                await extraction_result_service.update_extraction_status(session, extraction_id, "running")

            # Phase 1: Get current version for logging
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
                    **version_info,  # Phase 1
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

            # =====================================================================
            # TRIAGE PHASE: Analyze document and select optimal extraction engine
            # =====================================================================
            await run_log_service.log_event(
                session=session,
                run_id=run_id,
                level="INFO",
                event_type="triage",
                message="Analyzing document to select extraction engine...",
            )

            triage_plan = await triage_service.triage(
                file_path=temp_input_file,
                mime_type=asset.content_type,
                docling_enabled=self._is_docling_enabled(),
            )

            await run_log_service.log_event(
                session=session,
                run_id=run_id,
                level="INFO",
                event_type="triage",
                message=f"Selected engine: {triage_plan.engine} (complexity={triage_plan.complexity})",
                context=triage_plan.to_dict(),
            )

            # =====================================================================
            # EXTRACTION PHASE: Use triage-selected engine
            # =====================================================================
            # Check for unsupported file type
            if triage_plan.engine == "unsupported":
                await run_log_service.log_event(
                    session=session,
                    run_id=run_id,
                    level="ERROR",
                    event_type="error",
                    message=f"Unsupported file type: {triage_plan.reason}",
                )
                raise ValueError(f"Unsupported file type: {triage_plan.reason}")

            await run_log_service.log_event(
                session=session,
                run_id=run_id,
                level="INFO",
                event_type="progress",
                message=f"Extracting with {triage_plan.engine}...",
            )

            # Extract using triage-selected engine
            # Use triage engine for all supported types (fast_pdf, docling, extraction-service)
            if triage_plan.engine in ("fast_pdf", "docling", "extraction-service"):
                extraction_result = await self._extract_with_triage_engine(
                    file_path=temp_input_file,
                    triage_plan=triage_plan,
                )
            else:
                # Fall back to existing extraction logic for unknown engines
                logger.warning(f"Unknown triage engine '{triage_plan.engine}', falling back to document_service")
                extraction_result = await self._extract_content(
                    file_path=temp_input_file,
                    filename=asset.original_filename,
                )

            if not extraction_result or not extraction_result.get("markdown"):
                raise ValueError("Extraction produced no markdown content")

            markdown_content = extraction_result["markdown"]
            warnings = extraction_result.get("warnings", [])
            extraction_info = extraction_result.get("extraction_info", {})

            # Log extraction completion with engine details
            engine_name = extraction_info.get("engine_name") or extraction_info.get("engine", "unknown")
            engine_type = extraction_info.get("engine", "unknown")
            engine_url = extraction_info.get("url", "")

            await run_log_service.log_event(
                session=session,
                run_id=run_id,
                level="INFO",
                event_type="progress",
                message=f"Extraction complete using {engine_name} ({engine_type})",
                context={
                    "engine": engine_type,
                    "engine_name": engine_name,
                    "engine_url": engine_url,
                    "content_length": len(markdown_content),
                    "extraction_ok": extraction_info.get("ok", True),
                },
            )

            # Upload extracted markdown to object storage
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
            extractor_version = f"{engine_name}" if engine_name != "unknown" else engine_type
            extraction.extractor_version = extractor_version

            # =====================================================================
            # TRIAGE-BASED EXTRACTION TIER AND METADATA
            # =====================================================================
            # Store triage information in extraction result
            extraction.triage_engine = triage_plan.engine
            extraction.triage_needs_ocr = triage_plan.needs_ocr
            extraction.triage_needs_layout = triage_plan.needs_layout
            extraction.triage_complexity = triage_plan.complexity
            extraction.triage_duration_ms = triage_plan.triage_duration_ms

            # Set extraction_tier based on triage engine
            # fast_pdf, extraction-service -> "basic"
            # docling -> "enhanced"
            if triage_plan.engine == "docling":
                extraction.extraction_tier = "enhanced"
                asset.extraction_tier = "enhanced"
            else:
                extraction.extraction_tier = "basic"
                asset.extraction_tier = "basic"

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
                    "engine": engine_type,
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
                f"run={run_id}, time={extraction_time:.2f}s, engine={triage_plan.engine}"
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

                    from ...tasks import index_asset_task
                    index_asset_task.delay(asset_id=str(asset_id))

                    logger.info(f"Queued asset {asset_id} for search indexing")
                except Exception as e:
                    # Don't fail extraction if indexing queue fails
                    logger.warning(f"Failed to queue asset {asset_id} for indexing: {e}")

            # Emit event for completed extraction
            try:
                from ..event_service import event_service
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
                        "engine": triage_plan.engine,
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
                    from ..run_group_service import run_group_service
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
                "triage_engine": triage_plan.engine,
                "triage_complexity": triage_plan.complexity,
            }

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

            return {
                "status": "failed",
                "asset_id": str(asset_id),
                "run_id": str(run_id),
                "extraction_id": str(extraction_id),
                "error": error_message,
            }

        finally:
            # Cleanup temp directory
            if temp_dir and temp_dir.exists():
                import shutil
                try:
                    shutil.rmtree(temp_dir)
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
            # Web scrape documents use collection-based paths
            source_meta = asset.source_metadata or {}
            collection_slug = source_meta.get("scrape", {}).get("collection_name", "unknown").lower().replace(" ", "-")
            return storage_paths.scrape_document(org_id, collection_slug, filename, extracted=True)

        elif asset.source_type == "sharepoint":
            # SharePoint Sync files use sync config slug
            # Try to extract the slug from the raw_object_key for consistency
            # Format: {org_id}/sharepoint/{sync_slug}/{relative_path}/{filename}
            source_meta = asset.source_metadata or {}

            # Extract sync slug from raw_object_key if available
            sync_slug = None
            if asset.raw_object_key:
                parts = asset.raw_object_key.split("/")
                # Expected: [org_id, "sharepoint", sync_slug, ...]
                if len(parts) >= 3 and parts[1] == "sharepoint":
                    sync_slug = parts[2]

            # Fall back to sync_config_name from metadata
            if not sync_slug:
                sync_config_name = source_meta.get("sync", {}).get("config_name")
                if sync_config_name:
                    sync_slug = sync_config_name.lower().replace(" ", "-")

            # Fall back to legacy site_name for old SharePoint imports
            if not sync_slug:
                sync_slug = "unknown"

            # Get relative path within the synced folder
            folder_path = source_meta.get("sharepoint", {}).get("path", "")

            return storage_paths.sharepoint_sync(org_id, sync_slug, folder_path, filename, extracted=True)

        elif asset.source_type == "sam_gov":
            # SAM.gov attachments preserve SAM folder structure
            # Format: {org_id}/sam/{agency}/{bureau}/solicitations/{notice_id}/attachments/{filename}
            source_meta = asset.source_metadata or {}

            # Extract info from metadata
            sam_meta = source_meta.get("sam", {})
            agency = sam_meta.get("agency", "unknown-agency")
            bureau = sam_meta.get("bureau", agency)  # Fall back to agency if no bureau
            notice_id = sam_meta.get("solicitation_number") or sam_meta.get("notice_id", "unknown")

            # Try to extract from raw_object_key if metadata is incomplete
            if asset.raw_object_key and (notice_id == "unknown" or agency == "unknown-agency"):
                # Format: {org_id}/sam/{agency}/{bureau}/solicitations/{notice_id}/attachments/{filename}
                parts = asset.raw_object_key.split("/")
                if len(parts) >= 7 and parts[1] == "sam" and parts[4] == "solicitations":
                    agency = parts[2]
                    bureau = parts[3]
                    notice_id = parts[5]

            return storage_paths.sam_attachment(org_id, agency, bureau, notice_id, filename, extracted=True)

        else:
            # Uploads and other sources use UUID-based paths
            return storage_paths.upload(org_id, asset_id, filename, extracted=True)

    async def _extract_content(
        self,
        file_path: Path,
        filename: str,
    ) -> Dict[str, Any]:
        """
        Extract content using document_service.

        This wraps the existing extraction logic.

        Args:
            file_path: Path to file on disk
            filename: Original filename

        Returns:
            Dict with markdown, warnings, and extraction_info
        """
        try:
            # Use document_service's extraction logic
            # This calls either extraction-service or docling based on config
            # Pass None for engine to use the default from config.yml
            result = await document_service._extract_content(
                file_path,  # Pass Path object, not string
                engine=None,  # Use default engine from config
            )

            # Capture extraction info from document_service for logging
            extraction_info = getattr(document_service, '_last_extraction_info', {})

            return {
                "markdown": result,
                "warnings": [],
                "extraction_info": extraction_info,
            }

        except Exception as e:
            # Capture extraction info even on failure
            extraction_info = getattr(document_service, '_last_extraction_info', {})
            logger.error(f"Extraction failed: {e}, extraction_info: {extraction_info}")
            raise

    async def _fail_extraction(
        self,
        session: AsyncSession,
        run_id: UUID,
        extraction_id: UUID,
        asset_id: UUID,
        error_message: str,
    ):
        """
        Handle extraction failure by updating all related records.

        Args:
            session: Database session
            run_id: Run UUID
            extraction_id: ExtractionResult UUID
            asset_id: Asset UUID
            error_message: Error description
        """
        try:
            # Record extraction failure
            await extraction_result_service.record_extraction_failure(
                session=session,
                extraction_id=extraction_id,
                errors=[error_message],
            )

            # Update Asset status to failed (extraction failed but visible)
            await asset_service.update_asset_status(session, asset_id, "failed")

            # Fail the run
            await run_service.fail_run(session, run_id, error_message)

            # Log error
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

            # Notify group service if this run is part of a parent-child group
            try:
                run = await run_service.get_run(session, run_id)
                if run and run.group_id:
                    from ..run_group_service import run_group_service
                    await run_group_service.child_failed(session, run_id, error_message)
                    logger.debug(f"Notified group service of failed extraction for run {run_id}")
            except Exception as group_e:
                logger.warning(f"Failed to notify group service of failure: {group_e}")

        except Exception as e:
            logger.error(f"Failed to record extraction failure: {e}", exc_info=True)

    async def _check_file_type_support(
        self,
        file_extension: str,
    ) -> tuple[bool, set[str], str]:
        """
        Check if a file type is supported by any of the triage-routable extraction engines.

        The triage system routes files to different engines based on type and complexity:
        - fast_pdf: Simple PDFs
        - extraction-service: Office files, text, emails
        - docling: Complex PDFs and large Office files

        This method checks against ALL supported formats, not just the default engine.

        Args:
            file_extension: File extension including the dot (e.g., '.pdf', '.xlsb')

        Returns:
            Tuple of (is_supported, supported_formats, engine_name)
            - is_supported: True if the file type is supported by any engine
            - supported_formats: Set of all supported file extensions
            - engine_name: Description of the triage system
        """
        # Normalize extension
        ext = file_extension.lower()
        if not ext.startswith('.'):
            ext = f'.{ext}'

        # All formats supported across all triage-routable engines
        # fast_pdf handles PDFs
        # extraction-service handles Office, text, emails
        # docling handles complex PDFs and large Office files
        supported_formats = {
            # PDFs (fast_pdf or docling)
            ".pdf",
            # Office documents (extraction-service or docling)
            ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".xlsb",
            # Text and markup (extraction-service)
            ".txt", ".md", ".csv", ".html", ".htm", ".xml", ".json",
            # Email files (extraction-service)
            ".msg", ".eml",
        }

        engine_name = "Triage System (fast_pdf, extraction-service, docling)"
        is_supported = ext in supported_formats

        return (is_supported, supported_formats, engine_name)

    def _is_docling_enabled(self) -> bool:
        """
        Check if Docling service is available for enhancement.

        Returns:
            True if Docling is configured and enabled
        """
        extraction_config = config_loader.get_extraction_config()
        if extraction_config:
            # Check if docling engine is listed and enabled
            engines = getattr(extraction_config, 'engines', [])
            for engine in engines:
                if hasattr(engine, 'engine_type') and engine.engine_type == 'docling':
                    if hasattr(engine, 'enabled') and engine.enabled:
                        return True
        # Fallback to settings
        docling_url = getattr(settings, 'docling_service_url', None)
        return bool(docling_url)

    def _get_docling_service_url(self) -> str:
        """
        Get the Docling service URL from config.

        Returns:
            Docling service URL or default
        """
        extraction_config = config_loader.get_extraction_config()
        if extraction_config:
            engines = getattr(extraction_config, 'engines', [])
            for engine in engines:
                if hasattr(engine, 'engine_type') and engine.engine_type == 'docling':
                    if hasattr(engine, 'service_url'):
                        return engine.service_url
        # Fallback to settings
        return getattr(settings, 'docling_service_url', 'http://docling:5001')

    def _get_extraction_service_url(self) -> str:
        """
        Get the extraction service URL from config.

        Returns:
            Extraction service URL or default
        """
        extraction_config = config_loader.get_extraction_config()
        if extraction_config:
            engines = getattr(extraction_config, 'engines', [])
            for engine in engines:
                if hasattr(engine, 'engine_type') and engine.engine_type == 'extraction-service':
                    if hasattr(engine, 'service_url'):
                        return engine.service_url
        # Fallback to settings
        return getattr(settings, 'extraction_service_url', 'http://extraction:8010')

    async def _extract_with_triage_engine(
        self,
        file_path: Path,
        triage_plan: ExtractionPlan,
    ) -> Dict[str, Any]:
        """
        Extract content using the triage-selected engine.

        Args:
            file_path: Path to file on disk
            triage_plan: Extraction plan from triage

        Returns:
            Dict with markdown, warnings, and extraction_info
        """
        engine_type = triage_plan.engine

        try:
            if engine_type == "fast_pdf":
                engine = FastPdfEngine(name="fast-pdf-triage")
                result = await engine.extract(file_path)
            elif engine_type == "extraction-service":
                # Use extraction-service (MarkItDown) for Office files, text files, etc.
                extraction_url = self._get_extraction_service_url()
                engine = ExtractionServiceEngine(
                    name="extraction-service-triage",
                    service_url=extraction_url,
                )
                result = await engine.extract(file_path)
            elif engine_type == "docling":
                # Use Docling service for complex documents
                docling_url = self._get_docling_service_url()
                logger.info(f"Using Docling engine for complex document: {file_path.name}")
                engine = DoclingEngine(
                    name="docling-triage",
                    service_url=docling_url,
                )
                result = await engine.extract(file_path)
                if result.success:
                    return {
                        "markdown": result.content,
                        "warnings": [],
                        "extraction_info": {
                            "engine": "docling",
                            "engine_name": "Docling",
                        },
                    }
                else:
                    # Docling failed, fall back to appropriate engine based on file type
                    # PDFs should use fast_pdf, other files use extraction-service
                    file_ext = file_path.suffix.lower()
                    if file_ext == ".pdf":
                        logger.warning(f"Docling extraction failed for {file_path.name}, falling back to fast_pdf")
                        fallback_engine = FastPdfEngine(name="fast-pdf-fallback")
                        result = await fallback_engine.extract(file_path)
                        fallback_name = "fast_pdf"
                        fallback_display = "Fast PDF (Fallback)"
                    else:
                        logger.warning(f"Docling extraction failed for {file_path.name}, falling back to extraction-service")
                        extraction_url = self._get_extraction_service_url()
                        fallback_engine = ExtractionServiceEngine(
                            name="extraction-service-fallback",
                            service_url=extraction_url,
                        )
                        result = await fallback_engine.extract(file_path)
                        fallback_name = "extraction-service"
                        fallback_display = "Extraction Service (Fallback)"

                    if result.success:
                        return {
                            "markdown": result.content,
                            "warnings": [f"Docling failed, used {fallback_name} fallback"],
                            "extraction_info": {
                                "engine": fallback_name,
                                "engine_name": fallback_display,
                            },
                        }
                    else:
                        raise Exception(f"Both Docling and {fallback_name} failed: {result.error}")
            else:
                # Unknown engine, fall back to document_service
                logger.warning(f"Unknown triage engine: {engine_type}, falling back to document_service")
                markdown = await document_service._extract_content(
                    file_path,
                    engine=None,
                )
                extraction_info = getattr(document_service, '_last_extraction_info', {})
                return {
                    "markdown": markdown,
                    "warnings": [],
                    "extraction_info": extraction_info,
                }

            # Handle extraction result from local engines
            if result.success:
                return {
                    "markdown": result.content,
                    "warnings": [],
                    "extraction_info": {
                        "engine": engine_type,
                        "engine_name": result.metadata.get("engine_name", engine_type),
                        "ok": True,
                        **(result.metadata or {}),
                    },
                }
            else:
                raise ValueError(f"Extraction failed: {result.error}")

        except Exception as e:
            logger.error(f"Triage engine extraction failed: {e}")
            raise


# Singleton instance
extraction_orchestrator = ExtractionOrchestrator()
