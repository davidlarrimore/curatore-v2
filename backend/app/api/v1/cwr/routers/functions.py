# backend/app/api/v1/cwr/routers/functions.py
"""
Functions API router.

Provides endpoints for:
- Listing available functions
- Getting function documentation
- Executing functions directly (for testing/debugging)
"""

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.v1.cwr.schemas import (
    CategoryListResponse,
    ExecuteFunctionRequest,
    ExecuteFunctionResponse,
    FunctionListResponse,
    FunctionSchema,
    meta_to_function_schema,
)
from app.core.database.models import User
from app.core.shared.database_service import database_service
from app.cwr.tools import (
    FunctionCategory,
    FunctionContext,
    fn,
    initialize_functions,
)
from app.dependencies import (
    get_current_org_id_or_delegated,
    get_current_user_or_delegated,
    get_effective_org_id_or_delegated,
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
    current_user: User = Depends(get_current_user_or_delegated),
    org_id: Optional[UUID] = Depends(get_effective_org_id_or_delegated),
):
    """
    List all available functions.

    Optionally filter by category or tag.
    Functions are filtered by the org's enabled data sources — tools whose
    required_data_sources are not active for the org are excluded.
    System context (org_id=None) sees all functions.
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

    # Filter by org's enabled data sources (system context sees all)
    if org_id is not None:
        from app.core.metadata.registry_service import metadata_registry_service

        async with database_service.get_session() as session:
            enabled_ds = await metadata_registry_service.get_enabled_data_sources(session, org_id)
        if enabled_ds is not None:
            metas = [
                m for m in metas
                if not m.required_data_sources
                or any(ds in enabled_ds for ds in m.required_data_sources)
            ]

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
async def get_function(
    name: str,
    current_user: User = Depends(get_current_user_or_delegated),
    org_id: Optional[UUID] = Depends(get_effective_org_id_or_delegated),
):
    """
    Get documentation for a specific function.

    Returns 404 if the function's required data sources are not enabled
    for the current org.  System context (org_id=None) sees all functions.
    """
    initialize_functions()

    func = fn.get_or_none(name)
    if not func:
        raise HTTPException(status_code=404, detail=f"Function not found: {name}")

    # Check org data source availability
    if org_id is not None and func.meta.required_data_sources:
        from app.core.metadata.registry_service import metadata_registry_service

        async with database_service.get_session() as session:
            enabled_ds = await metadata_registry_service.get_enabled_data_sources(session, org_id)
        if enabled_ds is not None and not any(ds in enabled_ds for ds in func.meta.required_data_sources):
            raise HTTPException(status_code=404, detail=f"Function not found: {name}")

    return meta_to_function_schema(func.meta)


@router.post("/{name}/execute", response_model=ExecuteFunctionResponse)
async def execute_function(
    name: str,
    request: ExecuteFunctionRequest,
    current_user: User = Depends(get_current_user_or_delegated),
    org_id: UUID = Depends(get_current_org_id_or_delegated),
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

    # Governance: check required_data_sources before execution
    required_ds = getattr(func.meta, 'required_data_sources', None)
    if required_ds:
        from app.core.metadata.registry_service import metadata_registry_service

        async with database_service.get_session() as check_session:
            catalog = await metadata_registry_service.get_data_source_catalog(
                check_session, org_id
            )
            if not any(catalog.get(ds, {}).get("is_active", False) for ds in required_ds):
                raise HTTPException(
                    status_code=403,
                    detail=f"Function '{name}' requires data source(s) {required_ds} "
                    f"but none are enabled for this organization.",
                )

    async with database_service.get_session() as session:
        try:
            # Create execution context
            ctx = await FunctionContext.create(
                session=session,
                organization_id=org_id,
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
