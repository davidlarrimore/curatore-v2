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
                    from .index_service import index_service
                    minio = get_minio_service()

                    for asset in orphan_sp_list:
                        try:
                            # Remove from OpenSearch
                            try:
                                await index_service.delete_asset_index(asset.organization_id, asset.id)
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
    Reindex all assets to OpenSearch for full-text search.

    This handler:
    1. Checks if OpenSearch is enabled
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
    from .index_service import index_service
    from ..config import settings

    run_id = run.id

    await _log_event(
        session, run_id, "INFO", "progress",
        "Starting search reindex maintenance task"
    )

    # Check if OpenSearch is enabled
    opensearch_config = config_loader.get_opensearch_config()
    if opensearch_config:
        enabled = opensearch_config.enabled
    else:
        enabled = settings.opensearch_enabled

    if not enabled:
        await _log_event(
            session, run_id, "INFO", "progress",
            "OpenSearch is disabled, skipping reindex"
        )
        return {
            "status": "disabled",
            "message": "OpenSearch is not enabled",
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
            result = await index_service.reindex_organization(
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
    Clean up stale runs that are stuck in pending/running state.

    This handler finds runs that have been in 'pending' or 'running' status
    for longer than the configured timeout and marks them as cancelled.

    This prevents:
    - Runs showing as "running" forever in the UI
    - Confusion about extraction status
    - Resource tracking issues

    Args:
        session: Database session
        run: Run context for tracking
        config: Task configuration:
            - stale_running_hours: Hours before a 'running' run is stale (default: 2)
            - stale_pending_hours: Hours before a 'pending' run is stale (default: 1)
            - dry_run: If True, don't actually update (default: False)

    Returns:
        Dict with cleanup statistics
    """
    stale_running_hours = config.get("stale_running_hours", 2)
    stale_pending_hours = config.get("stale_pending_hours", 1)
    dry_run = config.get("dry_run", False)

    now = datetime.utcnow()
    running_cutoff = now - timedelta(hours=stale_running_hours)
    pending_cutoff = now - timedelta(hours=stale_pending_hours)

    results = {
        "stale_running_cancelled": 0,
        "stale_pending_cancelled": 0,
        "errors": 0,
        "dry_run": dry_run,
    }

    try:
        # Find stale 'running' runs
        stale_running_query = (
            select(Run)
            .where(Run.status == "running")
            .where(Run.started_at < running_cutoff)
        )
        stale_running = await session.execute(stale_running_query)
        stale_running_runs = list(stale_running.scalars().all())

        # Find stale 'pending' runs
        stale_pending_query = (
            select(Run)
            .where(Run.status == "pending")
            .where(Run.created_at < pending_cutoff)
        )
        stale_pending = await session.execute(stale_pending_query)
        stale_pending_runs = list(stale_pending.scalars().all())

        logger.info(
            f"Found {len(stale_running_runs)} stale running runs "
            f"(started before {running_cutoff})"
        )
        logger.info(
            f"Found {len(stale_pending_runs)} stale pending runs "
            f"(created before {pending_cutoff})"
        )

        if not dry_run:
            # Cancel stale running runs
            for stale_run in stale_running_runs:
                try:
                    stale_run.status = "cancelled"
                    stale_run.error_message = (
                        f"Cleaned up: stuck in running state for >{stale_running_hours} hours"
                    )
                    results["stale_running_cancelled"] += 1
                except Exception as e:
                    logger.error(f"Failed to cancel stale running run {stale_run.id}: {e}")
                    results["errors"] += 1

            # Cancel stale pending runs
            for stale_run in stale_pending_runs:
                try:
                    stale_run.status = "cancelled"
                    stale_run.error_message = (
                        f"Cleaned up: stuck in pending state for >{stale_pending_hours} hours"
                    )
                    results["stale_pending_cancelled"] += 1
                except Exception as e:
                    logger.error(f"Failed to cancel stale pending run {stale_run.id}: {e}")
                    results["errors"] += 1

            await session.flush()
        else:
            # Dry run - just count
            results["stale_running_cancelled"] = len(stale_running_runs)
            results["stale_pending_cancelled"] = len(stale_pending_runs)

    except Exception as e:
        logger.error(f"Stale run cleanup failed: {e}")
        results["errors"] += 1

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
                        func.json_extract(Run.config, "$.sync_config_id") == str(sync_config.id),
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
            await session.flush()

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
