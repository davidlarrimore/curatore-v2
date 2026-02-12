# backend/tests/test_tool_contracts.py
"""
Tests for the Tool Contracts system.

Covers:
- Contract generation from FunctionMeta (via as_contract())
- JSON Schema correctness (types, required, enum)
- Parameter type validation (pass/fail cases)
- Enum validation
- Contract caching in registry
- Governance metadata propagation
"""

import pytest
from app.cwr.tools.base import (
    BaseFunction,
    FunctionCategory,
    FunctionMeta,
    FunctionResult,
)
from app.cwr.tools.schema_utils import ContractView

# =============================================================================
# FIXTURES
# =============================================================================


def _make_meta(**overrides) -> FunctionMeta:
    """Create a FunctionMeta with defaults for testing."""
    defaults = dict(
        name="test_func",
        category=FunctionCategory.SEARCH,
        description="A test function",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "description": "Max results", "default": 10},
            },
            "required": ["query"],
        },
        output_schema={
            "type": "object",
            "description": "Search results",
        },
        tags=["test"],
        requires_llm=False,
    )
    defaults.update(overrides)
    return FunctionMeta(**defaults)


def _make_meta_with_output() -> FunctionMeta:
    """Create a FunctionMeta with detailed output schema."""
    return FunctionMeta(
        name="test_with_output",
        category=FunctionCategory.LLM,
        description="Test function with output schema",
        input_schema={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Input text"},
                "style": {
                    "type": "string",
                    "description": "Output style",
                    "default": "paragraph",
                    "enum": ["paragraph", "bullets", "one_sentence"],
                },
                "count": {"type": "integer", "description": "Count", "default": 5},
                "items": {"type": "array", "description": "Items", "items": {"type": "string"}},
                "config": {"type": "object", "description": "Config"},
                "verbose": {"type": "boolean", "description": "Verbose", "default": False},
                "threshold": {"type": "number", "description": "Threshold", "default": 0.5},
            },
            "required": ["text"],
        },
        output_schema={
            "type": "object",
            "description": "Classification result",
            "properties": {
                "category": {"type": "string", "description": "Category"},
                "confidence": {"type": "number", "description": "Score"},
            },
            "variants": [
                {
                    "description": "collection: when items provided",
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "item_id": {"type": "string", "description": "Item ID"},
                            "result": {"type": "object", "description": "Result"},
                        },
                    },
                },
            ],
        },
        tags=["llm", "test"],
        requires_llm=True,
        side_effects=False,
        is_primitive=True,
        payload_profile="full",
    )


class DummyFunction(BaseFunction):
    """Minimal function for validation testing."""
    meta = FunctionMeta(
        name="dummy",
        category=FunctionCategory.SEARCH,
        description="Dummy",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Query"},
                "limit": {"type": "integer", "description": "Limit", "default": 10},
                "mode": {
                    "type": "string",
                    "description": "Mode",
                    "default": "keyword",
                    "enum": ["keyword", "semantic", "hybrid"],
                },
                "tags": {"type": "array", "description": "Tags", "items": {"type": "string"}},
                "config": {"type": "object", "description": "Config"},
                "flag": {"type": "boolean", "description": "Flag", "default": False},
                "score": {"type": "number", "description": "Score", "default": 0.5},
            },
            "required": ["query"],
        },
        output_schema={
            "type": "array",
            "description": "Search results",
        },
        tags=["test"],
        requires_llm=False,
        side_effects=False,
        is_primitive=True,
        payload_profile="thin",
    )

    async def execute(self, ctx, **params):
        return FunctionResult.success_result(data=[])


# =============================================================================
# CONTRACT GENERATION TESTS
# =============================================================================


