# backend/app/api/v1/routers/salesforce.py
"""
Salesforce CRM Integration API endpoints for Curatore v2 API (v1).

Provides endpoints for importing and managing Salesforce CRM data including
Accounts, Contacts, and Opportunities from Salesforce export zip files.

Endpoints:
    Import:
        POST /salesforce/import - Upload zip file and start import

    Dashboard:
        GET /salesforce/stats - Get aggregated statistics

    Accounts:
        GET /salesforce/accounts - List accounts
        GET /salesforce/accounts/{id} - Get account details with contacts/opportunities

    Contacts:
        GET /salesforce/contacts - List contacts
        GET /salesforce/contacts/{id} - Get contact details

    Opportunities:
        GET /salesforce/opportunities - List opportunities
        GET /salesforce/opportunities/{id} - Get opportunity details

    Filters:
        GET /salesforce/filters/account-types - Get distinct account types
        GET /salesforce/filters/industries - Get distinct industries
        GET /salesforce/filters/stages - Get distinct opportunity stages
        GET /salesforce/filters/opportunity-types - Get distinct opportunity types

Security:
    - All endpoints require authentication
    - All data is organization-scoped
"""

import logging
import uuid as uuid_module
from datetime import datetime
from io import BytesIO
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel

from app.connectors.salesforce.salesforce_service import salesforce_service
from app.core.database.models import (
    SalesforceAccount,
    SalesforceContact,
    SalesforceOpportunity,
    User,
)
from app.core.shared.database_service import database_service
from app.core.shared.run_service import run_service
from app.core.storage.minio_service import get_minio_service
from app.core.tasks import salesforce_import_task
from app.dependencies import get_current_user

# Initialize router
router = APIRouter(prefix="/salesforce", tags=["Salesforce"])

# Initialize logger
logger = logging.getLogger("curatore.api.salesforce")


# =========================================================================
# REQUEST/RESPONSE MODELS
# =========================================================================


class SalesforceImportResponse(BaseModel):
    """Response after initiating Salesforce import."""

    run_id: str
    status: str = "pending"
    message: str = "Import job started"


class SalesforceStatsResponse(BaseModel):
    """Aggregated Salesforce statistics response."""

    accounts: Dict[str, Any]
    contacts: Dict[str, Any]
    opportunities: Dict[str, Any]


class AddressResponse(BaseModel):
    """Address details."""

    street: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None


class SalesforceAccountResponse(BaseModel):
    """Salesforce account response."""

    id: str
    salesforce_id: str
    name: str
    parent_salesforce_id: Optional[str] = None
    account_type: Optional[str] = None
    industry: Optional[str] = None
    department: Optional[str] = None
    description: Optional[str] = None
    website: Optional[str] = None
    phone: Optional[str] = None
    billing_address: Optional[Dict[str, Any]] = None
    shipping_address: Optional[Dict[str, Any]] = None
    small_business_flags: Optional[Dict[str, Any]] = None
    indexed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    # Counts (optional, included in detail view)
    contact_count: Optional[int] = None
    opportunity_count: Optional[int] = None


class SalesforceAccountListResponse(BaseModel):
    """List of Salesforce accounts response."""

    items: List[SalesforceAccountResponse]
    total: int
    limit: int
    offset: int


class SalesforceContactResponse(BaseModel):
    """Salesforce contact response."""

    id: str
    salesforce_id: str
    account_id: Optional[str] = None
    account_salesforce_id: Optional[str] = None
    first_name: Optional[str] = None
    last_name: str
    email: Optional[str] = None
    title: Optional[str] = None
    phone: Optional[str] = None
    mobile_phone: Optional[str] = None
    department: Optional[str] = None
    is_current_employee: Optional[bool] = None
    mailing_address: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime
    # Related data (optional)
    account_name: Optional[str] = None


class SalesforceContactListResponse(BaseModel):
    """List of Salesforce contacts response."""

    items: List[SalesforceContactResponse]
    total: int
    limit: int
    offset: int


class SalesforceOpportunityResponse(BaseModel):
    """Salesforce opportunity response."""

    id: str
    salesforce_id: str
    account_id: Optional[str] = None
    account_salesforce_id: Optional[str] = None
    name: str
    stage_name: Optional[str] = None
    amount: Optional[float] = None
    probability: Optional[float] = None
    close_date: Optional[str] = None  # ISO date string
    is_closed: Optional[bool] = None
    is_won: Optional[bool] = None
    opportunity_type: Optional[str] = None
    role: Optional[str] = None
    lead_source: Optional[str] = None
    fiscal_year: Optional[str] = None
    fiscal_quarter: Optional[str] = None
    description: Optional[str] = None
    custom_dates: Optional[Dict[str, Any]] = None
    linked_sharepoint_folder_id: Optional[str] = None
    linked_sam_solicitation_id: Optional[str] = None
    indexed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    # Related data (optional)
    account_name: Optional[str] = None


