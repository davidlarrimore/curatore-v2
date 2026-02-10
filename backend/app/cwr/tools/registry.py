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
from typing import Dict, List, Optional, Type, Any, TYPE_CHECKING
from .base import BaseFunction, FunctionCategory, FunctionMeta

if TYPE_CHECKING:
    from ..contracts.tool_contracts import ToolContract

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
        self._contracts: Dict[str, "ToolContract"] = {}
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
            from .primitives.llm.generate import GenerateFunction
            from .primitives.llm.extract import ExtractFunction
            from .primitives.llm.summarize import SummarizeFunction
            from .primitives.llm.classify import ClassifyFunction
            from .primitives.llm.decide import DecideFunction
            from .primitives.llm.route import RouteFunction
            self.register(GenerateFunction)
            self.register(ExtractFunction)
            self.register(SummarizeFunction)
            self.register(ClassifyFunction)
            self.register(DecideFunction)
            self.register(RouteFunction)
        except ImportError as e:
            logger.warning(f"Failed to import LLM functions: {e}")

        # Import search functions
        try:
            from .primitives.search.query_model import QueryModelFunction
            from .primitives.search.get_content import GetContentFunction
            from .primitives.search.get_asset import GetAssetFunction
            from .primitives.search.get import GetFunction
            from .primitives.search.search_assets import SearchAssetsFunction
            from .primitives.search.search_solicitations import SearchSolicitationsFunction
            from .primitives.search.search_notices import SearchNoticesFunction
            from .primitives.search.search_scraped_assets import SearchScrapedAssetsFunction
            from .primitives.search.search_salesforce import SearchSalesforceFunction
            from .primitives.search.search_forecasts import SearchForecastsFunction
            from .primitives.search.discover_data_sources import DiscoverDataSourcesFunction
            from .primitives.search.discover_metadata import DiscoverMetadataFunction
            self.register(QueryModelFunction)
            self.register(GetContentFunction)
            self.register(GetAssetFunction)
            self.register(GetFunction)
            self.register(SearchAssetsFunction)
            self.register(SearchSolicitationsFunction)
            self.register(SearchNoticesFunction)
            self.register(SearchScrapedAssetsFunction)
            self.register(SearchSalesforceFunction)
            self.register(SearchForecastsFunction)
            self.register(DiscoverDataSourcesFunction)
            self.register(DiscoverMetadataFunction)
        except ImportError as e:
            logger.warning(f"Failed to import search functions: {e}")

        # Import output functions
        try:
            from .primitives.output.update_metadata import UpdateMetadataFunction
            from .primitives.output.bulk_update_metadata import BulkUpdateMetadataFunction
            from .primitives.output.create_artifact import CreateArtifactFunction
            from .primitives.output.generate_document import GenerateDocumentFunction
            from .primitives.output.log import LogFunction
            from .primitives.output.update_source_metadata import UpdateSourceMetadataFunction
            self.register(UpdateMetadataFunction)
            self.register(BulkUpdateMetadataFunction)
            self.register(CreateArtifactFunction)
            self.register(GenerateDocumentFunction)
            self.register(LogFunction)
            self.register(UpdateSourceMetadataFunction)
        except ImportError as e:
            logger.warning(f"Failed to import output functions: {e}")

        # Import notify functions
        try:
            from .primitives.notify.send_email import SendEmailFunction
            from .primitives.notify.webhook import WebhookFunction
            self.register(SendEmailFunction)
            self.register(WebhookFunction)
        except ImportError as e:
            logger.warning(f"Failed to import notify functions: {e}")

        # Import compound functions
        try:
            from .compounds.analyze_solicitation import AnalyzeSolicitationFunction
            from .compounds.summarize_solicitations import SummarizeSolicitationsFunction
            from .compounds.generate_digest import GenerateDigestFunction
            from .compounds.classify_document import ClassifyDocumentFunction
            from .compounds.enrich_assets import EnrichAssetsFunction
            self.register(AnalyzeSolicitationFunction)
            self.register(SummarizeSolicitationsFunction)
            self.register(GenerateDigestFunction)
            self.register(ClassifyDocumentFunction)
            self.register(EnrichAssetsFunction)
        except ImportError as e:
            logger.warning(f"Failed to import compound functions: {e}")

        # Import email workflow functions (MCP two-step confirmation)
        try:
            from .compounds.email_workflow import PrepareEmailFunction, ConfirmEmailFunction
            self.register(PrepareEmailFunction)
            self.register(ConfirmEmailFunction)
        except ImportError as e:
            logger.warning(f"Failed to import email workflow functions: {e}")

        # Import flow control functions
        try:
            from .primitives.flow.if_branch import IfBranchFunction
            from .primitives.flow.switch_branch import SwitchBranchFunction
            from .primitives.flow.parallel import ParallelFunction
            from .primitives.flow.foreach import ForeachFunction
            self.register(IfBranchFunction)
            self.register(SwitchBranchFunction)
            self.register(ParallelFunction)
            self.register(ForeachFunction)
        except ImportError as e:
            logger.warning(f"Failed to import flow functions: {e}")

        # Import SharePoint/data functions
        try:
            from .primitives.sharepoint.sp_get_site import SpGetSiteFunction
            from .primitives.sharepoint.sp_list_items import SpListItemsFunction
            from .primitives.sharepoint.sp_get_item import SpGetItemFunction
            self.register(SpGetSiteFunction)
            self.register(SpListItemsFunction)
            self.register(SpGetItemFunction)
        except ImportError as e:
            logger.warning(f"Failed to import SharePoint functions: {e}")

    def get_contract(self, name: str) -> Optional["ToolContract"]:
        """
        Get a ToolContract for a function by name, with caching.

        Args:
            name: Function name

        Returns:
            ToolContract or None if function not found
        """
        if name in self._contracts:
            return self._contracts[name]

        meta = self.get_meta(name)
        if not meta:
            return None

        from ..contracts.tool_contracts import ContractGenerator
        contract = ContractGenerator.generate(meta)
        self._contracts[name] = contract
        return contract

    def list_contracts(self) -> List["ToolContract"]:
        """List contracts for all registered functions."""
        contracts = []
        for name in self._functions:
            contract = self.get_contract(name)
            if contract:
                contracts.append(contract)
        return contracts

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