class TestContractGeneration:
    """Tests for ContractView generation from FunctionMeta via as_contract()."""

    def test_basic_contract_generation(self):
        meta = _make_meta()
        contract = meta.as_contract()

        assert isinstance(contract, ContractView)
        assert contract.name == "test_func"
        assert contract.description == "A test function"
        assert contract.category == "search"
        assert contract.version == "1.0.0"
        assert contract.requires_llm is False
        assert contract.tags == ["test"]

    def test_governance_fields_defaults(self):
        meta = _make_meta()
        contract = meta.as_contract()

        assert contract.side_effects is False
        assert contract.is_primitive is True
        assert contract.payload_profile == "full"
        assert contract.exposure_profile == {"procedure": True, "agent": True}

    def test_governance_fields_custom(self):
        meta = _make_meta(
            side_effects=True,
            is_primitive=False,
            payload_profile="thin",
            exposure_profile={"procedure": True, "agent": False},
        )
        contract = meta.as_contract()

        assert contract.side_effects is True
        assert contract.is_primitive is False
        assert contract.payload_profile == "thin"
        assert contract.exposure_profile == {"procedure": True, "agent": False}

    def test_to_dict(self):
        meta = _make_meta()
        contract = meta.as_contract()
        d = contract.to_dict()

        assert d["name"] == "test_func"
        assert "input_schema" in d
        assert "output_schema" in d
        assert "side_effects" in d
        assert "is_primitive" in d
        assert "payload_profile" in d
        assert "exposure_profile" in d


# =============================================================================
# JSON SCHEMA TESTS
# =============================================================================


class TestInputSchema:
    """Tests for JSON Schema on ContractView input_schema."""

    def test_basic_input_schema(self):
        meta = _make_meta()
        contract = meta.as_contract()
        schema = contract.input_schema

        assert schema["type"] == "object"
        assert "query" in schema["properties"]
        assert "limit" in schema["properties"]
        assert "query" in schema["required"]
        assert "limit" not in schema.get("required", [])

    def test_string_type(self):
        meta = _make_meta()
        contract = meta.as_contract()
        assert contract.input_schema["properties"]["query"]["type"] == "string"

    def test_integer_type(self):
        meta = _make_meta()
        contract = meta.as_contract()
        assert contract.input_schema["properties"]["limit"]["type"] == "integer"
        assert contract.input_schema["properties"]["limit"]["default"] == 10

    def test_all_types(self):
        meta = _make_meta_with_output()
        contract = meta.as_contract()
        props = contract.input_schema["properties"]

        assert props["text"]["type"] == "string"
        assert props["count"]["type"] == "integer"
        assert props["items"]["type"] == "array"
        assert props["items"]["items"]["type"] == "string"
        assert props["config"]["type"] == "object"
        assert props["verbose"]["type"] == "boolean"
        assert props["threshold"]["type"] == "number"

    def test_enum_values(self):
        meta = _make_meta_with_output()
        contract = meta.as_contract()
        style_prop = contract.input_schema["properties"]["style"]

        assert style_prop["enum"] == ["paragraph", "bullets", "one_sentence"]

    def test_empty_params(self):
        meta = _make_meta(input_schema={
            "type": "object",
            "properties": {},
            "required": [],
        })
        contract = meta.as_contract()

        assert contract.input_schema["type"] == "object"
        assert contract.input_schema["properties"] == {}
        assert contract.input_schema["required"] == []


class TestOutputSchema:
    """Tests for output_schema on ContractView."""

    def test_no_output_schema(self):
        meta = _make_meta()
        contract = meta.as_contract()

        # Default output_schema was overridden in _make_meta to have description
        assert contract.output_schema["type"] == "object"
        assert "description" in contract.output_schema

    def test_dict_output_schema(self):
        meta = _make_meta_with_output()
        contract = meta.as_contract()

        assert contract.output_schema["type"] == "object"
        assert "properties" in contract.output_schema
        assert "category" in contract.output_schema["properties"]
        assert "confidence" in contract.output_schema["properties"]

    def test_output_variants(self):
        meta = _make_meta_with_output()
        contract = meta.as_contract()

        assert "variants" in contract.output_schema
        assert len(contract.output_schema["variants"]) == 1
        variant = contract.output_schema["variants"][0]
        assert "collection" in variant["description"]