class SalesforceOpportunityListResponse(BaseModel):
    """List of Salesforce opportunities response."""

    items: List[SalesforceOpportunityResponse]
    total: int
    limit: int
    offset: int


class FilterOptionsResponse(BaseModel):
    """Filter options response."""

    options: List[str]


# =========================================================================
# HELPER FUNCTIONS
# =========================================================================


def _account_to_response(
    account: SalesforceAccount,
    include_counts: bool = False,
) -> SalesforceAccountResponse:
    """Convert account model to response."""
    response = SalesforceAccountResponse(
        id=str(account.id),
        salesforce_id=account.salesforce_id,
        name=account.name,
        parent_salesforce_id=account.parent_salesforce_id,
        account_type=account.account_type,
        industry=account.industry,
        department=account.department,
        description=account.description,
        website=account.website,
        phone=account.phone,
        billing_address=account.billing_address,
        shipping_address=account.shipping_address,
        small_business_flags=account.small_business_flags,
        indexed_at=account.indexed_at,
        created_at=account.created_at,
        updated_at=account.updated_at,
    )
    if include_counts:
        response.contact_count = len(account.contacts) if account.contacts else 0
        response.opportunity_count = len(account.opportunities) if account.opportunities else 0
    return response


def _contact_to_response(
    contact: SalesforceContact,
    include_account: bool = False,
) -> SalesforceContactResponse:
    """Convert contact model to response."""
    response = SalesforceContactResponse(
        id=str(contact.id),
        salesforce_id=contact.salesforce_id,
        account_id=str(contact.account_id) if contact.account_id else None,
        account_salesforce_id=contact.account_salesforce_id,
        first_name=contact.first_name,
        last_name=contact.last_name,
        email=contact.email,
        title=contact.title,
        phone=contact.phone,
        mobile_phone=contact.mobile_phone,
        department=contact.department,
        is_current_employee=contact.is_current_employee,
        mailing_address=contact.mailing_address,
        created_at=contact.created_at,
        updated_at=contact.updated_at,
    )
    if include_account and contact.account:
        response.account_name = contact.account.name
    return response


def _opportunity_to_response(
    opportunity: SalesforceOpportunity,
    include_account: bool = False,
) -> SalesforceOpportunityResponse:
    """Convert opportunity model to response."""
    response = SalesforceOpportunityResponse(
        id=str(opportunity.id),
        salesforce_id=opportunity.salesforce_id,
        account_id=str(opportunity.account_id) if opportunity.account_id else None,
        account_salesforce_id=opportunity.account_salesforce_id,
        name=opportunity.name,
        stage_name=opportunity.stage_name,
        amount=opportunity.amount,
        probability=opportunity.probability,
        close_date=opportunity.close_date.isoformat() if opportunity.close_date else None,
        is_closed=opportunity.is_closed,
        is_won=opportunity.is_won,
        opportunity_type=opportunity.opportunity_type,
        role=opportunity.role,
        lead_source=opportunity.lead_source,
        fiscal_year=opportunity.fiscal_year,
        fiscal_quarter=opportunity.fiscal_quarter,
        description=opportunity.description,
        custom_dates=opportunity.custom_dates,
        linked_sharepoint_folder_id=str(opportunity.linked_sharepoint_folder_id) if opportunity.linked_sharepoint_folder_id else None,
        linked_sam_solicitation_id=str(opportunity.linked_sam_solicitation_id) if opportunity.linked_sam_solicitation_id else None,
        indexed_at=opportunity.indexed_at,
        created_at=opportunity.created_at,
        updated_at=opportunity.updated_at,
    )
    if include_account and opportunity.account:
        response.account_name = opportunity.account.name
    return response


# =========================================================================
# IMPORT ENDPOINTS
# =========================================================================


