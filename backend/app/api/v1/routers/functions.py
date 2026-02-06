# backend/app/api/v1/routers/functions.py
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
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ....services.database_service import database_service
from ....dependencies import get_current_user, get_current_user_optional
from ....database.models import User
from ....functions import (
    fn,
    FunctionContext,
    FunctionCategory,
    initialize_functions,
)

logger = logging.getLogger("curatore.api.functions")

router = APIRouter(prefix="/functions", tags=["Functions"])


# =============================================================================
# PYDANTIC MODELS
# =============================================================================


class ParameterSchema(BaseModel):
    """Parameter documentation schema."""
    name: str
    type: str
    description: str
    required: bool = True
    default: Any = None
    enum_values: Optional[List[str]] = None
    example: Any = None


class FunctionSchema(BaseModel):
    """Function metadata schema."""
    name: str
    category: str
    description: str
    parameters: List[ParameterSchema]
    returns: str
    examples: List[Dict[str, Any]] = []
    tags: List[str] = []
    requires_llm: bool = False
    requires_session: bool = True
    is_async: bool = True
    version: str = "1.0.0"


class FunctionListResponse(BaseModel):
    """List of functions response."""
    functions: List[FunctionSchema]
    categories: Dict[str, List[str]]
    total: int


class CategoryListResponse(BaseModel):
    """List of categories response."""
    categories: Dict[str, List[str]]


class ExecuteFunctionRequest(BaseModel):
    """Request to execute a function."""
    params: Dict[str, Any] = Field(default_factory=dict, description="Function parameters")
    dry_run: bool = Field(default=False, description="If true, function will not make changes")


class ExecuteFunctionResponse(BaseModel):
    """Function execution response."""
    status: str
    message: Optional[str] = None
    data: Any = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = {}
    items_processed: int = 0
    items_failed: int = 0
    duration_ms: Optional[int] = None


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

    functions = [
        FunctionSchema(
            name=m.name,
            category=m.category.value,
            description=m.description,
            parameters=[
                ParameterSchema(
                    name=p.name,
                    type=p.type,
                    description=p.description,
                    required=p.required,
                    default=p.default,
                    enum_values=p.enum_values,
                    example=p.example,
                )
                for p in m.parameters
            ],
            returns=m.returns,
            examples=m.examples,
            tags=m.tags,
            requires_llm=m.requires_llm,
            requires_session=m.requires_session,
            is_async=m.is_async,
            version=m.version,
        )
        for m in metas
    ]

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

    m = func.meta
    return FunctionSchema(
        name=m.name,
        category=m.category.value,
        description=m.description,
        parameters=[
            ParameterSchema(
                name=p.name,
                type=p.type,
                description=p.description,
                required=p.required,
                default=p.default,
                enum_values=p.enum_values,
                example=p.example,
            )
            for p in m.parameters
        ],
        returns=m.returns,
        examples=m.examples,
        tags=m.tags,
        requires_llm=m.requires_llm,
        requires_session=m.requires_session,
        is_async=m.is_async,
        version=m.version,
    )


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
                from ....functions.content import ContentItem
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