# =============================================================================
# PARAMETER VALIDATION TESTS
# =============================================================================


class TestParameterValidation:
    """Tests for validate_params in BaseFunction using JSON Schema input_schema."""

    def setup_method(self):
        self.func = DummyFunction()

    def test_valid_params(self):
        result = self.func.validate_params({"query": "test"})
        assert result["query"] == "test"
        assert result["limit"] == 10  # default

    def test_missing_required(self):
        with pytest.raises(ValueError, match="Missing required parameter"):
            self.func.validate_params({})

    def test_type_check_string(self):
        with pytest.raises(ValueError, match="expects type 'string'"):
            self.func.validate_params({"query": 123})

    def test_type_check_int(self):
        with pytest.raises(ValueError, match="expects type 'integer'"):
            self.func.validate_params({"query": "test", "limit": "abc"})

    def test_type_check_list(self):
        with pytest.raises(ValueError, match="expects type 'array'"):
            self.func.validate_params({"query": "test", "tags": "not-a-list"})

    def test_type_check_dict(self):
        with pytest.raises(ValueError, match="expects type 'object'"):
            self.func.validate_params({"query": "test", "config": "not-a-dict"})

    def test_type_check_bool(self):
        with pytest.raises(ValueError, match="expects type 'boolean'"):
            self.func.validate_params({"query": "test", "flag": "yes"})

    def test_type_check_float(self):
        # int should be accepted for number type
        result = self.func.validate_params({"query": "test", "score": 1})
        assert result["score"] == 1

    def test_type_check_float_rejects_string(self):
        with pytest.raises(ValueError, match="expects type 'number'"):
            self.func.validate_params({"query": "test", "score": "high"})

    def test_enum_validation_pass(self):
        result = self.func.validate_params({"query": "test", "mode": "semantic"})
        assert result["mode"] == "semantic"

    def test_enum_validation_fail(self):
        with pytest.raises(ValueError, match="not in allowed values"):
            self.func.validate_params({"query": "test", "mode": "invalid"})

    def test_template_bypass_type_check(self):
        """Template strings should bypass type validation."""
        result = self.func.validate_params({"query": "{{ params.q }}", "limit": "{{ steps.s1.count }}"})
        assert result["query"] == "{{ params.q }}"
        assert result["limit"] == "{{ steps.s1.count }}"

    def test_template_bypass_enum_check(self):
        """Template strings should bypass enum validation."""
        result = self.func.validate_params({"query": "test", "mode": "{{ params.mode }}"})
        assert result["mode"] == "{{ params.mode }}"


# =============================================================================
# CONTRACT CACHING TESTS
# =============================================================================


class TestContractCaching:
    """Tests for contract caching in FunctionRegistry."""

    def test_registry_caching(self):
        from app.cwr.tools.registry import FunctionRegistry

        registry = FunctionRegistry()
        registry.register(DummyFunction)

        # First call generates contract
        c1 = registry.get_contract("dummy")
        assert c1 is not None

        # Second call returns cached
        c2 = registry.get_contract("dummy")
        assert c1 is c2  # Same object

    def test_list_contracts(self):
        from app.cwr.tools.registry import FunctionRegistry

        registry = FunctionRegistry()
        registry.register(DummyFunction)

        contracts = registry.list_contracts()
        assert len(contracts) == 1
        assert contracts[0].name == "dummy"

    def test_unknown_contract(self):
        from app.cwr.tools.registry import FunctionRegistry

        registry = FunctionRegistry()
        assert registry.get_contract("nonexistent") is None


# =============================================================================
# PROCEDURE VALIDATOR INTEGRATION
# =============================================================================


