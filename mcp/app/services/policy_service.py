# Policy Service
"""Loads and enforces policy configuration."""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from app.config import settings
from app.models.policy import ClampConfig, Policy

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
                version=data.get("version", "2.0"),
                denylist=data.get("denylist", []),
                allowlist=data.get("allowlist", []),
                clamps=clamps,
                settings=data.get("settings", {}),
            )

            if self._policy.is_v2:
                logger.info(
                    f"Loaded policy v{self._policy.version} (auto-derive mode, "
                    f"{len(self._policy.denylist)} denied tools)"
                )
            else:
                logger.info(
                    f"Loaded policy v{self._policy.version} (legacy mode, "
                    f"{len(self._policy.allowlist)} allowed tools)"
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
        """
        Check if a tool is allowed by policy.

        In v2.0 (auto-derive) mode, this only checks the denylist.
        The exposure_profile check happens in filter_allowed() and tools_call.py.

        In v1.0 (legacy) mode, this checks the allowlist.
        """
        policy = self.policy
        if policy.is_v2:
            # Auto-derive: only blocked if explicitly denied
            return not policy.is_denied(tool_name)
        else:
            # Legacy: must be in allowlist
            return policy.is_allowed(tool_name)

    def is_denied(self, tool_name: str) -> bool:
        """Check if a tool is in the denylist (v2.0 mode)."""
        return self.policy.is_denied(tool_name)

    def filter_allowed(
        self,
        contracts: List[Dict[str, Any]],
        check_side_effects: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Filter contracts by policy.

        In v2.0 mode: auto-derive from exposure_profile.agent + denylist.
        In v1.0 mode: filter by allowlist.

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

            if policy.is_v2:
                # Auto-derive: allow if exposure_profile includes agent access
                exposure = contract.get("exposure_profile", {})
                if not exposure.get("agent", False):
                    continue
                # Check denylist
                if policy.is_denied(name):
                    logger.debug(f"Blocking {name}: in denylist")
                    continue
            else:
                # Legacy: check allowlist
                if not policy.is_allowed(name):
                    continue

            # Check side_effects if enabled
            if check_side_effects and policy.settings.block_side_effects:
                if contract.get("side_effects", False):
                    # Allow if in side_effects_allowlist
                    if name not in policy.settings.side_effects_allowlist:
                        logger.debug(f"Blocking {name}: has side effects")
                        continue
                    logger.debug(f"Allowing {name}: in side_effects_allowlist")

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
    def denylist(self) -> List[str]:
        """Get the current denylist."""
        return self.policy.denylist

    @property
    def allowlist(self) -> List[str]:
        """Get the current allowlist (legacy v1.0)."""
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
