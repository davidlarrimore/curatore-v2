"""
Extraction Orchestrator Service for Automatic Extraction.

Orchestrates the automatic extraction process for Assets using the existing
document_service extraction logic, wrapped with Phase 0 Run/ExtractionResult
tracking. This makes extraction automatic platform infrastructure.

Usage:
    from app.services.extraction_orchestrator import extraction_orchestrator

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

from ..database.models import Asset, Run, ExtractionResult
from ..services.asset_service import asset_service
from ..services.run_service import run_service
from ..services.extraction_result_service import extraction_result_service
from ..services.run_log_service import run_log_service
from ..services.minio_service import get_minio_service
from ..services.storage_path_service import storage_paths
from ..services.document_service import document_service
from ..models import OCRSettings, ProcessingOptions
from ..config import settings

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

        minio = get_minio_service()
        if not minio:
            error = "MinIO service unavailable"
            logger.error(error)
            await self._fail_extraction(session, run_id, extraction_id, asset_id, error)
            raise RuntimeError(error)

        temp_dir = None

        try:
            # Start the run
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

            # Extract using document_service
            await run_log_service.log_event(
                session=session,
                run_id=run_id,
                level="INFO",
                event_type="progress",
                message="Extracting content to markdown...",
            )

            # Call existing extraction logic
            extraction_result = await self._extract_content(
                file_path=temp_input_file,
                filename=asset.original_filename,
            )

            if not extraction_result or not extraction_result.get("markdown"):
                raise ValueError("Extraction produced no markdown content")

            markdown_content = extraction_result["markdown"]
            warnings = extraction_result.get("warnings", [])

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
                f"run={run_id}, time={extraction_time:.2f}s"
            )

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
            collection_slug = source_meta.get("collection_name", "unknown").lower().replace(" ", "-")
            return storage_paths.scrape_document(org_id, collection_slug, filename, extracted=True)

        elif asset.source_type == "sharepoint":
            # SharePoint files preserve folder structure
            source_meta = asset.source_metadata or {}
            site_name = source_meta.get("site_name", "unknown")
            folder_path = source_meta.get("folder_path", "")
            return storage_paths.sharepoint(org_id, site_name, folder_path, filename, extracted=True)

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
            Dict with markdown and warnings
        """
        try:
            # Use document_service's extraction logic
            # This calls either extraction-service or docling based on config
            # Pass None for engine to use the default from config.yml
            result = await document_service._extract_content(
                file_path,  # Pass Path object, not string
                engine=None,  # Use default engine from config
            )

            return {
                "markdown": result,
                "warnings": [],
            }

        except Exception as e:
            logger.error(f"Extraction failed: {e}")
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

        except Exception as e:
            logger.error(f"Failed to record extraction failure: {e}", exc_info=True)


# Singleton instance
extraction_orchestrator = ExtractionOrchestrator()
