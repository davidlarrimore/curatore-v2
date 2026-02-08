"""
Salesforce-related Celery tasks.

Handles Salesforce CRM reindexing and data import from zip files.
"""
import asyncio
import logging
import os
from typing import Any, Dict

from celery import shared_task

from app.celery_app import app as celery_app
from app.core.shared.database_service import database_service
from app.core.shared.config_loader import config_loader
from app.config import settings


def _is_search_enabled() -> bool:
    """Check if search is enabled via config.yml or environment variables."""
    search_config = config_loader.get_search_config()
    if search_config:
        return search_config.enabled
    return getattr(settings, "search_enabled", True)


# ============================================================================
# SALESFORCE REINDEX TASK
# ============================================================================


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 2})
def reindex_salesforce_organization_task(
    self,
    organization_id: str,
) -> Dict[str, Any]:
    """
    Reindex all Salesforce CRM data for an organization.

    This task indexes all existing Salesforce accounts, contacts, and opportunities
    to the search index for unified search. Useful for initial setup or recovery.

    Args:
        organization_id: Organization UUID string

    Returns:
        Dict with reindex statistics
    """
    from uuid import UUID

    logger = logging.getLogger("curatore.tasks.salesforce_indexing")

    # Check if search is enabled
    if not _is_search_enabled():
        logger.info("Search disabled, skipping Salesforce reindex")
        return {
            "status": "disabled",
            "message": "Search is disabled",
            "accounts_indexed": 0,
            "contacts_indexed": 0,
            "opportunities_indexed": 0,
        }

    logger.info(f"Starting Salesforce reindex task for organization {organization_id}")

    try:
        result = asyncio.run(
            _reindex_salesforce_organization_async(UUID(organization_id))
        )

        logger.info(
            f"Salesforce reindex completed for org {organization_id}: "
            f"{result.get('accounts_indexed', 0)} accounts, "
            f"{result.get('contacts_indexed', 0)} contacts, "
            f"{result.get('opportunities_indexed', 0)} opportunities indexed"
        )
        return result

    except Exception as e:
        logger.error(f"Salesforce reindex task failed for org {organization_id}: {e}", exc_info=True)
        return {
            "status": "failed",
            "message": str(e),
            "accounts_indexed": 0,
            "contacts_indexed": 0,
            "opportunities_indexed": 0,
        }


async def _reindex_salesforce_organization_async(
    organization_id,
) -> Dict[str, Any]:
    """
    Async wrapper for Salesforce organization reindex.

    Args:
        organization_id: Organization UUID

    Returns:
        Dict with reindex results
    """
    from app.core.search.pg_index_service import pg_index_service
    from app.connectors.salesforce.salesforce_service import salesforce_service
    from app.core.database.models import SalesforceAccount, SalesforceContact, SalesforceOpportunity
    from sqlalchemy import select

    logger = logging.getLogger("curatore.tasks.salesforce_indexing")

    accounts_indexed = 0
    contacts_indexed = 0
    opportunities_indexed = 0
    errors = []

    async with database_service.get_session() as session:
        # Build account name lookup for contacts and opportunities
        account_names: Dict[str, str] = {}

        # Index accounts
        logger.info("Indexing Salesforce accounts...")
        account_result = await session.execute(
            select(SalesforceAccount).where(
                SalesforceAccount.organization_id == organization_id
            )
        )
        accounts = account_result.scalars().all()
        logger.info(f"Found {len(accounts)} accounts to index")

        for account in accounts:
            account_names[str(account.id)] = account.name
            try:
                success = await pg_index_service.index_salesforce_account(
                    session=session,
                    organization_id=organization_id,
                    account_id=account.id,
                    salesforce_id=account.salesforce_id,
                    name=account.name,
                    account_type=account.account_type,
                    industry=account.industry,
                    description=account.description,
                    website=account.website,
                )
                if success:
                    accounts_indexed += 1
            except Exception as e:
                errors.append(f"Account {account.id}: {str(e)}")

        # Index contacts
        logger.info("Indexing Salesforce contacts...")
        contact_result = await session.execute(
            select(SalesforceContact).where(
                SalesforceContact.organization_id == organization_id
            )
        )
        contacts = contact_result.scalars().all()
        logger.info(f"Found {len(contacts)} contacts to index")

        for contact in contacts:
            account_name = account_names.get(str(contact.account_id)) if contact.account_id else None
            try:
                success = await pg_index_service.index_salesforce_contact(
                    session=session,
                    organization_id=organization_id,
                    contact_id=contact.id,
                    salesforce_id=contact.salesforce_id,
                    first_name=contact.first_name,
                    last_name=contact.last_name,
                    email=contact.email,
                    title=contact.title,
                    account_name=account_name,
                    department=contact.department,
                )
                if success:
                    contacts_indexed += 1
            except Exception as e:
                errors.append(f"Contact {contact.id}: {str(e)}")

        # Index opportunities
        logger.info("Indexing Salesforce opportunities...")
        opp_result = await session.execute(
            select(SalesforceOpportunity).where(
                SalesforceOpportunity.organization_id == organization_id
            )
        )
        opportunities = opp_result.scalars().all()
        logger.info(f"Found {len(opportunities)} opportunities to index")

        for opp in opportunities:
            account_name = account_names.get(str(opp.account_id)) if opp.account_id else None
            try:
                success = await pg_index_service.index_salesforce_opportunity(
                    session=session,
                    organization_id=organization_id,
                    opportunity_id=opp.id,
                    salesforce_id=opp.salesforce_id,
                    name=opp.name,
                    stage_name=opp.stage_name,
                    amount=float(opp.amount) if opp.amount else None,
                    opportunity_type=opp.opportunity_type,
                    account_name=account_name,
                    description=opp.description,
                    close_date=opp.close_date,
                )
                if success:
                    opportunities_indexed += 1
            except Exception as e:
                errors.append(f"Opportunity {opp.id}: {str(e)}")

    return {
        "status": "completed",
        "accounts_indexed": accounts_indexed,
        "contacts_indexed": contacts_indexed,
        "opportunities_indexed": opportunities_indexed,
        "errors": errors[:10] if errors else [],
    }


