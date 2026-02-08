# Policy Service Tests
"""Tests for policy loading and enforcement."""

import pytest
import tempfile
import os
import yaml

from app.services.policy_service import PolicyService
from app.models.policy import Policy, ClampConfig


class TestPolicyService:
    """Test policy service."""

    def test_load_default_policy(self):
        """Test loading with missing policy file."""
        service = PolicyService(policy_file="/nonexistent/policy.yaml")
        policy = service.load()

        assert isinstance(policy, Policy)
        assert policy.allowlist == []

    def test_load_policy_from_file(self):
        """Test loading policy from YAML file."""
        policy_data = {
            "version": "1.0",
            "allowlist": ["search_assets", "get_content"],
            "clamps": {
                "search_assets": {
                    "limit": {"max": 50, "default": 20},
                },
            },
            "settings": {
                "block_side_effects": True,
                "validate_facets": True,
            },
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(policy_data, f)
            policy_file = f.name

        try:
            service = PolicyService(policy_file=policy_file)
            policy = service.load()

            assert policy.version == "1.0"
            assert "search_assets" in policy.allowlist
            assert "get_content" in policy.allowlist
            assert policy.settings.block_side_effects is True
        finally:
            os.unlink(policy_file)

    def test_is_allowed(self):
        """Test allowlist checking."""
        service = PolicyService()
        service._policy = Policy(allowlist=["search_assets", "get_content"])

        assert service.is_allowed("search_assets") is True
        assert service.is_allowed("get_content") is True
        assert service.is_allowed("send_email") is False

    def test_apply_clamps_max(self):
        """Test applying max clamps."""
        service = PolicyService()
        service._policy = Policy(
            allowlist=["search_assets"],
            clamps={
                "search_assets": {"limit": ClampConfig(max=50, default=20)},
            },
        )

        # Value over max should be clamped
        result = service.apply_clamps("search_assets", {"limit": 100})
        assert result["limit"] == 50

        # Value under max should be preserved
        result = service.apply_clamps("search_assets", {"limit": 30})
        assert result["limit"] == 30

    def test_apply_clamps_default(self):
        """Test applying default clamps."""
        service = PolicyService()
        service._policy = Policy(
            allowlist=["search_assets"],
            clamps={
                "search_assets": {"limit": ClampConfig(max=50, default=20)},
            },
        )

        # Missing parameter should get default
        result = service.apply_clamps("search_assets", {"query": "test"})
        assert result["limit"] == 20
        assert result["query"] == "test"

    def test_apply_clamps_no_clamps(self):
        """Test with no clamps defined."""
        service = PolicyService()
        service._policy = Policy(allowlist=["search_assets"])

        # Arguments should pass through unchanged
        args = {"query": "test", "limit": 100}
        result = service.apply_clamps("search_assets", args)
        assert result == args

    def test_filter_allowed(self):
        """Test filtering contracts by policy."""
        service = PolicyService()
        service._policy = Policy(
            allowlist=["search_assets", "get_content"],
            settings={"block_side_effects": True},
        )

        contracts = [
            {"name": "search_assets", "side_effects": False},
            {"name": "get_content", "side_effects": False},
            {"name": "send_email", "side_effects": True},
            {"name": "unknown_tool", "side_effects": False},
        ]

        filtered = service.filter_allowed(contracts)

        assert len(filtered) == 2
        names = [c["name"] for c in filtered]
        assert "search_assets" in names
        assert "get_content" in names

    def test_reload(self):
        """Test policy reload."""
        policy_data = {"version": "1.0", "allowlist": ["tool1"]}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(policy_data, f)
            policy_file = f.name

        try:
            service = PolicyService(policy_file=policy_file)
            policy1 = service.load()
            assert "tool1" in policy1.allowlist

            # Update file
            policy_data["allowlist"] = ["tool1", "tool2"]
            with open(policy_file, "w") as f:
                yaml.dump(policy_data, f)

            # Reload
            policy2 = service.reload()
            assert "tool2" in policy2.allowlist
        finally:
            os.unlink(policy_file)
