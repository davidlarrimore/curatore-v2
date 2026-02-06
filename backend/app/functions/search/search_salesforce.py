# backend/app/functions/search/search_salesforce.py
"""
Search Salesforce function - Search across Salesforce CRM records.

Provides unified hybrid search across Salesforce Accounts, Contacts, and Opportunities
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
        description="Search Salesforce CRM records (Accounts, Contacts, Opportunities) with hybrid search",
        parameters=[
            ParameterDoc(
                name="query",
                type="str",
                description="Search query for name, description, email, and other text fields. Combines with all filters below for refined results.",
                required=False,
                default=None,
            ),
            ParameterDoc(
                name="search_mode",
                type="str",
                description="Search mode: 'keyword' for exact term matches, 'semantic' for conceptual similarity, 'hybrid' combines both for best results.",
                required=False,
                default="hybrid",
                enum_values=["keyword", "semantic", "hybrid"],
            ),
            ParameterDoc(
                name="semantic_weight",
                type="float",
                description="Balance between keyword and semantic search in hybrid mode. 0.0 = keyword only, 1.0 = semantic only, 0.5 = equal weight.",
                required=False,
                default=0.5,
            ),
            ParameterDoc(
                name="entity_types",
                type="list[str]",
                description="Which Salesforce entity types to search. Use 'account' for companies, 'contact' for people, 'opportunity' for deals/pursuits.",
                required=False,
                default=["account", "contact", "opportunity"],
                enum_values=["account", "contact", "opportunity"],
            ),
            ParameterDoc(
                name="account_id",
                type="str",
                description="Filter contacts and opportunities by their parent account UUID. Use to find all records related to a specific account.",
                required=False,
                default=None,
            ),
            ParameterDoc(
                name="account_type",
                type="str",
                description="Filter accounts by their type classification (e.g., 'Customer', 'Partner', 'Prospect').",
                required=False,
                default=None,
            ),
            ParameterDoc(
                name="industry",
                type="str",
                description="Filter accounts by industry (e.g., 'Government', 'Technology', 'Healthcare').",
                required=False,
                default=None,
            ),
            ParameterDoc(
                name="stage_name",
                type="str",
                description="Filter opportunities by sales stage (e.g., 'Qualification', 'Proposal', 'Negotiation', 'Closed Won').",
                required=False,
                default=None,
            ),
            ParameterDoc(
                name="is_open",
                type="bool",
                description="Filter opportunities: True for open/active opportunities, False for closed. Works with query to find matching open deals.",
                required=False,
                default=None,
            ),
            ParameterDoc(
                name="is_current_employee",
                type="bool",
                description="Filter contacts by employment status: True for current employees only, False for former employees.",
                required=False,
                default=None,
            ),
            ParameterDoc(
                name="limit",
                type="int",
                description="Maximum number of results",
                required=False,
                default=20,
            ),
            ParameterDoc(
                name="offset",
                type="int",
                description="Number of results to skip for pagination",
                required=False,
                default=0,
            ),
        ],
        returns="list[ContentItem]: Search results as ContentItem instances",
        tags=["search", "salesforce", "crm", "content", "hybrid"],
        requires_llm=False,
        examples=[
            {
                "description": "Search open opportunities with keyword",
                "params": {
                    "query": "federal contracts",
                    "search_mode": "hybrid",
                    "entity_types": ["opportunity"],
                    "is_open": True,
                },
            },
            {
                "description": "Semantic search for cybersecurity opportunities by stage",
                "params": {
                    "query": "cybersecurity services",
                    "search_mode": "semantic",
                    "entity_types": ["opportunity"],
                    "stage_name": "Qualification",
                    "is_open": True,
                },
            },
            {
                "description": "Search government accounts by industry",
                "params": {
                    "query": "agency",
                    "search_mode": "hybrid",
                    "entity_types": ["account"],
                    "industry": "Government",
                },
            },
            {
                "description": "Search contacts at a specific account",
                "params": {
                    "query": "program manager",
                    "entity_types": ["contact"],
                    "account_id": "uuid-here",
                    "is_current_employee": True,
                },
            },
            {
                "description": "Find all open deals mentioning cloud",
                "params": {
                    "query": "cloud migration",
                    "search_mode": "hybrid",
                    "entity_types": ["opportunity"],
                    "is_open": True,
                    "limit": 50,
                },
            },
        ],
    )

    async def execute(self, ctx: FunctionContext, **params) -> FunctionResult:
        """Execute Salesforce search with optional hybrid search."""
        query = params.get("query", "").strip() if params.get("query") else None
        search_mode = params.get("search_mode", "hybrid")
        semantic_weight = params.get("semantic_weight", 0.5)
        entity_types = params.get("entity_types") or ["account", "contact", "opportunity"]
        account_id = params.get("account_id")
        account_type = params.get("account_type")
        industry = params.get("industry")
        stage_name = params.get("stage_name")
        is_open = params.get("is_open")
        is_current_employee = params.get("is_current_employee")
        limit = min(params.get("limit", 20), 100)
        offset = params.get("offset", 0)

        # Import models
        from ...database.models import (
            SalesforceAccount,
            SalesforceContact,
            SalesforceOpportunity,
        )

        try:
            # If query is provided, use PgSearchService for hybrid search
            if query:
                return await self._search_with_pg_service(
                    ctx=ctx,
                    query=query,
                    search_mode=search_mode,
                    semantic_weight=semantic_weight,
                    entity_types=entity_types,
                    limit=limit,
                    offset=offset,
                )

            # Otherwise, use direct database query with filters (no text search)
            results: List[ContentItem] = []

            # Search accounts
            if "account" in entity_types:
                accounts = await self._search_accounts(
                    ctx=ctx,
                    query=None,  # No text search when using direct DB
                    account_type=account_type,
                    industry=industry,
                    limit=limit,
                )
                results.extend(accounts)

            # Search contacts
            if "contact" in entity_types:
                contacts = await self._search_contacts(
                    ctx=ctx,
                    query=None,
                    account_id=account_id,
                    is_current_employee=is_current_employee,
                    limit=limit,
                )
                results.extend(contacts)

            # Search opportunities
            if "opportunity" in entity_types:
                opportunities = await self._search_opportunities(
                    ctx=ctx,
                    query=None,
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

    async def _search_with_pg_service(
        self,
        ctx: FunctionContext,
        query: str,
        search_mode: str,
        semantic_weight: float,
        entity_types: List[str],
        limit: int,
        offset: int,
    ) -> FunctionResult:
        """Use PgSearchService for hybrid search."""
        search_results = await ctx.search_service.search_salesforce(
            session=ctx.session,
            organization_id=ctx.organization_id,
            query=query,
            search_mode=search_mode,
            semantic_weight=semantic_weight,
            entity_types=entity_types,
            limit=limit,
            offset=offset,
        )

        # Convert SearchHit results to ContentItem format
        results = []
        for hit in search_results.hits:
            item = ContentItem(
                id=hit.asset_id,
                type=f"salesforce_{hit.source_type.lower()}" if hit.source_type else "salesforce",
                display_type=hit.source_type or "Record",
                title=hit.title,
                text=None,
                text_format="json",
                fields={
                    "source_type": hit.source_type,
                    "url": hit.url,
                    "created_at": hit.created_at,
                },
                metadata={
                    "score": hit.score,
                    "keyword_score": hit.keyword_score,
                    "semantic_score": hit.semantic_score,
                    "highlights": hit.highlights,
                    "search_mode": search_mode,
                    "search_entity": hit.source_type.lower() if hit.source_type else None,
                },
            )
            results.append(item)

        return FunctionResult.success_result(
            data=results,
            message=f"Found {len(results)} Salesforce records matching '{query}'",
            metadata={
                "total": search_results.total,
                "limit": limit,
                "offset": offset,
                "has_more": offset + len(results) < search_results.total,
                "query": query,
                "search_mode": search_mode,
                "semantic_weight": semantic_weight,
                "entity_types": entity_types,
                "result_type": "ContentItem",
            },
            items_processed=len(results),
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
