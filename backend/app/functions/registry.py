# backend/app/functions/registry.py
"""
Function Registry for the Curatore Functions Framework.

The registry maintains a catalog of all available functions and provides:
- Function registration (automatic and manual)
- Function discovery by name, category, or tag
- Function instantiation
- Metadata access for documentation
"""

import logging
from typing import Dict, List, Optional, Type, Any
from .base import BaseFunction, FunctionCategory, FunctionMeta

logger = logging.getLogger("curatore.functions.registry")


class FunctionRegistry:
    """
    Central registry for all available functions.

    Provides function discovery, registration, and instantiation.
    Functions can be registered manually or discovered automatically
    from the functions package.

    Usage:
        # Register a function
        registry.register(GenerateFunction)

        # Get a function by name
        func = registry.get("llm_generate")
        result = await func(ctx, prompt="Hello")

        # List all functions
        for meta in registry.list_all():
            print(meta.name, meta.description)
    """

    def __init__(self):
        self._functions: Dict[str, Type[BaseFunction]] = {}
        self._instances: Dict[str, BaseFunction] = {}
        self._initialized = False

    def register(self, func_class: Type[BaseFunction]) -> None:
        """
        Register a function class.

        Args:
            func_class: BaseFunction subclass to register

        Raises:
            ValueError: If function class is invalid or name conflicts
        """
        if not hasattr(func_class, "meta") or not isinstance(func_class.meta, FunctionMeta):
            raise ValueError(f"Function class {func_class} must have a 'meta' attribute of type FunctionMeta")

        name = func_class.meta.name
        if name in self._functions:
            logger.warning(f"Overwriting function registration: {name}")

        self._functions[name] = func_class
        logger.debug(f"Registered function: {name}")

    def get(self, name: str) -> Optional[BaseFunction]:
        """
        Get a function instance by name.

        Returns a singleton instance of the function.

        Args:
            name: Function name

        Returns:
            Function instance or None if not found
        """
        if name not in self._functions:
            return None

        # Create singleton instance if needed
        if name not in self._instances:
            self._instances[name] = self._functions[name]()

        return self._instances[name]

    def get_class(self, name: str) -> Optional[Type[BaseFunction]]:
        """Get the function class by name."""
        return self._functions.get(name)

    def get_meta(self, name: str) -> Optional[FunctionMeta]:
        """Get function metadata by name."""
        func_class = self._functions.get(name)
        return func_class.meta if func_class else None

    def list_all(self) -> List[FunctionMeta]:
        """List metadata for all registered functions."""
        return [cls.meta for cls in self._functions.values()]

    def list_by_category(self, category: FunctionCategory) -> List[FunctionMeta]:
        """List functions in a specific category."""
        return [
            cls.meta
            for cls in self._functions.values()
            if cls.meta.category == category
        ]

    def list_by_tag(self, tag: str) -> List[FunctionMeta]:
        """List functions with a specific tag."""
        return [
            cls.meta
            for cls in self._functions.values()
            if tag in cls.meta.tags
        ]

    def list_names(self) -> List[str]:
        """List all registered function names."""
        return list(self._functions.keys())

    def get_categories(self) -> Dict[str, List[str]]:
        """Get functions organized by category."""
        categories: Dict[str, List[str]] = {}
        for cls in self._functions.values():
            cat = cls.meta.category.value
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(cls.meta.name)
        return categories

    def initialize(self) -> None:
        """
        Initialize the registry by discovering and registering all functions.

        This method should be called once at application startup.
        """
        if self._initialized:
            return

        self._discover_functions()
        self._initialized = True
        logger.info(f"Function registry initialized with {len(self._functions)} functions")

    def _discover_functions(self) -> None:
        """
        Discover and register all built-in functions.

        Imports function modules and registers their function classes.
        """
        # Import LLM functions
        try:
            from .llm.generate import GenerateFunction
            from .llm.extract import ExtractFunction
            from .llm.summarize import SummarizeFunction
            from .llm.classify import ClassifyFunction
            self.register(GenerateFunction)
            self.register(ExtractFunction)
            self.register(SummarizeFunction)
            self.register(ClassifyFunction)
        except ImportError as e:
            logger.warning(f"Failed to import LLM functions: {e}")

        # Import search functions
        try:
            from .search.query_model import QueryModelFunction
            from .search.get_content import GetContentFunction
            from .search.get_asset import GetAssetFunction
            from .search.get import GetFunction
            from .search.search_assets import SearchAssetsFunction
            from .search.search_solicitations import SearchSolicitationsFunction
            from .search.search_notices import SearchNoticesFunction
            from .search.search_scraped_assets import SearchScrapedAssetsFunction
            self.register(QueryModelFunction)
            self.register(GetContentFunction)
            self.register(GetAssetFunction)
            self.register(GetFunction)
            self.register(SearchAssetsFunction)
            self.register(SearchSolicitationsFunction)
            self.register(SearchNoticesFunction)
            self.register(SearchScrapedAssetsFunction)
        except ImportError as e:
            logger.warning(f"Failed to import search functions: {e}")

        # Import output functions
        try:
            from .output.update_metadata import UpdateMetadataFunction
            from .output.bulk_update_metadata import BulkUpdateMetadataFunction
            from .output.create_artifact import CreateArtifactFunction
            from .output.generate_document import GenerateDocumentFunction
            self.register(UpdateMetadataFunction)
            self.register(BulkUpdateMetadataFunction)
            self.register(CreateArtifactFunction)
            self.register(GenerateDocumentFunction)
        except ImportError as e:
            logger.warning(f"Failed to import output functions: {e}")

        # Import notify functions
        try:
            from .notify.send_email import SendEmailFunction
            from .notify.webhook import WebhookFunction
            self.register(SendEmailFunction)
            self.register(WebhookFunction)
        except ImportError as e:
            logger.warning(f"Failed to import notify functions: {e}")

        # Import compound functions
        try:
            from .compound.analyze_solicitation import AnalyzeSolicitationFunction
            from .compound.summarize_solicitations import SummarizeSolicitationsFunction
            from .compound.generate_digest import GenerateDigestFunction
            from .compound.classify_document import ClassifyDocumentFunction
            from .compound.enrich_assets import EnrichAssetsFunction
            self.register(AnalyzeSolicitationFunction)
            self.register(SummarizeSolicitationsFunction)
            self.register(GenerateDigestFunction)
            self.register(ClassifyDocumentFunction)
            self.register(EnrichAssetsFunction)
        except ImportError as e:
            logger.warning(f"Failed to import compound functions: {e}")

    def to_api_response(self) -> Dict[str, Any]:
        """
        Convert registry to API response format.

        Returns a dict with functions organized by category.
        """
        return {
            "functions": [meta.to_dict() for meta in self.list_all()],
            "categories": self.get_categories(),
            "total": len(self._functions),
        }


# Global singleton registry
function_registry = FunctionRegistry()


def get_function(name: str) -> Optional[BaseFunction]:
    """Get a function by name from the global registry."""
    function_registry.initialize()
    return function_registry.get(name)


def list_functions() -> List[FunctionMeta]:
    """List all registered functions."""
    function_registry.initialize()
    return function_registry.list_all()


def initialize_functions() -> None:
    """Initialize the function registry."""
    function_registry.initialize()
