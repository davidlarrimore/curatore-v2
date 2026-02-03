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
    SEARCH = "search"
    OUTPUT = "output"
    NOTIFY = "notify"
    COMPOUND = "compound"
    UTILITY = "utility"


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

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
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
        }


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

    def validate_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate and normalize input parameters.

        Checks required parameters are present and applies defaults.
        Override in subclasses for custom validation.

        Args:
            params: Input parameters

        Returns:
            Validated and normalized parameters

        Raises:
            ValueError: If required parameters are missing
        """
        validated = {}

        for param_doc in self.meta.parameters:
            if param_doc.name in params:
                validated[param_doc.name] = params[param_doc.name]
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
