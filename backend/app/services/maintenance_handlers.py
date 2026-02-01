"""
Maintenance task handlers for Curatore v2.

This module contains the actual implementation of maintenance tasks
that are scheduled and executed by the scheduled task system (Phase 5).

Each handler:
1. Receives a Run context for tracking
2. Performs its maintenance work
3. Logs progress via RunLogEvent
4. Returns a summary dict

Handlers:
- handle_job_cleanup: Delete expired jobs based on retention policies
- handle_orphan_detection: Find orphaned objects (assets without extraction, etc.)
- handle_retention_enforcement: Enforce data retention policies
- handle_health_report: Generate system health summary

Usage:
    from app.services.maintenance_handlers import MAINTENANCE_HANDLERS

    handler = MAINTENANCE_HANDLERS.get(task_type)
    if handler:
        result = await handler(session, run, config)
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import select, func, and_, or_, delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import (
    Asset,
    ExtractionResult,
    Artifact,
    Run,
    RunLogEvent,
    Organization,
    SharePointSyncConfig,
    SharePointSyncedDocument,
    AssetVersion,
    SamSearch,
)

logger = logging.getLogger("curatore.services.maintenance")


async def _log_event(
    session: AsyncSession,
    run_id: UUID,
    level: str,
    event_type: str,
    message: str,
    context: Optional[Dict[str, Any]] = None,
) -> None:
    """Helper to create a RunLogEvent."""
    event = RunLogEvent(
        id=uuid4(),
        run_id=run_id,
        level=level,
        event_type=event_type,
        message=message,
        context=context or {},
    )
    session.add(event)
    await session.flush()


# =============================================================================
# Handler: Job Cleanup (DEPRECATED)
# =============================================================================

async def handle_job_cleanup(
    session: AsyncSession,
    run: Run,
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """
    DEPRECATED: Job system has been removed in favor of Run-based tracking.

    This handler is kept as a no-op for backwards compatibility with
    existing scheduled tasks that may reference "gc.cleanup".

    Returns:
        Dict indicating deprecation
    """
    await _log_event(
        session, run.id, "INFO", "start",
        "Job cleanup task is deprecated - Job system has been removed",
        {"deprecated": True}
    )

    summary = {
        "status": "deprecated",
        "message": "Job system removed. Use Run-based tracking instead.",
        "deleted_jobs": 0,
        "deleted_documents": 0,
    }

    await _log_event(
        session, run.id, "INFO", "summary",
        "Job cleanup skipped (deprecated)",
        summary
    )

    return summary


# =============================================================================
# Handler: Orphan Detection
# =============================================================================

async def handle_orphan_detection(
    session: AsyncSession,
    run: Run,
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Find and fix orphaned objects in the system.

    Orphaned objects include:
    - Assets stuck in "pending" status without extraction runs
    - Assets without any extraction results
    - Artifacts without corresponding assets
    - Runs without results (stuck in pending/running)

    This handler both detects AND fixes certain issues:
    - Assets stuck in "pending" for >1 hour are marked as "failed"
    - Stuck runs (>24h) are marked as "failed"

    Args:
        session: Database session
        run: Run context for tracking
        config: Task configuration (auto_fix: bool = True)

    Returns:
        Dict with detection results:
        {
            "orphaned_assets": int,
            "stuck_pending_assets": int,
            "stuck_pending_fixed": int,
            "orphaned_artifacts": int,
            "stuck_runs": int,
            "stuck_runs_fixed": int,
            "details": {...}
        }
    """
    auto_fix = config.get("auto_fix", True)

    await _log_event(
        session, run.id, "INFO", "start",
        f"Starting orphan detection (auto_fix={auto_fix})",
        {"auto_fix": auto_fix}
    )

    orphaned_assets = 0
    stuck_pending_assets = 0
    stuck_pending_fixed = 0
    orphaned_artifacts = 0
    stuck_runs = 0
    stuck_runs_fixed = 0
    details = {
        "orphaned_asset_ids": [],
        "stuck_pending_asset_ids": [],
        "orphaned_artifact_ids": [],
        "stuck_run_ids": [],
    }

    try:
        # 1. Find assets stuck in "pending" status (older than 1 hour)
        # These are assets where extraction was never triggered or silently failed
        pending_cutoff = datetime.utcnow() - timedelta(hours=1)

        stuck_pending_result = await session.execute(
            select(Asset)
            .where(
                and_(
                    Asset.status == "pending",
                    Asset.created_at < pending_cutoff,
                )
            )
            .limit(500)
        )
        stuck_pending_list = list(stuck_pending_result.scalars().all())
        stuck_pending_assets = len(stuck_pending_list)
        details["stuck_pending_asset_ids"] = [str(a.id) for a in stuck_pending_list[:20]]

        if stuck_pending_assets > 0:
            await _log_event(
                session, run.id, "WARN", "progress",
                f"Found {stuck_pending_assets} assets stuck in 'pending' status",
                {"count": stuck_pending_assets, "sample_ids": details["stuck_pending_asset_ids"][:5]}
            )

            # Auto-fix: Re-trigger extraction for stuck pending assets
            if auto_fix:
                # Import here to avoid circular imports
                from .upload_integration_service import upload_integration_service

                for asset in stuck_pending_list:
                    try:
                        # Reset asset status and re-trigger extraction
                        asset.updated_at = datetime.utcnow()
                        # Track retry in metadata
                        retry_count = (asset.source_metadata or {}).get("extraction_retry_count", 0) + 1
                        asset.source_metadata = {
                            **(asset.source_metadata or {}),
                            "extraction_retry_count": retry_count,
                            "last_retry_at": datetime.utcnow().isoformat(),
                            "retry_reason": "Stuck in pending status - auto-retrying extraction",
                        }

                        # Only retry up to 3 times to avoid infinite loops
                        if retry_count <= 3:
                            await session.flush()
                            # Re-trigger extraction
                            await upload_integration_service.trigger_extraction(
                                session=session,
                                asset_id=asset.id,
                            )
                            stuck_pending_fixed += 1
                        else:
                            # Too many retries, mark as failed
                            asset.status = "failed"
                            asset.source_metadata = {
                                **asset.source_metadata,
                                "auto_failed_reason": f"Exceeded max retries ({retry_count})",
                                "auto_failed_at": datetime.utcnow().isoformat(),
                            }
                            logger.warning(f"Asset {asset.id} exceeded max retries, marking as failed")
                    except Exception as e:
                        logger.error(f"Failed to retry extraction for asset {asset.id}: {e}")
                        # Mark as failed if we can't retry
                        asset.status = "failed"
                        asset.source_metadata = {
                            **(asset.source_metadata or {}),
                            "auto_failed_reason": f"Retry failed: {str(e)}",
                            "auto_failed_at": datetime.utcnow().isoformat(),
                        }

                await session.flush()
                await _log_event(
                    session, run.id, "INFO", "fix",
                    f"Re-triggered extraction for {stuck_pending_fixed} stuck assets",
                    {"fixed_count": stuck_pending_fixed}
                )

        # 2. Find assets with "ready" status but no extraction results (older than 1 hour)
        extraction_cutoff = datetime.utcnow() - timedelta(hours=1)

        # Get all asset IDs that have extraction results
        assets_with_extraction = await session.execute(
            select(ExtractionResult.asset_id).distinct()
        )
        extraction_asset_ids = {row[0] for row in assets_with_extraction.fetchall()}

        # Find assets without extraction (excluding very recent ones)
        orphan_assets_result = await session.execute(
            select(Asset)
            .where(
                and_(
                    Asset.status == "ready",
                    Asset.created_at < extraction_cutoff,
                    ~Asset.id.in_(extraction_asset_ids) if extraction_asset_ids else True,
                )
            )
            .limit(100)
        )
        orphan_assets = list(orphan_assets_result.scalars().all())
        orphaned_assets = len(orphan_assets)
        details["orphaned_asset_ids"] = [str(a.id) for a in orphan_assets[:20]]

        if orphaned_assets > 0:
            await _log_event(
                session, run.id, "WARN", "progress",
                f"Found {orphaned_assets} 'ready' assets without extraction results",
                {"count": orphaned_assets}
            )

        # 3. Find stuck runs (pending/running for more than 24 hours)
        stuck_cutoff = datetime.utcnow() - timedelta(hours=24)
        stuck_runs_result = await session.execute(
            select(Run)
            .where(
                and_(
                    Run.status.in_(["pending", "running"]),
                    Run.created_at < stuck_cutoff,
                )
            )
            .limit(100)
        )
        stuck_run_list = list(stuck_runs_result.scalars().all())
        stuck_runs = len(stuck_run_list)
        details["stuck_run_ids"] = [str(r.id) for r in stuck_run_list[:20]]

        if stuck_runs > 0:
            await _log_event(
                session, run.id, "WARN", "progress",
                f"Found {stuck_runs} stuck runs (pending/running > 24h)",
                {"count": stuck_runs}
            )

            # Auto-fix: Mark stuck runs as "failed"
            if auto_fix:
                for stuck_run in stuck_run_list:
                    stuck_run.status = "failed"
                    stuck_run.completed_at = datetime.utcnow()
                    stuck_run.error_message = "Auto-failed: Run stuck in pending/running for >24 hours"
                    stuck_runs_fixed += 1

                await session.flush()
                await _log_event(
                    session, run.id, "INFO", "fix",
                    f"Marked {stuck_runs_fixed} stuck runs as 'failed'",
                    {"fixed_count": stuck_runs_fixed}
                )

        # 4. Find assets with missing raw files in object storage
        # These are assets that reference files that don't exist in MinIO/S3
        # Check ALL non-deleted assets (ready, pending, failed) to catch missing files
        missing_file_assets = 0
        missing_file_fixed = 0
        details["missing_file_asset_ids"] = []

        try:
            from .minio_service import get_minio_service
            minio_service = get_minio_service()

            # Check all assets that have storage references and aren't deleted
            # Include "ready" assets to catch files that were deleted after extraction
            assets_to_check_result = await session.execute(
                select(Asset)
                .where(
                    and_(
                        Asset.raw_bucket.isnot(None),
                        Asset.raw_object_key.isnot(None),
                        Asset.status.in_(["ready", "pending", "failed"]),
                    )
                )
                .limit(1000)  # Process up to 1000 assets per run
            )
            assets_to_check = list(assets_to_check_result.scalars().all())

            for asset in assets_to_check:
                try:
                    # Check if file exists in MinIO
                    exists = minio_service.object_exists(
                        bucket=asset.raw_bucket,
                        key=asset.raw_object_key,
                    )
                    if not exists:
                        missing_file_assets += 1
                        details["missing_file_asset_ids"].append(str(asset.id))

                        if auto_fix:
                            # Mark as failed with clear error message
                            asset.status = "failed"
                            asset.source_metadata = {
                                **(asset.source_metadata or {}),
                                "missing_file_detected_at": datetime.utcnow().isoformat(),
                                "missing_file_error": f"Raw file not found: {asset.raw_bucket}/{asset.raw_object_key}",
                            }
                            missing_file_fixed += 1
                except Exception as e:
                    logger.warning(f"Failed to check file existence for asset {asset.id}: {e}")

            if missing_file_assets > 0:
                await _log_event(
                    session, run.id, "WARN", "progress",
                    f"Found {missing_file_assets} assets with missing raw files in object storage",
                    {"count": missing_file_assets, "sample_ids": details["missing_file_asset_ids"][:5]}
                )

                if auto_fix and missing_file_fixed > 0:
                    await session.flush()
                    await _log_event(
                        session, run.id, "INFO", "fix",
                        f"Marked {missing_file_fixed} assets with missing files as 'failed'",
                        {"fixed_count": missing_file_fixed}
                    )

        except Exception as e:
            logger.warning(f"Missing file check failed (non-fatal): {e}")
            await _log_event(
                session, run.id, "WARN", "progress",
                f"Missing file check skipped: {str(e)}",
            )

        # 5. Find and clean up orphan SharePoint assets
        # These are assets with source_type='sharepoint' but their sync_config_id
        # no longer exists or is archived
        orphan_sharepoint_assets = 0
        orphan_sharepoint_fixed = 0
        details["orphan_sharepoint_asset_ids"] = []

        try:
            # Get all active (non-archived) sync config IDs
            configs_result = await session.execute(
                select(SharePointSyncConfig.id).where(
                    SharePointSyncConfig.status != "archived"
                )
            )
            active_config_ids = {str(c) for c in configs_result.scalars().all()}

            # Get SharePoint assets
            sp_assets_result = await session.execute(
                select(Asset)
                .where(
                    and_(
                        Asset.source_type == "sharepoint",
                        Asset.status != "deleted",
                    )
                )
                .limit(500)
            )
            sharepoint_assets = list(sp_assets_result.scalars().all())

            # Find orphan SharePoint assets
            orphan_sp_list = []
            for asset in sharepoint_assets:
                source_meta = asset.source_metadata or {}
                sync_config_id = source_meta.get("sync_config_id")

                # Asset is orphan if:
                # 1. No sync_config_id at all
                # 2. sync_config_id doesn't exist in active configs
                if not sync_config_id or sync_config_id not in active_config_ids:
                    orphan_sp_list.append(asset)

            orphan_sharepoint_assets = len(orphan_sp_list)
            details["orphan_sharepoint_asset_ids"] = [str(a.id) for a in orphan_sp_list[:20]]

            if orphan_sharepoint_assets > 0:
                await _log_event(
                    session, run.id, "WARN", "progress",
                    f"Found {orphan_sharepoint_assets} orphan SharePoint assets (sync config deleted/archived)",
                    {"count": orphan_sharepoint_assets, "sample_ids": details["orphan_sharepoint_asset_ids"][:5]}
                )

                # Auto-fix: Delete orphan SharePoint assets and their files
                if auto_fix:
                    from .minio_service import get_minio_service
                    from .pg_index_service import pg_index_service
                    minio = get_minio_service()

                    for asset in orphan_sp_list:
                        try:
                            # Remove from search index
                            try:
                                await pg_index_service.delete_asset_index(session, asset.organization_id, asset.id)
                            except:
                                pass

                            # Delete raw file from MinIO
                            if minio and asset.raw_bucket and asset.raw_object_key:
                                try:
                                    minio.delete_object(asset.raw_bucket, asset.raw_object_key)
                                except:
                                    pass

                            # Delete extracted files
                            extraction_result = await session.execute(
                                select(ExtractionResult).where(ExtractionResult.asset_id == asset.id)
                            )
                            extractions = list(extraction_result.scalars().all())
                            for extraction in extractions:
                                if minio and extraction.extracted_bucket and extraction.extracted_object_key:
                                    try:
                                        minio.delete_object(extraction.extracted_bucket, extraction.extracted_object_key)
                                    except:
                                        pass

                            # Delete extraction results
                            await session.execute(
                                delete(ExtractionResult).where(ExtractionResult.asset_id == asset.id)
                            )

                            # Delete asset versions
                            await session.execute(
                                delete(AssetVersion).where(AssetVersion.asset_id == asset.id)
                            )

                            # Delete any orphan synced document records
                            await session.execute(
                                delete(SharePointSyncedDocument).where(
                                    SharePointSyncedDocument.asset_id == asset.id
                                )
                            )

                            # Hard delete the asset
                            await session.execute(
                                delete(Asset).where(Asset.id == asset.id)
                            )
                            orphan_sharepoint_fixed += 1

                        except Exception as e:
                            logger.error(f"Failed to delete orphan SharePoint asset {asset.id}: {e}")

                    await session.flush()
                    await _log_event(
                        session, run.id, "INFO", "fix",
                        f"Deleted {orphan_sharepoint_fixed} orphan SharePoint assets and their files",
                        {"fixed_count": orphan_sharepoint_fixed}
                    )

        except Exception as e:
            logger.warning(f"SharePoint orphan check failed (non-fatal): {e}")
            await _log_event(
                session, run.id, "WARN", "progress",
                f"SharePoint orphan check skipped: {str(e)}",
            )

        # 6. Find orphaned artifacts (documents that no longer exist)
        # This is a lightweight check - just count artifacts with missing documents
        artifact_count_result = await session.execute(
            select(func.count(Artifact.id))
            .where(Artifact.status == "available")
        )
        total_artifacts = artifact_count_result.scalar() or 0
        orphaned_artifacts = 0  # Would need more complex query with joins

    except Exception as e:
        logger.error(f"Orphan detection failed: {e}")
        await _log_event(
            session, run.id, "ERROR", "error",
            f"Orphan detection failed: {str(e)}",
        )
        raise

    summary = {
        "orphaned_assets": orphaned_assets,
        "stuck_pending_assets": stuck_pending_assets,
        "stuck_pending_fixed": stuck_pending_fixed,
        "missing_file_assets": missing_file_assets,
        "missing_file_fixed": missing_file_fixed,
        "orphan_sharepoint_assets": orphan_sharepoint_assets,
        "orphan_sharepoint_fixed": orphan_sharepoint_fixed,
        "orphaned_artifacts": orphaned_artifacts,
        "stuck_runs": stuck_runs,
        "stuck_runs_fixed": stuck_runs_fixed,
        "auto_fix": auto_fix,
        "details": details,
    }

    # Log warning if orphans found
    total_issues = orphaned_assets + stuck_pending_assets + stuck_runs + missing_file_assets + orphan_sharepoint_assets
    total_fixed = stuck_pending_fixed + stuck_runs_fixed + missing_file_fixed + orphan_sharepoint_fixed
    level = "WARN" if (total_issues - total_fixed) > 0 else "INFO"
    await _log_event(
        session, run.id, level, "summary",
        f"Orphan detection complete: {total_issues} issues found, {total_fixed} auto-fixed",
        summary
    )

    return summary


