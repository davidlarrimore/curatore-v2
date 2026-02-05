# backend/app/functions/search/search_salesforce.py
"""
Search Salesforce function - Search across Salesforce CRM records.

Provides unified search across Salesforce Accounts, Contacts, and Opportunities
with filtering by entity type, account, stage, and other fields.
"""

from typing import Any, Dict, List, Optional
from uuid import UUID
import logging

from sqlalchemy import select, or_, func, and_

from ..base import (
    BaseFunction,
    FunctionMeta,
    FunctionCategory,
    FunctionResult,
    ParameterDoc,
)
from ..context import FunctionContext
from ..content import ContentItem

logger = logging.getLogger("curatore.functions.search.search_salesforce")


class SearchSalesforceFunction(BaseFunction):
    """
    Search Salesforce CRM records (Accounts, Contacts, Opportunities).

    Provides text search with filtering by entity type, account, stage, etc.

    Example:
        # Search all entities
        result = await fn.search_salesforce(ctx,
            query="Acme",
            limit=20,
        )

        # Search only opportunities in a specific stage
        result = await fn.search_salesforce(ctx,
            query="federal contract",
            entity_types=["opportunity"],
            stage_name="Qualification",
        )

        # Search contacts at a specific account
        result = await fn.search_salesforce(ctx,
            entity_types=["contact"],
            account_id="uuid-here",
        )
    """

    meta = FunctionMeta(
        name="search_salesforce",
        category=FunctionCategory.SEARCH,
        description="Search Salesforce CRM records (Accounts, Contacts, Opportunities)",
        parameters=[
            ParameterDoc(
                name="query",
                type="str",
                description="Text search query (searches name, description, email, etc.)",
                required=False,
                default=None,
            ),
            ParameterDoc(
                name="entity_types",
                type="list[str]",
                description="Entity types to search",
                required=False,
                default=["account", "contact", "opportunity"],
                enum_values=["account", "contact", "opportunity"],
            ),
            ParameterDoc(
                name="account_id",
                type="str",
                description="Filter by account UUID (for contacts/opportunities)",
                required=False,
                default=None,
            ),
            ParameterDoc(
                name="account_type",
                type="str",
                description="Filter accounts by type",
                required=False,
                default=None,
            ),
            ParameterDoc(
                name="industry",
                type="str",
                description="Filter accounts by industry",
                required=False,
                default=None,
            ),
            ParameterDoc(
                name="stage_name",
                type="str",
                description="Filter opportunities by stage",
                required=False,
                default=None,
            ),
            ParameterDoc(
                name="is_open",
                type="bool",
                description="Filter opportunities by open/closed status",
                required=False,
                default=None,
            ),
            ParameterDoc(
                name="is_current_employee",
                type="bool",
                description="Filter contacts by current employee status",
                required=False,
                default=None,
            ),
            ParameterDoc(
                name="limit",
                type="int",
                description="Maximum number of results per entity type",
                required=False,
                default=20,
            ),
        ],
        returns="list[ContentItem]: Search results as ContentItem instances",
        tags=["search", "salesforce", "crm", "content"],
        requires_llm=False,
        examples=[
            {
                "description": "Search all Salesforce records",
                "params": {
                    "query": "federal",
                    "limit": 10,
                },
            },
            {
                "description": "Search open opportunities",
                "params": {
                    "entity_types": ["opportunity"],
                    "is_open": True,
                    "limit": 20,
                },
            },
            {
                "description": "Search contacts at an account",
                "params": {
                    "entity_types": ["contact"],
                    "account_id": "uuid-here",
                },
            },
        ],
    )

    async def execute(self, ctx: FunctionContext, **params) -> FunctionResult:
        """Execute Salesforce search."""
        query = params.get("query", "").strip() if params.get("query") else None
        entity_types = params.get("entity_types") or ["account", "contact", "opportunity"]
        account_id = params.get("account_id")
        account_type = params.get("account_type")
        industry = params.get("industry")
        stage_name = params.get("stage_name")
        is_open = params.get("is_open")
        is_current_employee = params.get("is_current_employee")
        limit = min(params.get("limit", 20), 100)

        # Import models
        from ...database.models import (
            SalesforceAccount,
            SalesforceContact,
            SalesforceOpportunity,
        )

        results: List[ContentItem] = []

        try:
            # Search accounts
            if "account" in entity_types:
                accounts = await self._search_accounts(
                    ctx=ctx,
                    query=query,
                    account_type=account_type,
                    industry=industry,
                    limit=limit,
                )
                results.extend(accounts)

            # Search contacts
            if "contact" in entity_types:
                contacts = await self._search_contacts(
                    ctx=ctx,
                    query=query,
                    account_id=account_id,
                    is_current_employee=is_current_employee,
                    limit=limit,
                )
                results.extend(contacts)

            # Search opportunities
            if "opportunity" in entity_types:
                opportunities = await self._search_opportunities(
                    ctx=ctx,
                    query=query,
                    account_id=account_id,
                    stage_name=stage_name,
                    is_open=is_open,
                    limit=limit,
                )
                results.extend(opportunities)

            return FunctionResult.success_result(
                data=results,
                message=f"Found {len(results)} Salesforce records",
                metadata={
                    "query": query,
                    "entity_types": entity_types,
                    "total_found": len(results),
                    "filters_applied": {
                        "account_id": account_id,
                        "account_type": account_type,
                        "industry": industry,
                        "stage_name": stage_name,
                        "is_open": is_open,
                        "is_current_employee": is_current_employee,
                    },
                    "result_type": "ContentItem",
                },
                items_processed=len(results),
            )

        except Exception as e:
            logger.exception(f"Salesforce search failed: {e}")
            return FunctionResult.failed_result(
                error=str(e),
                message="Salesforce search failed",
            )

    async def _search_accounts(
        self,
        ctx: FunctionContext,
        query: Optional[str],
        account_type: Optional[str],
        industry: Optional[str],
        limit: int,
    ) -> List[ContentItem]:
        """Search Salesforce accounts."""
        from ...database.models import SalesforceAccount

        stmt = select(SalesforceAccount).where(
            SalesforceAccount.organization_id == ctx.organization_id
        )

        # Text search
        if query:
            stmt = stmt.where(
                or_(
                    SalesforceAccount.name.ilike(f"%{query}%"),
                    SalesforceAccount.description.ilike(f"%{query}%"),
                    SalesforceAccount.website.ilike(f"%{query}%"),
                )
            )

        # Filters
        if account_type:
            stmt = stmt.where(SalesforceAccount.account_type == account_type)
        if industry:
            stmt = stmt.where(SalesforceAccount.industry == industry)

        stmt = stmt.order_by(SalesforceAccount.name).limit(limit)

        result = await ctx.session.execute(stmt)
        rows = result.scalars().all()

        items = []
        for row in rows:
            item = ContentItem(
                id=str(row.id),
                type="salesforce_account",
                display_type="Account",
                title=row.name,
                text=None,
                text_format="json",
                fields={
                    "salesforce_id": row.salesforce_id,
                    "account_type": row.account_type,
                    "industry": row.industry,
                    "website": row.website,
                    "phone": row.phone,
                },
                metadata={
                    "search_entity": "account",
                },
            )
            items.append(item)

        return items

    async def _search_contacts(
        self,
        ctx: FunctionContext,
        query: Optional[str],
        account_id: Optional[str],
        is_current_employee: Optional[bool],
        limit: int,
    ) -> List[ContentItem]:
        """Search Salesforce contacts."""
        from ...database.models import SalesforceContact

        stmt = select(SalesforceContact).where(
            SalesforceContact.organization_id == ctx.organization_id
        )

        # Text search
        if query:
            stmt = stmt.where(
                or_(
                    SalesforceContact.first_name.ilike(f"%{query}%"),
                    SalesforceContact.last_name.ilike(f"%{query}%"),
                    SalesforceContact.email.ilike(f"%{query}%"),
                    SalesforceContact.title.ilike(f"%{query}%"),
                )
            )

        # Filters
        if account_id:
            stmt = stmt.where(SalesforceContact.account_id == UUID(account_id))
        if is_current_employee is not None:
            stmt = stmt.where(SalesforceContact.is_current_employee == is_current_employee)

        stmt = stmt.order_by(SalesforceContact.last_name, SalesforceContact.first_name).limit(limit)

        result = await ctx.session.execute(stmt)
        rows = result.scalars().all()

        items = []
        for row in rows:
            full_name = f"{row.first_name or ''} {row.last_name or ''}".strip()
            item = ContentItem(
                id=str(row.id),
                type="salesforce_contact",
                display_type="Contact",
                title=full_name or "Unknown Contact",
                text=None,
                text_format="json",
                fields={
                    "salesforce_id": row.salesforce_id,
                    "first_name": row.first_name,
                    "last_name": row.last_name,
                    "email": row.email,
                    "title": row.title,
                    "phone": row.phone,
                    "is_current_employee": row.is_current_employee,
                },
                metadata={
                    "search_entity": "contact",
                    "account_id": str(row.account_id) if row.account_id else None,
                },
            )
            items.append(item)

        return items

    async def _search_opportunities(
        self,
        ctx: FunctionContext,
        query: Optional[str],
        account_id: Optional[str],
        stage_name: Optional[str],
        is_open: Optional[bool],
        limit: int,
    ) -> List[ContentItem]:
        """Search Salesforce opportunities."""
        from ...database.models import SalesforceOpportunity

        stmt = select(SalesforceOpportunity).where(
            SalesforceOpportunity.organization_id == ctx.organization_id
        )

        # Text search
        if query:
            stmt = stmt.where(
                or_(
                    SalesforceOpportunity.name.ilike(f"%{query}%"),
                    SalesforceOpportunity.description.ilike(f"%{query}%"),
                )
            )

        # Filters
        if account_id:
            stmt = stmt.where(SalesforceOpportunity.account_id == UUID(account_id))
        if stage_name:
            stmt = stmt.where(SalesforceOpportunity.stage_name == stage_name)
        if is_open is not None:
            stmt = stmt.where(SalesforceOpportunity.is_closed == (not is_open))

        stmt = stmt.order_by(SalesforceOpportunity.close_date.desc()).limit(limit)

        result = await ctx.session.execute(stmt)
        rows = result.scalars().all()

        items = []
        for row in rows:
            item = ContentItem(
                id=str(row.id),
                type="salesforce_opportunity",
                display_type="Opportunity",
                title=row.name,
                text=None,
                text_format="json",
                fields={
                    "salesforce_id": row.salesforce_id,
                    "stage_name": row.stage_name,
                    "amount": float(row.amount) if row.amount else None,
                    "probability": row.probability,
                    "close_date": row.close_date.isoformat() if row.close_date else None,
                    "is_closed": row.is_closed,
                    "is_won": row.is_won,
                    "opportunity_type": row.opportunity_type,
                },
                metadata={
                    "search_entity": "opportunity",
                    "account_id": str(row.account_id) if row.account_id else None,
                },
            )
            items.append(item)

        return items