@router.post(
    "/import",
    response_model=SalesforceImportResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Import Salesforce data from zip file",
    description="Upload a Salesforce export zip file containing Account.csv, Contact.csv, and Opportunity.csv. Returns a run_id for tracking.",
)
async def import_salesforce_data(
    file: UploadFile = File(..., description="Salesforce export zip file"),
    current_user: User = Depends(get_current_user),
) -> SalesforceImportResponse:
    """
    Import Salesforce CRM data from an export zip file.

    The zip file should contain CSV exports from Salesforce:
    - Account.csv (or similar)
    - Contact.csv (or similar)
    - Opportunity.csv (or similar)

    Records are upserted by Salesforce ID (18-character).
    """
    # Validate file type
    if not file.filename or not file.filename.lower().endswith('.zip'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be a .zip file"
        )

    # Get MinIO service
    minio = get_minio_service()
    if not minio:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Object storage service not available"
        )

    # Read file content
    content = await file.read()

    # Upload to MinIO temp bucket for worker access
    # This enables horizontal scaling since all workers can access MinIO
    minio_key = f"{current_user.organization_id}/salesforce/imports/{uuid_module.uuid4().hex}.zip"

    try:
        minio.put_object(
            bucket=minio.bucket_temp,
            key=minio_key,
            data=BytesIO(content),
            length=len(content),
            content_type="application/zip",
            metadata={"original_filename": file.filename or "export.zip"},
        )
        logger.info(f"Uploaded Salesforce zip to MinIO: {minio.bucket_temp}/{minio_key}")
    except Exception as e:
        logger.error(f"Failed to upload to MinIO: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload file: {str(e)}"
        )

    try:
        async with database_service.get_session() as session:
            # Create run record
            run = await run_service.create_run(
                session=session,
                organization_id=current_user.organization_id,
                run_type="salesforce_import",
                created_by=current_user.id,
                config={
                    "filename": file.filename,
                    "file_size": len(content),
                    "minio_key": minio_key,  # Store MinIO key in config for reference
                },
            )
            await session.commit()

            # Queue the import task with MinIO key (not file path)
            salesforce_import_task.delay(
                run_id=str(run.id),
                organization_id=str(current_user.organization_id),
                minio_key=minio_key,
            )

            logger.info(f"Salesforce import started: run_id={run.id}, file={file.filename}, minio_key={minio_key}")

            return SalesforceImportResponse(
                run_id=str(run.id),
                status="pending",
                message=f"Import job started for {file.filename}",
            )

    except Exception as e:
        # Clean up MinIO object on error
        try:
            minio.delete_object(minio.bucket_temp, minio_key)
        except Exception as cleanup_err:
            logger.warning(f"Failed to clean up MinIO object: {cleanup_err}")
        logger.error(f"Failed to start Salesforce import: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start import: {str(e)}"
        )


# =========================================================================
# STATISTICS ENDPOINTS
# =========================================================================


@router.get(
    "/stats",
    response_model=SalesforceStatsResponse,
    summary="Get Salesforce dashboard statistics",
    description="Get aggregated statistics for accounts, contacts, and opportunities.",
)
async def get_salesforce_stats(
    current_user: User = Depends(get_current_user),
) -> SalesforceStatsResponse:
    """Get aggregated Salesforce statistics."""
    async with database_service.get_session() as session:
        stats = await salesforce_service.get_dashboard_stats(
            session=session,
            organization_id=current_user.organization_id,
        )
        return SalesforceStatsResponse(**stats)


# =========================================================================
# ACCOUNT ENDPOINTS
# =========================================================================


@router.get(
    "/accounts",
    response_model=SalesforceAccountListResponse,
    summary="List Salesforce accounts",
    description="List accounts with optional filtering by type, industry, or keyword.",
)
async def list_accounts(
    account_type: Optional[str] = Query(None, description="Filter by account type"),
    industry: Optional[str] = Query(None, description="Filter by industry"),
    keyword: Optional[str] = Query(None, description="Search in name and description"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Number to skip"),
    current_user: User = Depends(get_current_user),
) -> SalesforceAccountListResponse:
    """List Salesforce accounts."""
    async with database_service.get_session() as session:
        accounts, total = await salesforce_service.list_accounts(
            session=session,
            organization_id=current_user.organization_id,
            account_type=account_type,
            industry=industry,
            keyword=keyword,
            limit=limit,
            offset=offset,
        )

        return SalesforceAccountListResponse(
            items=[_account_to_response(a) for a in accounts],
            total=total,
            limit=limit,
            offset=offset,
        )


@router.get(
    "/accounts/{account_id}",
    response_model=SalesforceAccountResponse,
    summary="Get Salesforce account details",
    description="Get account details including contacts and opportunities counts.",
)
async def get_account(
    account_id: UUID,
    current_user: User = Depends(get_current_user),
) -> SalesforceAccountResponse:
    """Get Salesforce account details."""
    async with database_service.get_session() as session:
        account = await salesforce_service.get_account(
            session=session,
            organization_id=current_user.organization_id,
            account_id=account_id,
            include_contacts=True,
            include_opportunities=True,
        )

        if not account:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Account not found"
            )

        return _account_to_response(account, include_counts=True)


