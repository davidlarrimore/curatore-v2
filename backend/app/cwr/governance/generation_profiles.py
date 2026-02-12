# backend/app/cwr/governance/generation_profiles.py
"""
Generation Profiles - Control what tools and capabilities are available
during AI procedure generation.

Profiles define which tool categories are allowed, which specific tools
are blocked, and side-effect policies for generated procedures.

Usage:
    from app.cwr.governance.generation_profiles import get_profile, get_available_profiles

    profile = get_profile("workflow_standard")
    print(profile.allowed_categories)
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger("curatore.cwr.governance.generation_profiles")


class GenerationProfileName(str, Enum):
    """Available generation profile names."""
    SAFE_READONLY = "safe_readonly"
    WORKFLOW_STANDARD = "workflow_standard"
    ADMIN_FULL = "admin_full"


@dataclass(frozen=True)
class GenerationProfile:
    """
    A generation profile that constrains which tools and patterns the AI
    procedure generator can use.

    Attributes:
        name: Profile identifier
        description: Human-readable description for UI display
        allowed_categories: Set of tool categories allowed (search, llm, output, notify, flow, compound)
        blocked_tools: Specific tools blocked regardless of category
        allow_side_effects: Whether side-effect tools are permitted at all
        require_side_effect_confirmation: If True, side-effect steps must include confirm_side_effects: true
        max_search_limit: Maximum 'limit' value for search functions
        max_llm_tokens: Maximum token budget for LLM functions
    """
    name: GenerationProfileName
    description: str
    allowed_categories: frozenset = field(default_factory=frozenset)
    blocked_tools: frozenset = field(default_factory=frozenset)
    allow_side_effects: bool = False
    require_side_effect_confirmation: bool = False
    max_search_limit: int = 100
    max_llm_tokens: int = 4096

    def is_tool_allowed(self, tool_name: str, category: str, has_side_effects: bool = False) -> bool:
        """
        Check whether a tool is allowed under this profile.

        Args:
            tool_name: The function/tool name
            category: The tool's category (search, llm, output, etc.)
            has_side_effects: Whether the tool has side effects

        Returns:
            True if the tool is allowed
        """
        if tool_name in self.blocked_tools:
            return False
        if category not in self.allowed_categories:
            return False
        if has_side_effects and not self.allow_side_effects:
            return False
        return True

    def to_dict(self) -> Dict:
        """Convert to dictionary for API responses."""
        return {
            "name": self.name.value,
            "description": self.description,
            "allowed_categories": sorted(self.allowed_categories),
            "blocked_tools": sorted(self.blocked_tools),
            "allow_side_effects": self.allow_side_effects,
            "require_side_effect_confirmation": self.require_side_effect_confirmation,
            "max_search_limit": self.max_search_limit,
            "max_llm_tokens": self.max_llm_tokens,
        }


# ---------------------------------------------------------------------------
# Profile Definitions
# ---------------------------------------------------------------------------

GENERATION_PROFILES: Dict[GenerationProfileName, GenerationProfile] = {
    GenerationProfileName.SAFE_READONLY: GenerationProfile(
        name=GenerationProfileName.SAFE_READONLY,
        description="Read-only procedures: search, analyze with LLM, and flow control only. No emails, webhooks, or metadata updates.",
        allowed_categories=frozenset({"search", "llm", "flow"}),
        blocked_tools=frozenset({
            "send_email", "webhook",
            "update_metadata", "bulk_update_metadata",
            "create_artifact", "generate_document",
        }),
        allow_side_effects=False,
        require_side_effect_confirmation=False,
        max_search_limit=50,
        max_llm_tokens=4096,
    ),
    GenerationProfileName.WORKFLOW_STANDARD: GenerationProfile(
        name=GenerationProfileName.WORKFLOW_STANDARD,
        description="Standard workflow procedures: search, LLM, flow, notifications, and output (artifacts, documents). Blocks webhooks and metadata updates.",
        allowed_categories=frozenset({"search", "llm", "flow", "notify", "output", "compound"}),
        blocked_tools=frozenset({
            "webhook",
            "update_metadata", "bulk_update_metadata",
        }),
        allow_side_effects=True,
        require_side_effect_confirmation=False,
        max_search_limit=100,
        max_llm_tokens=4096,
    ),
    GenerationProfileName.ADMIN_FULL: GenerationProfile(
        name=GenerationProfileName.ADMIN_FULL,
        description="Full access: all tools including webhooks and metadata updates. Side-effect steps require confirmation.",
        allowed_categories=frozenset({"search", "llm", "flow", "notify", "output", "compound"}),
        blocked_tools=frozenset(),
        allow_side_effects=True,
        require_side_effect_confirmation=True,
        max_search_limit=200,
        max_llm_tokens=8192,
    ),
}


def get_profile(name: Optional[str] = None) -> GenerationProfile:
    """
    Get a generation profile by name.

    Args:
        name: Profile name string. Defaults to 'workflow_standard' if None or invalid.

    Returns:
        The matching GenerationProfile
    """
    if name is None:
        return GENERATION_PROFILES[GenerationProfileName.WORKFLOW_STANDARD]

    try:
        profile_name = GenerationProfileName(name)
        return GENERATION_PROFILES[profile_name]
    except (ValueError, KeyError):
        logger.warning(f"Unknown generation profile '{name}', falling back to workflow_standard")
        return GENERATION_PROFILES[GenerationProfileName.WORKFLOW_STANDARD]


def get_available_profiles() -> List[Dict]:
    """
    Get all available generation profiles for UI display.

    Returns:
        List of profile dicts with name, description, and constraints
    """
    return [profile.to_dict() for profile in GENERATION_PROFILES.values()]
