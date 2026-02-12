"""
Salesforce Service for CRM Data Management.

Provides CRUD operations for SalesforceAccount, SalesforceContact,
and SalesforceOpportunity models. This is the core service for
managing imported Salesforce CRM data.

Key Features:
- Upsert operations by Salesforce ID (18-character)
- Account hierarchy management via parent_salesforce_id
- Contact/Opportunity linking to Accounts
- Dashboard statistics aggregation
- Filtering and pagination

Usage:
    from app.connectors.salesforce.salesforce_service import salesforce_service

    # Upsert an account
    account = await salesforce_service.upsert_account(
        session=session,
        organization_id=org_id,
        salesforce_id="001XXXXXXXXXXXXXXX",
        name="Acme Corp",
        account_type="Customer",
    )

    # List opportunities
    opportunities, total = await salesforce_service.list_opportunities(
        session=session,
        organization_id=org_id,
        stage_name="Qualification",
    )
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database.models import (
    SalesforceAccount,
    SalesforceContact,
    SalesforceOpportunity,
)

logger = logging.getLogger("curatore.salesforce_service")


class SalesforceService:
    """
    Service for managing Salesforce CRM data.

    Handles CRUD operations for accounts, contacts, and opportunities
    with organization isolation.
    """

    # =========================================================================
    # ACCOUNT OPERATIONS
    # =========================================================================

    async def upsert_account(
        self,
        session: AsyncSession,
        organization_id: UUID,
        salesforce_id: str,
        name: str,
        parent_salesforce_id: Optional[str] = None,
        account_type: Optional[str] = None,
        industry: Optional[str] = None,
        department: Optional[str] = None,
        description: Optional[str] = None,
        website: Optional[str] = None,
        phone: Optional[str] = None,
        billing_address: Optional[Dict[str, Any]] = None,
        shipping_address: Optional[Dict[str, Any]] = None,
        small_business_flags: Optional[Dict[str, Any]] = None,
        raw_data: Optional[Dict[str, Any]] = None,
    ) -> SalesforceAccount:
        """
        Create or update a Salesforce account by salesforce_id.

        Args:
            session: Database session
            organization_id: Organization UUID
            salesforce_id: Salesforce 18-character ID
            name: Account name
            parent_salesforce_id: Parent account's Salesforce ID
            account_type: Account type classification
            industry: Industry classification
            department: Department field
            description: Account description
            website: Company website
            phone: Primary phone
            billing_address: Billing address dict
            shipping_address: Shipping address dict
            small_business_flags: SBA certification flags
            raw_data: Original CSV row data

        Returns:
            Created or updated SalesforceAccount instance
        """
        # Check for existing account
        result = await session.execute(
            select(SalesforceAccount).where(
                and_(
                    SalesforceAccount.organization_id == organization_id,
                    SalesforceAccount.salesforce_id == salesforce_id,
                )
            )
        )
        account = result.scalar_one_or_none()

        if account:
            # Update existing
            account.name = name
            account.parent_salesforce_id = parent_salesforce_id
            account.account_type = account_type
            account.industry = industry
            account.department = department
            account.description = description
            account.website = website
            account.phone = phone
            account.billing_address = billing_address
            account.shipping_address = shipping_address
            account.small_business_flags = small_business_flags
            account.raw_data = raw_data
            account.updated_at = datetime.utcnow()
            logger.debug(f"Updated account {salesforce_id}: {name}")
        else:
            # Create new
            account = SalesforceAccount(
                organization_id=organization_id,
                salesforce_id=salesforce_id,
                name=name,
                parent_salesforce_id=parent_salesforce_id,
                account_type=account_type,
                industry=industry,
                department=department,
                description=description,
                website=website,
                phone=phone,
                billing_address=billing_address,
                shipping_address=shipping_address,
                small_business_flags=small_business_flags,
                raw_data=raw_data,
            )
            session.add(account)
            logger.debug(f"Created account {salesforce_id}: {name}")

        return account

    async def get_account(
        self,
        session: AsyncSession,
        organization_id: UUID,
        account_id: UUID,
        include_contacts: bool = False,
        include_opportunities: bool = False,
    ) -> Optional[SalesforceAccount]:
        """Get an account by ID with optional related data."""
        options = []
        if include_contacts:
            options.append(selectinload(SalesforceAccount.contacts))
        if include_opportunities:
            options.append(selectinload(SalesforceAccount.opportunities))

        query = select(SalesforceAccount).where(
            and_(
                SalesforceAccount.organization_id == organization_id,
                SalesforceAccount.id == account_id,
            )
        )
        if options:
            query = query.options(*options)

        result = await session.execute(query)
        return result.scalar_one_or_none()

    async def get_account_by_sf_id(
        self,
        session: AsyncSession,
        organization_id: UUID,
        salesforce_id: str,
    ) -> Optional[SalesforceAccount]:
        """Get an account by Salesforce ID."""
        result = await session.execute(
            select(SalesforceAccount).where(
                and_(
                    SalesforceAccount.organization_id == organization_id,
                    SalesforceAccount.salesforce_id == salesforce_id,
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_accounts(
        self,
        session: AsyncSession,
        organization_id: UUID,
        account_type: Optional[str] = None,
        industry: Optional[str] = None,
        keyword: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Tuple[List[SalesforceAccount], int]:
        """
        List accounts with optional filters.

        Returns:
            Tuple of (accounts list, total count)
        """
        # Base query
        base_query = select(SalesforceAccount).where(
            SalesforceAccount.organization_id == organization_id
        )

        # Apply filters
        if account_type:
            base_query = base_query.where(SalesforceAccount.account_type == account_type)
        if industry:
            base_query = base_query.where(SalesforceAccount.industry == industry)
        if keyword:
            keyword_filter = f"%{keyword}%"
            base_query = base_query.where(
                or_(
                    SalesforceAccount.name.ilike(keyword_filter),
                    SalesforceAccount.description.ilike(keyword_filter),
                )
            )

        # Count total
        count_query = select(func.count()).select_from(base_query.subquery())
        total_result = await session.execute(count_query)
        total = total_result.scalar() or 0

        # Apply pagination and ordering
        query = base_query.order_by(SalesforceAccount.name).offset(offset).limit(limit)
        result = await session.execute(query)
        accounts = list(result.scalars().all())

        return accounts, total

    async def get_account_types(
        self,
        session: AsyncSession,
        organization_id: UUID,
    ) -> List[str]:
        """Get distinct account types for an organization."""
        result = await session.execute(
            select(SalesforceAccount.account_type)
            .where(
                and_(
                    SalesforceAccount.organization_id == organization_id,
                    SalesforceAccount.account_type.isnot(None),
                )
            )
            .distinct()
            .order_by(SalesforceAccount.account_type)
        )
        return [row[0] for row in result.all()]

    async def get_industries(
        self,
        session: AsyncSession,
        organization_id: UUID,
    ) -> List[str]:
        """Get distinct industries for an organization."""
        result = await session.execute(
            select(SalesforceAccount.industry)
            .where(
                and_(
                    SalesforceAccount.organization_id == organization_id,
                    SalesforceAccount.industry.isnot(None),
                )
            )
            .distinct()
            .order_by(SalesforceAccount.industry)
        )
        return [row[0] for row in result.all()]

    # =========================================================================
    # CONTACT OPERATIONS
    # =========================================================================

    async def upsert_contact(
        self,
        session: AsyncSession,
        organization_id: UUID,
        salesforce_id: str,
        last_name: str,
        first_name: Optional[str] = None,
        account_salesforce_id: Optional[str] = None,
        email: Optional[str] = None,
        title: Optional[str] = None,
        phone: Optional[str] = None,
        mobile_phone: Optional[str] = None,
        department: Optional[str] = None,
        is_current_employee: Optional[bool] = True,
        mailing_address: Optional[Dict[str, Any]] = None,
        raw_data: Optional[Dict[str, Any]] = None,
    ) -> SalesforceContact:
        """
        Create or update a Salesforce contact by salesforce_id.

        Args:
            session: Database session
            organization_id: Organization UUID
            salesforce_id: Salesforce 18-character ID
            last_name: Contact last name
            first_name: Contact first name
            account_salesforce_id: Parent account's Salesforce ID
            email: Email address
            title: Job title
            phone: Office phone
            mobile_phone: Mobile phone
            department: Department
            is_current_employee: Whether currently employed
            mailing_address: Mailing address dict
            raw_data: Original CSV row data

        Returns:
            Created or updated SalesforceContact instance
        """
        # Check for existing contact
        result = await session.execute(
            select(SalesforceContact).where(
                and_(
                    SalesforceContact.organization_id == organization_id,
                    SalesforceContact.salesforce_id == salesforce_id,
                )
            )
        )
        contact = result.scalar_one_or_none()

        if contact:
            # Update existing
            contact.first_name = first_name
            contact.last_name = last_name
            contact.account_salesforce_id = account_salesforce_id
            contact.email = email
            contact.title = title
            contact.phone = phone
            contact.mobile_phone = mobile_phone
            contact.department = department
            contact.is_current_employee = is_current_employee
            contact.mailing_address = mailing_address
            contact.raw_data = raw_data
            contact.updated_at = datetime.utcnow()
            logger.debug(f"Updated contact {salesforce_id}: {first_name} {last_name}")
        else:
            # Create new
            contact = SalesforceContact(
                organization_id=organization_id,
                salesforce_id=salesforce_id,
                first_name=first_name,
                last_name=last_name,
                account_salesforce_id=account_salesforce_id,
                email=email,
                title=title,
                phone=phone,
                mobile_phone=mobile_phone,
                department=department,
                is_current_employee=is_current_employee,
                mailing_address=mailing_address,
                raw_data=raw_data,
            )
            session.add(contact)
            logger.debug(f"Created contact {salesforce_id}: {first_name} {last_name}")

        return contact

    async def get_contact(
        self,
        session: AsyncSession,
        organization_id: UUID,
        contact_id: UUID,
        include_account: bool = False,
    ) -> Optional[SalesforceContact]:
        """Get a contact by ID with optional related data."""
        options = []
        if include_account:
            options.append(selectinload(SalesforceContact.account))

        query = select(SalesforceContact).where(
            and_(
                SalesforceContact.organization_id == organization_id,
                SalesforceContact.id == contact_id,
            )
        )
        if options:
            query = query.options(*options)

        result = await session.execute(query)
        return result.scalar_one_or_none()

    async def get_contact_by_sf_id(
        self,
        session: AsyncSession,
        organization_id: UUID,
        salesforce_id: str,
    ) -> Optional[SalesforceContact]:
        """Get a contact by Salesforce ID."""
        result = await session.execute(
            select(SalesforceContact).where(
                and_(
                    SalesforceContact.organization_id == organization_id,
                    SalesforceContact.salesforce_id == salesforce_id,
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_contacts(
        self,
        session: AsyncSession,
        organization_id: UUID,
        account_id: Optional[UUID] = None,
        keyword: Optional[str] = None,
        current_only: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> Tuple[List[SalesforceContact], int]:
        """
        List contacts with optional filters.

        Returns:
            Tuple of (contacts list, total count)
        """
        # Base query
        base_query = select(SalesforceContact).where(
            SalesforceContact.organization_id == organization_id
        )

        # Apply filters
        if account_id:
            base_query = base_query.where(SalesforceContact.account_id == account_id)
        if current_only:
            base_query = base_query.where(SalesforceContact.is_current_employee == True)
        if keyword:
            keyword_filter = f"%{keyword}%"
            base_query = base_query.where(
                or_(
                    SalesforceContact.first_name.ilike(keyword_filter),
                    SalesforceContact.last_name.ilike(keyword_filter),
                    SalesforceContact.email.ilike(keyword_filter),
                    SalesforceContact.title.ilike(keyword_filter),
                )
            )

        # Count total
        count_query = select(func.count()).select_from(base_query.subquery())
        total_result = await session.execute(count_query)
        total = total_result.scalar() or 0

        # Apply pagination and ordering
        query = (
            base_query
            .order_by(SalesforceContact.last_name, SalesforceContact.first_name)
            .offset(offset)
            .limit(limit)
        )
        result = await session.execute(query)
        contacts = list(result.scalars().all())

        return contacts, total

    async def link_contacts_to_accounts(
        self,
        session: AsyncSession,
        organization_id: UUID,
    ) -> int:
        """
        Link contacts to accounts by account_salesforce_id.

        Call after importing accounts and contacts to set account_id foreign keys.

        Returns:
            Number of contacts linked
        """
        # Get all accounts for the org
        account_result = await session.execute(
            select(SalesforceAccount.id, SalesforceAccount.salesforce_id).where(
                SalesforceAccount.organization_id == organization_id
            )
        )
        account_map = {row[1]: row[0] for row in account_result.all()}

        # Get contacts that need linking
        contact_result = await session.execute(
            select(SalesforceContact).where(
                and_(
                    SalesforceContact.organization_id == organization_id,
                    SalesforceContact.account_salesforce_id.isnot(None),
                    SalesforceContact.account_id.is_(None),
                )
            )
        )
        contacts = list(contact_result.scalars().all())

        linked_count = 0
        for contact in contacts:
            account_id = account_map.get(contact.account_salesforce_id)
            if account_id:
                contact.account_id = account_id
                linked_count += 1

        logger.info(f"Linked {linked_count} contacts to accounts")
        return linked_count

    # =========================================================================
    # OPPORTUNITY OPERATIONS
    # =========================================================================

    async def upsert_opportunity(
        self,
        session: AsyncSession,
        organization_id: UUID,
        salesforce_id: str,
        name: str,
        account_salesforce_id: Optional[str] = None,
        stage_name: Optional[str] = None,
        amount: Optional[float] = None,
        probability: Optional[float] = None,
        close_date: Optional[Any] = None,
        is_closed: Optional[bool] = False,
        is_won: Optional[bool] = False,
        opportunity_type: Optional[str] = None,
        role: Optional[str] = None,
        lead_source: Optional[str] = None,
        fiscal_year: Optional[str] = None,
        fiscal_quarter: Optional[str] = None,
        description: Optional[str] = None,
        custom_dates: Optional[Dict[str, Any]] = None,
        raw_data: Optional[Dict[str, Any]] = None,
    ) -> SalesforceOpportunity:
        """
        Create or update a Salesforce opportunity by salesforce_id.

        Args:
            session: Database session
            organization_id: Organization UUID
            salesforce_id: Salesforce 18-character ID
            name: Opportunity name
            account_salesforce_id: Parent account's Salesforce ID
            stage_name: Pipeline stage
            amount: Deal amount
            probability: Win probability (0-100)
            close_date: Expected close date
            is_closed: Whether closed
            is_won: Whether won (if closed)
            opportunity_type: Type classification
            role: Custom role field
            lead_source: Lead source
            fiscal_year: Fiscal year
            fiscal_quarter: Fiscal quarter
            description: Description
            custom_dates: Additional date fields
            raw_data: Original CSV row data

        Returns:
            Created or updated SalesforceOpportunity instance
        """
        # Check for existing opportunity
        result = await session.execute(
            select(SalesforceOpportunity).where(
                and_(
                    SalesforceOpportunity.organization_id == organization_id,
                    SalesforceOpportunity.salesforce_id == salesforce_id,
                )
            )
        )
        opportunity = result.scalar_one_or_none()

        if opportunity:
            # Update existing
            opportunity.name = name
            opportunity.account_salesforce_id = account_salesforce_id
            opportunity.stage_name = stage_name
            opportunity.amount = amount
            opportunity.probability = probability
            opportunity.close_date = close_date
            opportunity.is_closed = is_closed
            opportunity.is_won = is_won
            opportunity.opportunity_type = opportunity_type
            opportunity.role = role
            opportunity.lead_source = lead_source
            opportunity.fiscal_year = fiscal_year
            opportunity.fiscal_quarter = fiscal_quarter
            opportunity.description = description
            opportunity.custom_dates = custom_dates
            opportunity.raw_data = raw_data
            opportunity.updated_at = datetime.utcnow()
            logger.debug(f"Updated opportunity {salesforce_id}: {name}")
        else:
            # Create new
            opportunity = SalesforceOpportunity(
                organization_id=organization_id,
                salesforce_id=salesforce_id,
                name=name,
                account_salesforce_id=account_salesforce_id,
                stage_name=stage_name,
                amount=amount,
                probability=probability,
                close_date=close_date,
                is_closed=is_closed,
                is_won=is_won,
                opportunity_type=opportunity_type,
                role=role,
                lead_source=lead_source,
                fiscal_year=fiscal_year,
                fiscal_quarter=fiscal_quarter,
                description=description,
                custom_dates=custom_dates,
                raw_data=raw_data,
            )
            session.add(opportunity)
            logger.debug(f"Created opportunity {salesforce_id}: {name}")

        return opportunity

    async def get_opportunity(
        self,
        session: AsyncSession,
        organization_id: UUID,
        opportunity_id: UUID,
        include_account: bool = False,
    ) -> Optional[SalesforceOpportunity]:
        """Get an opportunity by ID with optional related data."""
        options = []
        if include_account:
            options.append(selectinload(SalesforceOpportunity.account))

        query = select(SalesforceOpportunity).where(
            and_(
                SalesforceOpportunity.organization_id == organization_id,
                SalesforceOpportunity.id == opportunity_id,
            )
        )
        if options:
            query = query.options(*options)

        result = await session.execute(query)
        return result.scalar_one_or_none()

    async def get_opportunity_by_sf_id(
        self,
        session: AsyncSession,
        organization_id: UUID,
        salesforce_id: str,
    ) -> Optional[SalesforceOpportunity]:
        """Get an opportunity by Salesforce ID."""
        result = await session.execute(
            select(SalesforceOpportunity).where(
                and_(
                    SalesforceOpportunity.organization_id == organization_id,
                    SalesforceOpportunity.salesforce_id == salesforce_id,
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_opportunities(
        self,
        session: AsyncSession,
        organization_id: UUID,
        account_id: Optional[UUID] = None,
        stage_name: Optional[str] = None,
        opportunity_type: Optional[str] = None,
        is_open: Optional[bool] = None,
        keyword: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Tuple[List[SalesforceOpportunity], int]:
        """
        List opportunities with optional filters.

        Returns:
            Tuple of (opportunities list, total count)
        """
        # Base query
        base_query = select(SalesforceOpportunity).where(
            SalesforceOpportunity.organization_id == organization_id
        )

        # Apply filters
        if account_id:
            base_query = base_query.where(SalesforceOpportunity.account_id == account_id)
        if stage_name:
            base_query = base_query.where(SalesforceOpportunity.stage_name == stage_name)
        if opportunity_type:
            base_query = base_query.where(SalesforceOpportunity.opportunity_type == opportunity_type)
        if is_open is not None:
            if is_open:
                base_query = base_query.where(SalesforceOpportunity.is_closed == False)
            else:
                base_query = base_query.where(SalesforceOpportunity.is_closed == True)
        if keyword:
            keyword_filter = f"%{keyword}%"
            base_query = base_query.where(
                or_(
                    SalesforceOpportunity.name.ilike(keyword_filter),
                    SalesforceOpportunity.description.ilike(keyword_filter),
                )
            )

        # Count total
        count_query = select(func.count()).select_from(base_query.subquery())
        total_result = await session.execute(count_query)
        total = total_result.scalar() or 0

        # Apply pagination and ordering
        query = (
            base_query
            .order_by(SalesforceOpportunity.close_date.desc().nullslast(), SalesforceOpportunity.name)
            .offset(offset)
            .limit(limit)
        )
        result = await session.execute(query)
        opportunities = list(result.scalars().all())

        return opportunities, total

    async def link_opportunities_to_accounts(
        self,
        session: AsyncSession,
        organization_id: UUID,
    ) -> int:
        """
        Link opportunities to accounts by account_salesforce_id.

        Call after importing accounts and opportunities to set account_id foreign keys.

        Returns:
            Number of opportunities linked
        """
        # Get all accounts for the org
        account_result = await session.execute(
            select(SalesforceAccount.id, SalesforceAccount.salesforce_id).where(
                SalesforceAccount.organization_id == organization_id
            )
        )
        account_map = {row[1]: row[0] for row in account_result.all()}

        # Get opportunities that need linking
        opp_result = await session.execute(
            select(SalesforceOpportunity).where(
                and_(
                    SalesforceOpportunity.organization_id == organization_id,
                    SalesforceOpportunity.account_salesforce_id.isnot(None),
                    SalesforceOpportunity.account_id.is_(None),
                )
            )
        )
        opportunities = list(opp_result.scalars().all())

        linked_count = 0
        for opp in opportunities:
            account_id = account_map.get(opp.account_salesforce_id)
            if account_id:
                opp.account_id = account_id
                linked_count += 1

        logger.info(f"Linked {linked_count} opportunities to accounts")
        return linked_count

    async def get_stage_names(
        self,
        session: AsyncSession,
        organization_id: UUID,
    ) -> List[str]:
        """Get distinct stage names for an organization."""
        result = await session.execute(
            select(SalesforceOpportunity.stage_name)
            .where(
                and_(
                    SalesforceOpportunity.organization_id == organization_id,
                    SalesforceOpportunity.stage_name.isnot(None),
                )
            )
            .distinct()
            .order_by(SalesforceOpportunity.stage_name)
        )
        return [row[0] for row in result.all()]

    async def get_opportunity_types(
        self,
        session: AsyncSession,
        organization_id: UUID,
    ) -> List[str]:
        """Get distinct opportunity types for an organization."""
        result = await session.execute(
            select(SalesforceOpportunity.opportunity_type)
            .where(
                and_(
                    SalesforceOpportunity.organization_id == organization_id,
                    SalesforceOpportunity.opportunity_type.isnot(None),
                )
            )
            .distinct()
            .order_by(SalesforceOpportunity.opportunity_type)
        )
        return [row[0] for row in result.all()]

    # =========================================================================
    # STATISTICS
    # =========================================================================

    async def get_dashboard_stats(
        self,
        session: AsyncSession,
        organization_id: UUID,
    ) -> Dict[str, Any]:
        """
        Get aggregated statistics for the Salesforce dashboard.

        Returns:
            Dictionary with counts, pipeline totals, and breakdowns
        """
        # Account count
        account_count_result = await session.execute(
            select(func.count(SalesforceAccount.id)).where(
                SalesforceAccount.organization_id == organization_id
            )
        )
        account_count = account_count_result.scalar() or 0

        # Contact count
        contact_count_result = await session.execute(
            select(func.count(SalesforceContact.id)).where(
                SalesforceContact.organization_id == organization_id
            )
        )
        contact_count = contact_count_result.scalar() or 0

        # Opportunity counts and totals
        opp_stats_result = await session.execute(
            select(
                func.count(SalesforceOpportunity.id),
                func.sum(SalesforceOpportunity.amount),
                func.count(SalesforceOpportunity.id).filter(SalesforceOpportunity.is_closed == False),
                func.sum(SalesforceOpportunity.amount).filter(SalesforceOpportunity.is_closed == False),
                func.count(SalesforceOpportunity.id).filter(SalesforceOpportunity.is_won == True),
                func.sum(SalesforceOpportunity.amount).filter(SalesforceOpportunity.is_won == True),
            ).where(SalesforceOpportunity.organization_id == organization_id)
        )
        opp_row = opp_stats_result.one()
        total_opportunities = opp_row[0] or 0
        total_pipeline_value = opp_row[1] or 0
        open_opportunities = opp_row[2] or 0
        open_pipeline_value = opp_row[3] or 0
        won_opportunities = opp_row[4] or 0
        won_value = opp_row[5] or 0

        # Stage breakdown
        stage_breakdown_result = await session.execute(
            select(
                SalesforceOpportunity.stage_name,
                func.count(SalesforceOpportunity.id),
                func.sum(SalesforceOpportunity.amount),
            )
            .where(
                and_(
                    SalesforceOpportunity.organization_id == organization_id,
                    SalesforceOpportunity.stage_name.isnot(None),
                )
            )
            .group_by(SalesforceOpportunity.stage_name)
            .order_by(func.count(SalesforceOpportunity.id).desc())
        )
        stage_breakdown = [
            {"stage": row[0], "count": row[1], "value": row[2] or 0}
            for row in stage_breakdown_result.all()
        ]

        # Account type breakdown
        type_breakdown_result = await session.execute(
            select(
                SalesforceAccount.account_type,
                func.count(SalesforceAccount.id),
            )
            .where(
                and_(
                    SalesforceAccount.organization_id == organization_id,
                    SalesforceAccount.account_type.isnot(None),
                )
            )
            .group_by(SalesforceAccount.account_type)
            .order_by(func.count(SalesforceAccount.id).desc())
        )
        account_type_breakdown = [
            {"type": row[0], "count": row[1]}
            for row in type_breakdown_result.all()
        ]

        return {
            "accounts": {
                "total": account_count,
                "by_type": account_type_breakdown,
            },
            "contacts": {
                "total": contact_count,
            },
            "opportunities": {
                "total": total_opportunities,
                "total_value": total_pipeline_value,
                "open": open_opportunities,
                "open_value": open_pipeline_value,
                "won": won_opportunities,
                "won_value": won_value,
                "by_stage": stage_breakdown,
            },
        }

    # =========================================================================
    # FULL SYNC SUPPORT (Get All IDs / Delete Missing)
    # =========================================================================

    async def get_all_account_sf_ids(
        self,
        session: AsyncSession,
        organization_id: UUID,
    ) -> set[str]:
        """Get all Salesforce IDs for accounts in an organization."""
        result = await session.execute(
            select(SalesforceAccount.salesforce_id).where(
                SalesforceAccount.organization_id == organization_id
            )
        )
        return {row[0] for row in result.all()}

    async def get_all_contact_sf_ids(
        self,
        session: AsyncSession,
        organization_id: UUID,
    ) -> set[str]:
        """Get all Salesforce IDs for contacts in an organization."""
        result = await session.execute(
            select(SalesforceContact.salesforce_id).where(
                SalesforceContact.organization_id == organization_id
            )
        )
        return {row[0] for row in result.all()}

    async def get_all_opportunity_sf_ids(
        self,
        session: AsyncSession,
        organization_id: UUID,
    ) -> set[str]:
        """Get all Salesforce IDs for opportunities in an organization."""
        result = await session.execute(
            select(SalesforceOpportunity.salesforce_id).where(
                SalesforceOpportunity.organization_id == organization_id
            )
        )
        return {row[0] for row in result.all()}

    async def delete_accounts_not_in(
        self,
        session: AsyncSession,
        organization_id: UUID,
        keep_sf_ids: set[str],
    ) -> int:
        """
        Delete accounts whose Salesforce IDs are not in the keep set.

        Returns:
            Number of accounts deleted
        """
        if not keep_sf_ids:
            # Safety: don't delete everything if keep set is empty
            return 0

        result = await session.execute(
            delete(SalesforceAccount).where(
                SalesforceAccount.organization_id == organization_id,
                SalesforceAccount.salesforce_id.notin_(keep_sf_ids),
            )
        )
        return result.rowcount

    async def delete_contacts_not_in(
        self,
        session: AsyncSession,
        organization_id: UUID,
        keep_sf_ids: set[str],
    ) -> int:
        """
        Delete contacts whose Salesforce IDs are not in the keep set.

        Returns:
            Number of contacts deleted
        """
        if not keep_sf_ids:
            return 0

        result = await session.execute(
            delete(SalesforceContact).where(
                SalesforceContact.organization_id == organization_id,
                SalesforceContact.salesforce_id.notin_(keep_sf_ids),
            )
        )
        return result.rowcount

    async def delete_opportunities_not_in(
        self,
        session: AsyncSession,
        organization_id: UUID,
        keep_sf_ids: set[str],
    ) -> int:
        """
        Delete opportunities whose Salesforce IDs are not in the keep set.

        Returns:
            Number of opportunities deleted
        """
        if not keep_sf_ids:
            return 0

        result = await session.execute(
            delete(SalesforceOpportunity).where(
                SalesforceOpportunity.organization_id == organization_id,
                SalesforceOpportunity.salesforce_id.notin_(keep_sf_ids),
            )
        )
        return result.rowcount


# Singleton instance
salesforce_service = SalesforceService()
