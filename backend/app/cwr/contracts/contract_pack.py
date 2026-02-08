# backend/app/cwr/contracts/contract_pack.py
"""
Tool Contract Pack - Filtered set of tool contracts for a generation profile.

Builds a profile-aware contract pack from the function registry, filtering
by exposure profile, generation profile categories, and blocked tools.

The contract pack is passed to the ContextBuilder to produce the LLM prompt
and to the PlanValidator to check tool availability.

Usage:
    from app.cwr.contracts.contract_pack import get_tool_contract_pack

    pack = get_tool_contract_pack(org_id=None, profile=profile)
    prompt_json = pack.to_prompt_json()
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.cwr.contracts.tool_contracts import ToolContract, ContractGenerator
from app.cwr.governance.generation_profiles import GenerationProfile, get_profile
from app.cwr.governance.capability_profiles import check_exposure
from app.cwr.tools.registry import function_registry

logger = logging.getLogger("curatore.cwr.contracts.contract_pack")


@dataclass
class ToolContractPack:
    """
    A filtered collection of tool contracts available under a generation profile.

    Attributes:
        profile: The generation profile used to filter tools
        contracts: List of ToolContract instances that passed filtering
    """
    profile: GenerationProfile
    contracts: List[ToolContract] = field(default_factory=list)

    def get_tool_names(self) -> List[str]:
        """Get sorted list of available tool names."""
        return sorted(c.name for c in self.contracts)

    def get_contract(self, name: str) -> Optional[ToolContract]:
        """Get a specific contract by tool name."""
        for c in self.contracts:
            if c.name == name:
                return c
        return None

    def to_prompt_json(self) -> str:
        """
        Produce compact JSON for embedding in the LLM system prompt.

        Each tool is represented with: name, description, category,
        input_schema, side_effects, and payload_profile.
        """
        tools = []
        for c in self.contracts:
            tool_entry: Dict[str, Any] = {
                "name": c.name,
                "description": c.description,
                "category": c.category,
                "input_schema": c.input_schema,
                "side_effects": c.side_effects,
                "payload_profile": c.payload_profile,
            }
            if c.requires_llm:
                tool_entry["requires_llm"] = True
            tools.append(tool_entry)

        return json.dumps(tools, indent=2)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "profile": self.profile.name.value,
            "tool_count": len(self.contracts),
            "tools": [c.to_dict() for c in self.contracts],
        }


def get_tool_contract_pack(
    org_id: Optional[UUID] = None,
    profile: Optional[GenerationProfile] = None,
    profile_name: Optional[str] = None,
) -> ToolContractPack:
    """
    Build a ToolContractPack filtered by generation profile and exposure policies.

    Filtering layers:
    1. Exposure profile - tool must be allowed in "procedure" context
    2. Category filter - tool's category must be in profile.allowed_categories
    3. Blocked tools - tool must not be in profile.blocked_tools
    4. Side effects - if profile.allow_side_effects is False, side-effect tools excluded

    Args:
        org_id: Organization ID (reserved for future org-specific filtering)
        profile: GenerationProfile to use. If None, resolved from profile_name.
        profile_name: Profile name string. Used if profile is None.

    Returns:
        ToolContractPack with filtered contracts
    """
    if profile is None:
        profile = get_profile(profile_name)

    function_registry.initialize()
    all_meta = function_registry.list_all()

    contracts: List[ToolContract] = []

    for meta in all_meta:
        # Layer 1: exposure profile check
        if not check_exposure(meta, "procedure"):
            continue

        # Layer 2: category filter
        category = meta.category.value
        if category not in profile.allowed_categories:
            continue

        # Layer 3: blocked tools
        if meta.name in profile.blocked_tools:
            continue

        # Layer 4: side effects policy
        if meta.side_effects and not profile.allow_side_effects:
            continue

        # Generate contract
        contract = ContractGenerator.generate(meta)
        contracts.append(contract)

    logger.info(
        f"Built contract pack: profile={profile.name.value}, "
        f"tools={len(contracts)}/{len(all_meta)}"
    )

    return ToolContractPack(profile=profile, contracts=contracts)
