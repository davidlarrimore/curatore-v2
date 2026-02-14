"""
SAM.gov Celery tasks for Curatore v2.

Handles SAM.gov data pulls, solicitation/notice refresh, attachment downloads,
summarization, and queued request processing.
"""
import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from celery import shared_task
from sqlalchemy import select

from app.celery_app import app as celery_app
from app.config import settings
from app.core.shared.config_loader import config_loader
from app.core.shared.database_service import database_service

# Logger for tasks
logger = logging.getLogger("curatore.tasks")


def _is_search_enabled() -> bool:
    """Check if search is enabled via config.yml or environment variables."""
    search_config = config_loader.get_search_config()
    if search_config:
        return search_config.enabled
    return getattr(settings, "search_enabled", True)


# ============================================================================
# HELPERS
# ============================================================================


def _extract_place_of_performance(place_of_performance: Optional[Dict]) -> Optional[str]:
    """
    Extract place of performance as a string from the JSON structure.

    The place_of_performance field has structure like:
    {
        "state": {"code": "VA", "name": "Virginia"},
        "zip": "20146",
        "country": {"code": "USA", "name": "UNITED STATES"}
    }

    Returns a formatted string like "Virginia, USA" or just the state/country name.
    """
    if not place_of_performance:
        return None

    parts = []

    # Try to get state name
    if "state" in place_of_performance and isinstance(place_of_performance["state"], dict):
        state_name = place_of_performance["state"].get("name")
        if state_name:
            parts.append(state_name)

    # Try to get country name
    if "country" in place_of_performance and isinstance(place_of_performance["country"], dict):
        country_name = place_of_performance["country"].get("name")
        if country_name and country_name != "UNITED STATES":  # Don't append if just USA
            parts.append(country_name)

    # Fallback to zip if nothing else
    if not parts and "zip" in place_of_performance:
        return place_of_performance["zip"]

    return ", ".join(parts) if parts else None


# ============================================================================
# SAM REINDEX TASK
# ============================================================================


@shared_task(name="app.tasks.reindex_sam_organization_task", bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 2})
def reindex_sam_organization_task(
    self,
    organization_id: str,
) -> Dict[str, Any]:
    """
    Reindex all SAM.gov data for an organization.

    This task indexes all existing SAM notices and solicitations to the
    search index for unified search. Useful for initial setup or recovery.

    Args:
        organization_id: Organization UUID string

    Returns:
        Dict with reindex statistics
    """
    from uuid import UUID

    logger = logging.getLogger("curatore.tasks.sam_indexing")

    # Check if search is enabled
    if not _is_search_enabled():
        logger.info("Search disabled, skipping SAM reindex")
        return {
            "status": "disabled",
            "message": "Search is disabled",
            "solicitations_indexed": 0,
            "notices_indexed": 0,
        }

    logger.info(f"Starting SAM reindex task for organization {organization_id}")

    try:
        result = asyncio.run(
            _reindex_sam_organization_async(UUID(organization_id))
        )

        logger.info(
            f"SAM reindex completed for org {organization_id}: "
            f"{result.get('solicitations_indexed', 0)} solicitations, "
            f"{result.get('notices_indexed', 0)} notices indexed"
        )
        return result

    except Exception as e:
        logger.error(f"SAM reindex task failed for org {organization_id}: {e}", exc_info=True)
        return {
            "status": "failed",
            "message": str(e),
            "solicitations_indexed": 0,
            "notices_indexed": 0,
        }


async def _reindex_sam_organization_async(
    organization_id,
) -> Dict[str, Any]:
    """
    Async wrapper for SAM organization reindex.

    Args:
        organization_id: Organization UUID

    Returns:
        Dict with reindex results
    """
    from app.connectors.sam_gov.sam_service import sam_service
    from app.core.search.pg_index_service import pg_index_service

    logger = logging.getLogger("curatore.tasks.sam_indexing")

    solicitations_indexed = 0
    notices_indexed = 0
    errors = []

    async with database_service.get_session() as session:
        # Get all solicitations for the organization
        solicitations, total_count = await sam_service.list_solicitations(
            session=session,
            organization_id=organization_id,
            limit=10000,  # Get all
        )

        logger.info(f"Found {total_count} solicitations to index")

        for solicitation in solicitations:
            try:
                # Index solicitation
                success = await pg_index_service.index_sam_solicitation(
                    session=session,
                    organization_id=organization_id,
                    solicitation_id=solicitation.id,
                    solicitation_number=solicitation.solicitation_number,
                    title=solicitation.title,
                    description=solicitation.description or "",
                    agency=solicitation.agency_name,
                    office=solicitation.office_name,
                    naics_code=solicitation.naics_code,
                    set_aside=solicitation.set_aside_code,
                    posted_date=solicitation.posted_date,
                    response_deadline=solicitation.response_deadline,
                    url=solicitation.sam_url,
                )
                if success:
                    solicitations_indexed += 1

                # Get and index notices for this solicitation
                notices = await sam_service.list_notices(
                    session=session,
                    solicitation_id=solicitation.id,
                )

                for notice in notices:
                    try:
                        success = await pg_index_service.index_sam_notice(
                            session=session,
                            organization_id=organization_id,
                            notice_id=notice.id,
                            sam_notice_id=notice.sam_notice_id,
                            solicitation_id=solicitation.id,
                            title=notice.title,
                            description=notice.description or "",
                            notice_type=notice.notice_type,
                            agency=solicitation.agency_name,
                            posted_date=notice.posted_date,
                            response_deadline=notice.response_deadline,
                            url=notice.sam_url,
                        )
                        if success:
                            notices_indexed += 1
                    except Exception as e:
                        errors.append(f"Notice {notice.id}: {str(e)}")

            except Exception as e:
                errors.append(f"Solicitation {solicitation.id}: {str(e)}")

    return {
        "status": "completed",
        "solicitations_indexed": solicitations_indexed,
        "notices_indexed": notices_indexed,
        "errors": errors[:10] if errors else [],
    }


# ============================================================================
# SAM.GOV TASKS (Phase 7)
# ============================================================================