@router.get(
    "/accounts/{account_id}/contacts",
    response_model=SalesforceContactListResponse,
    summary="Get contacts for an account",
    description="List all contacts associated with an account.",
)
async def get_account_contacts(
    account_id: UUID,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
) -> SalesforceContactListResponse:
    """Get contacts for a specific account."""
    async with database_service.get_session() as session:
        contacts, total = await salesforce_service.list_contacts(
            session=session,
            organization_id=current_user.organization_id,
            account_id=account_id,
            limit=limit,
            offset=offset,
        )

        return SalesforceContactListResponse(
            items=[_contact_to_response(c) for c in contacts],
            total=total,
            limit=limit,
            offset=offset,
        )


@router.get(
    "/accounts/{account_id}/opportunities",
    response_model=SalesforceOpportunityListResponse,
    summary="Get opportunities for an account",
    description="List all opportunities associated with an account.",
)
async def get_account_opportunities(
    account_id: UUID,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
) -> SalesforceOpportunityListResponse:
    """Get opportunities for a specific account."""
    async with database_service.get_session() as session:
        opportunities, total = await salesforce_service.list_opportunities(
            session=session,
            organization_id=current_user.organization_id,
            account_id=account_id,
            limit=limit,
            offset=offset,
        )

        return SalesforceOpportunityListResponse(
            items=[_opportunity_to_response(o) for o in opportunities],
            total=total,
            limit=limit,
            offset=offset,
        )


# =========================================================================
# CONTACT ENDPOINTS
# =========================================================================


@router.get(
    "/contacts",
    response_model=SalesforceContactListResponse,
    summary="List Salesforce contacts",
    description="List contacts with optional filtering by account or keyword.",
)
async def list_contacts(
    account_id: Optional[UUID] = Query(None, description="Filter by account ID"),
    keyword: Optional[str] = Query(None, description="Search in name, email, title"),
    current_only: bool = Query(False, description="Only show current employees"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Number to skip"),
    current_user: User = Depends(get_current_user),
) -> SalesforceContactListResponse:
    """List Salesforce contacts."""
    async with database_service.get_session() as session:
        contacts, total = await salesforce_service.list_contacts(
            session=session,
            organization_id=current_user.organization_id,
            account_id=account_id,
            keyword=keyword,
            current_only=current_only,
            limit=limit,
            offset=offset,
        )

        return SalesforceContactListResponse(
            items=[_contact_to_response(c) for c in contacts],
            total=total,
            limit=limit,
            offset=offset,
        )


@router.get(
    "/contacts/{contact_id}",
    response_model=SalesforceContactResponse,
    summary="Get Salesforce contact details",
    description="Get contact details including associated account.",
)
async def get_contact(
    contact_id: UUID,
    current_user: User = Depends(get_current_user),
) -> SalesforceContactResponse:
    """Get Salesforce contact details."""
    async with database_service.get_session() as session:
        contact = await salesforce_service.get_contact(
            session=session,
            organization_id=current_user.organization_id,
            contact_id=contact_id,
            include_account=True,
        )

        if not contact:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Contact not found"
            )

        return _contact_to_response(contact, include_account=True)


# =========================================================================
# OPPORTUNITY ENDPOINTS
# =========================================================================


