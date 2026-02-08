# backend/app/cwr/tools/__init__.py
"""
Curatore Functions Framework (CWR Tools)

A library of callable functions for use in procedures, pipelines, and direct API calls.

Usage:
    from app.cwr.tools import fn

    # Get a function
    generate = fn.get("generate")

    # Execute it
    result = await generate(ctx, prompt="Hello")

    # List available functions
    for meta in fn.list_all():
        print(meta.name)

The `fn` namespace provides a convenient interface to the function registry:
    - fn.get(name): Get function instance by name
    - fn.list_all(): List all function metadata
    - fn.list_by_category(cat): List functions in category
    - fn.get_categories(): Get functions organized by category
"""

from .base import (
    BaseFunction,
    FunctionResult,
    FunctionMeta,
    FunctionCategory,
    FunctionStatus,
    ParameterDoc,
)
from .context import FunctionContext
from .registry import (
    function_registry,
    get_function,
    list_functions,
    initialize_functions,
)
from ..contracts.tool_contracts import ToolContract, ContractGenerator
from .content import (
    ContentItem,
    ContentService,
    ContentTypeRegistry,
    content_service,
    content_type_registry,
)


class FunctionNamespace:
    """
    Convenience namespace for accessing functions.

    Provides a clean interface: fn.get("name"), fn.list_all(), etc.
    """

    def get(self, name: str) -> BaseFunction:
        """Get a function by name."""
        initialize_functions()
        func = function_registry.get(name)
        if func is None:
            raise KeyError(f"Function not found: {name}")
        return func

    def get_or_none(self, name: str) -> BaseFunction:
        """Get a function by name, or None if not found."""
        initialize_functions()
        return function_registry.get(name)

    def list_all(self):
        """List all function metadata."""
        initialize_functions()
        return function_registry.list_all()

    def list_by_category(self, category: FunctionCategory):
        """List functions in a category."""
        initialize_functions()
        return function_registry.list_by_category(category)

    def list_by_tag(self, tag: str):
        """List functions with a tag."""
        initialize_functions()
        return function_registry.list_by_tag(tag)

    def get_categories(self):
        """Get functions organized by category."""
        initialize_functions()
        return function_registry.get_categories()

    def register(self, func_class):
        """Register a function class."""
        function_registry.register(func_class)

    def __getattr__(self, name: str):
        """Allow fn.generate instead of fn.get("generate")."""
        return self.get(name)


# Global function namespace
fn = FunctionNamespace()


__all__ = [
    # Core classes
    "BaseFunction",
    "FunctionResult",
    "FunctionMeta",
    "FunctionCategory",
    "FunctionStatus",
    "ParameterDoc",
    "FunctionContext",
    # Registry
    "function_registry",
    "get_function",
    "list_functions",
    "initialize_functions",
    # Contracts
    "ToolContract",
    "ContractGenerator",
    # Content
    "ContentItem",
    "ContentService",
    "ContentTypeRegistry",
    "content_service",
    "content_type_registry",
    # Namespace
    "fn",
]
