# backend/app/functions/search/search_salesforce.py
"""
Search Salesforce function - Search across Salesforce CRM records.

Provides unified hybrid search across Salesforce Accounts, Contacts, and Opportunities
with filtering by entity type, account, stage, and other fields.
"""

import logging
from typing import List, Optional
from uuid import UUID

from sqlalchemy import or_, select

from ...base import (
    BaseFunction,
    FunctionCategory,
    FunctionMeta,
    FunctionResult,
)
from ...content import ContentItem
from ...context import FunctionContext

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
        description=(
            "Search Salesforce CRM records with hybrid search. "
            "Returns record summaries with relevance scores. To get full details, use "
            "get(item_type='salesforce_account', item_id='...') or the appropriate salesforce_ type. "
            "Use discover_data_sources(source_type='salesforce') to see configured connections."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Short keyword query (2-4 key terms work best). "
                        "Use specific names, company names, or acronyms. "
                        "Good: 'DISCOVER II', 'DHS cybersecurity'. "
                        "Use filters (entity_types, stage_name) to narrow results instead of adding more query terms."
                    ),
                    "default": None,
                },
                "search_mode": {
                    "type": "string",
                    "description": "Search mode: 'keyword' for exact term matches, 'semantic' for conceptual similarity, 'hybrid' combines both for best results.",
                    "default": "hybrid",
                    "enum": ["keyword", "semantic", "hybrid"],
                },
                "semantic_weight": {
                    "type": "number",
                    "description": "Balance between keyword and semantic search in hybrid mode. 0.0 = keyword only, 1.0 = semantic only, 0.5 = equal weight.",
                    "default": 0.5,
                },
                "entity_types": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["account", "contact", "opportunity"]},
                    "description": "Which Salesforce entity types to search. Use 'account' for companies, 'contact' for people, 'opportunity' for deals/pursuits.",
                    "default": ["account", "contact", "opportunity"],
                },
                "account_id": {
                    "type": "string",
                    "description": "Filter contacts and opportunities by their parent account UUID. Use to find all records related to a specific account.",
                    "default": None,
                },
                "account_type": {
                    "type": "string",
                    "description": "Filter accounts by their type classification (e.g., 'Customer', 'Partner', 'Prospect').",
                    "default": None,
                },
                "industry": {
                    "type": "string",
                    "description": "Filter accounts by industry (e.g., 'Government', 'Technology', 'Healthcare').",
                    "default": None,
                },
                "stage_name": {
                    "type": "string",
                    "description": "Filter opportunities by sales stage (e.g., 'Qualification', 'Proposal', 'Negotiation', 'Closed Won').",
                    "default": None,
                },
                "is_open": {
                    "type": "boolean",
                    "description": "Filter opportunities: True for open/active opportunities, False for closed. Works with query to find matching open deals.",
                    "default": None,
                },
                "is_current_employee": {
                    "type": "boolean",
                    "description": "Filter contacts by employment status: True for current employees only, False for former employees.",
                    "default": None,
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results",
                    "default": 20,
                },
                "offset": {
                    "type": "integer",
                    "description": "Number of results to skip for pagination",
                    "default": 0,
                },
            },
            "required": [],
        },
        output_schema={
            "type": "array",
            "description": "List of matching Salesforce records (accounts, contacts, opportunities)",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "Record UUID"},
                    "title": {"type": "string", "description": "Record name"},
                    "type": {"type": "string", "description": "Entity type: salesforce_account, salesforce_contact, salesforce_opportunity", "examples": ["salesforce_opportunity"]},
                    "salesforce_id": {"type": "string", "description": "Salesforce record ID", "nullable": True},
                    "account_type": {"type": "string", "description": "Account type (for accounts)", "nullable": True},
                    "industry": {"type": "string", "description": "Industry (for accounts)", "nullable": True},
                    "website": {"type": "string", "description": "Website URL (for accounts)", "nullable": True},
                    "first_name": {"type": "string", "description": "First name (for contacts)", "nullable": True},
                    "last_name": {"type": "string", "description": "Last name (for contacts)", "nullable": True},
                    "email": {"type": "string", "description": "Email address (for contacts)", "nullable": True},
                    "phone": {"type": "string", "description": "Phone number", "nullable": True},
                    "stage_name": {"type": "string", "description": "Sales stage (for opportunities)", "nullable": True},
                    "amount": {"type": "number", "description": "Deal amount (for opportunities)", "nullable": True},
                    "close_date": {"type": "string", "description": "Expected close date (for opportunities)", "nullable": True},
                    "is_closed": {"type": "boolean", "description": "Whether opportunity is closed", "nullable": True},
                    "is_won": {"type": "boolean", "description": "Whether opportunity was won", "nullable": True},
                    "score": {"type": "number", "description": "Relevance score", "nullable": True},
                },
            },
        },
        tags=["search", "salesforce", "crm", "content", "hybrid"],
        requires_llm=False,
        side_effects=False,
        is_primitive=True,
        payload_profile="thin",
        required_data_sources=["salesforce"],
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
            organization_id=ctx.requires_org_id,
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
        from app.core.database.models import SalesforceAccount

        stmt = select(SalesforceAccount).where(
            ctx.org_filter(SalesforceAccount.organization_id)
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
        from app.core.database.models import SalesforceContact

        stmt = select(SalesforceContact).where(
            ctx.org_filter(SalesforceContact.organization_id)
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
        from app.core.database.models import SalesforceOpportunity

        stmt = select(SalesforceOpportunity).where(
            ctx.org_filter(SalesforceOpportunity.organization_id)
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
