"""Tests for generation profiles."""

import pytest
from app.cwr.governance.generation_profiles import (
    GenerationProfile,
    GenerationProfileName,
    GENERATION_PROFILES,
    get_profile,
    get_available_profiles,
)


class TestGenerationProfileName:
    def test_enum_values(self):
        assert GenerationProfileName.SAFE_READONLY.value == "safe_readonly"
        assert GenerationProfileName.WORKFLOW_STANDARD.value == "workflow_standard"
        assert GenerationProfileName.ADMIN_FULL.value == "admin_full"

    def test_all_profiles_defined(self):
        for name in GenerationProfileName:
            assert name in GENERATION_PROFILES


class TestGenerationProfile:
    def test_safe_readonly_blocks_side_effects(self):
        profile = GENERATION_PROFILES[GenerationProfileName.SAFE_READONLY]
        assert not profile.allow_side_effects
        assert "send_email" in profile.blocked_tools
        assert "webhook" in profile.blocked_tools
        assert "update_metadata" in profile.blocked_tools

    def test_safe_readonly_categories(self):
        profile = GENERATION_PROFILES[GenerationProfileName.SAFE_READONLY]
        assert "search" in profile.allowed_categories
        assert "llm" in profile.allowed_categories
        assert "flow" in profile.allowed_categories
        assert "notify" not in profile.allowed_categories
        assert "output" not in profile.allowed_categories

    def test_workflow_standard_allows_notify_output(self):
        profile = GENERATION_PROFILES[GenerationProfileName.WORKFLOW_STANDARD]
        assert "notify" in profile.allowed_categories
        assert "output" in profile.allowed_categories
        assert profile.allow_side_effects
        assert not profile.require_side_effect_confirmation

    def test_workflow_standard_blocks_webhook(self):
        profile = GENERATION_PROFILES[GenerationProfileName.WORKFLOW_STANDARD]
        assert "webhook" in profile.blocked_tools
        assert "update_metadata" in profile.blocked_tools

    def test_admin_full_allows_all(self):
        profile = GENERATION_PROFILES[GenerationProfileName.ADMIN_FULL]
        assert len(profile.blocked_tools) == 0
        assert profile.allow_side_effects
        assert profile.require_side_effect_confirmation

    def test_admin_full_higher_limits(self):
        admin = GENERATION_PROFILES[GenerationProfileName.ADMIN_FULL]
        standard = GENERATION_PROFILES[GenerationProfileName.WORKFLOW_STANDARD]
        assert admin.max_search_limit >= standard.max_search_limit
        assert admin.max_llm_tokens >= standard.max_llm_tokens


class TestIsToolAllowed:
    def test_tool_allowed_in_category(self):
        profile = GENERATION_PROFILES[GenerationProfileName.WORKFLOW_STANDARD]
        assert profile.is_tool_allowed("search_notices", "search", has_side_effects=False)

    def test_tool_blocked_by_name(self):
        profile = GENERATION_PROFILES[GenerationProfileName.WORKFLOW_STANDARD]
        assert not profile.is_tool_allowed("webhook", "notify", has_side_effects=True)

    def test_tool_blocked_by_category(self):
        profile = GENERATION_PROFILES[GenerationProfileName.SAFE_READONLY]
        assert not profile.is_tool_allowed("send_email", "notify", has_side_effects=True)

    def test_side_effect_blocked(self):
        profile = GENERATION_PROFILES[GenerationProfileName.SAFE_READONLY]
        assert not profile.is_tool_allowed("some_tool", "search", has_side_effects=True)

    def test_side_effect_allowed_with_flag(self):
        profile = GENERATION_PROFILES[GenerationProfileName.WORKFLOW_STANDARD]
        assert profile.is_tool_allowed("send_email", "notify", has_side_effects=True)

    def test_admin_allows_all(self):
        profile = GENERATION_PROFILES[GenerationProfileName.ADMIN_FULL]
        assert profile.is_tool_allowed("webhook", "notify", has_side_effects=True)
        assert profile.is_tool_allowed("update_metadata", "output", has_side_effects=True)


class TestGetProfile:
    def test_default_is_workflow_standard(self):
        profile = get_profile(None)
        assert profile.name == GenerationProfileName.WORKFLOW_STANDARD

    def test_explicit_name(self):
        profile = get_profile("safe_readonly")
        assert profile.name == GenerationProfileName.SAFE_READONLY

    def test_invalid_falls_back(self):
        profile = get_profile("nonexistent_profile")
        assert profile.name == GenerationProfileName.WORKFLOW_STANDARD

    def test_all_names_resolvable(self):
        for name in ["safe_readonly", "workflow_standard", "admin_full"]:
            profile = get_profile(name)
            assert profile.name.value == name


class TestGetAvailableProfiles:
    def test_returns_list(self):
        profiles = get_available_profiles()
        assert isinstance(profiles, list)
        assert len(profiles) == 3

    def test_profile_dict_shape(self):
        profiles = get_available_profiles()
        for p in profiles:
            assert "name" in p
            assert "description" in p
            assert "allowed_categories" in p
            assert "blocked_tools" in p
            assert "allow_side_effects" in p

    def test_to_dict_roundtrip(self):
        profile = GENERATION_PROFILES[GenerationProfileName.SAFE_READONLY]
        d = profile.to_dict()
        assert d["name"] == "safe_readonly"
        assert isinstance(d["allowed_categories"], list)
        assert isinstance(d["blocked_tools"], list)
