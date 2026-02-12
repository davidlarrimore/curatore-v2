# Policy Service Tests
"""Tests for policy loading and enforcement."""

import os
import tempfile

import yaml
from app.models.policy import ClampConfig, Policy
from app.services.policy_service import PolicyService


class TestPolicyServiceV2:
    """Test policy service in v2.0 (auto-derive) mode."""

    def test_load_default_policy_is_v2(self):
        """Test that default policy uses v2.0."""
        service = PolicyService(policy_file="/nonexistent/policy.yaml")
        policy = service.load()

        assert isinstance(policy, Policy)
        assert policy.is_v2 is True
        assert policy.denylist == []

    def test_load_v2_policy_from_file(self):
        """Test loading v2.0 policy from YAML file."""
        policy_data = {
            "version": "2.0",
            "denylist": ["dangerous_tool"],
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

            assert policy.version == "2.0"
            assert policy.is_v2 is True
            assert "dangerous_tool" in policy.denylist
            assert policy.settings.block_side_effects is True
        finally:
            os.unlink(policy_file)

    def test_is_allowed_v2_not_denied(self):
        """Test that non-denied tools are allowed in v2.0 mode."""
        service = PolicyService()
        service._policy = Policy(version="2.0", denylist=["blocked_tool"])

        assert service.is_allowed("search_assets") is True
        assert service.is_allowed("get_content") is True
        assert service.is_allowed("blocked_tool") is False

    def test_is_denied(self):
        """Test denylist checking."""
        service = PolicyService()
        service._policy = Policy(version="2.0", denylist=["blocked_tool"])

        assert service.is_denied("blocked_tool") is True
        assert service.is_denied("search_assets") is False

    def test_filter_allowed_v2_by_exposure_profile(self):
        """Test auto-derive filtering by exposure_profile.agent."""
        service = PolicyService()
        service._policy = Policy(
            version="2.0",
            denylist=[],
            settings={"block_side_effects": False},
        )

        contracts = [
            {
                "name": "search_assets",
                "side_effects": False,
                "exposure_profile": {"procedure": True, "agent": True},
            },
            {
                "name": "internal_tool",
                "side_effects": False,
                "exposure_profile": {"procedure": True, "agent": False},
            },
            {
                "name": "agent_only",
                "side_effects": False,
                "exposure_profile": {"procedure": False, "agent": True},
            },
        ]

        filtered = service.filter_allowed(contracts, check_side_effects=False)

        names = [c["name"] for c in filtered]
        assert "search_assets" in names
        assert "agent_only" in names
        assert "internal_tool" not in names  # agent=False

    def test_filter_allowed_v2_denylist_override(self):
        """Test that denylist blocks even if exposure_profile.agent=True."""
        service = PolicyService()
        service._policy = Policy(
            version="2.0",
            denylist=["search_assets"],
            settings={"block_side_effects": False},
        )

        contracts = [
            {
                "name": "search_assets",
                "side_effects": False,
                "exposure_profile": {"procedure": True, "agent": True},
            },
            {
                "name": "get_content",
                "side_effects": False,
                "exposure_profile": {"procedure": True, "agent": True},
            },
        ]

        filtered = service.filter_allowed(contracts, check_side_effects=False)

        names = [c["name"] for c in filtered]
        assert "search_assets" not in names  # In denylist
        assert "get_content" in names

    def test_filter_allowed_v2_side_effects_blocked(self):
        """Test that side_effects blocking works in v2.0 mode."""
        service = PolicyService()
        service._policy = Policy(
            version="2.0",
            denylist=[],
            settings={
                "block_side_effects": True,
                "side_effects_allowlist": ["confirm_email"],
            },
        )

        contracts = [
            {
                "name": "search_assets",
                "side_effects": False,
                "exposure_profile": {"procedure": True, "agent": True},
            },
            {
                "name": "send_email",
                "side_effects": True,
                "exposure_profile": {"procedure": True, "agent": True},
            },
            {
                "name": "confirm_email",
                "side_effects": True,
                "exposure_profile": {"procedure": True, "agent": True},
            },
        ]

        filtered = service.filter_allowed(contracts)

        names = [c["name"] for c in filtered]
        assert "search_assets" in names
        assert "send_email" not in names  # Side effects blocked
        assert "confirm_email" in names  # In side_effects_allowlist

    def test_filter_allowed_v2_no_exposure_profile(self):
        """Test that contracts without exposure_profile are excluded."""
        service = PolicyService()
        service._policy = Policy(
            version="2.0",
            denylist=[],
            settings={"block_side_effects": False},
        )

        contracts = [
            {"name": "old_tool", "side_effects": False},  # No exposure_profile
            {
                "name": "new_tool",
                "side_effects": False,
                "exposure_profile": {"agent": True},
            },
        ]

        filtered = service.filter_allowed(contracts, check_side_effects=False)

        names = [c["name"] for c in filtered]
        assert "old_tool" not in names
        assert "new_tool" in names


class TestPolicyServiceV1Legacy:
    """Test policy service in v1.0 (legacy) mode."""

    def test_load_v1_policy(self):
        """Test loading v1.0 policy from YAML file."""
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
            },
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(policy_data, f)
            policy_file = f.name

        try:
            service = PolicyService(policy_file=policy_file)
            policy = service.load()

            assert policy.version == "1.0"
            assert policy.is_v2 is False
            assert "search_assets" in policy.allowlist
        finally:
            os.unlink(policy_file)

    def test_is_allowed_v1(self):
        """Test allowlist checking in v1.0 mode."""
        service = PolicyService()
        service._policy = Policy(
            version="1.0",
            allowlist=["search_assets", "get_content"],
        )

        assert service.is_allowed("search_assets") is True
        assert service.is_allowed("send_email") is False

    def test_filter_allowed_v1(self):
        """Test filtering contracts by allowlist in v1.0 mode."""
        service = PolicyService()
        service._policy = Policy(
            version="1.0",
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


class TestPolicyClamps:
    """Test parameter clamp application."""

    def test_apply_clamps_max(self):
        """Test applying max clamps."""
        service = PolicyService()
        service._policy = Policy(
            version="2.0",
            clamps={
                "search_assets": {"limit": ClampConfig(max=50, default=20)},
            },
        )

        result = service.apply_clamps("search_assets", {"limit": 100})
        assert result["limit"] == 50

        result = service.apply_clamps("search_assets", {"limit": 30})
        assert result["limit"] == 30

    def test_apply_clamps_default(self):
        """Test applying default clamps."""
        service = PolicyService()
        service._policy = Policy(
            version="2.0",
            clamps={
                "search_assets": {"limit": ClampConfig(max=50, default=20)},
            },
        )

        result = service.apply_clamps("search_assets", {"query": "test"})
        assert result["limit"] == 20
        assert result["query"] == "test"

    def test_apply_clamps_no_clamps(self):
        """Test with no clamps defined."""
        service = PolicyService()
        service._policy = Policy(version="2.0")

        args = {"query": "test", "limit": 100}
        result = service.apply_clamps("search_assets", args)
        assert result == args


class TestPolicyReload:
    """Test policy reload functionality."""

    def test_reload(self):
        """Test policy reload."""
        policy_data = {"version": "2.0", "denylist": ["tool1"]}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(policy_data, f)
            policy_file = f.name

        try:
            service = PolicyService(policy_file=policy_file)
            policy1 = service.load()
            assert "tool1" in policy1.denylist

            # Update file
            policy_data["denylist"] = ["tool1", "tool2"]
            with open(policy_file, "w") as f:
                yaml.dump(policy_data, f)

            # Reload
            policy2 = service.reload()
            assert "tool2" in policy2.denylist
        finally:
            os.unlink(policy_file)
