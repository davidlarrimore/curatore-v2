# backend/app/functions/search/query_model.py
"""
Query Model function - SQLAlchemy model queries.

Executes queries against SQLAlchemy models with filters and pagination.
"""

import logging
from typing import Any, Dict
from uuid import UUID

from sqlalchemy import Float, Integer, String, and_, func, select

from ...base import (
    BaseFunction,
    FunctionCategory,
    FunctionMeta,
    FunctionResult,
)
from ...context import FunctionContext

logger = logging.getLogger("curatore.functions.search.query_model")


# Allowed models for querying (whitelist for security)
ALLOWED_MODELS = {
    "Asset": "app.core.database.models.Asset",
    "ExtractionResult": "app.core.database.models.ExtractionResult",
    "Run": "app.core.database.models.Run",
    "SamSolicitation": "app.core.database.models.SamSolicitation",
    "SamNotice": "app.core.database.models.SamNotice",
    "ScrapeCollection": "app.core.database.models.ScrapeCollection",
    "SharePointSyncConfig": "app.core.database.models.SharePointSyncConfig",
    # Salesforce CRM models
    "SalesforceAccount": "app.core.database.models.SalesforceAccount",
    "SalesforceContact": "app.core.database.models.SalesforceContact",
    "SalesforceOpportunity": "app.core.database.models.SalesforceOpportunity",
    # Acquisition Forecast models
    "AgForecast": "app.core.database.models.AgForecast",
    "ApfsForecast": "app.core.database.models.ApfsForecast",
    "StateForecast": "app.core.database.models.StateForecast",
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
        description=(
            "Query database records directly with filters and pagination. "
            "Use this to get full details for forecasts (AgForecast, ApfsForecast, StateForecast), "
            "SAM searches (SamSolicitation, SamNotice), SharePoint configs, scrape collections, "
            "Salesforce records, and other entities. "
            "This is the recommended tool for getting forecast details after search_forecasts."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "model": {
                    "type": "string",
                    "description": "Database record type to query. Use AgForecast/ApfsForecast/StateForecast for forecast details, SamSolicitation/SamNotice for SAM data, Asset for documents, SharePointSyncConfig for SharePoint configs, etc.",
                    "enum": list(ALLOWED_MODELS.keys()),
                },
                "filters": {
                    "type": "object",
                    "description": "Filters to apply (field: value or field: {op: value})",
                    "default": None,
                    "examples": [{"status": "ready", "created_at": {"gte": "2026-01-01"}}],
                },
                "order_by": {
                    "type": "string",
                    "description": "Field to order by (prefix with - for descending)",
                    "default": "-created_at",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results",
                    "default": 100,
                },
                "offset": {
                    "type": "integer",
                    "description": "Number of results to skip",
                    "default": 0,
                },
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Fields to include in results (default: all)",
                    "default": None,
                },
            },
            "required": ["model"],
        },
        output_schema={
            "type": "array",
            "description": "List of model records. Fields vary by model type.",
            "items": {"type": "object"},
        },
        tags=["search", "database", "query"],
        requires_llm=False,
        side_effects=False,
        is_primitive=True,
        payload_profile="thin",
        examples=[
            {
                "description": "Get ready assets",
                "params": {
                    "model": "Asset",
                    "filters": {"status": "ready"},
                    "limit": 50,
                },
            },
            {
                "description": "Get full details for a specific AG forecast (after search_forecasts)",
                "params": {
                    "model": "AgForecast",
                    "filters": {"id": "<forecast-uuid>"},
                },
            },
            {
                "description": "Get DHS APFS forecasts for a fiscal year",
                "params": {
                    "model": "ApfsForecast",
                    "filters": {"fiscal_year": 2026},
                    "limit": 50,
                },
            },
            {
                "description": "Get recent SAM solicitations",
                "params": {
                    "model": "SamSolicitation",
                    "filters": {"status": "active"},
                    "order_by": "-created_at",
                    "limit": 20,
                },
            },
        ],
    )

    def _get_model_class(self, model_name: str):
        """Get SQLAlchemy model class by name."""
        if model_name not in ALLOWED_MODELS:
            raise ValueError(f"Model '{model_name}' is not allowed")

        # Import the model
        from app.core.database import models

        if hasattr(models, model_name):
            return getattr(models, model_name)

        raise ValueError(f"Model '{model_name}' not found")

    def _coerce_value(self, column, value):
        """Coerce filter value to match the column's SQL type."""
        try:
            col_type = column.property.columns[0].type
        except (AttributeError, IndexError):
            return value

        if isinstance(col_type, String) and isinstance(value, (int, float)):
            return str(value)
        if isinstance(col_type, (Integer, Float)) and isinstance(value, str):
            try:
                return int(value) if isinstance(col_type, Integer) else float(value)
            except ValueError:
                return value
        return value

    def _build_filters(self, model_class, filters: Dict[str, Any], ctx: FunctionContext):
        """Build SQLAlchemy filter conditions."""
        conditions = []

        # Always filter by organization
        if hasattr(model_class, "organization_id"):
            conditions.append(ctx.org_filter(model_class.organization_id))

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
                    op_value = self._coerce_value(column, op_value)
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
                        if isinstance(op_value, list):
                            op_value = [self._coerce_value(column, v) for v in op_value]
                        conditions.append(column.in_(op_value))
                    elif op == "nin":
                        if isinstance(op_value, list):
                            op_value = [self._coerce_value(column, v) for v in op_value]
                        conditions.append(column.notin_(op_value))
                    elif op == "contains":
                        conditions.append(column.contains(op_value))
                    elif op in ("ilike", "icontains"):
                        conditions.append(column.ilike(f"%{op_value}%"))
                    elif op == "is_null":
                        if op_value:
                            conditions.append(column.is_(None))
                        else:
                            conditions.append(column.isnot(None))
            else:
                # Simple equality with type coercion
                value = self._coerce_value(column, value)
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
            conditions = self._build_filters(model_class, filters, ctx)
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
            count_conditions = self._build_filters(model_class, filters, ctx)
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
