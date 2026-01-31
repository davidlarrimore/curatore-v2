"""
Upload Integration Service for Phase 0 Asset Creation.

Bridges the existing upload/Artifact system with the new Asset/Run models.
This service ensures that every upload automatically creates an Asset and
triggers extraction as platform infrastructure.

Usage:
    from app.services.upload_integration_service import upload_integration_service

    # After creating Artifact, create Asset
    asset = await upload_integration_service.create_asset_from_upload(
        session=session,
        artifact=artifact,
        uploader_id=user_id,
    )

    # Trigger automatic extraction
    run = await upload_integration_service.trigger_extraction(
        session=session,
        asset_id=asset.id,
    )
"""

import hashlib
import logging
from datetime import datetime
from typing import Optional, Tuple
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import Artifact, Asset, Run, ExtractionResult
from ..services.asset_service import asset_service
from ..services.run_service import run_service
from ..services.extraction_result_service import extraction_result_service
from ..services.run_log_service import run_log_service
from ..config import settings
from ..celery_app import app as celery_app

logger = logging.getLogger("curatore.upload_integration")


class UploadIntegrationService:
    """
    Service for integrating Phase 0 Asset model with existing upload workflows.

    Handles:
    - Creating Assets from uploaded Artifacts
    - Triggering automatic extraction Runs
    - Maintaining backward compatibility
    """

    async def create_asset_from_upload(
        self,
        session: AsyncSession,
        artifact: Artifact,
        uploader_id: Optional[UUID] = None,
        additional_metadata: Optional[dict] = None,
    ) -> Asset:
        """
        Create an Asset record from an uploaded Artifact.

        This is called after the Artifact has been created and the file
        has been uploaded to object storage. It creates the corresponding
        Asset record with provenance tracking.

        Args:
            session: Database session
            artifact: Artifact instance (already created)
            uploader_id: User ID who uploaded the file
            additional_metadata: Additional source metadata to store

        Returns:
            Created Asset instance
        """
        # Build source metadata with provenance
        source_metadata = {
            "artifact_id": str(artifact.id),
            "uploaded_at": datetime.utcnow().isoformat(),
            "upload_method": "api",
            **(additional_metadata or {}),
        }

        if uploader_id:
            source_metadata["uploader_id"] = str(uploader_id)

        # Create Asset
        asset = await asset_service.create_asset(
            session=session,
            organization_id=artifact.organization_id,
            source_type="upload",
            source_metadata=source_metadata,
            original_filename=artifact.original_filename,
            raw_bucket=artifact.bucket,
            raw_object_key=artifact.object_key,
            content_type=artifact.content_type,
            file_size=artifact.file_size,
            file_hash=artifact.file_hash,
            status="pending",  # Will become "ready" after successful extraction
            created_by=uploader_id,
        )

        logger.info(
            f"Created asset {asset.id} from artifact {artifact.id} "
            f"(document_id: {artifact.document_id})"
        )

        return asset

    # Content types that are already extracted inline (no separate extraction needed)
    INLINE_EXTRACTED_CONTENT_TYPES = {
        "text/html",
        "application/xhtml+xml",
    }

    async def trigger_extraction(
        self,
        session: AsyncSession,
        asset_id: UUID,
        extractor_version: Optional[str] = None,
    ) -> Optional[Tuple[Run, ExtractionResult]]:
        """
        Trigger automatic extraction for an Asset with content-type routing.

        Routes extraction based on content type:
        - HTML content: Skip (already extracted inline by Playwright during crawl)
        - Binary files (PDF, DOCX, etc.): Route to Docling/MarkItDown

        When extraction queue is enabled, this queues the extraction in the database
        rather than immediately submitting to Celery. The queue is processed by a
        periodic Celery beat task that throttles submissions based on capacity.

        Args:
            session: Database session
            asset_id: Asset UUID to extract
            extractor_version: Extractor version to use (defaults to config.yml default engine)

        Returns:
            Tuple of (Run, ExtractionResult) or None if skipped (HTML content)
        """
        from .extraction_queue_service import extraction_queue_service

        # Get asset
        asset = await asset_service.get_asset(session, asset_id)
        if not asset:
            raise ValueError(f"Asset {asset_id} not found")

        # Content-type routing: HTML is already extracted inline by Playwright
        if asset.content_type in self.INLINE_EXTRACTED_CONTENT_TYPES:
            logger.info(
                f"Skipping extraction for HTML asset {asset_id} "
                f"(content_type={asset.content_type}) - already extracted inline"
            )
            return None

        # Use extraction queue service if enabled
        if extraction_queue_service.queue_enabled:
            # Queue extraction (does NOT immediately submit to Celery)
            # Duplicate prevention is handled by queue_extraction()
            run, extraction, status = await extraction_queue_service.queue_extraction(
                session=session,
                asset_id=asset_id,
                organization_id=asset.organization_id,
                origin="system",
                priority=0,  # Normal priority for automatic extractions
                extractor_version=extractor_version,
            )

            if status == "already_pending":
                logger.info(
                    f"Extraction already pending for asset {asset_id}, "
                    f"returning existing run {run.id}"
                )
            else:
                logger.info(
                    f"Queued extraction for asset {asset_id}: "
                    f"run={run.id}, extraction={extraction.id}"
                )

            return (run, extraction)

        # Fallback: Direct Celery submission (queue disabled)
        # Cancel any pending/running extraction runs for this asset
        cancelled_count = await run_service.cancel_pending_runs_for_asset(
            session=session,
            asset_id=asset_id,
            run_type="extraction",
        )
        if cancelled_count > 0:
            logger.info(f"Cancelled {cancelled_count} previous extraction run(s) for asset {asset_id}")

        # Get extractor version from config if not provided
        if not extractor_version:
            from .config_loader import config_loader
            default_engine = config_loader.get_default_extraction_engine()
            if default_engine:
                extractor_version = default_engine.name
            else:
                extractor_version = "extraction-service"

        # Phase 1: Get current asset version
        current_version = await asset_service.get_current_asset_version(session, asset_id)
        asset_version_id = current_version.id if current_version else None

        # Create extraction Run
        run = await run_service.create_run(
            session=session,
            organization_id=asset.organization_id,
            run_type="extraction",
            origin="system",
            config={
                "extractor_version": extractor_version,
                "asset_id": str(asset_id),
                "asset_version_id": str(asset_version_id) if asset_version_id else None,  # Phase 1
                "version_number": asset.current_version_number,  # Phase 1
                "filename": asset.original_filename,
            },
            input_asset_ids=[str(asset_id)],
            created_by=None,  # System run
        )

        # Create extraction result (Phase 1: linked to version)
        extraction = await extraction_result_service.create_extraction_result(
            session=session,
            asset_id=asset_id,
            run_id=run.id,
            extractor_version=extractor_version,
            asset_version_id=asset_version_id,  # Phase 1
        )

        # Log extraction start
        await run_log_service.log_start(
            session=session,
            run_id=run.id,
            message=f"Automatic extraction queued for {asset.original_filename}",
            context={
                "asset_id": str(asset_id),
                "extraction_id": str(extraction.id),
                "filename": asset.original_filename,
                "file_size": asset.file_size,
            },
        )

        # Enqueue extraction task (async execution via Celery)
        from ..tasks import execute_extraction_task

        task = execute_extraction_task.apply_async(
            kwargs={
                "asset_id": str(asset_id),
                "run_id": str(run.id),
                "extraction_id": str(extraction.id),
            },
            queue="extraction",
        )

        logger.info(
            f"Triggered extraction for asset {asset_id}: "
            f"run={run.id}, extraction={extraction.id}, task={task.id}"
        )

        return (run, extraction)

    async def create_asset_and_trigger_extraction(
        self,
        session: AsyncSession,
        artifact: Artifact,
        uploader_id: Optional[UUID] = None,
        additional_metadata: Optional[dict] = None,
        extractor_version: Optional[str] = None,
    ) -> Tuple[Asset, Optional[Run], Optional[ExtractionResult]]:
        """
        Convenience method: Create Asset and trigger extraction in one call.

        This is the main entry point for integrating Phase 0 models with uploads.
        Note: For HTML content, extraction is skipped (inline extraction via Playwright).

        Args:
            session: Database session
            artifact: Uploaded artifact
            uploader_id: User who uploaded
            additional_metadata: Additional source metadata
            extractor_version: Extractor version

        Returns:
            Tuple of (Asset, Run, ExtractionResult) - Run and ExtractionResult may be None
            if extraction was skipped (HTML content already extracted inline)
        """
        # Create asset
        asset = await self.create_asset_from_upload(
            session=session,
            artifact=artifact,
            uploader_id=uploader_id,
            additional_metadata=additional_metadata,
        )

        # Trigger extraction (may return None for HTML content)
        result = await self.trigger_extraction(
            session=session,
            asset_id=asset.id,
            extractor_version=extractor_version,
        )

        if result:
            run, extraction = result
            return (asset, run, extraction)
        else:
            return (asset, None, None)

    async def link_asset_to_document_id(
        self,
        session: AsyncSession,
        asset_id: UUID,
        document_id: str,
    ) -> Asset:
        """
        Store document_id reference in Asset metadata for backward compatibility.

        This allows us to look up Assets by the legacy document_id string.

        Args:
            session: Database session
            asset_id: Asset UUID
            document_id: Legacy document ID string

        Returns:
            Updated Asset
        """
        return await asset_service.update_asset_metadata(
            session=session,
            asset_id=asset_id,
            source_metadata={"document_id": document_id},
        )

    async def trigger_reextraction(
        self,
        session: AsyncSession,
        asset_id: UUID,
        user_id: Optional[UUID] = None,
        extractor_version: Optional[str] = None,
    ) -> Tuple[Run, ExtractionResult]:
        """
        Trigger manual re-extraction for an existing Asset (Phase 1).

        Creates a new extraction Run with origin="user" to distinguish from
        automatic system extractions. Extracts the current version of the asset.

        When extraction queue is enabled, this queues the extraction with HIGH
        priority so user-requested re-extractions are processed before automatic ones.

        Args:
            session: Database session
            asset_id: Asset UUID to re-extract
            user_id: User requesting the re-extraction
            extractor_version: Extractor version to use (defaults to config.yml default engine)

        Returns:
            Tuple of (Run, ExtractionResult)

        Raises:
            ValueError: If asset not found or not in a re-extractable state
        """
        from .extraction_queue_service import extraction_queue_service

        # Get asset
        asset = await asset_service.get_asset(session, asset_id)
        if not asset:
            raise ValueError(f"Asset {asset_id} not found")

        # Check if asset is in a valid state for re-extraction
        if asset.status == "deleted":
            raise ValueError(f"Cannot re-extract deleted asset {asset_id}")

        # Cancel any pending/running extraction runs for this asset first
        cancelled_count = await run_service.cancel_pending_runs_for_asset(
            session=session,
            asset_id=asset_id,
            run_type="extraction",
        )
        if cancelled_count > 0:
            logger.info(f"Cancelled {cancelled_count} previous extraction run(s) for asset {asset_id}")

        # Use extraction queue service if enabled
        if extraction_queue_service.queue_enabled:
            # Queue extraction with HIGH priority (user-requested)
            run, extraction, status = await extraction_queue_service.queue_extraction(
                session=session,
                asset_id=asset_id,
                organization_id=asset.organization_id,
                origin="user",
                priority=1,  # High priority for user-requested re-extractions
                user_id=user_id,
                extractor_version=extractor_version,
            )

            logger.info(
                f"Queued manual re-extraction for asset {asset_id}: "
                f"run={run.id}, extraction={extraction.id}, priority=HIGH, user={user_id}"
            )

            return (run, extraction)

        # Fallback: Direct Celery submission (queue disabled)
        # Get extractor version from config if not provided
        if not extractor_version:
            from .config_loader import config_loader
            default_engine = config_loader.get_default_extraction_engine()
            if default_engine:
                extractor_version = default_engine.name
            else:
                extractor_version = "extraction-service"

        # Phase 1: Get current asset version
        current_version = await asset_service.get_current_asset_version(session, asset_id)
        asset_version_id = current_version.id if current_version else None

        # Create extraction Run (origin="user" for manual re-extraction)
        run = await run_service.create_run(
            session=session,
            organization_id=asset.organization_id,
            run_type="extraction",
            origin="user",  # Manual re-extraction
            config={
                "extractor_version": extractor_version,
                "asset_id": str(asset_id),
                "asset_version_id": str(asset_version_id) if asset_version_id else None,
                "version_number": asset.current_version_number,
                "filename": asset.original_filename,
                "manual_reextraction": True,  # Flag for tracking
            },
            input_asset_ids=[str(asset_id)],
            created_by=user_id,
        )

        # Create extraction result (Phase 1: linked to version)
        extraction = await extraction_result_service.create_extraction_result(
            session=session,
            asset_id=asset_id,
            run_id=run.id,
            extractor_version=extractor_version,
            asset_version_id=asset_version_id,
        )

        # Log re-extraction start
        await run_log_service.log_start(
            session=session,
            run_id=run.id,
            message=f"Manual re-extraction requested for {asset.original_filename} (version {asset.current_version_number or 1})",
            context={
                "asset_id": str(asset_id),
                "extraction_id": str(extraction.id),
                "filename": asset.original_filename,
                "file_size": asset.file_size,
                "version_number": asset.current_version_number,
                "requested_by": str(user_id) if user_id else "anonymous",
            },
        )

        # Enqueue extraction task (async execution via Celery)
        from ..tasks import execute_extraction_task

        task = execute_extraction_task.apply_async(
            kwargs={
                "asset_id": str(asset_id),
                "run_id": str(run.id),
                "extraction_id": str(extraction.id),
            },
            queue="extraction",
        )

        logger.info(
            f"Triggered manual re-extraction for asset {asset_id}: "
            f"run={run.id}, extraction={extraction.id}, task={task.id}, user={user_id}"
        )

        return (run, extraction)


# Singleton instance
upload_integration_service = UploadIntegrationService()