@shared_task(name="app.tasks.sam_pull_task", bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def sam_pull_task(
    self,
    search_id: str,
    organization_id: str,
    max_pages: int = 10,
    page_size: int = 100,
    auto_download_attachments: bool = True,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Celery task to pull opportunities from SAM.gov API.

    This task fetches opportunities matching a search configuration and
    creates/updates solicitations, notices, and attachments in the database.

    Args:
        search_id: SamSearch UUID string
        organization_id: Organization UUID string
        max_pages: Maximum pages to fetch (default 10)
        page_size: Results per page (default 100)
        auto_download_attachments: Whether to download attachments after pull (default True)
        run_id: Optional pre-created Run UUID string. If provided, uses this Run instead of creating a new one.

    Returns:
        Dict containing:
            - search_id: The search UUID
            - status: success, partial, or failed
            - total_fetched: Number of opportunities fetched
            - new_solicitations: Number of new solicitations created
            - updated_solicitations: Number of solicitations updated
            - new_notices: Number of notices created
            - new_attachments: Number of attachments discovered
            - attachment_downloads: Attachment download results (if auto_download enabled)
            - errors: List of error details
    """
    from sqlalchemy import select

    from app.connectors.sam_gov.sam_pull_service import sam_pull_service
    from app.connectors.sam_gov.sam_service import sam_service
    from app.core.database.models import Run
    from app.core.ops.heartbeat_service import heartbeat_service
    from app.core.shared.run_group_service import run_group_service

    logger = logging.getLogger("curatore.sam")
    logger.info(f"Starting SAM pull task for search {search_id}" + (f" (run_id={run_id})" if run_id else ""))

    # Convert run_id to UUID if provided
    run_uuid = uuid.UUID(run_id) if run_id else None

    try:
        async def _execute_pull():
            nonlocal run_uuid
            async with database_service.get_session() as session:
                # If run_id was provided, use the existing Run; otherwise create a new one
                if run_uuid:
                    # Fetch the existing Run
                    run_result = await session.execute(
                        select(Run).where(Run.id == run_uuid)
                    )
                    run = run_result.scalar_one_or_none()
                    if not run:
                        logger.error(f"Run not found: {run_uuid}")
                        raise ValueError(f"Run not found: {run_uuid}")
                    # Update to running status
                    run.status = "running"
                    run.started_at = datetime.utcnow()
                    await session.commit()
                else:
                    # Create a new Run record (for backward compatibility / scheduled pulls)
                    run = Run(
                        organization_id=uuid.UUID(organization_id),
                        run_type="sam_pull",
                        origin="system",
                        status="running",
                        config={
                            "search_id": search_id,
                            "max_pages": max_pages,
                            "page_size": page_size,
                            "auto_download_attachments": auto_download_attachments,
                        },
                        started_at=datetime.utcnow(),
                    )
                    session.add(run)
                    await session.flush()
                    run_uuid = run.id

                    # Update the search with the run_id
                    search = await sam_service.get_search(session, uuid.UUID(search_id))
                    if search:
                        search.last_pull_run_id = run.id
                        await session.commit()

                # Get search config for automation settings
                search = await sam_service.get_search(session, uuid.UUID(search_id))
                automation_config = (search.automation_config or {}) if search else {}

                # Create a group to track child extraction jobs
                group = None
                group_id = None
                if auto_download_attachments:
                    # Build group config from automation settings
                    group_config = {
                        "search_id": search_id,
                        "search_name": search.name if search else None,
                    }

                    # Add after_procedure configuration if specified
                    after_procedure = automation_config.get("after_procedure_slug")
                    if after_procedure:
                        group_config["after_procedure_slug"] = after_procedure
                        group_config["after_procedure_params"] = automation_config.get(
                            "after_procedure_params", {}
                        )

                    group = await run_group_service.create_group(
                        session=session,
                        organization_id=uuid.UUID(organization_id),
                        group_type="sam_pull",
                        parent_run_id=run_uuid,
                        config=group_config,
                    )
                    group_id = group.id
                    logger.info(f"Created group {group_id} for SAM pull task")

                # Send heartbeat before starting pull
                await heartbeat_service.beat(session, run_uuid, progress={"phase": "starting_pull"})

                # Perform the pull
                result = await sam_pull_service.pull_opportunities(
                    session=session,
                    search_id=uuid.UUID(search_id),
                    organization_id=uuid.UUID(organization_id),
                    max_pages=max_pages,
                    page_size=page_size,
                    auto_download_attachments=auto_download_attachments,
                    run_id=run_uuid,
                    group_id=group_id,
                )

                # Heartbeat after pull completes
                await heartbeat_service.beat(session, run_uuid, progress={
                    "phase": "pull_complete",
                    "total_fetched": result.get("total_fetched", 0),
                })

                # Finalize group after pull completes (handles case where all children complete fast)
                if group:
                    await run_group_service.finalize_group(session, group.id)
                    logger.info(f"Finalized group {group.id} for SAM pull task")

                # Log completion summary
                from app.core.shared.run_log_service import run_log_service
                status = "completed" if result.get("status") == "success" else "failed"
                total_fetched = result.get("total_fetched", 0)
                new_solicitations = result.get("new_solicitations", 0)
                updated_solicitations = result.get("updated_solicitations", 0)
                new_notices = result.get("new_notices", 0)
                updated_notices = result.get("updated_notices", 0)
                new_attachments = result.get("new_attachments", 0)
                error_count = len(result.get("errors", []))

                await run_log_service.log_summary(
                    session=session,
                    run_id=run_uuid,
                    message=f"SAM.gov pull {status}: {total_fetched} fetched, {new_solicitations} new solicitations, {updated_solicitations} updated solicitations, {new_notices} new notices",
                    context={
                        "status": status,
                        "total_fetched": total_fetched,
                        "new_solicitations": new_solicitations,
                        "updated_solicitations": updated_solicitations,
                        "new_notices": new_notices,
                        "updated_notices": updated_notices,
                        "new_attachments": new_attachments,
                        "errors": error_count,
                    },
                )

                # Update Run with results
                run.status = status
                run.completed_at = datetime.utcnow()
                run.results_summary = {
                    "total_fetched": result.get("total_fetched", 0),
                    "new_solicitations": result.get("new_solicitations", 0),
                    "updated_solicitations": result.get("updated_solicitations", 0),
                    "new_notices": result.get("new_notices", 0),
                    "updated_notices": result.get("updated_notices", 0),
                    "new_attachments": result.get("new_attachments", 0),
                    "status": result.get("status"),
                }
                # Capture error message from either 'error' (single) or 'errors' (list)
                if result.get("error"):
                    run.error_message = result.get("error")
                elif result.get("errors"):
                    run.error_message = "; ".join(str(e) for e in result["errors"][:5])
                await session.commit()

                # Emit event for completed SAM pull
                if status == "completed":
                    from app.core.shared.event_service import event_service
                    try:
                        await event_service.emit(
                            session=session,
                            event_name="sam_pull.completed",
                            organization_id=uuid.UUID(organization_id),
                            payload={
                                "search_id": search_id,
                                "run_id": str(run_uuid),
                                "total_fetched": total_fetched,
                                "new_solicitations": new_solicitations,
                                "updated_solicitations": updated_solicitations,
                                "new_notices": new_notices,
                                "updated_notices": updated_notices,
                                "new_attachments": new_attachments,
                            },
                            source_run_id=run_uuid,
                        )
                    except Exception as event_error:
                        logger.warning(f"Failed to emit sam_pull.completed event: {event_error}")

                return result

        result = asyncio.run(_execute_pull())

        logger.info(
            f"SAM pull completed: {result.get('new_solicitations', 0)} new, "
            f"{result.get('updated_solicitations', 0)} updated"
        )

        if "attachment_downloads" in result:
            ad = result["attachment_downloads"]
            logger.info(
                f"Attachment downloads: {ad.get('downloaded', 0)} downloaded, "
                f"{ad.get('failed', 0)} failed"
            )

        return result

    except Exception as e:
        logger.error(f"SAM pull task failed: {e}")
        error_msg = str(e)

        # Update Run status to failed if we have a run_uuid
        if run_uuid:
            try:
                async def _mark_failed():
                    async with database_service.get_session() as session:
                        from sqlalchemy import select
                        result = await session.execute(
                            select(Run).where(Run.id == run_uuid)
                        )
                        run = result.scalar_one_or_none()
                        if run:
                            run.status = "failed"
                            run.completed_at = datetime.utcnow()
                            run.error_message = error_msg
                            await session.commit()
                asyncio.run(_mark_failed())
            except Exception as inner_e:
                logger.error(f"Failed to update run status: {inner_e}")

        raise


@celery_app.task(bind=True, name="app.tasks.sam_refresh_solicitation_task", autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 2})
def sam_refresh_solicitation_task(
    self,
    solicitation_id: str,
    organization_id: str,
    download_attachments: bool = True,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Celery task to refresh a solicitation from SAM.gov.

    Re-fetches solicitation data from SAM.gov API, updates notices and descriptions,
    and optionally downloads pending attachments.

    Args:
        solicitation_id: SamSolicitation UUID string
        organization_id: Organization UUID string
        download_attachments: Whether to download pending attachments (default True)
        run_id: Pre-created Run UUID string

    Returns:
        Dict containing:
            - solicitation_id: The solicitation UUID
            - status: success or failed
            - opportunities_found: Number of opportunities found
            - notices_created: New notices created
            - notices_updated: Notices updated
            - description_updated: Whether description was updated
            - attachments_downloaded: Number of attachments downloaded (if enabled)
            - error: Error message (if failed)
    """
    from app.connectors.sam_gov.sam_pull_service import sam_pull_service
    from app.core.database.models import Run
    from app.core.shared.run_log_service import run_log_service

    logger = logging.getLogger("curatore.sam")
    logger.info(f"Starting SAM refresh task for solicitation {solicitation_id}")

    run_uuid = uuid.UUID(run_id) if run_id else None

    try:
        async def _execute_refresh():
            nonlocal run_uuid
            async with database_service.get_session() as session:
                # Get existing Run or create new one
                if run_uuid:
                    run_result = await session.execute(
                        select(Run).where(Run.id == run_uuid)
                    )
                    run = run_result.scalar_one_or_none()
                    if not run:
                        raise ValueError(f"Run not found: {run_uuid}")
                    run.status = "running"
                    run.started_at = datetime.utcnow()
                else:
                    run = Run(
                        organization_id=uuid.UUID(organization_id),
                        run_type="sam_refresh",
                        origin="user",
                        status="running",
                        config={
                            "solicitation_id": solicitation_id,
                            "download_attachments": download_attachments,
                        },
                        started_at=datetime.utcnow(),
                    )
                    session.add(run)
                    await session.flush()
                    run_uuid = run.id
                await session.commit()

                # Log start
                await run_log_service.log_start(
                    session=session,
                    run_id=run_uuid,
                    message=f"Starting refresh for solicitation {solicitation_id}",
                    context={"download_attachments": download_attachments},
                )

                # Perform the refresh
                result = await sam_pull_service.refresh_solicitation(
                    session=session,
                    solicitation_id=uuid.UUID(solicitation_id),
                    organization_id=uuid.UUID(organization_id),
                )

                # Download attachments if requested and no errors
                attachments_downloaded = 0
                if download_attachments and not result.get("error"):
                    await run_log_service.log_event(
                        session=session,
                        run_id=run_uuid,
                        level="INFO",
                        event_type="progress",
                        message="Downloading pending attachments",
                        context={"phase": "downloading"},
                    )
                    download_result = await sam_pull_service.download_all_attachments(
                        session=session,
                        solicitation_id=uuid.UUID(solicitation_id),
                        organization_id=uuid.UUID(organization_id),
                    )
                    attachments_downloaded = download_result.get("downloaded", 0)
                    result["attachments_downloaded"] = attachments_downloaded
                    result["attachments_failed"] = download_result.get("failed", 0)

                # Determine status
                status = "failed" if result.get("error") else "completed"

                # Log summary
                summary_parts = []
                if result.get("opportunities_found", 0) > 0:
                    summary_parts.append(f"{result['opportunities_found']} opportunities found")
                if result.get("notices_created", 0) > 0:
                    summary_parts.append(f"{result['notices_created']} new notices")
                if result.get("notices_updated", 0) > 0:
                    summary_parts.append(f"{result['notices_updated']} notices updated")
                if result.get("description_updated"):
                    summary_parts.append("description updated")
                if attachments_downloaded > 0:
                    summary_parts.append(f"{attachments_downloaded} attachments downloaded")

                summary_msg = ", ".join(summary_parts) if summary_parts else "No changes"

                await run_log_service.log_summary(
                    session=session,
                    run_id=run_uuid,
                    message=f"Refresh {status}: {summary_msg}",
                    context={
                        "status": status,
                        **result,
                    },
                )

                # Update Run
                run_result = await session.execute(
                    select(Run).where(Run.id == run_uuid)
                )
                run = run_result.scalar_one()
                run.status = status
                run.completed_at = datetime.utcnow()
                run.results_summary = {
                    "opportunities_found": result.get("opportunities_found", 0),
                    "notices_created": result.get("notices_created", 0),
                    "notices_updated": result.get("notices_updated", 0),
                    "description_updated": result.get("description_updated", False),
                    "attachments_downloaded": attachments_downloaded,
                }
                if result.get("error"):
                    run.error_message = result["error"]
                await session.commit()

                return result

        result = asyncio.run(_execute_refresh())
        logger.info(f"SAM refresh completed for solicitation {solicitation_id}")
        return result

    except Exception as e:
        logger.error(f"SAM refresh task failed: {e}")
        error_msg = str(e)

        # Update Run to failed
        if run_uuid:
            try:
                async def _mark_failed():
                    async with database_service.get_session() as session:
                        run_result = await session.execute(
                            select(Run).where(Run.id == run_uuid)
                        )
                        run = run_result.scalar_one_or_none()
                        if run:
                            run.status = "failed"
                            run.completed_at = datetime.utcnow()
                            run.error_message = error_msg
                            await session.commit()
                asyncio.run(_mark_failed())
            except Exception as inner_e:
                logger.error(f"Failed to update run status: {inner_e}")

        raise


@celery_app.task(bind=True, name="app.tasks.sam_refresh_notice_task", autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 2})
def sam_refresh_notice_task(
    self,
    notice_id: str,
    organization_id: str,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Celery task to refresh a standalone notice from SAM.gov.

    Searches SAM.gov by notice ID to get full metadata and updates the notice.
    Also triggers auto-summary generation if the summary is pending.

    Args:
        notice_id: SamNotice UUID string
        organization_id: Organization UUID string
        run_id: Pre-created Run UUID string

    Returns:
        Dict containing:
            - notice_id: The notice UUID
            - status: success or failed
            - notice_updated: Whether notice was updated
            - summary_triggered: Whether summary generation was triggered
            - error: Error message (if failed)
    """
    from app.connectors.sam_gov.sam_pull_service import sam_pull_service
    from app.connectors.sam_gov.sam_service import sam_service
    from app.core.database.models import Run
    from app.core.shared.run_log_service import run_log_service

    logger = logging.getLogger("curatore.sam")
    logger.info(f"Starting SAM refresh task for notice {notice_id}")

    run_uuid = uuid.UUID(run_id) if run_id else None

    try:
        async def _execute_refresh():
            nonlocal run_uuid
            async with database_service.get_session() as session:
                # Get existing Run or create new one
                if run_uuid:
                    run_result = await session.execute(
                        select(Run).where(Run.id == run_uuid)
                    )
                    run = run_result.scalar_one_or_none()
                    if not run:
                        raise ValueError(f"Run not found: {run_uuid}")
                    run.status = "running"
                    run.started_at = datetime.utcnow()
                else:
                    run = Run(
                        organization_id=uuid.UUID(organization_id),
                        run_type="sam_refresh",
                        origin="user",
                        status="running",
                        config={
                            "notice_id": notice_id,
                        },
                        started_at=datetime.utcnow(),
                    )
                    session.add(run)
                    await session.flush()
                    run_uuid = run.id
                await session.commit()

                # Get the notice
                notice = await sam_service.get_notice(session, uuid.UUID(notice_id))
                if not notice:
                    raise ValueError(f"Notice not found: {notice_id}")

                # Log start
                await run_log_service.log_start(
                    session=session,
                    run_id=run_uuid,
                    message=f"Starting refresh for notice: {notice.title or notice.sam_notice_id}",
                    context={"notice_id": notice_id, "sam_notice_id": notice.sam_notice_id},
                )
                await session.commit()

                result = {
                    "notice_id": notice_id,
                    "notice_updated": False,
                    "summary_triggered": False,
                    "opportunities_found": 0,
                }

                # Search SAM.gov by notice ID
                search_config = {
                    "notice_id": notice.sam_notice_id,
                    "active_only": False,
                }

                await run_log_service.log_event(
                    session=session,
                    run_id=run_uuid,
                    level="INFO",
                    event_type="progress",
                    message=f"Searching SAM.gov for notice {notice.sam_notice_id}",
                    context={"phase": "searching"},
                )
                await session.commit()

                opportunities, total = await sam_pull_service.search_opportunities(
                    search_config,
                    limit=10,
                    session=session,
                    organization_id=uuid.UUID(organization_id),
                )

                result["opportunities_found"] = len(opportunities)

                if opportunities:
                    opp = opportunities[0]

                    # Fetch full description
                    description = opp.get("description")
                    description_url = None
                    if description and description.startswith("http"):
                        description_url = description
                        full_description = await sam_pull_service.fetch_notice_description(
                            notice.sam_notice_id, session, uuid.UUID(organization_id)
                        )
                        if full_description:
                            description = full_description

                    # Update notice with all metadata
                    await sam_service.update_notice(
                        session,
                        notice_id=uuid.UUID(notice_id),
                        title=opp.get("title"),
                        description=description,
                        description_url=description_url,
                        response_deadline=opp.get("response_deadline"),
                        raw_data=opp.get("raw_data"),
                        full_parent_path=opp.get("full_parent_path"),
                        agency_name=opp.get("agency_name"),
                        bureau_name=opp.get("bureau_name"),
                        office_name=opp.get("office_name"),
                        naics_code=opp.get("naics_code"),
                        psc_code=opp.get("psc_code"),
                        set_aside_code=opp.get("set_aside_code"),
                        ui_link=opp.get("ui_link"),
                    )
                    result["notice_updated"] = True

                    await run_log_service.log_event(
                        session=session,
                        run_id=run_uuid,
                        level="INFO",
                        event_type="progress",
                        message="Updated notice with SAM.gov metadata",
                        context={"agency": opp.get("agency_name"), "has_description": bool(description)},
                    )
                    await session.commit()

                    # Trigger auto-summary if pending
                    # Re-fetch notice to get current state
                    notice = await sam_service.get_notice(session, uuid.UUID(notice_id))
                    if notice and notice.summary_status in ("pending", None):
                        notice.summary_status = "generating"
                        await session.commit()

                        sam_auto_summarize_notice_task.delay(
                            notice_id=notice_id,
                            organization_id=organization_id,
                        )
                        result["summary_triggered"] = True

                        await run_log_service.log_event(
                            session=session,
                            run_id=run_uuid,
                            level="INFO",
                            event_type="progress",
                            message="Triggered auto-summary generation",
                            context={"phase": "summary"},
                        )
                        await session.commit()
                else:
                    # No results from SAM.gov search
                    await run_log_service.log_event(
                        session=session,
                        run_id=run_uuid,
                        level="WARN",
                        event_type="progress",
                        message="No results found from SAM.gov search",
                        context={"sam_notice_id": notice.sam_notice_id},
                    )
                    await session.commit()

                # Log summary
                status = "completed"
                summary_msg = "Notice updated" if result["notice_updated"] else "No changes"
                if result["summary_triggered"]:
                    summary_msg += ", summary generation triggered"

                await run_log_service.log_summary(
                    session=session,
                    run_id=run_uuid,
                    message=f"Refresh {status}: {summary_msg}",
                    context={"status": status, **result},
                )

                # Update Run
                run_result = await session.execute(
                    select(Run).where(Run.id == run_uuid)
                )
                run = run_result.scalar_one()
                run.status = status
                run.completed_at = datetime.utcnow()
                run.results_summary = result
                await session.commit()

                return result

        result = asyncio.run(_execute_refresh())
        logger.info(f"SAM refresh completed for notice {notice_id}")
        return result

    except Exception as e:
        logger.error(f"SAM notice refresh task failed: {e}")
        error_msg = str(e)

        # Update Run to failed
        if run_uuid:
            try:
                async def _mark_failed():
                    async with database_service.get_session() as session:
                        run_result = await session.execute(
                            select(Run).where(Run.id == run_uuid)
                        )
                        run = run_result.scalar_one_or_none()
                        if run:
                            run.status = "failed"
                            run.completed_at = datetime.utcnow()
                            run.error_message = error_msg
                            await session.commit()
                asyncio.run(_mark_failed())
            except Exception as inner_e:
                logger.error(f"Failed to update run status: {inner_e}")

        raise


@shared_task(name="app.tasks.sam_download_attachment_task", bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def sam_download_attachment_task(
    self,
    attachment_id: str,
    organization_id: str,
) -> Dict[str, Any]:
    """
    Celery task to download a single attachment from SAM.gov.

    Downloads the attachment and creates an Asset for extraction.

    Args:
        attachment_id: SamAttachment UUID string
        organization_id: Organization UUID string

    Returns:
        Dict containing:
            - attachment_id: The attachment UUID
            - asset_id: Created Asset UUID (if successful)
            - status: downloaded or failed
            - error: Error message (if failed)
    """
    from app.connectors.sam_gov.sam_pull_service import sam_pull_service

    logger = logging.getLogger("curatore.sam")
    logger.info(f"Starting SAM attachment download task for {attachment_id}")

    try:
        async def _download():
            async with database_service.get_session() as session:
                asset = await sam_pull_service.download_attachment(
                    session=session,
                    attachment_id=uuid.UUID(attachment_id),
                    organization_id=uuid.UUID(organization_id),
                )
                return asset

        asset = asyncio.run(_download())

        if asset:
            logger.info(f"Attachment {attachment_id} downloaded -> Asset {asset.id}")
            return {
                "attachment_id": attachment_id,
                "asset_id": str(asset.id),
                "status": "downloaded",
            }
        else:
            return {
                "attachment_id": attachment_id,
                "status": "failed",
                "error": "Download failed - check attachment record for details",
            }

    except Exception as e:
        logger.error(f"SAM attachment download task failed: {e}")
        raise


@shared_task(name="app.tasks.sam_summarize_task", bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 2})
def sam_summarize_task(
    self,
    solicitation_id: str,
    organization_id: str,
    summary_type: str = "executive",
    model: Optional[str] = None,
    include_attachments: bool = True,
) -> Dict[str, Any]:
    """
    Celery task to generate an LLM summary for a solicitation.

    Args:
        solicitation_id: SamSolicitation UUID string
        organization_id: Organization UUID string
        summary_type: Type of summary (executive, technical, compliance, full)
        model: LLM model to use (None = default)
        include_attachments: Whether to include extracted attachment content

    Returns:
        Dict containing:
            - solicitation_id: The solicitation UUID
            - summary_id: Created summary UUID (if successful)
            - summary_type: Type of summary generated
            - status: success or failed
            - error: Error message (if failed)
    """
    from app.connectors.sam_gov.sam_summarization_service import sam_summarization_service

    logger = logging.getLogger("curatore.sam")
    logger.info(f"Starting SAM summarize task for solicitation {solicitation_id}")

    try:
        async def _summarize():
            async with database_service.get_session() as session:
                return await sam_summarization_service.summarize_solicitation(
                    session=session,
                    solicitation_id=uuid.UUID(solicitation_id),
                    organization_id=uuid.UUID(organization_id),
                    summary_type=summary_type,
                    model=model,
                    include_attachments=include_attachments,
                )

        summary = asyncio.run(_summarize())

        if summary:
            logger.info(f"Summary {summary.id} generated for solicitation {solicitation_id}")
            return {
                "solicitation_id": solicitation_id,
                "summary_id": str(summary.id),
                "summary_type": summary_type,
                "status": "success",
            }
        else:
            return {
                "solicitation_id": solicitation_id,
                "summary_type": summary_type,
                "status": "failed",
                "error": "Summary generation failed",
            }

    except Exception as e:
        logger.error(f"SAM summarize task failed: {e}")
        raise


@shared_task(name="app.tasks.sam_batch_summarize_task", bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 2})
def sam_batch_summarize_task(
    self,
    search_id: str,
    organization_id: str,
    summary_type: str = "executive",
    model: Optional[str] = None,
    limit: int = 10,
) -> Dict[str, Any]:
    """
    Celery task to generate summaries for multiple solicitations.

    Args:
        search_id: SamSearch UUID string
        organization_id: Organization UUID string
        summary_type: Type of summary to generate
        model: LLM model to use (None = default)
        limit: Maximum solicitations to summarize

    Returns:
        Dict containing:
            - search_id: The search UUID
            - summary_type: Type of summary generated
            - total_candidates: Total solicitations eligible
            - processed: Number processed
            - success: Number successfully summarized
            - failed: Number failed
            - errors: List of error details
    """
    from app.connectors.sam_gov.sam_summarization_service import sam_summarization_service

    logger = logging.getLogger("curatore.sam")
    logger.info(f"Starting SAM batch summarize task for search {search_id}")

    try:
        async def _batch_summarize():
            async with database_service.get_session() as session:
                return await sam_summarization_service.batch_summarize(
                    session=session,
                    search_id=uuid.UUID(search_id),
                    organization_id=uuid.UUID(organization_id),
                    summary_type=summary_type,
                    model=model,
                    limit=limit,
                )

        result = asyncio.run(_batch_summarize())

        logger.info(
            f"Batch summarize completed: {result.get('success', 0)} succeeded, "
            f"{result.get('failed', 0)} failed"
        )

        return {
            "search_id": search_id,
            "summary_type": summary_type,
            **result,
        }

    except Exception as e:
        logger.error(f"SAM batch summarize task failed: {e}")
        raise


@shared_task(name="app.tasks.sam_auto_summarize_task", bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 5})
def sam_auto_summarize_task(
    self,
    solicitation_id: str,
    organization_id: str,
    is_update: bool = False,
    wait_for_assets: bool = True,
    _retry_count: int = 0,
) -> Dict[str, Any]:
    """
    Celery task to auto-generate a summary for a solicitation after pull.

    This task is triggered automatically after a SAM pull to generate
    BD-focused summaries using LLM. If no LLM is configured, falls back
    to using the notice description.

    Priority Queue Behavior:
    - This task runs on the 'processing_priority' queue
    - If attachments have pending extractions, it boosts their priority
    - Task will retry until all assets are ready (up to 5 retries)

    Args:
        solicitation_id: SamSolicitation UUID string
        organization_id: Organization UUID string
        is_update: Whether this is an update (new notice added)
        wait_for_assets: Whether to wait for pending asset extractions
        _retry_count: Internal retry counter for asset waiting

    Returns:
        Dict containing:
            - solicitation_id: The solicitation UUID
            - status: pending, ready, failed, no_llm, or waiting_for_assets
            - summary_preview: First 200 chars of summary (if generated)
    """
    from datetime import datetime

    from app.connectors.sam_gov.sam_service import sam_service
    from app.connectors.sam_gov.sam_summarization_service import sam_summarization_service

    logger = logging.getLogger("curatore.sam")
    logger.info(f"Starting SAM auto-summarize task for solicitation {solicitation_id}")

    try:
        async def _check_and_boost_pending_assets():
            """Check for pending assets and boost their priority using the priority queue service."""
            from app.core.ops.priority_queue_service import (
                BoostReason,
                priority_queue_service,
            )

            async with database_service.get_session() as session:
                # Get all attachment assets for this solicitation
                asset_ids = await priority_queue_service.get_solicitation_attachment_assets(
                    session=session,
                    solicitation_id=uuid.UUID(solicitation_id),
                )

                if not asset_ids:
                    return True, []  # No assets to wait for

                # Check which are ready
                all_ready, ready_ids, pending_ids = await priority_queue_service.check_assets_ready(
                    session=session,
                    asset_ids=asset_ids,
                )

                if all_ready:
                    return True, []

                # Boost pending assets
                boost_result = await priority_queue_service.boost_multiple_extractions(
                    session=session,
                    asset_ids=pending_ids,
                    reason=BoostReason.SAM_SUMMARIZATION,
                    organization_id=uuid.UUID(organization_id),
                )

                logger.info(
                    f"Solicitation {solicitation_id}: {len(pending_ids)} pending assets, "
                    f"boosted {boost_result['boosted']} extractions"
                )

                return False, pending_ids

        # Check for pending assets if configured to wait
        if wait_for_assets:
            all_ready, pending_ids = asyncio.run(_check_and_boost_pending_assets())

            if not all_ready and _retry_count < 10:  # Max 10 retries (about 5 minutes total)
                logger.info(
                    f"Waiting for {len(pending_ids)} assets to complete extraction, "
                    f"retry {_retry_count + 1}/10"
                )
                # Update status to indicate waiting
                async def _update_waiting_status():
                    async with database_service.get_session() as session:
                        await sam_service.update_solicitation_summary_status(
                            session=session,
                            solicitation_id=uuid.UUID(solicitation_id),
                            status="generating",  # Still show generating
                        )
                asyncio.run(_update_waiting_status())

                # Retry after 30 seconds
                sam_auto_summarize_task.apply_async(
                    kwargs={
                        "solicitation_id": solicitation_id,
                        "organization_id": organization_id,
                        "is_update": is_update,
                        "wait_for_assets": True,
                        "_retry_count": _retry_count + 1,
                    },
                    countdown=30,
                    queue="processing_priority",
                )
                return {
                    "solicitation_id": solicitation_id,
                    "status": "waiting_for_assets",
                    "pending_assets": len(pending_ids),
                    "retry_count": _retry_count + 1,
                }

        async def _generate_summary():
            async with database_service.get_session() as session:
                # Generate the summary
                summary = await sam_summarization_service.generate_auto_summary(
                    session=session,
                    solicitation_id=uuid.UUID(solicitation_id),
                    organization_id=uuid.UUID(organization_id),
                    is_update=is_update,
                )

                if summary:
                    # Determine status based on whether LLM was used
                    has_llm = bool(settings.openai_api_key)
                    status = "ready" if has_llm else "no_llm"

                    # Update solicitation with summary and status
                    await sam_service.update_solicitation_summary_status(
                        session=session,
                        solicitation_id=uuid.UUID(solicitation_id),
                        status=status,
                        summary_generated_at=datetime.utcnow() if status == "ready" else None,
                    )

                    # Also update the description field if we have a summary
                    from sqlalchemy import update

                    from app.core.database.models import SamSolicitation
                    await session.execute(
                        update(SamSolicitation)
                        .where(SamSolicitation.id == uuid.UUID(solicitation_id))
                        .values(description=summary)
                    )
                    await session.commit()

                    return {
                        "solicitation_id": solicitation_id,
                        "status": status,
                        "summary_preview": summary[:200] + "..." if len(summary) > 200 else summary,
                    }
                else:
                    # Mark as failed
                    await sam_service.update_solicitation_summary_status(
                        session=session,
                        solicitation_id=uuid.UUID(solicitation_id),
                        status="failed",
                    )

                    return {
                        "solicitation_id": solicitation_id,
                        "status": "failed",
                        "error": "Summary generation returned None",
                    }

        result = asyncio.run(_generate_summary())
        logger.info(f"Auto-summarize completed for {solicitation_id}: status={result.get('status')}")
        return result

    except Exception as e:
        logger.error(f"SAM auto-summarize task failed: {e}")

        # Mark as failed in DB
        try:
            async def _mark_failed():
                async with database_service.get_session() as session:
                    await sam_service.update_solicitation_summary_status(
                        session=session,
                        solicitation_id=uuid.UUID(solicitation_id),
                        status="failed",
                    )

            asyncio.run(_mark_failed())
        except Exception as inner_e:
            logger.error(f"Failed to mark solicitation as failed: {inner_e}")

        raise


@shared_task(name="app.tasks.sam_auto_summarize_notice_task", bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def sam_auto_summarize_notice_task(
    self,
    notice_id: str,
    organization_id: str,
    wait_for_assets: bool = True,
    _retry_count: int = 0,
) -> Dict[str, Any]:
    """
    Celery task to auto-generate a summary for a notice.

    Works for both standalone notices (Special Notices without solicitation)
    and solicitation-linked notices. Uses the notice's metadata, description,
    and any attached documents to generate a comprehensive summary.

    Args:
        notice_id: SamNotice UUID string
        organization_id: Organization UUID string
        wait_for_assets: If True, retry if attachments are still processing
        _retry_count: Internal retry counter for asset waiting

    Returns:
        Dict containing:
            - notice_id: The notice UUID
            - status: pending, ready, failed, no_llm, or waiting_for_assets
            - summary_preview: First 200 chars of summary (if generated)
    """
    from datetime import datetime

    from app.connectors.sam_gov.sam_service import sam_service
    from app.core.database.models import ExtractionResult
    from app.core.llm.llm_service import LLMService

    logger = logging.getLogger("curatore.sam")
    logger.info(f"Starting SAM auto-summarize task for notice {notice_id}")

    MAX_ASSET_WAIT_RETRIES = 10

    try:
        async def _generate_notice_summary():
            async with database_service.get_session() as session:
                # Get the notice with attachments
                notice = await sam_service.get_notice(session, uuid.UUID(notice_id))
                if not notice:
                    logger.error(f"Notice not found: {notice_id}")
                    return {"notice_id": notice_id, "status": "failed", "error": "Notice not found"}

                # Check if we should wait for asset processing
                if wait_for_assets and notice.attachments:
                    pending_assets = [
                        att for att in notice.attachments
                        if att.download_status == "downloaded" and att.asset_id
                    ]

                    if pending_assets:
                        # Check if any extractions are still pending
                        from sqlalchemy import and_, select
                        pending_extractions = await session.execute(
                            select(ExtractionResult)
                            .where(
                                and_(
                                    ExtractionResult.asset_id.in_([a.asset_id for a in pending_assets]),
                                    ExtractionResult.status.in_(["pending", "running"])
                                )
                            )
                        )
                        if pending_extractions.scalars().first() and _retry_count < MAX_ASSET_WAIT_RETRIES:
                            logger.info(f"Notice {notice_id} has pending extractions, retrying in 30s...")
                            notice.summary_status = "pending"
                            await session.commit()

                            # Schedule retry
                            sam_auto_summarize_notice_task.apply_async(
                                kwargs={
                                    "notice_id": notice_id,
                                    "organization_id": organization_id,
                                    "wait_for_assets": True,
                                    "_retry_count": _retry_count + 1,
                                },
                                countdown=30,
                                queue="sam",
                            )
                            return {"notice_id": notice_id, "status": "waiting_for_assets"}

                # Check for LLM availability (infrastructure service, global config)
                has_llm = bool(settings.openai_api_key)

                if not has_llm:
                    # No LLM - mark as no_llm, keep original description
                    notice.summary_status = "no_llm"
                    await session.commit()
                    logger.info(f"No LLM available for notice {notice_id}, using original description")
                    return {"notice_id": notice_id, "status": "no_llm"}

                # Update status to generating
                notice.summary_status = "generating"
                await session.commit()

                # Get extracted content from attachments
                attachment_content = ""
                if notice.attachments:
                    from app.core.storage.minio_service import get_minio_service
                    minio = get_minio_service()

                    content_parts = []
                    for att in notice.attachments:
                        if att.download_status == "downloaded" and att.asset_id:
                            # Get extraction result
                            extraction = await session.execute(
                                select(ExtractionResult)
                                .where(ExtractionResult.asset_id == att.asset_id)
                                .where(ExtractionResult.status == "completed")
                                .order_by(ExtractionResult.created_at.desc())
                                .limit(1)
                            )
                            ext_result = extraction.scalar_one_or_none()

                            if ext_result and ext_result.extracted_object_key:
                                try:
                                    content = await minio.download_text(
                                        bucket=ext_result.extracted_bucket,
                                        object_key=ext_result.extracted_object_key,
                                    )
                                    if content:
                                        content_parts.append(f"\n--- Attachment: {att.filename} ---\n{content[:5000]}")
                                except Exception as e:
                                    logger.warning(f"Failed to fetch attachment content: {e}")

                    if content_parts:
                        attachment_content = "\n".join(content_parts)

                # Build the prompt
                notice_type_name = {
                    "o": "Solicitation",
                    "p": "Presolicitation",
                    "k": "Combined Synopsis/Solicitation",
                    "r": "Sources Sought",
                    "s": "Special Notice",
                    "a": "Amendment",
                    "i": "Intent to Bundle",
                    "g": "Sale of Surplus Property",
                }.get(notice.notice_type, notice.notice_type or "Notice")

                prompt = f"""You are a Business Development analyst at a government contracting company.
Analyze this SAM.gov {notice_type_name} and provide a comprehensive summary.

NOTICE INFORMATION:
Title: {notice.title or 'Untitled'}
Type: {notice_type_name}
Agency: {notice.agency_name or 'Unknown'}
Sub-Agency/Bureau: {notice.bureau_name or 'N/A'}
Office: {notice.office_name or 'N/A'}
NAICS Code: {notice.naics_code or 'N/A'}
PSC Code: {notice.psc_code or 'N/A'}
Set-Aside: {notice.set_aside_code or 'None'}
Posted Date: {notice.posted_date.strftime('%Y-%m-%d') if notice.posted_date else 'Unknown'}
Response Deadline: {notice.response_deadline.strftime('%Y-%m-%d %H:%M') if notice.response_deadline else 'N/A'}

NOTICE DESCRIPTION:
{notice.description or 'No description available'}

{f"ATTACHMENT CONTENT:{attachment_content}" if attachment_content else ""}

Provide your analysis in the following JSON format:
{{
    "summary": "A 2-3 paragraph summary explaining: (1) What this notice is about and its purpose; (2) Key requirements, information, or announcements; (3) Important dates and action items",
    "notice_purpose": "Brief one-line description of the notice's primary purpose",
    "key_information": [
        {{"item": "Important detail or requirement", "category": "Requirements/Dates/Contacts/Action Items"}}
    ],
    "dates": {{
        "posted": "Date posted",
        "response_deadline": "Response deadline or 'N/A'",
        "other_dates": ["Any other relevant dates mentioned"]
    }},
    "contacts": [
        {{"name": "Contact name", "email": "Email", "phone": "Phone"}}
    ],
    "recommendation": "pursue/monitor/pass",
    "recommendation_rationale": "Brief explanation of why BD team should take this action"
}}

Respond ONLY with valid JSON, no additional text."""

                # Create LLM client from database connection or use default
                llm_service = LLMService()
                client = None
                model = settings.openai_model or "gpt-4o-mini"

                if llm_conn and llm_conn.is_active and llm_conn.config.get("api_key"):
                    client = await llm_service._create_client_from_config(llm_conn.config)
                    model = llm_conn.config.get("model", model)
                    logger.info(f"Using database LLM connection for notice summary: {llm_conn.name}")

                if not client:
                    client = llm_service._client

                if not client:
                    logger.error(f"No LLM client available for notice {notice_id}")
                    notice.summary_status = "failed"
                    await session.commit()
                    return {"notice_id": notice_id, "status": "failed", "error": "No LLM client available"}

                # Call LLM
                try:
                    response = client.chat.completions.create(
                        model=model,
                        messages=[
                            {
                                "role": "system",
                                "content": "You are a Business Development analyst at a government contracting company. Provide accurate, professional analysis of federal notices.",
                            },
                            {"role": "user", "content": prompt},
                        ],
                        temperature=0.3,
                        max_tokens=4000,
                    )

                    response_text = response.choices[0].message.content
                    if not response_text:
                        notice.summary_status = "failed"
                        await session.commit()
                        return {"notice_id": notice_id, "status": "failed", "error": "LLM returned empty response"}

                    # Parse JSON response
                    import json
                    import re

                    parsed = None
                    try:
                        parsed = json.loads(response_text)
                    except json.JSONDecodeError:
                        # Try to extract JSON from markdown
                        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", response_text)
                        if json_match:
                            try:
                                parsed = json.loads(json_match.group(1))
                            except json.JSONDecodeError:
                                pass
                        if not parsed:
                            json_match = re.search(r"\{[\s\S]*\}", response_text)
                            if json_match:
                                try:
                                    parsed = json.loads(json_match.group(0))
                                except json.JSONDecodeError:
                                    pass

                    if parsed:
                        summary = parsed.get("summary", "")
                        recommendation = parsed.get("recommendation", "")
                        rationale = parsed.get("recommendation_rationale", "")
                        if recommendation and rationale:
                            summary += f"\n\n**Recommendation: {recommendation.upper()}** - {rationale}"
                    else:
                        summary = response_text[:2000]

                    # Update notice with generated summary
                    notice.description = summary
                    notice.summary_status = "ready"
                    notice.summary_generated_at = datetime.utcnow()
                    await session.commit()

                    logger.info(f"Generated summary for notice {notice_id}")
                    return {
                        "notice_id": notice_id,
                        "status": "ready",
                        "summary_preview": summary[:200] + "..." if len(summary) > 200 else summary,
                    }

                except Exception as e:
                    logger.error(f"LLM error for notice {notice_id}: {e}")
                    notice.summary_status = "failed"
                    await session.commit()
                    return {"notice_id": notice_id, "status": "failed", "error": str(e)}

        result = asyncio.run(_generate_notice_summary())
        logger.info(f"Auto-summarize completed for notice {notice_id}: status={result.get('status')}")
        return result

    except Exception as e:
        logger.error(f"SAM notice auto-summarize task failed: {e}")

        # Mark as failed in DB
        try:
            async def _mark_failed():
                async with database_service.get_session() as session:
                    from app.connectors.sam_gov.sam_service import sam_service
                    notice = await sam_service.get_notice(session, uuid.UUID(notice_id))
                    if notice:
                        notice.summary_status = "failed"
                        await session.commit()

            asyncio.run(_mark_failed())
        except Exception as inner_e:
            logger.error(f"Failed to mark notice as failed: {inner_e}")

        raise


@shared_task(name="app.tasks.sam_process_queued_requests_task", bind=True)
def sam_process_queued_requests_task(
    self,
    organization_id: Optional[str] = None,
    limit: int = 50,
) -> Dict[str, Any]:
    """
    Celery task to process queued SAM.gov API requests.

    When API rate limits are exceeded, requests are queued for later execution.
    This task processes pending requests that are past their scheduled time.

    Should be scheduled to run regularly (e.g., every 5 minutes or hourly).

    Args:
        organization_id: Optional org to process (None = all orgs)
        limit: Maximum requests to process in this run

    Returns:
        Dict containing:
            - processed: Number of requests processed
            - succeeded: Number that succeeded
            - failed: Number that failed
            - remaining: Number still pending
            - errors: List of error details
    """
    from app.connectors.sam_gov.sam_api_usage_service import sam_api_usage_service
    from app.connectors.sam_gov.sam_pull_service import sam_pull_service

    logger = logging.getLogger("curatore.sam")
    logger.info("Starting SAM queue processing task")

    results = {
        "processed": 0,
        "succeeded": 0,
        "failed": 0,
        "remaining": 0,
        "errors": [],
    }

    try:
        async def _process_queue():
            async with database_service.get_session() as session:
                org_uuid = uuid.UUID(organization_id) if organization_id else None

                # Get pending requests
                pending = await sam_api_usage_service.get_pending_requests(
                    session, org_uuid, limit
                )

                if not pending:
                    logger.info("No pending SAM requests to process")
                    return results

                for request in pending:
                    # Check rate limit before processing
                    can_call, remaining = await sam_api_usage_service.check_limit(
                        session, request.organization_id
                    )

                    if not can_call:
                        logger.info(
                            f"Rate limit still exceeded for org {request.organization_id}, "
                            f"skipping request {request.id}"
                        )
                        continue

                    # Mark as processing
                    await sam_api_usage_service.mark_request_processing(
                        session, request.id
                    )
                    results["processed"] += 1

                    try:
                        if request.request_type == "search":
                            # Re-execute the search
                            # This would typically be handled by re-triggering sam_pull_task
                            # For now, we'll mark it completed with a note
                            await sam_api_usage_service.mark_request_completed(
                                session, request.id,
                                result={"note": "Queued search should be re-triggered manually"}
                            )
                            results["succeeded"] += 1

                        elif request.request_type == "attachment":
                            # Process attachment download
                            attachment_id = request.attachment_id or request.request_params.get("attachment_id")
                            if attachment_id:
                                asset = await sam_pull_service.download_attachment(
                                    session=session,
                                    attachment_id=uuid.UUID(str(attachment_id)),
                                    organization_id=request.organization_id,
                                    check_rate_limit=True,  # Will record the call
                                )
                                if asset:
                                    await sam_api_usage_service.mark_request_completed(
                                        session, request.id,
                                        result={"asset_id": str(asset.id)}
                                    )
                                    results["succeeded"] += 1
                                else:
                                    await sam_api_usage_service.mark_request_failed(
                                        session, request.id,
                                        error="Attachment download failed"
                                    )
                                    results["failed"] += 1
                            else:
                                await sam_api_usage_service.mark_request_failed(
                                    session, request.id,
                                    error="No attachment_id in request params"
                                )
                                results["failed"] += 1

                        elif request.request_type == "detail":
                            # Detail requests are typically retried inline
                            await sam_api_usage_service.mark_request_completed(
                                session, request.id,
                                result={"note": "Detail request should be re-triggered manually"}
                            )
                            results["succeeded"] += 1

                        else:
                            await sam_api_usage_service.mark_request_failed(
                                session, request.id,
                                error=f"Unknown request type: {request.request_type}"
                            )
                            results["failed"] += 1

                    except Exception as e:
                        logger.error(f"Error processing queued request {request.id}: {e}")
                        await sam_api_usage_service.mark_request_failed(
                            session, request.id,
                            error=str(e)
                        )
                        results["failed"] += 1
                        results["errors"].append({
                            "request_id": str(request.id),
                            "error": str(e),
                        })

                # Get remaining count
                remaining_requests = await sam_api_usage_service.get_pending_requests(
                    session, org_uuid, limit=1000
                )
                results["remaining"] = len(remaining_requests)

                return results

        result = asyncio.run(_process_queue())

        logger.info(
            f"SAM queue processing completed: {result['succeeded']} succeeded, "
            f"{result['failed']} failed, {result['remaining']} remaining"
        )

        return result

    except Exception as e:
        logger.error(f"SAM queue processing task failed: {e}")
        raise
