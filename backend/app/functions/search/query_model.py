# backend/app/functions/search/query_model.py
"""
Query Model function - SQLAlchemy model queries.

Executes queries against SQLAlchemy models with filters and pagination.
"""

from typing import Any, Dict, List, Optional, Type
from uuid import UUID
import logging

from sqlalchemy import select, and_, or_, func
from sqlalchemy.orm import selectinload

from ..base import (
    BaseFunction,
    FunctionMeta,
    FunctionCategory,
    FunctionResult,
    ParameterDoc,
)
from ..context import FunctionContext

logger = logging.getLogger("curatore.functions.search.query_model")


# Allowed models for querying (whitelist for security)
ALLOWED_MODELS = {
    "Asset": "app.database.models.Asset",
    "ExtractionResult": "app.database.models.ExtractionResult",
    "Run": "app.database.models.Run",
    "SamSolicitation": "app.database.models.SamSolicitation",
    "SamNotice": "app.database.models.SamNotice",
    "ScrapeCollection": "app.database.models.ScrapeCollection",
    "SharePointSyncConfig": "app.database.models.SharePointSyncConfig",
    # Salesforce CRM models
    "SalesforceAccount": "app.database.models.SalesforceAccount",
    "SalesforceContact": "app.database.models.SalesforceContact",
    "SalesforceOpportunity": "app.database.models.SalesforceOpportunity",
}


class QueryModelFunction(BaseFunction):
    """
    Query SQLAlchemy models with filters.

    Provides a secure interface to query database models with filters,
    sorting, and pagination. Only allowed models can be queried.

    Example:
        result = await fn.query_model(ctx,
            model="Asset",
            filters={"status": "ready", "source_type": "sharepoint"},
            order_by="-created_at",
            limit=100,
        )
    """

    meta = FunctionMeta(
        name="query_model",
        category=FunctionCategory.SEARCH,
        description="Query SQLAlchemy models with filters",
        parameters=[
            ParameterDoc(
                name="model",
                type="str",
                description="Model name to query",
                required=True,
                enum_values=list(ALLOWED_MODELS.keys()),
            ),
            ParameterDoc(
                name="filters",
                type="dict",
                description="Filters to apply (field: value or field: {op: value})",
                required=False,
                default=None,
                example={"status": "ready", "created_at": {"gte": "2026-01-01"}},
            ),
            ParameterDoc(
                name="order_by",
                type="str",
                description="Field to order by (prefix with - for descending)",
                required=False,
                default="-created_at",
            ),
            ParameterDoc(
                name="limit",
                type="int",
                description="Maximum number of results",
                required=False,
                default=100,
            ),
            ParameterDoc(
                name="offset",
                type="int",
                description="Number of results to skip",
                required=False,
                default=0,
            ),
            ParameterDoc(
                name="fields",
                type="list[str]",
                description="Fields to include in results (default: all)",
                required=False,
                default=None,
            ),
        ],
        returns="list[dict]: Query results",
        tags=["search", "database", "query"],
        requires_llm=False,
        examples=[
            {
                "description": "Get ready assets",
                "params": {
                    "model": "Asset",
                    "filters": {"status": "ready"},
                    "limit": 50,
                },
            },
        ],
    )

    def _get_model_class(self, model_name: str):
        """Get SQLAlchemy model class by name."""
        if model_name not in ALLOWED_MODELS:
            raise ValueError(f"Model '{model_name}' is not allowed")

        # Import the model
        from ...database import models

        if hasattr(models, model_name):
            return getattr(models, model_name)

        raise ValueError(f"Model '{model_name}' not found")

    def _build_filters(self, model_class, filters: Dict[str, Any], org_id: UUID):
        """Build SQLAlchemy filter conditions."""
        conditions = []

        # Always filter by organization
        if hasattr(model_class, "organization_id"):
            conditions.append(model_class.organization_id == org_id)

        if not filters:
            return conditions

        for field, value in filters.items():
            if not hasattr(model_class, field):
                logger.warning(f"Ignoring unknown field: {field}")
                continue

            column = getattr(model_class, field)

            if isinstance(value, dict):
                # Operator-based filter
                for op, op_value in value.items():
                    if op == "eq":
                        conditions.append(column == op_value)
                    elif op == "ne":
                        conditions.append(column != op_value)
                    elif op == "gt":
                        conditions.append(column > op_value)
                    elif op == "gte":
                        conditions.append(column >= op_value)
                    elif op == "lt":
                        conditions.append(column < op_value)
                    elif op == "lte":
                        conditions.append(column <= op_value)
                    elif op == "in":
                        conditions.append(column.in_(op_value))
                    elif op == "contains":
                        conditions.append(column.contains(op_value))
                    elif op == "ilike":
                        conditions.append(column.ilike(f"%{op_value}%"))
                    elif op == "is_null":
                        if op_value:
                            conditions.append(column.is_(None))
                        else:
                            conditions.append(column.isnot(None))
            else:
                # Simple equality
                conditions.append(column == value)

        return conditions

    async def execute(self, ctx: FunctionContext, **params) -> FunctionResult:
        """Execute model query."""
        model_name = params["model"]
        filters = params.get("filters") or {}
        order_by = params.get("order_by", "-created_at")
        limit = min(params.get("limit", 100), 1000)  # Cap at 1000
        offset = params.get("offset", 0)
        fields = params.get("fields")

        try:
            model_class = self._get_model_class(model_name)

            # Build query
            query = select(model_class)

            # Apply filters
            conditions = self._build_filters(model_class, filters, ctx.organization_id)
            if conditions:
                query = query.where(and_(*conditions))

            # Apply ordering
            if order_by:
                descending = order_by.startswith("-")
                field_name = order_by.lstrip("-")
                if hasattr(model_class, field_name):
                    order_column = getattr(model_class, field_name)
                    query = query.order_by(order_column.desc() if descending else order_column)

            # Apply pagination
            query = query.limit(limit).offset(offset)

            # Execute query
            result = await ctx.session.execute(query)
            rows = result.scalars().all()

            # Convert to dicts
            results = []
            for row in rows:
                row_dict = {}
                for column in row.__table__.columns:
                    if fields and column.name not in fields:
                        continue
                    value = getattr(row, column.name)
                    # Convert UUIDs to strings
                    if isinstance(value, UUID):
                        value = str(value)
                    row_dict[column.name] = value
                results.append(row_dict)

            # Get total count for pagination info
            count_query = select(func.count()).select_from(model_class)
            count_conditions = self._build_filters(model_class, filters, ctx.organization_id)
            if count_conditions:
                count_query = count_query.where(and_(*count_conditions))
            total_result = await ctx.session.execute(count_query)
            total = total_result.scalar()

            return FunctionResult.success_result(
                data=results,
                message=f"Found {len(results)} {model_name} records",
                metadata={
                    "model": model_name,
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                    "has_more": offset + len(results) < total,
                },
                items_processed=len(results),
            )

        except ValueError as e:
            return FunctionResult.failed_result(
                error=str(e),
                message="Invalid query parameters",
            )
        except Exception as e:
            logger.exception(f"Query failed: {e}")
            return FunctionResult.failed_result(
                error=str(e),
                message="Database query failed",
            )
