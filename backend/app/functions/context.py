# backend/app/functions/context.py
"""
Function execution context for the Curatore Functions Framework.

The FunctionContext provides functions with access to:
- Database session
- Services (LLM, search, storage, etc.)
- Organization context
- Run tracking (if executing within a procedure/pipeline)
- Logging utilities
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from uuid import UUID
import logging

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("curatore.functions.context")


@dataclass
class FunctionContext:
    """
    Execution context passed to all functions.

    Provides access to services, database session, and execution metadata.
    Functions should not create their own service instances - they should
    use the services provided in the context.

    Attributes:
        session: Database session for queries
        organization_id: Organization context for multi-tenancy
        user_id: User who triggered the execution (if applicable)
        run_id: Run ID if executing within a procedure/pipeline
        procedure_id: Procedure ID if applicable
        pipeline_id: Pipeline ID if applicable
        params: Global parameters passed to the procedure/pipeline
        variables: Variables accumulated during execution (for templating)
        dry_run: If True, functions should not make changes

    Services (lazily loaded):
        llm_service: LLM operations
        search_service: Full-text and semantic search
        minio_service: Object storage
        asset_service: Asset CRUD
        run_service: Run tracking and logging
    """

    # Required context
    session: AsyncSession
    organization_id: UUID

    # Optional execution context
    user_id: Optional[UUID] = None
    run_id: Optional[UUID] = None
    procedure_id: Optional[UUID] = None
    pipeline_id: Optional[UUID] = None

    # Execution state
    params: Dict[str, Any] = field(default_factory=dict)
    variables: Dict[str, Any] = field(default_factory=dict)
    dry_run: bool = False

    # Internal state
    _services: Dict[str, Any] = field(default_factory=dict, repr=False)
    _logger: Optional[logging.Logger] = field(default=None, repr=False)

    def __post_init__(self):
        """Initialize the context."""
        self._logger = logging.getLogger(f"curatore.functions.ctx.{self.organization_id}")

    # =========================================================================
    # SERVICE ACCESSORS (Lazy Loading)
    # =========================================================================

    @property
    def llm_service(self):
        """Get or create LLM service."""
        if "llm" not in self._services:
            from ..services.llm_service import llm_service
            self._services["llm"] = llm_service
        return self._services["llm"]

    @property
    def search_service(self):
        """Get or create search service."""
        if "search" not in self._services:
            from ..services.pg_search_service import PgSearchService
            self._services["search"] = PgSearchService()
        return self._services["search"]

    @property
    def minio_service(self):
        """Get or create MinIO service."""
        if "minio" not in self._services:
            from ..services.minio_service import get_minio_service
            self._services["minio"] = get_minio_service()
        return self._services["minio"]

    @property
    def asset_service(self):
        """Get or create asset service."""
        if "asset" not in self._services:
            from ..services.asset_service import AssetService
            self._services["asset"] = AssetService()
        return self._services["asset"]

    @property
    def run_service(self):
        """Get or create run service."""
        if "run" not in self._services:
            from ..services.run_service import run_service
            self._services["run"] = run_service
        return self._services["run"]

    @property
    def embedding_service(self):
        """Get or create embedding service."""
        if "embedding" not in self._services:
            from ..services.embedding_service import EmbeddingService
            self._services["embedding"] = EmbeddingService()
        return self._services["embedding"]

    @property
    def sam_service(self):
        """Get or create SAM.gov service."""
        if "sam" not in self._services:
            from ..services.sam_service import SamService
            self._services["sam"] = SamService()
        return self._services["sam"]

    @property
    def content_service(self):
        """Get or create content service for ContentItem operations."""
        if "content" not in self._services:
            from .content import content_service
            self._services["content"] = content_service
        return self._services["content"]

    # =========================================================================
    # VARIABLE MANAGEMENT
    # =========================================================================

    def set_variable(self, name: str, value: Any) -> None:
        """Set a variable for use in subsequent steps."""
        self.variables[name] = value
        self._logger.debug(f"Set variable: {name} = {type(value).__name__}")

    def get_variable(self, name: str, default: Any = None) -> Any:
        """Get a variable by name."""
        return self.variables.get(name, default)

    def get_step_result(self, step_name: str) -> Any:
        """
        Get the result from a previous step.

        Convention: step results are stored as variables with key "steps.{step_name}"
        """
        return self.variables.get(f"steps.{step_name}")

    def set_step_result(self, step_name: str, result: Any) -> None:
        """Store the result of a step for use by subsequent steps."""
        self.variables[f"steps.{step_name}"] = result

    # =========================================================================
    # LOGGING UTILITIES
    # =========================================================================

    def log_info(self, message: str, **context) -> None:
        """Log an info message with optional context."""
        self._logger.info(message, extra={"context": context})

    def log_warning(self, message: str, **context) -> None:
        """Log a warning message with optional context."""
        self._logger.warning(message, extra={"context": context})

    def log_error(self, message: str, **context) -> None:
        """Log an error message with optional context."""
        self._logger.error(message, extra={"context": context})

    async def log_run_event(
        self,
        level: str,
        event_type: str,
        message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Log an event to the run log if run_id is set.

        This creates a RunLogEvent record for structured logging.
        """
        if not self.run_id:
            # No run context, just log normally
            self._logger.log(
                logging.INFO if level == "INFO" else logging.WARNING if level == "WARN" else logging.ERROR,
                message,
            )
            return

        try:
            # Use run_log_service for structured logging (NOT run_service)
            from app.services.run_log_service import run_log_service
            await run_log_service.log_event(
                session=self.session,
                run_id=self.run_id,
                level=level,
                event_type=event_type,
                message=message,
                context=context,
            )
        except Exception as e:
            self._logger.error(f"Failed to log run event: {e}")

    # =========================================================================
    # TEMPLATE RENDERING
    # =========================================================================

    def render_template(self, template: str, item: Any = None) -> str:
        """
        Render a Jinja2 template string with context variables.

        Available variables:
        - params: Procedure/pipeline parameters
        - steps: Results from previous steps
        - item: Current item when iterating with foreach
        - now(): Current datetime (UTC)
        - now_et(): Current datetime (US Eastern)
        - today(): Current date string (US Eastern, formatted as 'Month Day, Year')
        - org_id: Organization ID

        Args:
            template: Jinja2 template string
            item: Optional item context for foreach iteration
        """
        try:
            from jinja2 import Template
            from zoneinfo import ZoneInfo

            def now_et():
                """Return current datetime in US Eastern timezone."""
                return datetime.now(ZoneInfo("America/New_York"))

            def today():
                """Return today's date formatted as 'Month Day, Year' in US Eastern."""
                return datetime.now(ZoneInfo("America/New_York")).strftime("%B %d, %Y")

            t = Template(template)
            context = {
                "params": self.params,
                "steps": {
                    k.replace("steps.", ""): v
                    for k, v in self.variables.items()
                    if k.startswith("steps.")
                },
                "variables": self.variables,
                "now": datetime.utcnow,
                "now_et": now_et,
                "today": today,
                "org_id": str(self.organization_id),
            }

            # Add item to context if provided (for foreach iteration)
            if item is not None:
                context["item"] = item

            return t.render(**context)
        except Exception as e:
            self._logger.error(f"Template rendering failed: {e}")
            raise ValueError(f"Failed to render template: {e}")

    def render_params(self, params: Dict[str, Any], item: Any = None) -> Dict[str, Any]:
        """
        Render all string values in a params dict as templates.

        Recursively processes nested dicts and lists.
        When a value is purely a template expression (like "{{ steps.data }}"),
        preserves the original data type instead of converting to string.

        Args:
            params: Dictionary of parameters to render
            item: Optional item context for foreach iteration (makes {{ item.xxx }} available)
        """
        def render_value(value: Any) -> Any:
            if isinstance(value, str) and "{{" in value:
                # Check if this is a pure template expression (entire string is one {{ }})
                # that should preserve its data type
                stripped = value.strip()
                if stripped.startswith("{{") and stripped.endswith("}}"):
                    # Extract the expression and evaluate directly to preserve type
                    inner_expr = stripped[2:-2].strip()
                    result = self._evaluate_expression(inner_expr, item=item)
                    if result is not None:
                        return result
                # Fall back to string template rendering
                return self.render_template(value, item=item)
            elif isinstance(value, dict):
                return {k: render_value(v) for k, v in value.items()}
            elif isinstance(value, list):
                return [render_value(i) for i in value]
            return value

        return render_value(params)

    def _evaluate_expression(self, expression: str, item: Any = None) -> Any:
        """
        Evaluate a Jinja2-like expression and return the actual value (preserving type).

        Supports:
        - steps.step_name -> step result
        - params.param_name -> parameter value
        - item.field -> current item field (in foreach context)
        - Simple attribute access chains

        Args:
            expression: The expression to evaluate (without {{ }})
            item: Optional item context for foreach iteration
        """
        try:
            # Build context for evaluation
            context = {
                "params": self.params,
                "steps": {
                    k.replace("steps.", ""): v
                    for k, v in self.variables.items()
                    if k.startswith("steps.")
                },
                "variables": self.variables,
                "now": datetime.utcnow,
                "org_id": str(self.organization_id),
            }

            # Add item to context if provided
            if item is not None:
                context["item"] = item

            # Handle simple dot-notation access (e.g., "steps.query_notices")
            parts = expression.split(".")
            if parts[0] in context:
                result = context[parts[0]]
                for part in parts[1:]:
                    if isinstance(result, dict):
                        result = result.get(part)
                    elif hasattr(result, part):
                        result = getattr(result, part)
                    else:
                        return None
                return result

            # For complex expressions, fall back to None (will use string rendering)
            return None
        except Exception:
            return None

    # =========================================================================
    # CONTEXT CREATION
    # =========================================================================

    @classmethod
    async def create(
        cls,
        session: AsyncSession,
        organization_id: UUID,
        user_id: Optional[UUID] = None,
        run_id: Optional[UUID] = None,
        procedure_id: Optional[UUID] = None,
        pipeline_id: Optional[UUID] = None,
        params: Optional[Dict[str, Any]] = None,
        dry_run: bool = False,
    ) -> "FunctionContext":
        """
        Create a new function context.

        This is the preferred way to create contexts as it can perform
        any necessary async initialization.
        """
        return cls(
            session=session,
            organization_id=organization_id,
            user_id=user_id,
            run_id=run_id,
            procedure_id=procedure_id,
            pipeline_id=pipeline_id,
            params=params or {},
            dry_run=dry_run,
        )

    def child_context(
        self,
        run_id: Optional[UUID] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> "FunctionContext":
        """
        Create a child context with inherited state.

        Useful for nested procedure/pipeline calls.
        """
        return FunctionContext(
            session=self.session,
            organization_id=self.organization_id,
            user_id=self.user_id,
            run_id=run_id or self.run_id,
            procedure_id=self.procedure_id,
            pipeline_id=self.pipeline_id,
            params={**self.params, **(params or {})},
            variables=self.variables.copy(),
            dry_run=self.dry_run,
            _services=self._services,  # Share services
        )