class TestValidatorWithContracts:
    """Tests for procedure validator using tool contracts."""

    def setup_method(self):
        from app.cwr.contracts.validation import ProcedureValidator
        self.validator = ProcedureValidator()

    def test_type_mismatch_error(self):
        """Validator should catch type mismatches using contract schemas."""
        definition = {
            "name": "Test",
            "slug": "test-proc",
            "steps": [
                {
                    "name": "search",
                    "function": "search_assets",
                    "params": {
                        "query": "test",
                        "limit": "not-an-int",  # Should be int
                    },
                },
            ],
        }
        result = self.validator.validate(definition)
        type_errors = [e for e in result.errors if e.code.value == "INVALID_PARAM_TYPE"]
        assert len(type_errors) > 0

    def test_template_bypasses_type_check(self):
        """Template strings should not trigger type errors."""
        definition = {
            "name": "Test",
            "slug": "test-proc",
            "steps": [
                {
                    "name": "search",
                    "function": "search_assets",
                    "params": {
                        "query": "{{ params.q }}",
                        "limit": "{{ params.limit }}",
                    },
                },
            ],
        }
        result = self.validator.validate(definition)
        type_errors = [e for e in result.errors if e.code.value == "INVALID_PARAM_TYPE"]
        assert len(type_errors) == 0


# =============================================================================
# TYPE MAPPING TESTS
# =============================================================================


class TestTypeMapping:
    """Tests for the type string to JSON Schema mapping in schema_utils."""

    @pytest.mark.parametrize("type_str,expected_type", [
        ("str", "string"),
        ("string", "string"),
        ("int", "integer"),
        ("integer", "integer"),
        ("float", "number"),
        ("number", "number"),
        ("bool", "boolean"),
        ("boolean", "boolean"),
        ("list", "array"),
        ("dict", "object"),
        ("object", "object"),
    ])
    def test_basic_type_mapping(self, type_str, expected_type):
        from app.cwr.tools.schema_utils import param_type_to_json_schema
        schema = param_type_to_json_schema(type_str)
        assert schema["type"] == expected_type

    @pytest.mark.parametrize("type_str,expected_items_type", [
        ("list[str]", "string"),
        ("list[dict]", "object"),
        ("list[int]", "integer"),
    ])
    def test_parameterized_list_mapping(self, type_str, expected_items_type):
        from app.cwr.tools.schema_utils import param_type_to_json_schema
        schema = param_type_to_json_schema(type_str)
        assert schema["type"] == "array"
        assert schema["items"]["type"] == expected_items_type

    def test_unknown_type_defaults_to_string(self):
        from app.cwr.tools.schema_utils import param_type_to_json_schema
        schema = param_type_to_json_schema("unknown_type")
        assert schema["type"] == "string"


# =============================================================================
# EXPLICIT OUTPUT SCHEMA TESTS
# =============================================================================


class TestExplicitOutputSchemas:
    """Verify that the 4 tools that previously lacked output_schema now have explicit ones."""

    def test_get_content_output_schema(self):
        from app.cwr.tools.primitives.search.get_content import GetContentFunction
        schema = GetContentFunction.meta.output_schema
        assert schema is not None
        assert schema["type"] == "array"
        assert "items" in schema
        assert "asset_id" in schema["items"]["properties"]
        assert "content" in schema["items"]["properties"]

    def test_get_asset_output_schema(self):
        from app.cwr.tools.primitives.search.get_asset import GetAssetFunction
        schema = GetAssetFunction.meta.output_schema
        assert schema is not None
        assert schema["type"] == "object"
        assert "asset_id" in schema["properties"]
        assert "filename" in schema["properties"]
        assert "content" in schema["properties"]

    def test_get_output_schema(self):
        from app.cwr.tools.primitives.search.get import GetFunction
        schema = GetFunction.meta.output_schema
        assert schema is not None
        assert schema["type"] == "object"
        assert "id" in schema["properties"]
        assert "title" in schema["properties"]
        assert "text" in schema["properties"]

    def test_query_model_output_schema(self):
        from app.cwr.tools.primitives.search.query_model import QueryModelFunction
        schema = QueryModelFunction.meta.output_schema
        assert schema is not None
        assert schema["type"] == "array"
        # Dynamic schema — items is generic object
        assert schema["items"]["type"] == "object"
        # No properties defined (fields vary by model)
        assert "properties" not in schema["items"]
