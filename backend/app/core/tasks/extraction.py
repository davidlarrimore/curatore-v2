"""
Extraction-related Celery tasks for Curatore v2.

Handles document extraction, recovery, queue management, search indexing,
organization reindexing, and tiered extraction enhancement.
"""
import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

from celery import shared_task
from sqlalchemy import select, and_

from app.celery_app import app as celery_app
from app.core.shared.database_service import database_service
from app.core.ingestion.extraction_orchestrator import extraction_orchestrator
from app.core.shared.config_loader import config_loader
from app.config import settings


# Logger for tasks
logger = logging.getLogger("curatore.tasks")


def _is_search_enabled() -> bool:
    """Check if search is enabled via config.yml or environment variables."""
    search_config = config_loader.get_search_config()
    if search_config:
        return search_config.enabled
    return getattr(settings, "search_enabled", True)


# ============================================================================
# PHASE 0: EXTRACTION TASKS
# ============================================================================

@celery_app.task(bind=True, name="app.tasks.execute_extraction_task", autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 2})
def execute_extraction_task(
    self,
    asset_id: str,
    run_id: str,
    extraction_id: str,
) -> Dict[str, Any]:
    """
    Execute automatic extraction for an Asset (Phase 0).

    This task is triggered when an Asset is uploaded and orchestrates
    the extraction process using extraction_orchestrator.

    Args:
        asset_id: Asset UUID string
        run_id: Run UUID string
        extraction_id: ExtractionResult UUID string

    Returns:
        Dict with extraction result details
    """
    from uuid import UUID

    logger = logging.getLogger("curatore.tasks.extraction")
    logger.info(f"Starting extraction task for asset {asset_id}")

    try:
        result = asyncio.run(
            _execute_extraction_async(
                asset_id=UUID(asset_id),
                run_id=UUID(run_id),
                extraction_id=UUID(extraction_id),
            )
        )

        logger.info(f"Extraction completed for asset {asset_id}: {result.get('status')}")
        return result

    except Exception as e:
        logger.error(f"Extraction task failed for asset {asset_id}: {e}", exc_info=True)
        raise


async def _execute_extraction_async(
    asset_id,
    run_id,
    extraction_id,
) -> Dict[str, Any]:
    """
    Async wrapper for extraction orchestrator.

    Args:
        asset_id: Asset UUID
        run_id: Run UUID
        extraction_id: ExtractionResult UUID

    Returns:
        Dict with extraction result
    """
    from app.core.ops.heartbeat_service import heartbeat_service

    async with database_service.get_session() as session:
        # Use auto-heartbeat to signal we're alive every 30 seconds
        async with heartbeat_service.auto_heartbeat(session, run_id):
            result = await extraction_orchestrator.execute_extraction(
                session=session,
                asset_id=asset_id,
                run_id=run_id,
                extraction_id=extraction_id,
            )
            await session.commit()
            return result


# ============================================================================
# STARTUP RECOVERY TASK - Recover orphaned extractions after restart
# ============================================================================


@shared_task(bind=True, name="app.tasks.recover_orphaned_extractions")
def recover_orphaned_extractions(
    self,
    max_age_hours: int = 24,
    limit: int = 100,
) -> Dict[str, Any]:
    """
    Recover orphaned extractions after service restart.

    This task finds extractions that were in "pending" or "running" state
    when the service crashed/restarted and re-queues them for processing.

    Should be called:
    1. On worker startup (via celery signal)
    2. Periodically via scheduled task (as backup)

    Args:
        max_age_hours: Only recover extractions created within this window
        limit: Maximum number of extractions to recover per invocation

    Returns:
        Dict with recovery statistics
    """
    logger = logging.getLogger("curatore.tasks.recovery")
    logger.info(f"Starting orphaned extraction recovery (max_age={max_age_hours}h, limit={limit})")

    try:
        result = asyncio.run(
            _recover_orphaned_extractions_async(max_age_hours, limit)
        )
        logger.info(f"Recovery complete: {result}")
        return result
    except Exception as e:
        logger.error(f"Recovery failed: {e}", exc_info=True)
        return {"status": "failed", "error": str(e)}


