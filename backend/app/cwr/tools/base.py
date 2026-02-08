# backend/app/functions/base.py
"""
Base classes for the Curatore Functions Framework.

This module provides the foundation for creating callable functions that can be
used in procedures, pipelines, and direct API calls. Functions are the atomic
units of work in the procedures framework.

Key Classes:
    - BaseFunction: Abstract base class for all functions
    - FunctionResult: Standard result wrapper for function outputs
    - FunctionMeta: Metadata about a function for discovery/documentation
    - ParameterDoc: Documentation for function parameters
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Type, TypeVar, Generic, Union
from uuid import UUID
import logging

logger = logging.getLogger("curatore.functions")


class FunctionCategory(str, Enum):
    """Categories for organizing functions."""
    LLM = "llm"
    LOGIC = "logic"
    SEARCH = "search"
    OUTPUT = "output"
    NOTIFY = "notify"
    COMPOUND = "compound"
    UTILITY = "utility"
    FLOW = "flow"


class FunctionStatus(str, Enum):
    """Status of function execution."""
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"  # Some items succeeded, some failed
    SKIPPED = "skipped"  # Function was skipped (e.g., no input)


@dataclass
class ParameterDoc:
    """Documentation for a single function parameter."""
    name: str
    type: str
    description: str
    required: bool = True
    default: Any = None
    enum_values: Optional[List[str]] = None
    example: Any = None


@dataclass
class OutputFieldDoc:
    """
    Documentation for a single output field.

    Used within OutputSchema to document the structure of function outputs,
    making it easier for engineers and AI to understand and use the fields
    in templates.

    Attributes:
        name: Field name (used in templates as {{ item.name }})
        type: Data type ("str", "int", "float", "bool", "list[str]", "dict", etc.)
        description: Human-readable description of the field
        example: Optional example value
        nullable: Whether the field can be None/null
    """
    name: str
    type: str
    description: str
    example: Any = None
    nullable: bool = False


@dataclass
class OutputSchema:
    """
    Structured documentation for function output.

    Provides machine-readable documentation of what a function returns,
    including field names, types, and descriptions. This enables:
    - Engineers to know exact field names when writing procedures
    - AI procedure generator to reliably generate correct template references
    - API consumers to understand the output structure programmatically

    Attributes:
        type: Top-level return type ("str", "dict", "list[ContentItem]", etc.)
        description: Human-readable description of the output
        fields: List of field documentation for structured types
        example: Optional complete example of the output
    """
    type: str
    description: str
    fields: List[OutputFieldDoc] = field(default_factory=list)
    example: Any = None


@dataclass
class OutputVariant:
    """
    Alternative output schema for dual-mode functions.

    Some functions (like LLM functions) return different types depending on
    their mode of operation. For example, llm_generate returns a string in
    single mode but a list of dicts in collection mode. OutputVariant allows
    documenting these alternative outputs.

    Attributes:
        mode: Mode name (e.g., "single", "collection")
        condition: When this variant applies (e.g., "when items parameter provided")
        schema: The OutputSchema for this mode
    """
    mode: str
    condition: str
    schema: OutputSchema


@dataclass
class FunctionMeta:
    """
    Metadata about a function for discovery and documentation.

    This metadata is used by:
    - The functions API for listing available functions
    - The procedure/pipeline executor for validation
    - Documentation generation
    """
    name: str
    category: FunctionCategory
    description: str
    parameters: List[ParameterDoc] = field(default_factory=list)
    returns: str = "FunctionResult"
    examples: List[Dict[str, Any]] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    requires_llm: bool = False
    requires_session: bool = True
    is_async: bool = True
    version: str = "1.0.0"
    # Structured output documentation (optional, supplements 'returns' string)
    output_schema: Optional[OutputSchema] = None
    output_variants: List[OutputVariant] = field(default_factory=list)
    # Governance metadata for Tool Contracts
    side_effects: bool = False
    is_primitive: bool = True
    payload_profile: str = "full"  # "thin" | "full" | "summary"
    exposure_profile: Dict[str, Any] = field(default_factory=lambda: {"procedure": True, "agent": True})

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        result = {
            "name": self.name,
            "category": self.category.value,
            "description": self.description,
            "parameters": [
                {
                    "name": p.name,
                    "type": p.type,
                    "description": p.description,
                    "required": p.required,
                    "default": p.default,
                    "enum_values": p.enum_values,
                    "example": p.example,
                }
                for p in self.parameters
            ],
            "returns": self.returns,
            "examples": self.examples,
            "tags": self.tags,
            "requires_llm": self.requires_llm,
            "requires_session": self.requires_session,
            "is_async": self.is_async,
            "version": self.version,
            "side_effects": self.side_effects,
            "is_primitive": self.is_primitive,
            "payload_profile": self.payload_profile,
            "exposure_profile": self.exposure_profile,
        }

        # Add output_schema if present
        if self.output_schema:
            result["output_schema"] = {
                "type": self.output_schema.type,
                "description": self.output_schema.description,
                "fields": [
                    {
                        "name": f.name,
                        "type": f.type,
                        "description": f.description,
                        "example": f.example,
                        "nullable": f.nullable,
                    }
                    for f in self.output_schema.fields
                ],
                "example": self.output_schema.example,
            }

        # Add output_variants if present
        if self.output_variants:
            result["output_variants"] = [
                {
                    "mode": v.mode,
                    "condition": v.condition,
                    "schema": {
                        "type": v.schema.type,
                        "description": v.schema.description,
                        "fields": [
                            {
                                "name": f.name,
                                "type": f.type,
                                "description": f.description,
                                "example": f.example,
                                "nullable": f.nullable,
                            }
                            for f in v.schema.fields
                        ],
                        "example": v.schema.example,
                    },
                }
                for v in self.output_variants
            ]

        return result


@dataclass
class FunctionResult:
    """
    Standard result wrapper for function outputs.

    All functions return a FunctionResult to provide consistent handling
    of success/failure states, data, and metadata.

    Attributes:
        status: Execution status (success, failed, partial, skipped)
        data: The actual result data (varies by function)
        message: Human-readable result message
        error: Error message if status is failed
        metadata: Additional metadata about the execution
        items_processed: Number of items processed (for batch operations)
        items_failed: Number of items that failed
        duration_ms: Execution time in milliseconds
    """
    status: FunctionStatus
    data: Any = None
    message: Optional[str] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    items_processed: int = 0
    items_failed: int = 0
    duration_ms: Optional[int] = None

    @property
    def success(self) -> bool:
        """Check if the function succeeded."""
        return self.status == FunctionStatus.SUCCESS

    @property
    def failed(self) -> bool:
        """Check if the function failed."""
        return self.status == FunctionStatus.FAILED

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses and logging."""
        result = {
            "status": self.status.value,
            "message": self.message,
            "items_processed": self.items_processed,
            "items_failed": self.items_failed,
            "metadata": self.metadata,
        }
        if self.data is not None:
            # Don't include full data in summary - it could be large
            if isinstance(self.data, (list, tuple)):
                result["data_count"] = len(self.data)
            elif isinstance(self.data, dict):
                result["data_keys"] = list(self.data.keys())
            else:
                result["data_type"] = type(self.data).__name__
        if self.error:
            result["error"] = self.error
        if self.duration_ms is not None:
            result["duration_ms"] = self.duration_ms
        return result

    @classmethod
    def success_result(
        cls,
        data: Any = None,
        message: str = "Success",
        **kwargs
    ) -> "FunctionResult":
        """Create a successful result."""
        return cls(
            status=FunctionStatus.SUCCESS,
            data=data,
            message=message,
            **kwargs
        )

    @classmethod
    def failed_result(
        cls,
        error: str,
        message: Optional[str] = None,
        data: Any = None,
        **kwargs
    ) -> "FunctionResult":
        """Create a failed result."""
        return cls(
            status=FunctionStatus.FAILED,
            data=data,
            message=message or f"Failed: {error}",
            error=error,
            **kwargs
        )

    @classmethod
    def partial_result(
        cls,
        data: Any,
        items_processed: int,
        items_failed: int,
        message: Optional[str] = None,
        **kwargs
    ) -> "FunctionResult":
        """Create a partial success result (some items failed)."""
        return cls(
            status=FunctionStatus.PARTIAL,
            data=data,
            message=message or f"Partial success: {items_processed} processed, {items_failed} failed",
            items_processed=items_processed,
            items_failed=items_failed,
            **kwargs
        )

    @classmethod
    def skipped_result(
        cls,
        message: str = "Skipped",
        **kwargs
    ) -> "FunctionResult":
        """Create a skipped result."""
        return cls(
            status=FunctionStatus.SKIPPED,
            message=message,
            **kwargs
        )


