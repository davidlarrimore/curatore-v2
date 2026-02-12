"""
Celery tasks for web scraping (crawl and collection deletion).

Extracted from the monolithic tasks.py to improve maintainability.
"""
import asyncio
import logging
import uuid
from typing import Any, Dict, Optional

from celery import shared_task
from sqlalchemy import select

from app.core.shared.database_service import database_service

# ============================================================================
# WEB SCRAPING TASKS
# ============================================================================

@shared_task(bind=True, name="app.tasks.scrape_crawl_task", soft_time_limit=3600, time_limit=3900)  # 60 minute soft limit, 65 minute hard limit
def scrape_crawl_task(
    self,
    collection_id: str,
    organization_id: str,
    run_id: str,
    user_id: Optional[str] = None,
    max_pages: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Execute web scraping crawl for a collection.

    This task:
    1. Fetches pages from seed URLs using Playwright
    2. Extracts content and converts to Markdown
    3. Creates Assets for each page
    4. Downloads discovered documents (PDFs, etc.)
    5. Tracks progress via Run record

    Args:
        collection_id: ScrapeCollection UUID string
        organization_id: Organization UUID string
        run_id: Run UUID string
        user_id: Optional user UUID string who initiated the crawl
        max_pages: Optional maximum pages to crawl

    Returns:
        Dict with crawl results
    """
    logger = logging.getLogger("curatore.tasks.scrape_crawl")
    logger.info(f"Starting web scrape for collection {collection_id}")

    try:
        result = asyncio.run(
            _scrape_crawl_async(
                collection_id=uuid.UUID(collection_id),
                organization_id=uuid.UUID(organization_id),
                run_id=uuid.UUID(run_id),
                user_id=uuid.UUID(user_id) if user_id else None,
                max_pages=max_pages,
            )
        )

        logger.info(f"Web scrape completed for collection {collection_id}: {result}")
        return result

    except Exception as e:
        logger.error(f"Web scrape failed for collection {collection_id}: {e}", exc_info=True)
        # Mark run as failed
        asyncio.run(_fail_scrape_run(uuid.UUID(run_id), str(e)))
        raise


async def _scrape_crawl_async(
    collection_id,
    organization_id,
    run_id,
    user_id: Optional[uuid.UUID],
    max_pages: Optional[int],
) -> Dict[str, Any]:
    """
    Async implementation of web scraping crawl.

    Creates a RunGroup to track child extraction jobs and supports:
    - Priority-based extraction queueing (Scrape = SAM_SCRAPE priority)
    - Parent-child job tracking for timeout and cancellation
    - Post-crawl procedure triggers via group completion events
    """
    from app.connectors.scrape.crawl_service import crawl_service
    from app.core.database.models import ScrapeCollection
    from app.core.ops.heartbeat_service import heartbeat_service
    from app.core.shared.run_group_service import run_group_service
    from app.core.shared.run_log_service import run_log_service
    from app.core.shared.run_service import run_service

    logger = logging.getLogger("curatore.tasks.scrape_crawl")

    async with database_service.get_session() as session:
        # Get collection for config
        collection = await session.get(ScrapeCollection, collection_id)
        collection_name = collection.name if collection else "Unknown"
        automation_config = getattr(collection, 'automation_config', {}) or {} if collection else {}

        # Create RunGroup for tracking child extractions
        group = await run_group_service.create_group(
            session=session,
            organization_id=organization_id,
            group_type="scrape",
            parent_run_id=run_id,
            config={
                "collection_id": str(collection_id),
                "collection_name": collection_name,
                "max_pages": max_pages,
                "after_procedure_slug": automation_config.get("after_procedure_slug"),
                "after_procedure_params": automation_config.get("after_procedure_params", {}),
            },
        )
        group_id = group.id

        # Log start and send initial heartbeat
        await run_log_service.log_event(
            session=session,
            run_id=run_id,
            level="INFO",
            event_type="start",
            message=f"Starting web scrape (max_pages={max_pages})",
            context={"group_id": str(group_id)},
        )
        await heartbeat_service.beat(session, run_id, progress={"phase": "starting_crawl"})
        await session.commit()

        try:
            # Execute crawl - this handles run state transitions internally
            # Pass group_id for child extraction tracking
            result = await crawl_service.crawl_collection(
                session=session,
                collection_id=collection_id,
                user_id=user_id,
                max_pages=max_pages,
                run_id=run_id,
                group_id=group_id,  # Pass group_id for child extraction tracking
            )

            # Heartbeat after crawl completes
            await heartbeat_service.beat(session, run_id, progress={
                "phase": "crawl_complete",
                "pages_crawled": result.get("pages_crawled", 0),
            })

            # Finalize the group (handles case where children complete before parent finishes)
            await run_group_service.finalize_group(session, group_id)

            await run_log_service.log_summary(
                session=session,
                run_id=run_id,
                message=(
                    f"Crawl completed: {result.get('pages_crawled', 0)} pages crawled, "
                    f"{result.get('pages_new', 0)} new, "
                    f"{result.get('pages_updated', 0)} updated, "
                    f"{result.get('pages_failed', 0)} failed, "
                    f"{result.get('documents_discovered', 0)} documents discovered"
                ),
                context={
                    "pages_crawled": result.get("pages_crawled", 0),
                    "pages_new": result.get("pages_new", 0),
                    "pages_updated": result.get("pages_updated", 0),
                    "pages_failed": result.get("pages_failed", 0),
                    "documents_discovered": result.get("documents_discovered", 0),
                    "group_id": str(group_id),
                },
            )
            await session.commit()

            return result

        except Exception as e:
            logger.error(f"Scrape crawl error: {e}")
            await run_log_service.log_event(
                session=session,
                run_id=run_id,
                level="ERROR",
                event_type="error",
                message=str(e),
            )
            await run_service.fail_run(session, run_id, str(e))

            # Mark the group as failed (prevents post-job triggers)
            await run_group_service.mark_group_failed(session, group_id, str(e))

            await session.commit()
            raise


async def _fail_scrape_run(run_id, error_message: str):
    """Mark a scrape run as failed."""
    from app.core.shared.run_service import run_service

    async with database_service.get_session() as session:
        await run_service.fail_run(session, run_id, error_message)
        await session.commit()


# ============================================================================
# WEB SCRAPING DELETION TASK
# ============================================================================

async def _fail_deletion_run(run_id, error_message: str):
    """Mark a deletion run as failed."""
    from app.core.shared.run_service import run_service

    async with database_service.get_session() as session:
        await run_service.fail_run(session, run_id, error_message)
        await session.commit()


@shared_task(
    name="app.tasks.async_delete_scrape_collection_task",
    bind=True,
    queue="maintenance",
    soft_time_limit=1800,  # 30 minute soft limit
    time_limit=1860,  # 31 minute hard limit
)
def async_delete_scrape_collection_task(
    self,
    collection_id: str,
    organization_id: str,
    run_id: str,
    collection_name: str,
) -> Dict[str, Any]:
    """
    Asynchronously delete a scrape collection with full cleanup.

    This task performs a complete removal including:
    1. Cancel pending extraction jobs
    2. Delete files from MinIO storage (raw and extracted)
    3. Hard delete Asset records from database
    4. Remove documents from search index
    5. Delete ScrapedAsset records
    6. Delete ScrapeSource records
    7. Delete related Run records (except the deletion tracking run)
    8. Delete the collection itself
    9. Complete the tracking run with results summary

    Args:
        collection_id: ScrapeCollection UUID string
        organization_id: Organization UUID string
        run_id: Run UUID string (for tracking this deletion)
        collection_name: Name of the collection being deleted (for logging)

    Returns:
        Dict with deletion results
    """
    logger = logging.getLogger("curatore.tasks.scrape_delete")
    logger.info(f"Starting async deletion for scrape collection {collection_id} ({collection_name})")

    try:
        result = asyncio.run(
            _async_delete_scrape_collection(
                collection_id=uuid.UUID(collection_id),
                organization_id=uuid.UUID(organization_id),
                run_id=uuid.UUID(run_id),
                collection_name=collection_name,
            )
        )

        logger.info(f"Async deletion completed for collection {collection_id}: {result}")
        return result

    except Exception as e:
        logger.error(f"Async deletion failed for collection {collection_id}: {e}", exc_info=True)
        # Mark run as failed
        asyncio.run(_fail_deletion_run(uuid.UUID(run_id), str(e)))
        raise


async def _async_delete_scrape_collection(
    collection_id,
    organization_id,
    run_id,
    collection_name: str,
) -> Dict[str, Any]:
    """
    Async implementation of scrape collection deletion.
    """
    from sqlalchemy import delete as sql_delete

    from app.connectors.scrape.scrape_service import scrape_service
    from app.core.database.models import (
        Asset,
        AssetVersion,
        ExtractionResult,
        Run,
        RunLogEvent,
        ScrapeCollection,
        ScrapedAsset,
        ScrapeSource,
    )
    from app.core.search.pg_index_service import pg_index_service
    from app.core.shared.asset_service import asset_service
    from app.core.shared.run_log_service import run_log_service
    from app.core.shared.run_service import run_service
    from app.core.storage.minio_service import get_minio_service

    logger = logging.getLogger("curatore.tasks.scrape_delete")

    async with database_service.get_session() as session:
        # Start the run
        await run_service.start_run(session, run_id)
        await session.commit()

        await run_log_service.log_event(
            session=session,
            run_id=run_id,
            level="INFO",
            event_type="phase",
            message=f"Starting deletion of scrape collection: {collection_name}",
            context={"phase": "starting", "collection_id": str(collection_id)},
        )
        await session.commit()

        # Get the collection
        collection = await scrape_service.get_collection(session, collection_id)
        if not collection:
            await run_service.fail_run(session, run_id, "Collection not found")
            await session.commit()
            return {"error": "Collection not found"}

        minio = get_minio_service()

        stats = {
            "collection_name": collection_name,
            "assets_deleted": 0,
            "files_deleted": 0,
            "scraped_assets_deleted": 0,
            "sources_deleted": 0,
            "runs_deleted": 0,
            "extractions_cancelled": 0,
            "search_removed": 0,
            "storage_freed_bytes": 0,
            "errors": [],
        }

        # =================================================================
        # PHASE 1: CANCEL PENDING EXTRACTIONS
        # =================================================================
        await run_log_service.log_event(
            session=session,
            run_id=run_id,
            level="INFO",
            event_type="phase",
            message="Phase 1: Cancelling pending extraction jobs",
            context={"phase": "cancel_extractions"},
        )
        await session.commit()

        try:
            # Find and cancel extraction runs for assets in this collection
            scraped_result = await session.execute(
                select(ScrapedAsset.asset_id).where(
                    ScrapedAsset.collection_id == collection_id,
                    ScrapedAsset.asset_id.isnot(None),
                )
            )
            asset_ids = [str(row[0]) for row in scraped_result.all()]  # Convert UUIDs to strings

            if asset_ids:
                # Find pending extraction runs for these assets
                # Use Python filtering instead of array overlap for database compatibility
                pending_runs_result = await session.execute(
                    select(Run).where(
                        Run.run_type == "extraction",
                        Run.status.in_(["pending", "submitted", "running"]),
                    )
                )
                all_pending_runs = list(pending_runs_result.scalars().all())

                # Filter runs that have any of our asset IDs
                pending_runs = [
                    r for r in all_pending_runs
                    if r.input_asset_ids and any(str(aid) in [str(x) for x in r.input_asset_ids] for aid in asset_ids)
                ]

                for pending_run in pending_runs:
                    try:
                        pending_run.status = "cancelled"
                        pending_run.error_message = "Cancelled: collection being deleted"
                        stats["extractions_cancelled"] += 1
                    except Exception as e:
                        stats["errors"].append(f"Failed to cancel run {pending_run.id}: {e}")

                await session.commit()

            logger.info(f"Cancelled {stats['extractions_cancelled']} pending extractions")
        except Exception as e:
            stats["errors"].append(f"Failed to cancel extractions: {e}")
            logger.warning(f"Failed to cancel extractions: {e}")

        # =================================================================
        # PHASE 2: GET SCRAPED ASSETS
        # =================================================================
        await run_log_service.log_event(
            session=session,
            run_id=run_id,
            level="INFO",
            event_type="phase",
            message="Phase 2: Gathering scraped assets",
            context={"phase": "gather_assets"},
        )
        await session.commit()

        scraped_result = await session.execute(
            select(ScrapedAsset).where(ScrapedAsset.collection_id == collection_id)
        )
        scraped_assets = list(scraped_result.scalars().all())
        total_scraped = len(scraped_assets)

        await run_log_service.log_event(
            session=session,
            run_id=run_id,
            level="INFO",
            event_type="info",
            message=f"Found {total_scraped} scraped assets to delete",
            context={"total_scraped_assets": total_scraped},
        )
        await session.commit()

        # =================================================================
        # PHASE 3: DELETE ASSETS AND FILES
        # =================================================================
        await run_log_service.log_event(
            session=session,
            run_id=run_id,
            level="INFO",
            event_type="phase",
            message="Phase 3: Deleting assets and files",
            context={"phase": "delete_assets", "total": total_scraped},
        )
        await session.commit()

        processed = 0
        last_progress = 0

        for scraped in scraped_assets:
            if scraped.asset_id:
                try:
                    # Remove from search index
                    try:
                        await pg_index_service.delete_asset_index(session, organization_id, scraped.asset_id)
                        stats["search_removed"] += 1
                    except Exception as e:
                        stats["errors"].append(f"Search index removal failed for {scraped.asset_id}: {e}")

                    # Get asset to find file locations
                    asset = await asset_service.get_asset(session, scraped.asset_id)
                    if asset:
                        # Delete from MinIO (raw files)
                        if asset.storage_path:
                            try:
                                await minio.delete_file(asset.storage_path)
                                stats["files_deleted"] += 1
                            except Exception as e:
                                stats["errors"].append(f"MinIO raw delete failed: {e}")

                        # Delete extracted files
                        if asset.extraction_result:
                            if asset.extraction_result.storage_path:
                                try:
                                    await minio.delete_file(asset.extraction_result.storage_path)
                                    stats["files_deleted"] += 1
                                except Exception as e:
                                    stats["errors"].append(f"MinIO extracted delete failed: {e}")

                        # Delete extraction results
                        await session.execute(
                            sql_delete(ExtractionResult).where(
                                ExtractionResult.asset_id == scraped.asset_id
                            )
                        )

                        # Delete asset versions
                        await session.execute(
                            sql_delete(AssetVersion).where(
                                AssetVersion.asset_id == scraped.asset_id
                            )
                        )

                        # Delete the asset
                        await session.execute(
                            sql_delete(Asset).where(Asset.id == scraped.asset_id)
                        )
                        stats["assets_deleted"] += 1

                except Exception as e:
                    stats["errors"].append(f"Failed to delete asset {scraped.asset_id}: {e}")
                    logger.warning(f"Failed to delete asset {scraped.asset_id}: {e}")

            processed += 1

            # Update progress every 10%
            progress_pct = int((processed / total_scraped) * 100) if total_scraped > 0 else 100
            if progress_pct >= last_progress + 10:
                await run_service.update_run_progress(
                    session=session,
                    run_id=run_id,
                    current=processed,
                    total=total_scraped,
                    unit="assets",
                    phase="deleting_assets",
                )
                await session.commit()
                last_progress = progress_pct

        await session.commit()

        # =================================================================
        # PHASE 4: DELETE SCRAPED ASSET RECORDS
        # =================================================================
        await run_log_service.log_event(
            session=session,
            run_id=run_id,
            level="INFO",
            event_type="phase",
            message="Phase 4: Deleting scraped asset records",
            context={"phase": "delete_scraped_records"},
        )
        await session.commit()

        await session.execute(
            sql_delete(ScrapedAsset).where(ScrapedAsset.collection_id == collection_id)
        )
        stats["scraped_assets_deleted"] = total_scraped

        # =================================================================
        # PHASE 5: DELETE SOURCES
        # =================================================================
        await run_log_service.log_event(
            session=session,
            run_id=run_id,
            level="INFO",
            event_type="phase",
            message="Phase 5: Deleting sources",
            context={"phase": "delete_sources"},
        )
        await session.commit()

        sources_result = await session.execute(
            sql_delete(ScrapeSource).where(ScrapeSource.collection_id == collection_id)
        )
        stats["sources_deleted"] = sources_result.rowcount

        # =================================================================
        # PHASE 6: DELETE RELATED RUNS (EXCEPT THIS ONE)
        # =================================================================
        await run_log_service.log_event(
            session=session,
            run_id=run_id,
            level="INFO",
            event_type="phase",
            message="Phase 6: Deleting related crawl runs",
            context={"phase": "delete_runs"},
        )
        await session.commit()

        # Find all runs related to this collection (crawl runs)
        # Use run_type filter + Python filtering for database-agnostic JSON query
        runs_result = await session.execute(
            select(Run).where(
                Run.run_type.in_(["scrape_crawl", "scrape_delete"]),
                Run.id != run_id,  # Don't delete this deletion tracking run yet
            )
        )
        all_scrape_runs = list(runs_result.scalars().all())

        # Filter to runs matching this collection_id
        runs = [
            r for r in all_scrape_runs
            if r.config and r.config.get("collection_id") == str(collection_id)
        ]

        for related_run in runs:
            # Delete run log events first
            await session.execute(
                sql_delete(RunLogEvent).where(RunLogEvent.run_id == related_run.id)
            )
            await session.execute(
                sql_delete(Run).where(Run.id == related_run.id)
            )
            stats["runs_deleted"] += 1

        # =================================================================
        # PHASE 7: DELETE COLLECTION
        # =================================================================
        await run_log_service.log_event(
            session=session,
            run_id=run_id,
            level="INFO",
            event_type="phase",
            message="Phase 7: Deleting collection",
            context={"phase": "delete_collection"},
        )
        await session.commit()

        await session.execute(
            sql_delete(ScrapeCollection).where(ScrapeCollection.id == collection_id)
        )

        await session.commit()

        # =================================================================
        # PHASE 8: COMPLETE THE RUN
        # =================================================================
        status_msg = "completed successfully" if len(stats["errors"]) == 0 else "completed with errors"

        await run_service.complete_run(
            session=session,
            run_id=run_id,
            results_summary=stats,
        )

        await run_log_service.log_summary(
            session=session,
            run_id=run_id,
            message=f"Scrape collection deletion {status_msg}: {collection_name}",
            context={
                "assets_deleted": stats["assets_deleted"],
                "files_deleted": stats["files_deleted"],
                "scraped_assets_deleted": stats["scraped_assets_deleted"],
                "sources_deleted": stats["sources_deleted"],
                "runs_deleted": stats["runs_deleted"],
                "search_removed": stats["search_removed"],
                "storage_freed_mb": round(stats["storage_freed_bytes"] / (1024 * 1024), 2),
                "errors": stats["errors"][:5] if stats["errors"] else [],
                "status": "success" if len(stats["errors"]) == 0 else "partial",
            },
        )

        await session.commit()

        logger.info(
            f"Deleted scrape collection {collection_id} ({collection_name}) with cleanup: "
            f"assets={stats['assets_deleted']}, scraped={stats['scraped_assets_deleted']}, "
            f"sources={stats['sources_deleted']}, runs={stats['runs_deleted']}"
        )

        return stats