@router.get(
    "/opportunities",
    response_model=SalesforceOpportunityListResponse,
    summary="List Salesforce opportunities",
    description="List opportunities with optional filtering by stage, type, or keyword.",
)
async def list_opportunities(
    account_id: Optional[UUID] = Query(None, description="Filter by account ID"),
    stage_name: Optional[str] = Query(None, description="Filter by stage name"),
    opportunity_type: Optional[str] = Query(None, description="Filter by opportunity type"),
    is_open: Optional[bool] = Query(None, description="Filter by open/closed status"),
    keyword: Optional[str] = Query(None, description="Search in name and description"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Number to skip"),
    current_user: User = Depends(get_current_user),
) -> SalesforceOpportunityListResponse:
    """List Salesforce opportunities."""
    async with database_service.get_session() as session:
        opportunities, total = await salesforce_service.list_opportunities(
            session=session,
            organization_id=current_user.organization_id,
            account_id=account_id,
            stage_name=stage_name,
            opportunity_type=opportunity_type,
            is_open=is_open,
            keyword=keyword,
            limit=limit,
            offset=offset,
        )

        return SalesforceOpportunityListResponse(
            items=[_opportunity_to_response(o) for o in opportunities],
            total=total,
            limit=limit,
            offset=offset,
        )


@router.get(
    "/opportunities/{opportunity_id}",
    response_model=SalesforceOpportunityResponse,
    summary="Get Salesforce opportunity details",
    description="Get opportunity details including associated account.",
)
async def get_opportunity(
    opportunity_id: UUID,
    current_user: User = Depends(get_current_user),
) -> SalesforceOpportunityResponse:
    """Get Salesforce opportunity details."""
    async with database_service.get_session() as session:
        opportunity = await salesforce_service.get_opportunity(
            session=session,
            organization_id=current_user.organization_id,
            opportunity_id=opportunity_id,
            include_account=True,
        )

        if not opportunity:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Opportunity not found"
            )

        return _opportunity_to_response(opportunity, include_account=True)


# =========================================================================
# FILTER OPTIONS ENDPOINTS
# =========================================================================


@router.get(
    "/filters/account-types",
    response_model=FilterOptionsResponse,
    summary="Get account type filter options",
    description="Get distinct account types for filter dropdowns.",
)
async def get_account_types(
    current_user: User = Depends(get_current_user),
) -> FilterOptionsResponse:
    """Get distinct account types."""
    async with database_service.get_session() as session:
        types = await salesforce_service.get_account_types(
            session=session,
            organization_id=current_user.organization_id,
        )
        return FilterOptionsResponse(options=types)


@router.get(
    "/filters/industries",
    response_model=FilterOptionsResponse,
    summary="Get industry filter options",
    description="Get distinct industries for filter dropdowns.",
)
async def get_industries(
    current_user: User = Depends(get_current_user),
) -> FilterOptionsResponse:
    """Get distinct industries."""
    async with database_service.get_session() as session:
        industries = await salesforce_service.get_industries(
            session=session,
            organization_id=current_user.organization_id,
        )
        return FilterOptionsResponse(options=industries)


@router.get(
    "/filters/stages",
    response_model=FilterOptionsResponse,
    summary="Get stage filter options",
    description="Get distinct opportunity stages for filter dropdowns.",
)
async def get_stages(
    current_user: User = Depends(get_current_user),
) -> FilterOptionsResponse:
    """Get distinct opportunity stages."""
    async with database_service.get_session() as session:
        stages = await salesforce_service.get_stage_names(
            session=session,
            organization_id=current_user.organization_id,
        )
        return FilterOptionsResponse(options=stages)


@router.get(
    "/filters/opportunity-types",
    response_model=FilterOptionsResponse,
    summary="Get opportunity type filter options",
    description="Get distinct opportunity types for filter dropdowns.",
)
async def get_opportunity_types(
    current_user: User = Depends(get_current_user),
) -> FilterOptionsResponse:
    """Get distinct opportunity types."""
    async with database_service.get_session() as session:
        types = await salesforce_service.get_opportunity_types(
            session=session,
            organization_id=current_user.organization_id,
        )
        return FilterOptionsResponse(options=types)


# =========================================================================
# REINDEX ENDPOINTS
# =========================================================================


class ReindexResponse(BaseModel):
    """Reindex operation response."""

    status: str
    message: str
    task_id: Optional[str] = None


@router.post(
    "/reindex",
    response_model=ReindexResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Reindex Salesforce data for search",
    description="Trigger a reindex of all Salesforce accounts, contacts, and opportunities for search.",
)
async def reindex_salesforce(
    current_user: User = Depends(get_current_user),
) -> ReindexResponse:
    """
    Reindex all Salesforce data for search.

    This endpoint triggers a background task to index all Salesforce accounts,
    contacts, and opportunities to the search_chunks table. Use this after
    importing data or to fix missing search results.
    """
    from app.core.tasks import reindex_salesforce_organization_task

    try:
        # Queue background task
        task = reindex_salesforce_organization_task.delay(
            organization_id=str(current_user.organization_id),
        )

        logger.info(
            f"Queued Salesforce reindex for org {current_user.organization_id}, task_id={task.id}"
        )

        return ReindexResponse(
            status="queued",
            message="Salesforce reindex task has been queued. This may take several minutes.",
            task_id=task.id,
        )

    except Exception as e:
        logger.error(f"Failed to queue Salesforce reindex: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to queue reindex: {str(e)}"
        )
