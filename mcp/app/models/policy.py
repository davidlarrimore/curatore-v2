# Policy Configuration Models
"""Pydantic models for policy configuration."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ClampConfig(BaseModel):
    """Configuration for a single parameter clamp."""

    max: Optional[int] = Field(default=None, description="Maximum allowed value")
    default: Optional[int] = Field(default=None, description="Default value if not provided")
    min: Optional[int] = Field(default=None, description="Minimum allowed value")


class ToolClamps(BaseModel):
    """Clamps for a specific tool - maps parameter names to clamp configs."""

    # Dynamic fields - each key is a parameter name
    class Config:
        extra = "allow"


class PolicySettings(BaseModel):
    """Global policy settings."""

    block_side_effects: bool = Field(
        default=True,
        description="Block all functions with side_effects=true",
    )
    side_effects_allowlist: List[str] = Field(
        default_factory=list,
        description="Functions with side_effects=true that are allowed anyway (e.g., confirm_email)",
    )
    validate_facets: bool = Field(
        default=True,
        description="Validate facet_filters against metadata catalog",
    )
    contract_cache_ttl: int = Field(
        default=300,
        description="Cache TTL for contracts in seconds",
    )
    metadata_cache_ttl: int = Field(
        default=600,
        description="Cache TTL for metadata catalog in seconds",
    )


class Policy(BaseModel):
    """Complete policy configuration."""

    version: str = Field(default="1.0", description="Policy version")
    allowlist: List[str] = Field(
        default_factory=list,
        description="List of allowed tool names",
    )
    clamps: Dict[str, Dict[str, ClampConfig]] = Field(
        default_factory=dict,
        description="Parameter clamps per tool",
    )
    settings: PolicySettings = Field(
        default_factory=PolicySettings,
        description="Global policy settings",
    )

    def is_allowed(self, tool_name: str) -> bool:
        """Check if a tool is in the allowlist."""
        return tool_name in self.allowlist

    def get_clamps(self, tool_name: str) -> Dict[str, ClampConfig]:
        """Get parameter clamps for a tool."""
        raw_clamps = self.clamps.get(tool_name, {})
        return {k: ClampConfig(**v) if isinstance(v, dict) else v for k, v in raw_clamps.items()}

    def apply_clamps(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply parameter clamps to tool arguments.

        Returns a new dict with clamped values.
        """
        clamps = self.get_clamps(tool_name)
        if not clamps:
            return arguments

        result = dict(arguments)
        for param_name, clamp in clamps.items():
            if param_name in result:
                value = result[param_name]
                if isinstance(value, (int, float)):
                    # Apply max clamp
                    if clamp.max is not None and value > clamp.max:
                        result[param_name] = clamp.max
                    # Apply min clamp
                    if clamp.min is not None and value < clamp.min:
                        result[param_name] = clamp.min
            else:
                # Apply default if parameter not provided
                if clamp.default is not None:
                    result[param_name] = clamp.default

        return result
