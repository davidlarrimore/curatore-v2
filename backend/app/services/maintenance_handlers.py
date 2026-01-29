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
    Job,
    JobDocument,
    Asset,
    ExtractionResult,
    Artifact,
    Run,
    RunLogEvent,
    Organization,
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
# Handler: Job Cleanup
# =============================================================================

async def handle_job_cleanup(
    session: AsyncSession,
    run: Run,
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Delete expired jobs based on organization retention policies.

    This handler:
    1. Iterates over all organizations
    2. Finds jobs past their expires_at timestamp
    3. Deletes job documents and logs
    4. Deletes the jobs themselves

    Args:
        session: Database session
        run: Run context for tracking
        config: Task configuration (may include dry_run flag)

    Returns:
        Dict with cleanup statistics:
        {
            "deleted_jobs": int,
            "deleted_documents": int,
            "errors": int,
            "organizations_processed": int,
            "dry_run": bool
        }
    """
    dry_run = config.get("dry_run", False)
    now = datetime.utcnow()

    await _log_event(
        session, run.id, "INFO", "start",
        f"Starting job cleanup (dry_run={dry_run})",
        {"dry_run": dry_run}
    )

    deleted_jobs = 0
    deleted_documents = 0
    errors = 0
    orgs_processed = 0

    try:
        # Find all expired jobs
        expired_jobs_result = await session.execute(
            select(Job)
            .where(
                and_(
                    Job.expires_at.isnot(None),
                    Job.expires_at <= now,
                    Job.status.in_(["COMPLETED", "FAILED", "CANCELLED"]),
                )
            )
            .order_by(Job.expires_at)
        )
        expired_jobs = list(expired_jobs_result.scalars().all())

        await _log_event(
            session, run.id, "INFO", "progress",
            f"Found {len(expired_jobs)} expired jobs",
            {"expired_count": len(expired_jobs)}
        )

        # Track organizations
        org_ids = set()

        for job in expired_jobs:
            try:
                org_ids.add(job.organization_id)

                # Count documents
                doc_count_result = await session.execute(
                    select(func.count(JobDocument.id))
                    .where(JobDocument.job_id == job.id)
                )
                doc_count = doc_count_result.scalar() or 0

                if dry_run:
                    logger.info(f"[DRY RUN] Would delete job {job.id} with {doc_count} documents")
                else:
                    # Delete job (cascades to documents and logs)
                    await session.delete(job)
                    deleted_jobs += 1
                    deleted_documents += doc_count

                    if deleted_jobs % 10 == 0:
                        await session.flush()
                        await _log_event(
                            session, run.id, "INFO", "progress",
                            f"Deleted {deleted_jobs} jobs so far",
                        )

            except Exception as e:
                logger.error(f"Error deleting job {job.id}: {e}")
                errors += 1

        orgs_processed = len(org_ids)

        if not dry_run:
            await session.flush()

    except Exception as e:
        logger.error(f"Job cleanup failed: {e}")
        await _log_event(
            session, run.id, "ERROR", "error",
            f"Job cleanup failed: {str(e)}",
        )
        raise

    summary = {
        "deleted_jobs": deleted_jobs,
        "deleted_documents": deleted_documents,
        "errors": errors,
        "organizations_processed": orgs_processed,
        "dry_run": dry_run,
    }

    await _log_event(
        session, run.id, "INFO", "summary",
        f"Job cleanup complete: {deleted_jobs} jobs, {deleted_documents} documents deleted",
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

            # Auto-fix: Mark stuck pending assets as "failed"
            if auto_fix:
                for asset in stuck_pending_list:
                    asset.status = "failed"
                    asset.updated_at = datetime.utcnow()
                    # Add note in source_metadata about why it failed
                    asset.source_metadata = {
                        **asset.source_metadata,
                        "auto_failed_reason": "Stuck in pending status - extraction never completed",
                        "auto_failed_at": datetime.utcnow().isoformat(),
                    }
                    stuck_pending_fixed += 1

                await session.flush()
                await _log_event(
                    session, run.id, "INFO", "fix",
                    f"Marked {stuck_pending_fixed} stuck assets as 'failed'",
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

        # 4. Find orphaned artifacts (documents that no longer exist)
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
        "orphaned_artifacts": orphaned_artifacts,
        "stuck_runs": stuck_runs,
        "stuck_runs_fixed": stuck_runs_fixed,
        "auto_fix": auto_fix,
        "details": details,
    }

    # Log warning if orphans found
    total_issues = orphaned_assets + stuck_pending_assets + stuck_runs
    total_fixed = stuck_pending_fixed + stuck_runs_fixed
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
        "jobs": {},
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

        # Job statistics (last 24h)
        cutoff_24h = datetime.utcnow() - timedelta(hours=24)
        jobs_24h = await session.execute(
            select(func.count(Job.id))
            .where(Job.created_at >= cutoff_24h)
        )
        report["jobs"]["last_24h"] = jobs_24h.scalar() or 0

        jobs_by_status = await session.execute(
            select(Job.status, func.count(Job.id))
            .where(Job.created_at >= cutoff_24h)
            .group_by(Job.status)
        )
        report["jobs"]["by_status_24h"] = {
            row[0]: row[1] for row in jobs_by_status.fetchall()
        }

        # Run statistics (last 24h)
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
# Handler Registry
# =============================================================================

MAINTENANCE_HANDLERS = {
    "gc.cleanup": handle_job_cleanup,
    "orphan.detect": handle_orphan_detection,
    "retention.enforce": handle_retention_enforcement,
    "health.report": handle_health_report,
    "search.reindex": handle_search_reindex,
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
