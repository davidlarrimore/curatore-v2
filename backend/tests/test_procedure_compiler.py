# backend/tests/test_procedure_compiler.py
"""
Tests for the AI Procedure Compiler (v2).

Tests cover:
- Context builder system prompt content
- Plan-level efficiency patterns (thin -> materialize -> LLM)
- Facet validation in the procedure validator
"""

import pytest
from unittest.mock import patch, MagicMock

from app.cwr.contracts.validation import ProcedureValidator, ValidationErrorCode
from app.cwr.procedures.compiler.context_builder import ContextBuilder
from app.cwr.governance.generation_profiles import get_profile


# =============================================================================
# SYSTEM PROMPT TESTS (v2: ContextBuilder)
# =============================================================================


class TestSystemPrompt:
    """Tests for v2 context builder system prompt content."""

    def test_system_prompt_includes_efficiency_patterns(self):
        """Verify system prompt contains the efficiency patterns section."""
        profile = get_profile("workflow_standard")
        # Create a minimal mock contract pack
        mock_pack = MagicMock()
        mock_pack.profile = profile
        mock_pack.to_prompt_json.return_value = "[]"

        builder = ContextBuilder(mock_pack, profile)
        section = builder._build_efficiency_patterns()

        assert "Thin" in section
        assert "get_content" in section
        assert "payload_profile" in section
        assert "Side Effects Last" in section


class TestSearchDecisionTree:
    """Tests for search function selection decision tree."""

    def test_decision_tree_covers_all_search_types(self):
        """Verify decision tree mentions all key search functions."""
        profile = get_profile("workflow_standard")
        mock_pack = MagicMock()
        mock_pack.profile = profile
        mock_pack.to_prompt_json.return_value = "[]"

        builder = ContextBuilder(mock_pack, profile)
        section = builder._build_search_decision_tree()

        assert "search_assets" in section
        assert "search_solicitations" in section
        assert "search_notices" in section
        assert "search_salesforce" in section
        assert "search_forecasts" in section
        assert "search_scraped_assets" in section
        assert "get_content" in section


class TestProfileConstraints:
    """Tests for profile constraints section in system prompt."""

    def test_safe_readonly_constraints(self):
        profile = get_profile("safe_readonly")
        mock_pack = MagicMock()
        mock_pack.profile = profile
        mock_pack.to_prompt_json.return_value = "[]"

        builder = ContextBuilder(mock_pack, profile)
        section = builder._build_profile_constraints()

        assert "safe_readonly" in section
        assert "Side effects allowed**: no" in section

    def test_admin_full_constraints(self):
        profile = get_profile("admin_full")
        mock_pack = MagicMock()
        mock_pack.profile = profile
        mock_pack.to_prompt_json.return_value = "[]"

        builder = ContextBuilder(mock_pack, profile)
        section = builder._build_profile_constraints()

        assert "admin_full" in section
        assert "confirm_side_effects" in section


# =============================================================================
# FACET VALIDATION TESTS
# =============================================================================


class TestFacetValidation:
    """Tests for facet filter validation in the procedure validator."""

    def setup_method(self):
        self.validator = ProcedureValidator()

    def test_facet_validation_warns_on_invalid_facet(self):
        """Unknown facet names should produce warnings."""
        mock_facets = {
            "agency": {"display_name": "Agency", "data_type": "string"},
            "naics_code": {"display_name": "NAICS Code", "data_type": "string"},
        }

        step = {
            "name": "search_step",
            "function": "search_assets",
            "params": {
                "query": "test",
                "facet_filters": {
                    "agency": "GSA",
                    "nonexistent_facet": "value",
                },
            },
        }

        with patch(
            "app.core.metadata.registry_service.metadata_registry_service"
        ) as mock_registry:
            mock_registry.get_facet_definitions.return_value = mock_facets

            warnings = self.validator._validate_facet_filters(step, "steps[0]")

        assert len(warnings) == 1
        assert warnings[0].code == ValidationErrorCode.INVALID_FACET_FILTER
        assert "nonexistent_facet" in warnings[0].message

    def test_facet_validation_passes_valid_facets(self):
        """Known facet names should produce no warnings."""
        mock_facets = {
            "agency": {"display_name": "Agency", "data_type": "string"},
            "naics_code": {"display_name": "NAICS Code", "data_type": "string"},
        }

        step = {
            "name": "search_step",
            "function": "search_assets",
            "params": {
                "query": "test",
                "facet_filters": {
                    "agency": "GSA",
                    "naics_code": "541512",
                },
            },
        }

        with patch(
            "app.core.metadata.registry_service.metadata_registry_service"
        ) as mock_registry:
            mock_registry.get_facet_definitions.return_value = mock_facets

            warnings = self.validator._validate_facet_filters(step, "steps[0]")

        assert len(warnings) == 0

    def test_facet_validation_skips_no_facet_filters(self):
        """Steps without facet_filters should produce no warnings."""
        step = {
            "name": "search_step",
            "function": "search_assets",
            "params": {"query": "test"},
        }

        warnings = self.validator._validate_facet_filters(step, "steps[0]")

        assert len(warnings) == 0

    def test_facet_validation_skips_template_values(self):
        """Template expression facet_filters should be skipped."""
        step = {
            "name": "search_step",
            "function": "search_assets",
            "params": {
                "query": "test",
                "facet_filters": "{{ params.filters }}",
            },
        }

        warnings = self.validator._validate_facet_filters(step, "steps[0]")

        assert len(warnings) == 0
