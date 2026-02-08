# backend/app/api/v1/cwr/routers/functions.py
"""
Functions API router.

Provides endpoints for:
- Listing available functions
- Getting function documentation
- Executing functions directly (for testing/debugging)
"""

from typing import Any, Dict, List, Optional
from uuid import UUID
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.shared.database_service import database_service
from app.dependencies import get_current_user, get_current_user_optional
from app.core.database.models import User
from app.cwr.tools import (
    fn,
    FunctionContext,
    FunctionCategory,
    initialize_functions,
)
from app.api.v1.cwr.schemas import (
    FunctionSchema,
    FunctionListResponse,
    CategoryListResponse,
    ExecuteFunctionRequest,
    ExecuteFunctionResponse,
    meta_to_function_schema,
)

logger = logging.getLogger("curatore.api.functions")

router = APIRouter(prefix="/functions", tags=["Functions"])


# =============================================================================
# ENDPOINTS
# =============================================================================


@router.get("/", response_model=FunctionListResponse)
async def list_functions(
    category: Optional[str] = Query(None, description="Filter by category"),
    tag: Optional[str] = Query(None, description="Filter by tag"),
):
    """
    List all available functions.

    Optionally filter by category or tag.
    """
    initialize_functions()

    if category:
        try:
            cat = FunctionCategory(category)
            metas = fn.list_by_category(cat)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid category: {category}")
    elif tag:
        metas = fn.list_by_tag(tag)
    else:
        metas = fn.list_all()

    functions = [meta_to_function_schema(m) for m in metas]

    return FunctionListResponse(
        functions=functions,
        categories=fn.get_categories(),
        total=len(functions),
    )


@router.get("/categories", response_model=CategoryListResponse)
async def list_categories():
    """
    List function categories with their functions.
    """
    initialize_functions()
    return CategoryListResponse(categories=fn.get_categories())


@router.get("/{name}", response_model=FunctionSchema)
async def get_function(name: str):
    """
    Get documentation for a specific function.
    """
    initialize_functions()

    func = fn.get_or_none(name)
    if not func:
        raise HTTPException(status_code=404, detail=f"Function not found: {name}")

    return meta_to_function_schema(func.meta)


@router.post("/{name}/execute", response_model=ExecuteFunctionResponse)
async def execute_function(
    name: str,
    request: ExecuteFunctionRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Execute a function directly.

    This endpoint is primarily for testing and debugging functions.
    In production, functions are typically executed via procedures/pipelines.
    """
    initialize_functions()

    func = fn.get_or_none(name)
    if not func:
        raise HTTPException(status_code=404, detail=f"Function not found: {name}")

    async with database_service.get_session() as session:
        try:
            # Create execution context
            ctx = await FunctionContext.create(
                session=session,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                dry_run=request.dry_run,
            )

            # Execute function
            result = await func(ctx, **request.params)

            # Commit if successful and not dry run
            if result.success and not request.dry_run:
                await session.commit()

            # Convert ContentItem objects to dicts for JSON serialization
            data = result.data
            if data is not None:
                from app.cwr.tools.content import ContentItem
                if isinstance(data, list):
                    data = [
                        item.to_dict() if isinstance(item, ContentItem) else item
                        for item in data
                    ]
                elif isinstance(data, ContentItem):
                    data = data.to_dict()

            return ExecuteFunctionResponse(
                status=result.status.value,
                message=result.message,
                data=data,
                error=result.error,
                metadata=result.metadata,
                items_processed=result.items_processed,
                items_failed=result.items_failed,
                duration_ms=result.duration_ms,
            )

        except Exception as e:
            logger.exception(f"Function execution failed: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Function execution failed: {str(e)}",
            )