# ============================================================================
# SALESFORCE CRM IMPORT TASKS
# ============================================================================


@celery_app.task(bind=True, name="app.tasks.salesforce_import_task")
def salesforce_import_task(
    self,
    run_id: str,
    organization_id: str,
    minio_key: str,
) -> Dict[str, Any]:
    """
    Import Salesforce CRM data from an export zip file stored in MinIO.

    This task downloads a zip file from MinIO temp bucket, processes it
    to extract Salesforce Account, Contact, and Opportunity CSV exports,
    and upserts records by Salesforce ID.

    Args:
        run_id: Run UUID string for tracking
        organization_id: Organization UUID string
        minio_key: MinIO object key in the temp bucket

    Returns:
        Dict with import statistics
    """
    from uuid import UUID
    from app.core.storage.minio_service import get_minio_service
    import tempfile

    logger = logging.getLogger("curatore.tasks.salesforce")
    logger.info(f"Starting Salesforce import task for run {run_id}, minio_key={minio_key}")

    # Download from MinIO to local temp file
    minio = get_minio_service()
    if not minio:
        error_msg = "MinIO service not available"
        logger.error(error_msg)
        asyncio.run(_fail_salesforce_import_run(UUID(run_id), error_msg))
        raise RuntimeError(error_msg)

    local_temp_path = None
    try:
        # Download zip from MinIO temp bucket
        logger.info(f"Downloading from MinIO: {minio.bucket_temp}/{minio_key}")
        zip_content = minio.get_object(minio.bucket_temp, minio_key)

        # Write to local temp file for processing
        with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as tmp:
            tmp.write(zip_content.getvalue())
            local_temp_path = tmp.name
        logger.info(f"Downloaded to local temp: {local_temp_path}")

        # Execute the import
        result = asyncio.run(
            _execute_salesforce_import_async(
                run_id=UUID(run_id),
                organization_id=UUID(organization_id),
                zip_path=local_temp_path,
            )
        )

        logger.info(f"Salesforce import completed for run {run_id}: {result}")
        return result

    except Exception as e:
        logger.error(f"Salesforce import task failed for run {run_id}: {e}", exc_info=True)
        # Mark run as failed
        asyncio.run(_fail_salesforce_import_run(UUID(run_id), str(e)))
        raise

    finally:
        # Clean up local temp file
        if local_temp_path and os.path.exists(local_temp_path):
            try:
                os.unlink(local_temp_path)
                logger.info(f"Cleaned up local temp file: {local_temp_path}")
            except Exception as cleanup_err:
                logger.warning(f"Failed to clean up local temp file {local_temp_path}: {cleanup_err}")

        # Clean up MinIO object (temp bucket has lifecycle policy, but explicit cleanup is cleaner)
        if minio and minio_key:
            try:
                minio.delete_object(minio.bucket_temp, minio_key)
                logger.info(f"Cleaned up MinIO object: {minio.bucket_temp}/{minio_key}")
            except Exception as cleanup_err:
                logger.warning(f"Failed to clean up MinIO object {minio_key}: {cleanup_err}")


async def _execute_salesforce_import_async(
    run_id,
    organization_id,
    zip_path: str,
) -> Dict[str, Any]:
    """
    Async wrapper for Salesforce import.

    Args:
        run_id: Run UUID
        organization_id: Organization UUID
        zip_path: Path to the zip file

    Returns:
        Dict with import statistics
    """
    from app.core.shared.run_service import run_service
    from app.connectors.salesforce.salesforce_import_service import salesforce_import_service

    async with database_service.get_session() as session:
        # Update run to running
        await run_service.update_run_status(
            session, run_id, "running"
        )
        await session.commit()

        try:
            # Execute import
            result = await salesforce_import_service.import_from_zip(
                session=session,
                organization_id=organization_id,
                zip_path=zip_path,
                run_id=run_id,
            )

            # Complete the run
            await run_service.complete_run(
                session=session,
                run_id=run_id,
                results_summary=result,
            )
            await session.commit()

            return result

        except Exception as e:
            await session.rollback()
            await run_service.fail_run(
                session=session,
                run_id=run_id,
                error_message=str(e),
            )
            await session.commit()
            raise


async def _fail_salesforce_import_run(run_id, error: str) -> None:
    """Mark a Salesforce import run as failed."""
    from app.core.shared.run_service import run_service

    async with database_service.get_session() as session:
        await run_service.fail_run(session, run_id, error)
        await session.commit()
