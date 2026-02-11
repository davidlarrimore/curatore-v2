# backend/app/pipelines/base.py
"""
Base classes for the Curatore Pipelines Framework.

Pipelines process collections of items through multiple stages.
Each stage can gather, filter, transform, or enrich items.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
from datetime import datetime


class StageType(str, Enum):
    """Types of pipeline stages."""
    GATHER = "gather"      # Collect items to process
    FILTER = "filter"      # Filter items based on criteria
    TRANSFORM = "transform"  # Transform/modify items
    ENRICH = "enrich"      # Add derived data to items
    OUTPUT = "output"      # Output/save results


class OnErrorPolicy(str, Enum):
    """Policy for handling stage failures."""
    FAIL = "fail"
    SKIP = "skip"
    CONTINUE = "continue"


@dataclass
class StageDefinition:
    """
    Definition of a pipeline stage.

    Stages process items and can:
    - gather: Collect initial items to process
    - filter: Remove items that don't match criteria
    - transform: Modify items
    - enrich: Add derived metadata
    - output: Save/export results
    """
    name: str
    type: StageType
    function: str
    params: Dict[str, Any] = field(default_factory=dict)
    on_error: OnErrorPolicy = OnErrorPolicy.SKIP  # Skip failed items by default
    batch_size: int = 50
    description: str = ""


@dataclass
class ParameterDefinition:
    """Definition of a pipeline parameter."""
    name: str
    type: str = "str"
    description: str = ""
    required: bool = False
    default: Any = None


@dataclass
class TriggerDefinition:
    """Definition of a pipeline trigger."""
    type: str
    cron_expression: Optional[str] = None
    event_name: Optional[str] = None
    event_filter: Optional[Dict[str, Any]] = None


@dataclass
class PipelineDefinition:
    """
    Complete definition of a pipeline.

    Pipelines process items through stages with checkpointing.
    """
    name: str
    slug: str
    description: str = ""
    version: str = "1.0.0"

    parameters: List[ParameterDefinition] = field(default_factory=list)
    stages: List[StageDefinition] = field(default_factory=list)
    triggers: List[TriggerDefinition] = field(default_factory=list)

    on_error: OnErrorPolicy = OnErrorPolicy.CONTINUE
    checkpoint_after_stages: List[str] = field(default_factory=list)

    tags: List[str] = field(default_factory=list)
    is_system: bool = False
    source_type: str = "system"
    source_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
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
                }
                for p in self.parameters
            ],
            "stages": [
                {
                    "name": s.name,
                    "type": s.type.value,
                    "function": s.function,
                    "params": s.params,
                    "on_error": s.on_error.value,
                    "batch_size": s.batch_size,
                    "description": s.description,
                }
                for s in self.stages
            ],
            "triggers": [
                {
                    "type": t.type,
                    "cron_expression": t.cron_expression,
                    "event_name": t.event_name,
                    "event_filter": t.event_filter,
                }
                for t in self.triggers
            ],
            "on_error": self.on_error.value,
            "checkpoint_after_stages": self.checkpoint_after_stages,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any], source_type: str = "system", source_path: str = None) -> "PipelineDefinition":
        """Create from dictionary."""
        parameters = [
            ParameterDefinition(
                name=p["name"],
                type=p.get("type", "str"),
                description=p.get("description", ""),
                required=p.get("required", False),
                default=p.get("default"),
            )
            for p in data.get("parameters", [])
        ]

        stages = [
            StageDefinition(
                name=s["name"],
                type=StageType(s["type"]),
                function=s["function"],
                params=s.get("params", {}),
                on_error=OnErrorPolicy(s.get("on_error", "skip")),
                batch_size=s.get("batch_size", 50),
                description=s.get("description", ""),
            )
            for s in data.get("stages", [])
        ]

        triggers = [
            TriggerDefinition(
                type=t["type"],
                cron_expression=t.get("cron_expression"),
                event_name=t.get("event_name"),
                event_filter=t.get("event_filter"),
            )
            for t in data.get("triggers", [])
        ]

        return cls(
            name=data["name"],
            slug=data["slug"],
            description=data.get("description", ""),
            version=data.get("version", "1.0.0"),
            parameters=parameters,
            stages=stages,
            triggers=triggers,
            on_error=OnErrorPolicy(data.get("on_error", "continue")),
            checkpoint_after_stages=data.get("checkpoint_after_stages", []),
            tags=data.get("tags", []),
            is_system=data.get("is_system", False),
            source_type=source_type,
            source_path=source_path,
        )


class BasePipeline:
    """Base class for Python-defined pipelines."""
    definition: PipelineDefinition

    async def pre_execute(self, ctx) -> None:
        """Hook called before pipeline executes."""
        pass

    async def post_execute(self, ctx, results) -> Dict[str, Any]:
        """Hook called after pipeline executes."""
        return results

    async def on_stage_complete(self, ctx, stage: StageDefinition, items: List[Any]) -> None:
        """Hook called after each stage completes."""
        pass
