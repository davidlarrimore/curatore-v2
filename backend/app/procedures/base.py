# backend/app/procedures/base.py
"""
Base classes for the Curatore Procedures Framework.

Defines the structure for procedure definitions including:
- Parameters (inputs with defaults)
- Steps (function calls with configuration)
- Outputs (result handling)
- Error handling policies
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
from datetime import datetime


class OnErrorPolicy(str, Enum):
    """Policy for handling step failures."""
    FAIL = "fail"      # Stop procedure on error
    SKIP = "skip"      # Skip this step, continue to next
    CONTINUE = "continue"  # Continue despite error (log warning)


@dataclass
class ParameterDefinition:
    """Definition of a procedure parameter."""
    name: str
    type: str = "str"
    description: str = ""
    required: bool = False
    default: Any = None
    enum_values: Optional[List[str]] = None


@dataclass
class StepDefinition:
    """
    Definition of a single step in a procedure.

    Each step calls a function with parameters. Parameters can include
    Jinja2 templates to reference:
    - {{ params.xxx }}: Procedure parameters
    - {{ steps.step_name.xxx }}: Results from previous steps
    - {{ item.xxx }}: Current item when using foreach
    - {{ now() }}: Current datetime

    Iteration:
    - foreach: Template expression that evaluates to a list (or single item)
    - When foreach is set, the step runs once per item
    - {{ item }} is available in params during each iteration
    - Results are collected into a list
    """
    name: str
    function: str
    params: Dict[str, Any] = field(default_factory=dict)
    on_error: OnErrorPolicy = OnErrorPolicy.FAIL
    condition: Optional[str] = None  # Jinja2 expression that must be true
    description: str = ""
    foreach: Optional[str] = None  # Template expression for iteration


@dataclass
class OutputDefinition:
    """Definition of procedure output handling."""
    type: str = "result"  # result, artifact, email, webhook
    config: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TriggerDefinition:
    """Definition of a procedure trigger."""
    type: str  # cron, event, webhook
    cron_expression: Optional[str] = None
    event_name: Optional[str] = None
    event_filter: Optional[Dict[str, Any]] = None
    webhook_path: Optional[str] = None


@dataclass
class ProcedureDefinition:
    """
    Complete definition of a procedure.

    Procedures are loaded from YAML files or defined in Python code.
    """
    name: str
    slug: str
    description: str = ""
    version: str = "1.0.0"

    # Parameters (inputs)
    parameters: List[ParameterDefinition] = field(default_factory=list)

    # Steps (function calls)
    steps: List[StepDefinition] = field(default_factory=list)

    # Outputs
    outputs: List[OutputDefinition] = field(default_factory=list)

    # Triggers
    triggers: List[TriggerDefinition] = field(default_factory=list)

    # Error handling
    on_error: OnErrorPolicy = OnErrorPolicy.FAIL

    # Metadata
    tags: List[str] = field(default_factory=list)
    is_system: bool = False
    source_type: str = "yaml"
    source_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage/serialization."""
        return {
            "name": self.name,
            "slug": self.slug,
            "description": self.description,
            "version": self.version,
            "parameters": [
                {
                    "name": p.name,
                    "type": p.type,
                    "description": p.description,
                    "required": p.required,
                    "default": p.default,
                    "enum_values": p.enum_values,
                }
                for p in self.parameters
            ],
            "steps": [
                {
                    "name": s.name,
                    "function": s.function,
                    "params": s.params,
                    "on_error": s.on_error.value,
                    "condition": s.condition,
                    "description": s.description,
                    "foreach": s.foreach,
                }
                for s in self.steps
            ],
            "outputs": [
                {"type": o.type, "config": o.config}
                for o in self.outputs
            ],
            "triggers": [
                {
                    "type": t.type,
                    "cron_expression": t.cron_expression,
                    "event_name": t.event_name,
                    "event_filter": t.event_filter,
                    "webhook_path": t.webhook_path,
                }
                for t in self.triggers
            ],
            "on_error": self.on_error.value,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any], source_type: str = "yaml", source_path: str = None) -> "ProcedureDefinition":
        """Create from dictionary (loaded from YAML/JSON)."""
        parameters = [
            ParameterDefinition(
                name=p["name"],
                type=p.get("type", "str"),
                description=p.get("description", ""),
                required=p.get("required", False),
                default=p.get("default"),
                enum_values=p.get("enum_values"),
            )
            for p in data.get("parameters", [])
        ]

        steps = [
            StepDefinition(
                name=s["name"],
                function=s["function"],
                params=s.get("params", {}),
                on_error=OnErrorPolicy(s.get("on_error", "fail")),
                condition=s.get("condition"),
                description=s.get("description", ""),
                foreach=s.get("foreach"),
            )
            for s in data.get("steps", [])
        ]

        outputs = [
            OutputDefinition(
                type=o.get("type", "result"),
                config=o.get("config", {}),
            )
            for o in data.get("outputs", [])
        ]

        triggers = [
            TriggerDefinition(
                type=t["type"],
                cron_expression=t.get("cron_expression"),
                event_name=t.get("event_name"),
                event_filter=t.get("event_filter"),
                webhook_path=t.get("webhook_path"),
            )
            for t in data.get("triggers", [])
        ]

        return cls(
            name=data["name"],
            slug=data["slug"],
            description=data.get("description", ""),
            version=data.get("version", "1.0.0"),
            parameters=parameters,
            steps=steps,
            outputs=outputs,
            triggers=triggers,
            on_error=OnErrorPolicy(data.get("on_error", "fail")),
            tags=data.get("tags", []),
            is_system=data.get("is_system", False),
            source_type=source_type,
            source_path=source_path,
        )


class BaseProcedure:
    """
    Base class for Python-defined procedures.

    For complex procedures that need Python logic, extend this class.
    Simple procedures should use YAML definitions instead.

    Example:
        class MyProcedure(BaseProcedure):
            definition = ProcedureDefinition(
                name="My Procedure",
                slug="my_procedure",
                steps=[...],
            )

            async def pre_execute(self, ctx):
                # Optional: Run before steps
                pass

            async def post_execute(self, ctx, results):
                # Optional: Run after steps
                pass
    """

    # Subclasses must define this
    definition: ProcedureDefinition

    async def pre_execute(self, ctx: "FunctionContext") -> None:
        """Hook called before steps execute. Override to add custom logic."""
        pass

    async def post_execute(self, ctx: "FunctionContext", results: Dict[str, Any]) -> Dict[str, Any]:
        """Hook called after steps execute. Override to modify/process results."""
        return results

    async def on_step_error(self, ctx: "FunctionContext", step: StepDefinition, error: Exception) -> None:
        """Hook called when a step fails. Override for custom error handling."""
        pass


# Type hint import
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ..functions.context import FunctionContext
