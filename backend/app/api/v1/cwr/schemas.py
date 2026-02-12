"""
CWR (Content Workflow Runtime) namespace Pydantic schemas.

Functions, procedures, and pipeline API models.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# =============================================================================
# FUNCTION SCHEMAS
# =============================================================================


class FunctionSchema(BaseModel):
    """Function metadata schema."""
    name: str
    category: str
    description: str
    input_schema: Dict[str, Any] = {}
    output_schema: Dict[str, Any] = {}
    examples: List[Dict[str, Any]] = []
    tags: List[str] = []
    requires_llm: bool = False
    requires_session: bool = True
    is_async: bool = True
    version: str = "1.0.0"
    # Governance fields
    side_effects: bool = False
    is_primitive: bool = True
    payload_profile: str = "full"
    exposure_profile: Dict[str, Any] = {}


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
# TOOL CONTRACT SCHEMAS
# =============================================================================


class ToolContractResponse(BaseModel):
    """Tool contract with JSON Schema input/output and governance metadata."""
    name: str
    description: str
    category: str
    version: str
    input_schema: Dict[str, Any]
    output_schema: Dict[str, Any]
    side_effects: bool
    is_primitive: bool
    payload_profile: str
    exposure_profile: Dict[str, Any]
    requires_llm: bool
    requires_session: bool
    tags: List[str]


class ToolContractListResponse(BaseModel):
    """List of tool contracts response."""
    contracts: List[ToolContractResponse]
    total: int


# =============================================================================
# PROCEDURE VERSION SCHEMAS
# =============================================================================


class ProcedureVersionSummary(BaseModel):
    """Summary of a procedure version for list responses."""
    version: int
    change_summary: Optional[str] = None
    created_by: Optional[str] = None
    created_at: datetime


class ProcedureVersionDetail(ProcedureVersionSummary):
    """Full procedure version detail including definition."""
    definition: Dict[str, Any]


class ProcedureVersionListResponse(BaseModel):
    """List of procedure versions."""
    versions: List[ProcedureVersionSummary]
    total: int


class ProcedureVersionDiffChange(BaseModel):
    """A single change in a version diff."""
    path: str
    type: str  # "added", "removed", "changed"
    old_value: Any = None
    new_value: Any = None


class ProcedureVersionDiff(BaseModel):
    """Diff between two procedure versions."""
    version_a: int
    version_b: int
    changes: List[ProcedureVersionDiffChange]


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def meta_to_function_schema(m) -> FunctionSchema:
    """
    Convert a FunctionMeta instance to a FunctionSchema response.

    Args:
        m: FunctionMeta instance

    Returns:
        FunctionSchema for API response
    """
    return FunctionSchema(
        name=m.name,
        category=m.category.value,
        description=m.description,
        input_schema=m.input_schema,
        output_schema=m.output_schema,
        examples=m.examples,
        tags=m.tags,
        requires_llm=m.requires_llm,
        requires_session=m.requires_session,
        is_async=m.is_async,
        version=m.version,
        side_effects=m.side_effects,
        is_primitive=m.is_primitive,
        payload_profile=m.payload_profile,
        exposure_profile=m.exposure_profile,
    )
