# Policy Service
"""Loads and enforces policy configuration."""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from app.config import settings
from app.models.policy import Policy, ClampConfig

logger = logging.getLogger("mcp.services.policy_service")


class PolicyService:
    """Manages policy configuration and enforcement."""

    def __init__(self, policy_file: Optional[str] = None):
        self._policy_file = policy_file or settings.policy_file
        self._policy: Optional[Policy] = None

    def load(self) -> Policy:
        """
        Load policy from YAML file.

        Returns:
            Policy configuration
        """
        if self._policy is not None:
            return self._policy

        try:
            policy_path = Path(self._policy_file)
            if not policy_path.exists():
                logger.warning(f"Policy file not found: {self._policy_file}, using defaults")
                self._policy = Policy()
                return self._policy

            with open(policy_path) as f:
                data = yaml.safe_load(f)

            # Convert clamps to proper format
            clamps = {}
            raw_clamps = data.get("clamps", {})
            for tool_name, tool_clamps in raw_clamps.items():
                clamps[tool_name] = {}
                for param_name, clamp_config in tool_clamps.items():
                    if isinstance(clamp_config, dict):
                        clamps[tool_name][param_name] = ClampConfig(**clamp_config)
                    else:
                        clamps[tool_name][param_name] = ClampConfig(max=clamp_config)

            self._policy = Policy(
                version=data.get("version", "1.0"),
                allowlist=data.get("allowlist", []),
                clamps=clamps,
                settings=data.get("settings", {}),
            )
            logger.info(
                f"Loaded policy v{self._policy.version} with "
                f"{len(self._policy.allowlist)} allowed tools"
            )
            return self._policy

        except Exception as e:
            logger.exception(f"Error loading policy: {e}")
            self._policy = Policy()
            return self._policy

    def reload(self) -> Policy:
        """Force reload policy from file."""
        self._policy = None
        return self.load()

    @property
    def policy(self) -> Policy:
        """Get current policy, loading if needed."""
        if self._policy is None:
            return self.load()
        return self._policy

    def is_allowed(self, tool_name: str) -> bool:
        """Check if a tool is allowed by policy."""
        return self.policy.is_allowed(tool_name)

    def filter_allowed(
        self,
        contracts: List[Dict[str, Any]],
        check_side_effects: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Filter contracts by policy allowlist and side_effects.

        Args:
            contracts: List of ToolContract dictionaries
            check_side_effects: If True, also filter by side_effects flag

        Returns:
            Filtered list of contracts
        """
        policy = self.policy
        result = []

        for contract in contracts:
            name = contract.get("name", "")

            # Check allowlist
            if not policy.is_allowed(name):
                continue

            # Check side_effects if enabled
            if check_side_effects and policy.settings.block_side_effects:
                if contract.get("side_effects", False):
                    logger.debug(f"Blocking {name}: has side effects")
                    continue

            result.append(contract)

        return result

    def apply_clamps(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Apply parameter clamps to tool arguments.

        Args:
            tool_name: Tool name
            arguments: Original arguments

        Returns:
            Arguments with clamps applied
        """
        return self.policy.apply_clamps(tool_name, arguments)

    def get_clamps(self, tool_name: str) -> Dict[str, ClampConfig]:
        """Get clamps for a specific tool."""
        return self.policy.get_clamps(tool_name)

    @property
    def allowlist(self) -> List[str]:
        """Get the current allowlist."""
        return self.policy.allowlist

    @property
    def block_side_effects(self) -> bool:
        """Check if side effects should be blocked."""
        return self.policy.settings.block_side_effects

    @property
    def validate_facets(self) -> bool:
        """Check if facets should be validated."""
        return self.policy.settings.validate_facets

    @property
    def contract_cache_ttl(self) -> int:
        """Get contract cache TTL in seconds."""
        return self.policy.settings.contract_cache_ttl

    @property
    def metadata_cache_ttl(self) -> int:
        """Get metadata cache TTL in seconds."""
        return self.policy.settings.metadata_cache_ttl


# Global policy service instance
policy_service = PolicyService()