# =============================================================================
# Handler: Retention Enforcement
# =============================================================================

async def handle_retention_enforcement(
    session: AsyncSession,
    run: Run,
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Enforce data retention policies.

    This handler:
    1. Checks organization retention settings
    2. Removes data older than retention period
    3. Updates artifact statuses

    Note: S3 lifecycle policies handle object storage cleanup.
    This handler manages database records.

    Args:
        session: Database session
        run: Run context for tracking
        config: Task configuration

    Returns:
        Dict with enforcement statistics
    """
    dry_run = config.get("dry_run", False)

    await _log_event(
        session, run.id, "INFO", "start",
        f"Starting retention enforcement (dry_run={dry_run})",
    )

    # Get default retention from config
    default_retention_days = config.get("default_retention_days", 90)
    cutoff = datetime.utcnow() - timedelta(days=default_retention_days)

    deleted_artifacts = 0
    updated_assets = 0
    errors = 0

    try:
        # Mark old artifacts as deleted (soft delete)
        if not dry_run:
            old_artifacts_result = await session.execute(
                select(Artifact)
                .where(
                    and_(
                        Artifact.created_at < cutoff,
                        Artifact.status == "available",
                        Artifact.artifact_type == "temp",  # Only temp artifacts
                    )
                )
                .limit(1000)
            )
            old_artifacts = list(old_artifacts_result.scalars().all())

            for artifact in old_artifacts:
                artifact.status = "deleted"
                artifact.deleted_at = datetime.utcnow()
                deleted_artifacts += 1

            await session.flush()

        await _log_event(
            session, run.id, "INFO", "progress",
            f"Marked {deleted_artifacts} temp artifacts as deleted",
        )

    except Exception as e:
        logger.error(f"Retention enforcement failed: {e}")
        await _log_event(
            session, run.id, "ERROR", "error",
            f"Retention enforcement failed: {str(e)}",
        )
        raise

    summary = {
        "deleted_artifacts": deleted_artifacts,
        "updated_assets": updated_assets,
        "errors": errors,
        "retention_days": default_retention_days,
        "dry_run": dry_run,
    }

    await _log_event(
        session, run.id, "INFO", "summary",
        f"Retention enforcement complete: {deleted_artifacts} artifacts marked deleted",
        summary
    )

    return summary


# =============================================================================
# Handler: Health Report
# =============================================================================

async def handle_health_report(
    session: AsyncSession,
    run: Run,
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Generate a system health summary.

    This handler collects system-wide metrics:
    - Asset counts and status distribution
    - Job counts and status distribution
    - Run counts by type
    - Storage usage estimates

    Args:
        session: Database session
        run: Run context for tracking
        config: Task configuration

    Returns:
        Dict with health metrics
    """
    await _log_event(
        session, run.id, "INFO", "start",
        "Starting health report generation",
    )

    report = {
        "generated_at": datetime.utcnow().isoformat(),
        "assets": {},
        "runs": {},
        "organizations": {},
    }

    try:
        # Asset statistics
        total_assets = await session.execute(
            select(func.count(Asset.id))
        )
        report["assets"]["total"] = total_assets.scalar() or 0

        assets_by_status = await session.execute(
            select(Asset.status, func.count(Asset.id))
            .group_by(Asset.status)
        )
        report["assets"]["by_status"] = {
            row[0]: row[1] for row in assets_by_status.fetchall()
        }

        # Run statistics (last 24h)
        cutoff_24h = datetime.utcnow() - timedelta(hours=24)
        runs_24h = await session.execute(
            select(func.count(Run.id))
            .where(Run.created_at >= cutoff_24h)
        )
        report["runs"]["last_24h"] = runs_24h.scalar() or 0

        runs_by_type = await session.execute(
            select(Run.run_type, func.count(Run.id))
            .where(Run.created_at >= cutoff_24h)
            .group_by(Run.run_type)
        )
        report["runs"]["by_type_24h"] = {
            row[0]: row[1] for row in runs_by_type.fetchall()
        }

        # Organization count
        org_count = await session.execute(
            select(func.count(Organization.id))
            .where(Organization.is_active == True)
        )
        report["organizations"]["active"] = org_count.scalar() or 0

        # Extraction success rate (last 7 days)
        cutoff_7d = datetime.utcnow() - timedelta(days=7)
        total_extractions = await session.execute(
            select(func.count(ExtractionResult.id))
            .where(ExtractionResult.created_at >= cutoff_7d)
        )
        successful_extractions = await session.execute(
            select(func.count(ExtractionResult.id))
            .where(
                and_(
                    ExtractionResult.created_at >= cutoff_7d,
                    ExtractionResult.status == "completed",
                )
            )
        )
        total = total_extractions.scalar() or 0
        success = successful_extractions.scalar() or 0
        report["extractions"] = {
            "total_7d": total,
            "successful_7d": success,
            "success_rate": (success / total * 100) if total > 0 else 100,
        }

    except Exception as e:
        logger.error(f"Health report generation failed: {e}")
        await _log_event(
            session, run.id, "ERROR", "error",
            f"Health report failed: {str(e)}",
        )
        raise

    # Determine overall health status
    health_status = "healthy"
    warnings = []

    if report["assets"].get("by_status", {}).get("failed", 0) > 10:
        warnings.append("High number of failed assets")
        health_status = "degraded"

    if report["extractions"].get("success_rate", 100) < 90:
        warnings.append("Extraction success rate below 90%")
        health_status = "degraded"

    report["health_status"] = health_status
    report["warnings"] = warnings

    await _log_event(
        session, run.id, "INFO", "summary",
        f"Health report generated: {health_status}",
        report
    )

    return report


# =============================================================================
# Handler: Search Reindex (Phase 6)
# =============================================================================

async def handle_search_reindex(
    session: AsyncSession,
    run: Run,
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Reindex all assets to PostgreSQL + pgvector for full-text and semantic search.

    This handler:
    1. Checks if search is enabled
    2. Iterates over all organizations (or specific org if configured)
    3. Reindexes all assets with completed extractions
    4. Reports indexing statistics

    Args:
        session: Database session
        run: Run context for tracking
        config: Task configuration:
            - organization_id: Optional specific org to reindex
            - batch_size: Batch size for bulk operations (default: 100)

    Returns:
        Dict with reindex statistics:
        {
            "status": "completed" | "disabled" | "failed",
            "organizations_processed": int,
            "total_assets": int,
            "indexed": int,
            "failed": int,
            "errors": list
        }
    """
    from .config_loader import config_loader
    from .pg_index_service import pg_index_service
    from ..config import settings

    run_id = run.id

    await _log_event(
        session, run_id, "INFO", "progress",
        "Starting search reindex maintenance task"
    )

    # Check if search is enabled
    search_config = config_loader.get_search_config()
    if search_config:
        enabled = search_config.enabled
    else:
        enabled = getattr(settings, "search_enabled", True)

    if not enabled:
        await _log_event(
            session, run_id, "INFO", "progress",
            "Search is disabled, skipping reindex"
        )
        return {
            "status": "disabled",
            "message": "Search is not enabled",
            "organizations_processed": 0,
            "total_assets": 0,
            "indexed": 0,
            "failed": 0,
        }

    # Get configuration
    specific_org_id = config.get("organization_id")
    batch_size = config.get("batch_size", 100)

    # Get organizations to process
    if specific_org_id:
        org_query = select(Organization).where(Organization.id == specific_org_id)
    else:
        org_query = select(Organization).where(Organization.is_active == True)

    org_result = await session.execute(org_query)
    organizations = list(org_result.scalars().all())

    total_orgs = len(organizations)
    total_assets = 0
    total_indexed = 0
    total_failed = 0
    all_errors: List[str] = []

    await _log_event(
        session, run_id, "INFO", "progress",
        f"Processing {total_orgs} organization(s) for reindex"
    )

    for org in organizations:
        await _log_event(
            session, run_id, "INFO", "progress",
            f"Reindexing assets for organization: {org.name}"
        )

        try:
            result = await pg_index_service.reindex_organization(
                session=session,
                organization_id=org.id,
                batch_size=batch_size,
            )

            org_total = result.get("total", 0)
            org_indexed = result.get("indexed", 0)
            org_failed = result.get("failed", 0)
            org_errors = result.get("errors", [])

            total_assets += org_total
            total_indexed += org_indexed
            total_failed += org_failed
            all_errors.extend(org_errors[:5])  # Limit errors per org

            await _log_event(
                session, run_id, "INFO", "progress",
                f"Organization {org.name}: {org_indexed}/{org_total} indexed, {org_failed} failed"
            )

        except Exception as e:
            error_msg = f"Failed to reindex org {org.name}: {str(e)}"
            logger.error(error_msg)
            all_errors.append(error_msg)
            await _log_event(
                session, run_id, "ERROR", "error",
                error_msg
            )

    # Final summary
    await _log_event(
        session, run_id, "INFO", "summary",
        f"Search reindex completed: {total_indexed}/{total_assets} assets indexed across {total_orgs} organizations",
        context={
            "organizations_processed": total_orgs,
            "total_assets": total_assets,
            "indexed": total_indexed,
            "failed": total_failed,
        }
    )

    return {
        "status": "completed",
        "organizations_processed": total_orgs,
        "total_assets": total_assets,
        "indexed": total_indexed,
        "failed": total_failed,
        "errors": all_errors[:20],  # Limit total errors
    }


# =============================================================================
# Stale Run Cleanup Handler
# =============================================================================


async def handle_stale_run_cleanup(
    session: AsyncSession,
    run: Run,
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Clean up stale runs that are stuck in pending/submitted/running state.

    This handler finds runs that have been stuck for longer than the configured
    timeout and either retries them (up to max_retries) or marks them as failed.

    Enhanced to handle:
    - Submitted runs (Celery task may be lost) - shorter timeout
    - Running runs (worker may have crashed)
    - Pending runs (queue processing may have failed)

    Args:
        session: Database session
        run: Run context for tracking
        config: Task configuration:
            - stale_running_hours: Hours before a 'running' run is stale (default: 2)
            - stale_submitted_minutes: Minutes before a 'submitted' run is stale (default: 30)
            - stale_pending_hours: Hours before a 'pending' run is stale (default: 1)
            - max_retries: Max retry attempts before marking as failed (default: 3)
            - dry_run: If True, don't actually update (default: False)

    Returns:
        Dict with cleanup statistics
    """
    from ..database.models import Asset

    stale_running_hours = config.get("stale_running_hours", 2)
    stale_submitted_minutes = config.get("stale_submitted_minutes", 30)
    stale_pending_hours = config.get("stale_pending_hours", 1)
    max_retries = config.get("max_retries", 3)
    dry_run = config.get("dry_run", False)

    now = datetime.utcnow()
    running_cutoff = now - timedelta(hours=stale_running_hours)
    submitted_cutoff = now - timedelta(minutes=stale_submitted_minutes)
    pending_cutoff = now - timedelta(hours=stale_pending_hours)

    results = {
        "stale_submitted_reset": 0,
        "stale_running_reset": 0,
        "stale_pending_reset": 0,
        "orphaned_maintenance_timed_out": 0,
        "failed_max_retries": 0,
        "errors": 0,
        "dry_run": dry_run,
    }

    await _log_event(
        session, run.id, "INFO", "start",
        f"Starting stale run cleanup (submitted>{stale_submitted_minutes}m, "
        f"running>{stale_running_hours}h, pending>{stale_pending_hours}h, max_retries={max_retries})"
    )

    try:
        # Find stale 'submitted' runs (Celery task may be lost)
        stale_submitted_query = (
            select(Run)
            .where(and_(
                Run.run_type == "extraction",
                Run.status == "submitted",
                Run.submitted_to_celery_at < submitted_cutoff,
            ))
        )
        stale_submitted = await session.execute(stale_submitted_query)
        stale_submitted_runs = list(stale_submitted.scalars().all())

        # Find stale 'running' runs
        stale_running_query = (
            select(Run)
            .where(and_(
                Run.run_type == "extraction",
                Run.status == "running",
                Run.started_at < running_cutoff,
            ))
        )
        stale_running = await session.execute(stale_running_query)
        stale_running_runs = list(stale_running.scalars().all())

        # Find stale 'pending' runs (queue processing failed)
        stale_pending_query = (
            select(Run)
            .where(and_(
                Run.run_type == "extraction",
                Run.status == "pending",
                Run.created_at < pending_cutoff,
            ))
        )
        stale_pending = await session.execute(stale_pending_query)
        stale_pending_runs = list(stale_pending.scalars().all())

        await _log_event(
            session, run.id, "INFO", "progress",
            f"Found {len(stale_submitted_runs)} submitted, {len(stale_running_runs)} running, "
            f"{len(stale_pending_runs)} pending stale runs"
        )

        if not dry_run:
            all_stale_runs = [
                (stale_submitted_runs, "submitted", "stale_submitted_reset"),
                (stale_running_runs, "running", "stale_running_reset"),
                (stale_pending_runs, "pending", "stale_pending_reset"),
            ]

            for runs_list, status_name, result_key in all_stale_runs:
                for stale_run in runs_list:
                    try:
                        # Special handling for maintenance runs - they're time-sensitive
                        # If a maintenance run is stuck pending, the scheduled time has passed
                        # and retrying doesn't make sense - mark as timed_out immediately
                        if stale_run.run_type == "system_maintenance" and status_name == "pending":
                            stale_run.status = "timed_out"
                            stale_run.completed_at = now
                            stale_run.error_message = (
                                "Orphaned maintenance run - Celery task was never executed. "
                                "The scheduled time has passed."
                            )
                            results["orphaned_maintenance_timed_out"] += 1

                            logger.warning(
                                f"Maintenance run {stale_run.id} was orphaned (pending), marked as timed_out"
                            )
                            continue

                        retry_count = (stale_run.config or {}).get("stale_retry_count", 0) + 1

                        if retry_count > max_retries:
                            # Too many retries, mark as failed
                            stale_run.status = "failed"
                            stale_run.completed_at = now
                            stale_run.error_message = (
                                f"Failed after {retry_count} attempts: stuck in {status_name} state"
                            )
                            results["failed_max_retries"] += 1

                            # Update associated asset
                            if stale_run.input_asset_ids:
                                try:
                                    asset_id = UUID(stale_run.input_asset_ids[0])
                                    asset = await session.get(Asset, asset_id)
                                    if asset and asset.status == "pending":
                                        asset.status = "failed"
                                        asset.source_metadata = {
                                            **(asset.source_metadata or {}),
                                            "failed_reason": f"Extraction failed after {retry_count} retries",
                                            "failed_at": now.isoformat(),
                                        }
                                except Exception as e:
                                    logger.warning(f"Failed to update asset for run {stale_run.id}: {e}")

                            logger.warning(
                                f"Run {stale_run.id} exceeded max retries ({retry_count}), marked as failed"
                            )
                        else:
                            # Reset to pending for retry
                            stale_run.status = "pending"
                            stale_run.celery_task_id = None
                            stale_run.submitted_to_celery_at = None
                            stale_run.started_at = None
                            stale_run.timeout_at = None
                            stale_run.config = {
                                **(stale_run.config or {}),
                                "stale_retry_count": retry_count,
                                "last_stale_reset_at": now.isoformat(),
                                "stale_reason": f"Was stuck in {status_name} state",
                            }
                            results[result_key] += 1

                            logger.info(
                                f"Reset run {stale_run.id} from {status_name} to pending "
                                f"(retry #{retry_count})"
                            )

                    except Exception as e:
                        logger.error(f"Failed to process stale run {stale_run.id}: {e}")
                        results["errors"] += 1

            await session.flush()

    except Exception as e:
        logger.error(f"Stale run cleanup failed: {e}")
        results["errors"] += 1

    await _log_event(
        session, run.id, "INFO", "complete",
        f"Stale run cleanup complete: {results['stale_submitted_reset']} submitted reset, "
        f"{results['stale_running_reset']} running reset, {results['stale_pending_reset']} pending reset, "
        f"{results['orphaned_maintenance_timed_out']} orphaned maintenance timed out, "
        f"{results['failed_max_retries']} failed (max retries)",
        results
    )

    return results


# =============================================================================
# Handler: SharePoint Scheduled Sync
# =============================================================================

async def handle_sharepoint_scheduled_sync(
    session: AsyncSession,
    run: Run,
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Execute scheduled SharePoint sync for all configs with matching frequency.

    This handler:
    1. Finds all SharePointSyncConfigs with the specified frequency
    2. Skips configs that already have a running sync
    3. Triggers sharepoint_sync_task for each eligible config

    Args:
        session: Database session
        run: Run context for tracking
        config: Task configuration:
            - frequency: "hourly" or "daily" (required)

    Returns:
        Dict with sync statistics:
        {
            "frequency": str,
            "configs_found": int,
            "syncs_triggered": int,
            "syncs_skipped": int,
            "errors": list
        }
    """
    from uuid import uuid4

    frequency = config.get("frequency")
    if not frequency:
        await _log_event(
            session, run.id, "ERROR", "error",
            "Missing 'frequency' in config (expected 'hourly' or 'daily')"
        )
        return {
            "status": "failed",
            "error": "Missing frequency configuration",
        }

    await _log_event(
        session, run.id, "INFO", "start",
        f"Starting scheduled SharePoint sync for frequency: {frequency}"
    )

    # Find all active sync configs with matching frequency
    configs_result = await session.execute(
        select(SharePointSyncConfig).where(
            and_(
                SharePointSyncConfig.sync_frequency == frequency,
                SharePointSyncConfig.is_active == True,
                SharePointSyncConfig.status == "active",
            )
        )
    )
    sync_configs = list(configs_result.scalars().all())

    configs_found = len(sync_configs)
    syncs_triggered = 0
    syncs_skipped = 0
    errors: List[str] = []

    await _log_event(
        session, run.id, "INFO", "progress",
        f"Found {configs_found} SharePoint sync configs with frequency '{frequency}'"
    )

    for sync_config in sync_configs:
        try:
            # Check if there's already a running sync for this config
            active_run_result = await session.execute(
                select(Run).where(
                    and_(
                        Run.run_type.in_(["sharepoint_sync", "sharepoint_import"]),
                        Run.status.in_(["pending", "running"]),
                        Run.config["sync_config_id"].astext == str(sync_config.id),
                    )
                ).limit(1)
            )
            active_run = active_run_result.scalar_one_or_none()

            if active_run:
                await _log_event(
                    session, run.id, "INFO", "progress",
                    f"Skipping '{sync_config.name}' - sync already in progress (run_id={active_run.id})"
                )
                syncs_skipped += 1
                continue

            # Create a new run for this sync
            sync_run = Run(
                id=uuid4(),
                organization_id=sync_config.organization_id,
                run_type="sharepoint_sync",
                origin="scheduled",
                status="pending",
                config={
                    "sync_config_id": str(sync_config.id),
                    "sync_config_name": sync_config.name,
                    "full_sync": False,
                    "triggered_by_task": str(run.id),
                },
            )
            session.add(sync_run)

            # Commit before dispatching Celery task to ensure Run is visible to worker
            await session.commit()

            # Trigger the sync task
            from ..tasks import sharepoint_sync_task
            sharepoint_sync_task.delay(
                sync_config_id=str(sync_config.id),
                organization_id=str(sync_config.organization_id),
                run_id=str(sync_run.id),
                full_sync=False,
            )

            syncs_triggered += 1
            await _log_event(
                session, run.id, "INFO", "progress",
                f"Triggered sync for '{sync_config.name}' (run_id={sync_run.id})"
            )

        except Exception as e:
            error_msg = f"Failed to trigger sync for '{sync_config.name}': {str(e)}"
            logger.error(error_msg)
            errors.append(error_msg)
            await _log_event(
                session, run.id, "ERROR", "error",
                error_msg
            )

    summary = {
        "frequency": frequency,
        "configs_found": configs_found,
        "syncs_triggered": syncs_triggered,
        "syncs_skipped": syncs_skipped,
        "errors": errors,
    }

    await _log_event(
        session, run.id, "INFO", "summary",
        f"Scheduled SharePoint sync complete: {syncs_triggered}/{configs_found} syncs triggered, {syncs_skipped} skipped",
        summary
    )

    return summary


# =============================================================================
# Handler: SAM.gov Scheduled Pull
# =============================================================================

async def handle_sam_scheduled_pull(
    session: AsyncSession,
    run: Run,
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Execute scheduled SAM.gov pulls for all searches with matching frequency.

    This handler:
    1. Finds all SamSearch records with the specified frequency
    2. Skips searches that already have a running pull
    3. Triggers sam_pull_task for each eligible search

    Args:
        session: Database session
        run: Run context for tracking
        config: Task configuration:
            - frequency: "hourly" or "daily" (required)

    Returns:
        Dict with pull statistics:
        {
            "frequency": str,
            "searches_found": int,
            "pulls_triggered": int,
            "pulls_skipped": int,
            "errors": list
        }
    """
    from uuid import uuid4

    frequency = config.get("frequency")
    if not frequency:
        await _log_event(
            session, run.id, "ERROR", "error",
            "Missing 'frequency' in config (expected 'hourly' or 'daily')"
        )
        return {
            "status": "failed",
            "error": "Missing frequency configuration",
        }

    await _log_event(
        session, run.id, "INFO", "start",
        f"Starting scheduled SAM.gov pull for frequency: {frequency}"
    )

    # Find all active SAM searches with matching frequency
    searches_result = await session.execute(
        select(SamSearch).where(
            and_(
                SamSearch.pull_frequency == frequency,
                SamSearch.is_active == True,
                SamSearch.status == "active",
            )
        )
    )
    sam_searches = list(searches_result.scalars().all())

    searches_found = len(sam_searches)
    pulls_triggered = 0
    pulls_skipped = 0
    errors: List[str] = []

    await _log_event(
        session, run.id, "INFO", "progress",
        f"Found {searches_found} SAM searches with frequency '{frequency}'"
    )

    for search in sam_searches:
        try:
            # Check if there's already a running pull for this search
            active_run_result = await session.execute(
                select(Run).where(
                    and_(
                        Run.run_type == "sam_pull",
                        Run.status.in_(["pending", "running"]),
                        Run.config["search_id"].astext == str(search.id),
                    )
                ).limit(1)
            )
            active_run = active_run_result.scalar_one_or_none()

            if active_run:
                await _log_event(
                    session, run.id, "INFO", "progress",
                    f"Skipping '{search.name}' - pull already in progress (run_id={active_run.id})"
                )
                pulls_skipped += 1
                continue

            # Create a new run for this pull
            pull_run = Run(
                id=uuid4(),
                organization_id=search.organization_id,
                run_type="sam_pull",
                origin="scheduled",
                status="pending",
                config={
                    "search_id": str(search.id),
                    "search_name": search.name,
                    "triggered_by_task": str(run.id),
                },
            )
            session.add(pull_run)

            # Commit before dispatching Celery task to ensure Run is visible to worker
            await session.commit()

            # Trigger the pull task
            from ..tasks import sam_pull_task
            sam_pull_task.delay(
                search_id=str(search.id),
                organization_id=str(search.organization_id),
                run_id=str(pull_run.id),
            )

            pulls_triggered += 1
            await _log_event(
                session, run.id, "INFO", "progress",
                f"Triggered pull for '{search.name}' (run_id={pull_run.id})"
            )

        except Exception as e:
            error_msg = f"Failed to trigger pull for '{search.name}': {str(e)}"
            logger.error(error_msg)
            errors.append(error_msg)
            await _log_event(
                session, run.id, "ERROR", "error",
                error_msg
            )

    summary = {
        "frequency": frequency,
        "searches_found": searches_found,
        "pulls_triggered": pulls_triggered,
        "pulls_skipped": pulls_skipped,
        "errors": errors,
    }

    await _log_event(
        session, run.id, "INFO", "summary",
        f"Scheduled SAM.gov pull complete: {pulls_triggered}/{searches_found} pulls triggered, {pulls_skipped} skipped",
        summary
    )

    return summary


# =============================================================================
# Queue Pending Assets Handler (Safety Net)
# =============================================================================


async def handle_queue_pending_assets(
    session: AsyncSession,
    run: Run,
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Safety-net handler to queue extractions for orphaned pending assets.

    This runs frequently (every 5 minutes) to catch any assets that were
    created without extraction being properly queued. This is a safety net -
    the primary mechanism is auto-queueing in asset_service.

    Scenarios this catches:
    - Race conditions during high load
    - Bugs in ingest services that don't call asset_service properly
    - Manual database insertions
    - Recovery after service restarts

    Args:
        session: Database session
        run: Run context for tracking
        config: Task configuration
            - limit: Max assets to process per run (default: 100)
            - min_age_seconds: Min age to avoid race conditions (default: 60)

    Returns:
        Dict with processing results
    """
    limit = config.get("limit", 100)
    min_age_seconds = config.get("min_age_seconds", 60)

    await _log_event(
        session, run.id, "INFO", "start",
        f"Starting queue pending assets check (limit={limit}, min_age={min_age_seconds}s)"
    )

    try:
        from .extraction_queue_service import extraction_queue_service

        # Find assets needing extraction
        orphaned_ids = await extraction_queue_service.find_assets_needing_extraction(
            session=session,
            limit=limit,
            min_age_seconds=min_age_seconds,
        )

        if not orphaned_ids:
            await _log_event(
                session, run.id, "INFO", "complete",
                "No orphaned pending assets found"
            )
            return {
                "orphaned_found": 0,
                "queued": 0,
                "skipped": 0,
                "errors": 0,
            }

        await _log_event(
            session, run.id, "WARN", "progress",
            f"Found {len(orphaned_ids)} orphaned pending assets",
            {"sample_ids": [str(aid) for aid in orphaned_ids[:5]]}
        )

        # Queue extractions for orphaned assets
        queued = 0
        skipped = 0
        errors = 0
        error_details = []

        for asset_id in orphaned_ids:
            try:
                run_result, extraction, status = await extraction_queue_service.queue_extraction_for_asset(
                    session=session,
                    asset_id=asset_id,
                )

                if status == "queued":
                    queued += 1
                elif status in ("skipped_content_type", "already_pending"):
                    skipped += 1
                else:
                    errors += 1
                    error_details.append({"asset_id": str(asset_id), "status": status})

            except Exception as e:
                errors += 1
                error_details.append({"asset_id": str(asset_id), "error": str(e)})
                logger.error(f"Failed to queue extraction for orphaned asset {asset_id}: {e}")

        await session.commit()

        summary = {
            "orphaned_found": len(orphaned_ids),
            "queued": queued,
            "skipped": skipped,
            "errors": errors,
            "error_details": error_details[:10] if error_details else [],
        }

        await _log_event(
            session, run.id, "INFO", "complete",
            f"Queue pending assets complete: {queued} queued, {skipped} skipped, {errors} errors",
            summary
        )

        return summary

    except Exception as e:
        error_msg = f"Queue pending assets failed: {str(e)}"
        logger.error(error_msg)
        await _log_event(session, run.id, "ERROR", "error", error_msg)
        raise


# =============================================================================
# Handler: Queue Pending Enhancements
# =============================================================================


async def handle_queue_pending_enhancements(
    session: AsyncSession,
    run: Run,
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Queue enhancement jobs for assets that completed basic extraction
    but haven't had enhancement queued yet.

    This runs periodically to catch assets that:
    - Have completed basic extraction (extraction_tier = 'basic')
    - Are enhancement_eligible = True
    - Haven't had enhancement queued (enhancement_queued_at is NULL)
    - Have a completed ExtractionResult

    Args:
        session: Database session
        run: Run context for tracking
        config: Task configuration
            - limit: Max assets to process per run (default: 50)
            - min_age_seconds: Min age since extraction completed (default: 60)

    Returns:
        Dict with processing results
    """
    limit = config.get("limit", 50)
    min_age_seconds = config.get("min_age_seconds", 60)

    await _log_event(
        session, run.id, "INFO", "start",
        f"Starting queue pending enhancements check (limit={limit})"
    )

    try:
        from datetime import timedelta
        from .extraction_orchestrator import extraction_orchestrator

        cutoff = datetime.utcnow() - timedelta(seconds=min_age_seconds)

        # Find assets eligible for enhancement that haven't been queued
        # - enhancement_eligible = True
        # - enhancement_queued_at IS NULL (not yet queued)
        # - extraction_tier = 'basic' (has basic extraction)
        # - Has a completed ExtractionResult
        query = (
            select(Asset)
            .join(ExtractionResult, ExtractionResult.asset_id == Asset.id)
            .where(
                and_(
                    Asset.enhancement_eligible == True,
                    Asset.enhancement_queued_at.is_(None),
                    Asset.extraction_tier == "basic",
                    Asset.status == "ready",
                    ExtractionResult.status == "completed",
                    ExtractionResult.created_at < cutoff,
                )
            )
            .distinct()
            .limit(limit)
        )
        result = await session.execute(query)
        assets = list(result.scalars().all())

        if not assets:
            await _log_event(
                session, run.id, "INFO", "complete",
                "No assets pending enhancement found"
            )
            return {
                "found": 0,
                "queued": 0,
                "errors": 0,
            }

        await _log_event(
            session, run.id, "INFO", "progress",
            f"Found {len(assets)} assets needing enhancement",
            {"sample_ids": [str(a.id) for a in assets[:5]]}
        )

        # Queue enhancements
        queued = 0
        errors = 0
        error_details = []

        for asset in assets:
            try:
                enhancement_result = await extraction_orchestrator._queue_enhancement(
                    session=session,
                    asset=asset,
                    organization_id=asset.organization_id,
                )
                if enhancement_result.get("queued"):
                    queued += 1
            except Exception as e:
                errors += 1
                error_details.append({"asset_id": str(asset.id), "error": str(e)})
                logger.error(f"Failed to queue enhancement for asset {asset.id}: {e}")

        await session.commit()

        summary = {
            "found": len(assets),
            "queued": queued,
            "errors": errors,
            "error_details": error_details[:10] if error_details else [],
        }

        await _log_event(
            session, run.id, "INFO", "complete",
            f"Queue pending enhancements complete: {queued} queued, {errors} errors",
            summary
        )

        return summary

    except Exception as e:
        error_msg = f"Queue pending enhancements failed: {str(e)}"
        logger.error(error_msg)
        await _log_event(session, run.id, "ERROR", "error", error_msg)
        raise


# =============================================================================
# Handler Registry
# =============================================================================

MAINTENANCE_HANDLERS = {
    "gc.cleanup": handle_job_cleanup,
    "orphan.detect": handle_orphan_detection,
    "retention.enforce": handle_retention_enforcement,
    "health.report": handle_health_report,
    "search.reindex": handle_search_reindex,
    "stale_run.cleanup": handle_stale_run_cleanup,
    "sharepoint.scheduled_sync": handle_sharepoint_scheduled_sync,
    "sam.scheduled_pull": handle_sam_scheduled_pull,
    "extraction.queue_pending": handle_queue_pending_assets,
    "enhancement.queue_pending": handle_queue_pending_enhancements,
}


async def get_handler(task_type: str):
    """
    Get the handler function for a task type.

    Args:
        task_type: Type of maintenance task

    Returns:
        Handler function or None if not found
    """
    return MAINTENANCE_HANDLERS.get(task_type)
