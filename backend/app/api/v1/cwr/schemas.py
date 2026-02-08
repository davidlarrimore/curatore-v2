"""
CWR (Content Workflow Runtime) namespace Pydantic schemas.

Functions, procedures, and pipeline API models.
"""
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field


# =============================================================================
# FUNCTION SCHEMAS
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


class OutputFieldSchema(BaseModel):
    """Output field documentation schema."""
    name: str
    type: str
    description: str
    example: Any = None
    nullable: bool = False


class OutputSchemaResponse(BaseModel):
    """Output schema documentation."""
    type: str
    description: str
    fields: List[OutputFieldSchema] = []
    example: Any = None


class OutputVariantResponse(BaseModel):
    """Output variant for dual-mode functions."""
    mode: str
    condition: str
    schema: OutputSchemaResponse


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
    output_schema: Optional[OutputSchemaResponse] = None
    output_variants: List[OutputVariantResponse] = []
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


def convert_output_schema(meta) -> tuple:
    """
    Convert FunctionMeta output_schema and output_variants to API response models.

    Args:
        meta: FunctionMeta instance

    Returns:
        Tuple of (output_schema, output_variants) in API response format
    """
    output_schema = None
    output_variants = []

    if meta.output_schema:
        output_schema = OutputSchemaResponse(
            type=meta.output_schema.type,
            description=meta.output_schema.description,
            fields=[
                OutputFieldSchema(
                    name=f.name,
                    type=f.type,
                    description=f.description,
                    example=f.example,
                    nullable=f.nullable,
                )
                for f in meta.output_schema.fields
            ],
            example=meta.output_schema.example,
        )

    if meta.output_variants:
        output_variants = [
            OutputVariantResponse(
                mode=v.mode,
                condition=v.condition,
                schema=OutputSchemaResponse(
                    type=v.schema.type,
                    description=v.schema.description,
                    fields=[
                        OutputFieldSchema(
                            name=f.name,
                            type=f.type,
                            description=f.description,
                            example=f.example,
                            nullable=f.nullable,
                        )
                        for f in v.schema.fields
                    ],
                    example=v.schema.example,
                ),
            )
            for v in meta.output_variants
        ]

    return output_schema, output_variants


def meta_to_function_schema(m) -> FunctionSchema:
    """
    Convert a FunctionMeta instance to a FunctionSchema response.

    Args:
        m: FunctionMeta instance

    Returns:
        FunctionSchema for API response
    """
    output_schema, output_variants = convert_output_schema(m)
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
        output_schema=output_schema,
        output_variants=output_variants,
        side_effects=m.side_effects,
        is_primitive=m.is_primitive,
        payload_profile=m.payload_profile,
        exposure_profile=m.exposure_profile,
    )
