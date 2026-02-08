# backend/app/api/v1/cwr/routers/contracts.py
"""
Tool Contracts API router.

Provides endpoints for:
- Listing tool contracts with JSON Schema input/output
- Getting individual contracts by function name
- Retrieving input/output schemas separately
"""

from typing import Any, Dict, List, Optional
import logging

from fastapi import APIRouter, HTTPException, Query

from app.cwr.tools import initialize_functions
from app.cwr.tools.registry import function_registry
from app.api.v1.cwr.schemas import (
    ToolContractResponse,
    ToolContractListResponse,
)

logger = logging.getLogger("curatore.api.contracts")

router = APIRouter(prefix="/contracts", tags=["Tool Contracts"])


@router.get("/", response_model=ToolContractListResponse)
async def list_contracts(
    category: Optional[str] = Query(None, description="Filter by category"),
    side_effects: Optional[bool] = Query(None, description="Filter by side_effects"),
    is_primitive: Optional[bool] = Query(None, description="Filter by is_primitive"),
    payload_profile: Optional[str] = Query(None, description="Filter by payload_profile"),
):
    """
    List all tool contracts.

    Returns formal JSON Schema contracts for all registered functions,
    including governance metadata (side effects, exposure profiles).
    """
    initialize_functions()

    contracts = function_registry.list_contracts()

    # Apply filters
    if category is not None:
        contracts = [c for c in contracts if c.category == category]
    if side_effects is not None:
        contracts = [c for c in contracts if c.side_effects == side_effects]
    if is_primitive is not None:
        contracts = [c for c in contracts if c.is_primitive == is_primitive]
    if payload_profile is not None:
        contracts = [c for c in contracts if c.payload_profile == payload_profile]

    return ToolContractListResponse(
        contracts=[ToolContractResponse(**c.to_dict()) for c in contracts],
        total=len(contracts),
    )


@router.get("/{name}", response_model=ToolContractResponse)
async def get_contract(name: str):
    """
    Get the tool contract for a specific function.

    Returns JSON Schema input/output definitions and governance metadata.
    """
    initialize_functions()

    contract = function_registry.get_contract(name)
    if not contract:
        raise HTTPException(status_code=404, detail=f"Function not found: {name}")

    return ToolContractResponse(**contract.to_dict())


@router.get("/{name}/input-schema", response_model=Dict[str, Any])
async def get_input_schema(name: str):
    """
    Get the JSON Schema for a function's input parameters.
    """
    initialize_functions()

    contract = function_registry.get_contract(name)
    if not contract:
        raise HTTPException(status_code=404, detail=f"Function not found: {name}")

    return contract.input_schema


@router.get("/{name}/output-schema", response_model=Dict[str, Any])
async def get_output_schema(name: str):
    """
    Get the JSON Schema for a function's output.
    """
    initialize_functions()

    contract = function_registry.get_contract(name)
    if not contract:
        raise HTTPException(status_code=404, detail=f"Function not found: {name}")

    return contract.output_schema