async def _recover_orphaned_extractions_async(
    max_age_hours: int,
    limit: int,
) -> Dict[str, Any]:
    """
    Async implementation of orphaned extraction recovery.

    Enhanced to handle:
    1. Runs stuck in "submitted" where Celery task may be lost
    2. Runs stuck in "running" that exceeded timeout
    3. ExtractionResults stuck in pending/running

    Uses queue service for proper capacity management instead of direct Celery submission.
    """
    from app.core.database.models import Run, ExtractionResult, Asset
    from app.core.ingestion.extraction_queue_service import extraction_queue_service
    from sqlalchemy import or_

    logger = logging.getLogger("curatore.tasks.recovery")
    now = datetime.utcnow()
    cutoff = now - timedelta(hours=max_age_hours)

    # Different timeouts for different statuses
    submitted_stale_cutoff = now - timedelta(minutes=15)  # Submitted should move to running quickly
    running_stale_cutoff = now - timedelta(minutes=30)    # Running shouldn't take >30 min usually
    pending_stale_cutoff = now - timedelta(minutes=10)    # Pending should be picked up quickly

    recovered_runs = 0
    recovered_extractions = 0
    skipped = 0
    errors = []

    async with database_service.get_session() as session:
        # =========================================================================
        # Phase 1: Recover stuck RUNS (submitted/running status)
        # =========================================================================

        # Find runs stuck in "submitted" status (Celery task may be lost)
        submitted_runs = await session.execute(
            select(Run)
            .where(
                and_(
                    Run.run_type == "extraction",
                    Run.status == "submitted",
                    Run.submitted_to_celery_at < submitted_stale_cutoff,
                    Run.created_at >= cutoff,
                )
            )
            .limit(limit // 2)
        )
        stuck_submitted = list(submitted_runs.scalars().all())

        # Find runs stuck in "running" status (worker may have crashed)
        running_runs = await session.execute(
            select(Run)
            .where(
                and_(
                    Run.run_type == "extraction",
                    Run.status == "running",
                    Run.started_at < running_stale_cutoff,
                    Run.created_at >= cutoff,
                )
            )
            .limit(limit // 2)
        )
        stuck_running = list(running_runs.scalars().all())

        logger.info(
            f"Found {len(stuck_submitted)} stuck submitted runs, "
            f"{len(stuck_running)} stuck running runs"
        )

        # Reset stuck runs to "pending" so queue service will re-process them
        for run in stuck_submitted + stuck_running:
            try:
                old_status = run.status
                retry_count = (run.config or {}).get("recovery_retry_count", 0) + 1

                if retry_count > 3:
                    # Too many retries, mark as failed
                    run.status = "failed"
                    run.completed_at = now
                    run.error_message = f"Failed after {retry_count} recovery attempts (stuck in {old_status})"
                    logger.warning(f"Run {run.id} exceeded max recovery retries, marking as failed")

                    # Update associated asset
                    if run.input_asset_ids:
                        asset = await session.get(Asset, UUID(run.input_asset_ids[0]))
                        if asset and asset.status == "pending":
                            asset.status = "failed"
                else:
                    # Reset to pending for retry
                    run.status = "pending"
                    run.celery_task_id = None
                    run.submitted_to_celery_at = None
                    run.started_at = None
                    run.timeout_at = None
                    run.config = {
                        **(run.config or {}),
                        "recovery_retry_count": retry_count,
                        "last_recovery_at": now.isoformat(),
                        "recovery_reason": f"Stuck in {old_status} status",
                    }
                    logger.info(f"Reset run {run.id} from {old_status} to pending (retry #{retry_count})")
                    recovered_runs += 1

            except Exception as e:
                logger.error(f"Failed to recover run {run.id}: {e}")
                errors.append({"run_id": str(run.id), "error": str(e)})

        # =========================================================================
        # Phase 2: Recover orphaned EXTRACTION RESULTS (no active run)
        # =========================================================================

        result = await session.execute(
            select(ExtractionResult)
            .where(
                and_(
                    ExtractionResult.status.in_(["pending", "running"]),
                    ExtractionResult.created_at >= cutoff,
                    ExtractionResult.created_at < pending_stale_cutoff,
                )
            )
            .limit(limit)
        )
        orphaned_extractions = result.scalars().all()

        logger.info(f"Found {len(orphaned_extractions)} potentially orphaned extractions")

        for extraction in orphaned_extractions:
            try:
                # Get the associated asset
                asset = await session.get(Asset, extraction.asset_id)

                if not asset:
                    logger.warning(f"Asset not found for extraction {extraction.id}, skipping")
                    skipped += 1
                    continue

                # Check if asset already has a completed extraction
                if asset.status == "ready":
                    logger.debug(f"Asset {asset.id} already ready, marking extraction as completed")
                    extraction.status = "completed"
                    skipped += 1
                    continue

                # Check if the associated run is still active
                if extraction.run_id:
                    run = await session.get(Run, extraction.run_id)
                    if run and run.status in ("pending", "submitted", "running"):
                        # Run is still being processed, skip
                        skipped += 1
                        continue

                # Re-queue through queue service for proper capacity management
                logger.info(f"Re-queueing extraction for asset {asset.id} via queue service")

                run_result, ext_result, status = await extraction_queue_service.queue_extraction_for_asset(
                    session=session,
                    asset_id=asset.id,
                    skip_content_type_check=True,  # Already know this needs extraction
                )

                if status == "queued":
                    recovered_extractions += 1
                    # Mark old extraction as superseded
                    extraction.status = "failed"
                    extraction.error_message = "Superseded by recovery - original run was stuck"
                else:
                    skipped += 1

            except Exception as e:
                logger.error(f"Failed to recover extraction {extraction.id}: {e}")
                errors.append({"extraction_id": str(extraction.id), "error": str(e)})

        await session.commit()

    return {
        "status": "success",
        "recovered_runs": recovered_runs,
        "recovered_extractions": recovered_extractions,
        "skipped": skipped,
        "errors": len(errors),
        "error_details": errors[:10],
    }


# ============================================================================
# EXTRACTION QUEUE TASKS
# ============================================================================
# These tasks manage the database-backed extraction queue:
# - process_extraction_queue_task: Submit pending extractions to Celery
# - check_extraction_timeouts_task: Mark timed-out extractions


@shared_task(bind=True, name="app.tasks.process_extraction_queue_task")
def process_extraction_queue_task(self) -> Dict[str, Any]:
    """
    Submit queued extractions to Celery based on available capacity.

    This task runs every N seconds (default: 5) and:
    1. Counts currently active extractions (submitted + running)
    2. Calculates available slots (MAX_CONCURRENT - active)
    3. Submits pending runs ordered by priority, then created_at

    Returns:
        Dict with queue processing statistics
    """
    logger = logging.getLogger("curatore.tasks.queue")
    logger.debug("Processing extraction queue...")

    try:
        result = asyncio.run(_process_extraction_queue_async())
        if result.get("submitted", 0) > 0:
            logger.info(f"Submitted {result['submitted']} extractions to Celery")
        return result
    except Exception as e:
        logger.error(f"Error processing extraction queue: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}


async def _process_extraction_queue_async() -> Dict[str, Any]:
    """Async wrapper for extraction queue processing."""
    from app.core.ingestion.extraction_queue_service import extraction_queue_service

    async with database_service.get_session() as session:
        return await extraction_queue_service.process_queue(session)


@shared_task(bind=True, name="app.tasks.check_extraction_timeouts_task")
def check_extraction_timeouts_task(self) -> Dict[str, Any]:
    """
    Mark timed-out extractions with explicit 'timed_out' status.

    This task runs every minute and finds runs where:
    - status IN ('submitted', 'running')
    - timeout_at < now()

    These runs are marked as 'timed_out' (distinct from 'failed').

    Returns:
        Dict with timeout check statistics
    """
    logger = logging.getLogger("curatore.tasks.queue")
    logger.debug("Checking extraction timeouts...")

    try:
        result = asyncio.run(_check_extraction_timeouts_async())
        if result.get("count", 0) > 0:
            logger.warning(f"Marked {result['count']} extractions as timed_out")
        return result
    except Exception as e:
        logger.error(f"Error checking extraction timeouts: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}


async def _check_extraction_timeouts_async() -> Dict[str, Any]:
    """Async wrapper for extraction timeout checking."""
    from app.core.ingestion.extraction_queue_service import extraction_queue_service

    async with database_service.get_session() as session:
        return await extraction_queue_service.check_timeouts(session)


# ============================================================================
# SEARCH INDEXING TASKS
# ============================================================================


@celery_app.task(bind=True, name="app.tasks.index_asset_task", autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 2})
def index_asset_task(
    self,
    asset_id: str,
) -> Dict[str, Any]:
    """
    Index an asset to PostgreSQL search_chunks after extraction.

    This task is triggered when an asset's extraction completes successfully.
    It downloads the extracted markdown from MinIO, chunks it, generates
    embeddings, and indexes to PostgreSQL for hybrid full-text + semantic search.

    Args:
        asset_id: Asset UUID string

    Returns:
        Dict with indexing result:
        {
            "asset_id": str,
            "status": "indexed" | "skipped" | "failed",
            "message": str
        }
    """
    from uuid import UUID

    logger = logging.getLogger("curatore.tasks.indexing")

    # Check if search is enabled
    if not _is_search_enabled():
        logger.debug(f"Search disabled, skipping index for asset {asset_id}")
        return {
            "asset_id": asset_id,
            "status": "skipped",
            "message": "Search is disabled",
        }

    logger.info(f"Starting index task for asset {asset_id}")

    try:
        result = asyncio.run(_index_asset_async(UUID(asset_id)))

        if result:
            logger.info(f"Indexed asset {asset_id} to search")
            return {
                "asset_id": asset_id,
                "status": "indexed",
                "message": "Successfully indexed to search",
            }
        else:
            logger.warning(f"Failed to index asset {asset_id}")
            return {
                "asset_id": asset_id,
                "status": "failed",
                "message": "Indexing returned False",
            }

    except Exception as e:
        logger.error(f"Index task failed for asset {asset_id}: {e}", exc_info=True)
        raise


async def _index_asset_async(asset_id) -> bool:
    """
    Async wrapper for index service.

    Args:
        asset_id: Asset UUID

    Returns:
        True if indexed successfully
    """
    from app.core.search.pg_index_service import pg_index_service

    async with database_service.get_session() as session:
        return await pg_index_service.index_asset(session, asset_id)


@shared_task(bind=True, name="app.tasks.reindex_organization_task", autoretry_for=(), retry_kwargs={"max_retries": 0})
def reindex_organization_task(
    self,
    organization_id: str,
    batch_size: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Reindex all assets for an organization.

    This task is triggered manually by admins to rebuild the search index
    for an organization. Useful for migrations and recovery.

    Args:
        organization_id: Organization UUID string
        batch_size: Optional batch size for bulk indexing

    Returns:
        Dict with reindex statistics:
        {
            "status": "completed" | "disabled" | "failed",
            "total": int,
            "indexed": int,
            "failed": int,
            "errors": list
        }
    """
    from uuid import UUID

    logger = logging.getLogger("curatore.tasks.indexing")

    # Check if search is enabled
    if not _is_search_enabled():
        logger.info("Search disabled, skipping reindex")
        return {
            "status": "disabled",
            "message": "Search is disabled",
            "total": 0,
            "indexed": 0,
            "failed": 0,
        }

    logger.info(f"Starting reindex task for organization {organization_id}")

    try:
        result = asyncio.run(
            _reindex_organization_async(UUID(organization_id), batch_size)
        )

        logger.info(
            f"Reindex completed for org {organization_id}: "
            f"{result.get('indexed', 0)}/{result.get('total', 0)} indexed"
        )
        return result

    except Exception as e:
        logger.error(f"Reindex task failed for org {organization_id}: {e}", exc_info=True)
        return {
            "status": "failed",
            "message": str(e),
            "total": 0,
            "indexed": 0,
            "failed": 0,
        }


async def _reindex_organization_async(
    organization_id,
    batch_size: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Async wrapper for organization reindex.

    Args:
        organization_id: Organization UUID
        batch_size: Optional batch size

    Returns:
        Dict with reindex results
    """
    from app.core.search.pg_index_service import pg_index_service

    async with database_service.get_session() as session:
        return await pg_index_service.reindex_organization(
            session, organization_id, batch_size or 50
        )


# ============================================================================
# TIERED EXTRACTION: ENHANCEMENT TASK (Phase 2)
# ============================================================================

# File types that benefit from Docling enhancement (structured documents)
ENHANCEMENT_ELIGIBLE_EXTENSIONS = {
    ".pdf", ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls"
}


def is_enhancement_eligible(filename: str) -> bool:
    """Check if file type is eligible for Docling enhancement."""
    from pathlib import Path
    ext = Path(filename).suffix.lower()
    return ext in ENHANCEMENT_ELIGIBLE_EXTENSIONS


@shared_task(bind=True, name="app.tasks.enhance_extraction_task", autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 2})
def enhance_extraction_task(
    self,
    asset_id: str,
    run_id: str,
    extraction_id: str,
    force: bool = False,
) -> Dict[str, Any]:
    """
    Background task to enhance extraction quality using Docling.

    This task runs after basic extraction completes successfully. It attempts
    to extract the same asset using Docling and compares results. If Docling
    produces significantly better output, the extraction is upgraded.

    Args:
        asset_id: Asset UUID string
        run_id: Run UUID string (for the enhancement run)
        extraction_id: ExtractionResult UUID string (for the enhancement result)
        force: If True, always replace even if Docling output is not better

    Returns:
        Dict with enhancement result details:
            - status: "enhanced", "skipped", "failed", "no_improvement"
            - basic_length: Length of basic extraction
            - enhanced_length: Length of Docling extraction
            - improvement_percent: Percentage improvement in content length
    """
    logger = logging.getLogger("curatore.tasks.enhancement")
    logger.info(f"Starting extraction enhancement for asset {asset_id}")

    try:
        result = asyncio.run(
            _enhance_extraction_async(
                asset_id=uuid.UUID(asset_id),
                run_id=uuid.UUID(run_id),
                extraction_id=uuid.UUID(extraction_id),
                force=force,
            )
        )

        logger.info(f"Enhancement completed for asset {asset_id}: {result.get('status')}")
        return result

    except Exception as e:
        logger.error(f"Enhancement task failed for asset {asset_id}: {e}", exc_info=True)
        raise


async def _enhance_extraction_async(
    asset_id,
    run_id,
    extraction_id,
    force: bool = False,
) -> Dict[str, Any]:
    """
    Async implementation of extraction enhancement.

    Enhancement logic:
    1. Get the basic extraction content
    2. Extract using Docling
    3. Compare results (length, structure)
    4. If Docling is significantly better (>20% more content), upgrade
    5. Update asset.extraction_tier to "enhanced"
    """
    from io import BytesIO
    from pathlib import Path

    from app.core.database.models import Asset, ExtractionResult, Run
    from app.core.shared.asset_service import asset_service
    from app.core.shared.run_service import run_service
    from app.core.ingestion.extraction_result_service import extraction_result_service
    from app.core.shared.run_log_service import run_log_service
    from app.core.storage.minio_service import get_minio_service
    from app.core.shared.document_service import document_service
    from app.core.storage.storage_path_service import storage_paths

    logger = logging.getLogger("curatore.tasks.enhancement")

    # NOTE: We no longer use character length comparison for enhancement decisions.
    # Docling produces better structured markdown (better headings, tables, formatting),
    # not necessarily more characters. If Docling extraction succeeds, we use it.

    async with database_service.get_session() as session:
        # Get models
        asset = await asset_service.get_asset(session, asset_id)
        run = await run_service.get_run(session, run_id)
        extraction = await extraction_result_service.get_extraction_result(session, extraction_id)

        if not asset or not run or not extraction:
            error = f"Asset, Run, or Extraction not found: {asset_id}, {run_id}, {extraction_id}"
            logger.error(error)
            return {"status": "failed", "error": error}

        # Skip if run is already in a terminal state (redelivered by Celery after restart)
        if run.status in ("completed", "failed", "timed_out", "cancelled"):
            logger.info(
                f"Enhancement run {run_id} already in terminal state '{run.status}', skipping"
            )
            return {
                "status": f"already_{run.status}",
                "asset_id": str(asset_id),
                "run_id": str(run_id),
                "message": f"Run was already {run.status} (task re-delivered after restart)",
            }

        # Skip if already enhanced
        if asset.extraction_tier == "enhanced" and not force:
            logger.info(f"Asset {asset_id} already enhanced, skipping")
            return {"status": "skipped", "reason": "already_enhanced"}

        # Get basic extraction content for comparison
        minio = get_minio_service()
        if not minio:
            return {"status": "failed", "error": "MinIO service unavailable"}

        # Find the latest successful basic extraction
        from sqlalchemy import select, and_
        basic_extraction_result = await session.execute(
            select(ExtractionResult)
            .where(and_(
                ExtractionResult.asset_id == asset_id,
                ExtractionResult.status == "completed",
                ExtractionResult.extraction_tier == "basic",
            ))
            .order_by(ExtractionResult.created_at.desc())
            .limit(1)
        )
        basic_extraction = basic_extraction_result.scalar_one_or_none()

        if not basic_extraction:
            return {"status": "skipped", "reason": "no_basic_extraction"}

        # Get basic extraction content
        try:
            basic_content_io = minio.get_object(
                basic_extraction.extracted_bucket,
                basic_extraction.extracted_object_key
            )
            basic_content = basic_content_io.getvalue().decode('utf-8')
            basic_length = len(basic_content)
        except Exception as e:
            logger.error(f"Failed to read basic extraction: {e}")
            return {"status": "failed", "error": f"Cannot read basic extraction: {e}"}

        # Start the enhancement run
        await run_service.start_run(session, run_id)
        await extraction_result_service.update_extraction_status(session, extraction_id, "running")

        await run_log_service.log_event(
            session=session,
            run_id=run_id,
            level="INFO",
            event_type="progress",
            message=f"Starting Docling enhancement for {asset.original_filename}",
            context={
                "asset_id": str(asset_id),
                "basic_length": basic_length,
            },
        )

        # Download asset to temp file for Docling processing
        import tempfile
        import shutil
        import time

        temp_dir = Path(tempfile.mkdtemp(prefix="curatore_enhance_"))
        temp_input_file = temp_dir / asset.original_filename

        try:
            file_data = minio.get_object(asset.raw_bucket, asset.raw_object_key)
            temp_input_file.write_bytes(file_data.getvalue())

            # Extract using Docling specifically
            # Find the first enabled Docling engine from config
            start_time = time.time()

            try:
                # Get enabled Docling engine name from config
                docling_engine_name = None
                extraction_config = config_loader.get_extraction_config()
                if extraction_config:
                    engines = getattr(extraction_config, 'engines', [])
                    for engine in engines:
                        if hasattr(engine, 'engine_type') and engine.engine_type == 'docling':
                            if hasattr(engine, 'enabled') and engine.enabled:
                                docling_engine_name = engine.name
                                break

                if not docling_engine_name:
                    logger.warning(f"No enabled Docling engine found in config, skipping enhancement")
                    await extraction_result_service.record_extraction_failure(
                        session=session,
                        extraction_id=extraction_id,
                        errors=["No Docling engine configured for enhancement"],
                    )
                    await run_service.fail_run(session, run_id, "No Docling engine configured")
                    await session.commit()
                    return {"status": "failed", "error": "No Docling engine configured"}

                enhanced_content = await document_service._extract_content(
                    temp_input_file,
                    engine=docling_engine_name,  # Use actual Docling engine name from config
                )
                enhanced_length = len(enhanced_content) if enhanced_content else 0
            except Exception as e:
                logger.warning(f"Docling extraction failed: {e}")
                await run_log_service.log_event(
                    session=session,
                    run_id=run_id,
                    level="WARN",
                    event_type="error",
                    message=f"Docling extraction failed: {e}",
                )
                await extraction_result_service.record_extraction_failure(
                    session=session,
                    extraction_id=extraction_id,
                    errors=[str(e)],
                )
                await run_service.fail_run(session, run_id, str(e))
                await session.commit()
                return {"status": "failed", "error": str(e)}

            extraction_time = time.time() - start_time

            # Log extraction details (informational only - not used for decision)
            await run_log_service.log_event(
                session=session,
                run_id=run_id,
                level="INFO",
                event_type="progress",
                message=f"Docling extraction complete: basic={basic_length} chars, docling={enhanced_length} chars",
                context={
                    "basic_length": basic_length,
                    "enhanced_length": enhanced_length,
                    "extraction_time_seconds": extraction_time,
                },
            )

            # Always use Docling output if extraction succeeded.
            # Docling produces better structured markdown (headings, tables, formatting),
            # regardless of character count.
            if enhanced_content:
                # Upload enhanced content
                extracted_bucket = settings.minio_bucket_processed
                extracted_key = storage_paths.upload(
                    str(asset.organization_id),
                    str(asset_id),
                    asset.original_filename,
                    extracted=True
                )

                minio.put_object(
                    bucket=extracted_bucket,
                    key=extracted_key,
                    data=BytesIO(enhanced_content.encode('utf-8')),
                    length=len(enhanced_content.encode('utf-8')),
                    content_type="text/markdown",
                )

                # Record successful enhancement
                await extraction_result_service.record_extraction_success(
                    session=session,
                    extraction_id=extraction_id,
                    bucket=extracted_bucket,
                    key=extracted_key,
                    extraction_time_seconds=extraction_time,
                    warnings=[],
                )

                # Update extraction tier on the extraction result
                extraction.extraction_tier = "enhanced"

                # Update asset's extraction tier
                asset.extraction_tier = "enhanced"

                # Complete the run
                await run_service.complete_run(
                    session=session,
                    run_id=run_id,
                    results_summary={
                        "status": "enhanced",
                        "basic_length": basic_length,
                        "enhanced_length": enhanced_length,
                        "engine": "docling",
                    },
                )

                await run_log_service.log_summary(
                    session=session,
                    run_id=run_id,
                    message="Enhancement successful: upgraded to Docling extraction",
                    context={
                        "basic_length": basic_length,
                        "enhanced_length": enhanced_length,
                        "engine": "docling",
                    },
                )

                await session.commit()

                logger.info(f"Asset {asset_id} enhanced with Docling extraction")

                # Re-index the asset with enhanced content
                from app.core.shared.config_loader import config_loader as cfg_loader
                search_config = cfg_loader.get_search_config()
                search_enabled = search_config.enabled if search_config else getattr(settings, "search_enabled", True)

                if search_enabled:
                    try:
                        index_asset_task.delay(asset_id=str(asset_id))
                        logger.info(f"Queued re-indexing for enhanced asset {asset_id}")
                    except Exception as e:
                        # Don't fail enhancement if indexing queue fails
                        logger.warning(f"Failed to queue re-indexing for asset {asset_id}: {e}")

                return {
                    "status": "enhanced",
                    "basic_length": basic_length,
                    "enhanced_length": enhanced_length,
                    "engine": "docling",
                }

            else:
                # Docling returned empty content - this is a failure case
                await extraction_result_service.record_extraction_failure(
                    session=session,
                    extraction_id=extraction_id,
                    errors=["Docling extraction returned empty content"],
                )

                await run_service.fail_run(
                    session=session,
                    run_id=run_id,
                    error="Docling extraction returned empty content",
                )

                await run_log_service.log_event(
                    session=session,
                    run_id=run_id,
                    level="ERROR",
                    event_type="error",
                    message="Docling extraction returned empty content",
                )

                await session.commit()

                return {
                    "status": "failed",
                    "error": "Docling extraction returned empty content",
                }

        finally:
            # Cleanup temp directory
            if temp_dir.exists():
                try:
                    shutil.rmtree(temp_dir)
                except Exception as e:
                    logger.warning(f"Failed to cleanup temp directory: {e}")