@dataclass
class FlowResult(FunctionResult):
    """
    Returned by flow control functions to direct the executor.

    Flow functions (if_branch, switch_branch, parallel, foreach) return this
    specialized result to tell the executor which branches to execute.

    Attributes:
        branch_key: For if_branch/switch_branch - the name of the single branch to run
        branches_to_run: For parallel - list of branch names to run concurrently
        items_to_iterate: For foreach - the resolved list of items to iterate over
        skipped_indices: For foreach - indices of items that were filtered out by condition
    """
    branch_key: Optional[str] = None
    branches_to_run: Optional[List[str]] = None
    items_to_iterate: Optional[List[Any]] = None
    skipped_indices: Optional[List[int]] = None

    @classmethod
    def success_result(
        cls,
        data: Any = None,
        message: str = "Success",
        branch_key: Optional[str] = None,
        branches_to_run: Optional[List[str]] = None,
        items_to_iterate: Optional[List[Any]] = None,
        skipped_indices: Optional[List[int]] = None,
        **kwargs
    ) -> "FlowResult":
        """Create a successful flow result."""
        return cls(
            status=FunctionStatus.SUCCESS,
            data=data,
            message=message,
            branch_key=branch_key,
            branches_to_run=branches_to_run,
            items_to_iterate=items_to_iterate,
            skipped_indices=skipped_indices,
            **kwargs
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses and logging."""
        result = super().to_dict()
        if self.branch_key is not None:
            result["branch_key"] = self.branch_key
        if self.branches_to_run is not None:
            result["branches_to_run"] = self.branches_to_run
        if self.items_to_iterate is not None:
            result["items_count"] = len(self.items_to_iterate)
        if self.skipped_indices is not None:
            result["skipped_count"] = len(self.skipped_indices)
        return result


# Type variable for function context
T = TypeVar("T")


class BaseFunction(ABC):
    """
    Abstract base class for all Curatore functions.

    Functions are the atomic units of work in the procedures framework.
    Each function:
    - Has metadata describing its purpose and parameters
    - Receives a FunctionContext with services and state
    - Returns a FunctionResult with the output

    Subclasses must implement:
    - meta: Class attribute with FunctionMeta
    - execute(): Async method that performs the function's work

    Example:
        class GenerateFunction(BaseFunction):
            meta = FunctionMeta(
                name="generate",
                category=FunctionCategory.LLM,
                description="Generate text using LLM",
                parameters=[
                    ParameterDoc("prompt", "str", "The prompt to generate from"),
                    ParameterDoc("model", "str", "Model to use", required=False),
                ],
            )

            async def execute(self, ctx: FunctionContext, **params) -> FunctionResult:
                prompt = params["prompt"]
                result = await ctx.llm_service.generate(prompt)
                return FunctionResult.success_result(data=result)
    """

    # Subclasses must define this
    meta: FunctionMeta

    @abstractmethod
    async def execute(self, ctx: "FunctionContext", **params) -> FunctionResult:
        """
        Execute the function.

        Args:
            ctx: Function context with services and state
            **params: Function parameters (validated against meta.parameters)

        Returns:
            FunctionResult with the output
        """
        pass

    # Type string to Python type mapping for validation
    _TYPE_CHECKS: Dict[str, type] = {
        "str": str,
        "string": str,
        "int": int,
        "integer": int,
        "float": (int, float),
        "number": (int, float),
        "bool": bool,
        "boolean": bool,
        "list": list,
        "list[str]": list,
        "list[string]": list,
        "list[int]": list,
        "list[dict]": list,
        "list[object]": list,
        "dict": dict,
        "object": dict,
    }

    def _check_type(self, name: str, value: Any, type_str: str) -> None:
        """
        Check that a parameter value matches its declared type.

        Args:
            name: Parameter name
            value: Parameter value
            type_str: Type string from ParameterDoc

        Raises:
            ValueError: If value doesn't match the expected type
        """
        expected = self._TYPE_CHECKS.get(type_str.strip().lower())
        if expected is None:
            return  # Unknown type, skip check

        if not isinstance(value, expected):
            expected_name = type_str
            actual_name = type(value).__name__
            raise ValueError(
                f"Parameter '{name}' expects type '{expected_name}' but got '{actual_name}'"
            )

    def validate_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate and normalize input parameters.

        Checks required parameters, applies defaults, validates types,
        and checks enum constraints. Template strings (Jinja2 {{ ... }})
        bypass type and enum validation since they're resolved at runtime.

        Args:
            params: Input parameters

        Returns:
            Validated and normalized parameters

        Raises:
            ValueError: If required parameters are missing or types are invalid
        """
        validated = {}

        for param_doc in self.meta.parameters:
            if param_doc.name in params:
                value = params[param_doc.name]
                validated[param_doc.name] = value

                # Skip type/enum validation for template strings
                if isinstance(value, str) and "{{" in value:
                    continue

                # Type checking
                self._check_type(param_doc.name, value, param_doc.type)

                # Enum validation
                if param_doc.enum_values and value not in param_doc.enum_values:
                    raise ValueError(
                        f"Parameter '{param_doc.name}' value '{value}' not in allowed values: "
                        f"{param_doc.enum_values}"
                    )

            elif param_doc.required:
                raise ValueError(f"Missing required parameter: {param_doc.name}")
            elif param_doc.default is not None:
                validated[param_doc.name] = param_doc.default

        return validated

    async def __call__(self, ctx: "FunctionContext", **params) -> FunctionResult:
        """
        Callable interface for function execution.

        Validates parameters and executes the function with timing.
        """
        start_time = datetime.utcnow()

        try:
            # Validate parameters
            validated_params = self.validate_params(params)

            # Execute function
            result = await self.execute(ctx, **validated_params)

            # Add timing
            duration = (datetime.utcnow() - start_time).total_seconds() * 1000
            result.duration_ms = int(duration)

            return result

        except ValueError as e:
            # Parameter validation error
            return FunctionResult.failed_result(
                error=str(e),
                message="Parameter validation failed",
            )
        except Exception as e:
            # Unexpected error
            logger.exception(f"Function {self.meta.name} failed: {e}")
            return FunctionResult.failed_result(
                error=str(e),
                message=f"Function execution failed: {type(e).__name__}",
            )

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(name={self.meta.name})>"


# Import FunctionContext here to avoid circular imports
# This will be defined in context.py
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .context import FunctionContext
