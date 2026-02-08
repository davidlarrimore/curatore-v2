# backend/tests/test_tool_contracts.py
"""
Tests for the Tool Contracts system.

Covers:
- Contract generation from FunctionMeta
- JSON Schema correctness (types, required, enum)
- Parameter type validation (pass/fail cases)
- Enum validation
- Contract caching in registry
- Governance metadata propagation
"""

import pytest
from app.cwr.tools.base import (
    FunctionMeta,
    FunctionCategory,
    FunctionResult,
    ParameterDoc,
    OutputSchema,
    OutputFieldDoc,
    OutputVariant,
    BaseFunction,
)
from app.cwr.contracts import ToolContract, ContractGenerator


# =============================================================================
# FIXTURES
# =============================================================================


def _make_meta(**overrides) -> FunctionMeta:
    """Create a FunctionMeta with defaults for testing."""
    defaults = dict(
        name="test_func",
        category=FunctionCategory.SEARCH,
        description="A test function",
        parameters=[
            ParameterDoc(name="query", type="str", description="Search query", required=True),
            ParameterDoc(name="limit", type="int", description="Max results", required=False, default=10),
        ],
        returns="list: Search results",
        tags=["test"],
        requires_llm=False,
    )
    defaults.update(overrides)
    return FunctionMeta(**defaults)


def _make_meta_with_output() -> FunctionMeta:
    """Create a FunctionMeta with output schema."""
    return FunctionMeta(
        name="test_with_output",
        category=FunctionCategory.LLM,
        description="Test function with output schema",
        parameters=[
            ParameterDoc(name="text", type="str", description="Input text", required=True),
            ParameterDoc(
                name="style", type="str", description="Output style",
                required=False, default="paragraph",
                enum_values=["paragraph", "bullets", "one_sentence"],
            ),
            ParameterDoc(name="count", type="int", description="Count", required=False, default=5),
            ParameterDoc(name="items", type="list[str]", description="Items", required=False),
            ParameterDoc(name="config", type="dict", description="Config", required=False),
            ParameterDoc(name="verbose", type="bool", description="Verbose", required=False, default=False),
            ParameterDoc(name="threshold", type="float", description="Threshold", required=False, default=0.5),
        ],
        returns="dict: Result",
        output_schema=OutputSchema(
            type="dict",
            description="Classification result",
            fields=[
                OutputFieldDoc(name="category", type="str", description="Category"),
                OutputFieldDoc(name="confidence", type="float", description="Score"),
            ],
        ),
        output_variants=[
            OutputVariant(
                mode="collection",
                condition="when items provided",
                schema=OutputSchema(
                    type="list[dict]",
                    description="List of results",
                    fields=[
                        OutputFieldDoc(name="item_id", type="str", description="Item ID"),
                        OutputFieldDoc(name="result", type="dict", description="Result"),
                    ],
                ),
            ),
        ],
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
        parameters=[
            ParameterDoc(name="query", type="str", description="Query", required=True),
            ParameterDoc(name="limit", type="int", description="Limit", required=False, default=10),
            ParameterDoc(
                name="mode", type="str", description="Mode",
                required=False, default="keyword",
                enum_values=["keyword", "semantic", "hybrid"],
            ),
            ParameterDoc(name="tags", type="list[str]", description="Tags", required=False),
            ParameterDoc(name="config", type="dict", description="Config", required=False),
            ParameterDoc(name="flag", type="bool", description="Flag", required=False, default=False),
            ParameterDoc(name="score", type="float", description="Score", required=False, default=0.5),
        ],
        returns="list",
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
    """Tests for ToolContract generation from FunctionMeta."""

    def test_basic_contract_generation(self):
        meta = _make_meta()
        contract = ContractGenerator.generate(meta)

        assert isinstance(contract, ToolContract)
        assert contract.name == "test_func"
        assert contract.description == "A test function"
        assert contract.category == "search"
        assert contract.version == "1.0.0"
        assert contract.requires_llm is False
        assert contract.tags == ["test"]

    def test_governance_fields_defaults(self):
        meta = _make_meta()
        contract = ContractGenerator.generate(meta)

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
        contract = ContractGenerator.generate(meta)

        assert contract.side_effects is True
        assert contract.is_primitive is False
        assert contract.payload_profile == "thin"
        assert contract.exposure_profile == {"procedure": True, "agent": False}

    def test_to_dict(self):
        meta = _make_meta()
        contract = ContractGenerator.generate(meta)
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
    """Tests for JSON Schema generation from parameters."""

    def test_basic_input_schema(self):
        meta = _make_meta()
        contract = ContractGenerator.generate(meta)
        schema = contract.input_schema

        assert schema["type"] == "object"
        assert "query" in schema["properties"]
        assert "limit" in schema["properties"]
        assert "query" in schema["required"]
        assert "limit" not in schema.get("required", [])

    def test_string_type(self):
        meta = _make_meta()
        contract = ContractGenerator.generate(meta)
        assert contract.input_schema["properties"]["query"]["type"] == "string"

    def test_integer_type(self):
        meta = _make_meta()
        contract = ContractGenerator.generate(meta)
        assert contract.input_schema["properties"]["limit"]["type"] == "integer"
        assert contract.input_schema["properties"]["limit"]["default"] == 10

    def test_all_types(self):
        meta = _make_meta_with_output()
        contract = ContractGenerator.generate(meta)
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
        contract = ContractGenerator.generate(meta)
        style_prop = contract.input_schema["properties"]["style"]

        assert style_prop["enum"] == ["paragraph", "bullets", "one_sentence"]

    def test_empty_params(self):
        meta = _make_meta(parameters=[])
        contract = ContractGenerator.generate(meta)

        assert contract.input_schema["type"] == "object"
        assert contract.input_schema["properties"] == {}
        assert contract.input_schema["required"] == []


class TestOutputSchema:
    """Tests for JSON Schema generation from output schema."""

    def test_no_output_schema(self):
        meta = _make_meta()
        contract = ContractGenerator.generate(meta)

        assert contract.output_schema["type"] == "object"
        assert contract.output_schema["description"] == "Function output"

    def test_dict_output_schema(self):
        meta = _make_meta_with_output()
        contract = ContractGenerator.generate(meta)

        assert contract.output_schema["type"] == "object"
        assert "properties" in contract.output_schema
        assert "category" in contract.output_schema["properties"]
        assert "confidence" in contract.output_schema["properties"]

    def test_output_variants(self):
        meta = _make_meta_with_output()
        contract = ContractGenerator.generate(meta)

        assert "variants" in contract.output_schema
        assert len(contract.output_schema["variants"]) == 1
        variant = contract.output_schema["variants"][0]
        assert "collection" in variant["description"]


# =============================================================================
# PARAMETER VALIDATION TESTS
# =============================================================================


class TestParameterValidation:
    """Tests for enhanced validate_params in BaseFunction."""

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
        with pytest.raises(ValueError, match="expects type 'str'"):
            self.func.validate_params({"query": 123})

    def test_type_check_int(self):
        with pytest.raises(ValueError, match="expects type 'int'"):
            self.func.validate_params({"query": "test", "limit": "abc"})

    def test_type_check_list(self):
        with pytest.raises(ValueError, match="expects type 'list\\[str\\]'"):
            self.func.validate_params({"query": "test", "tags": "not-a-list"})

    def test_type_check_dict(self):
        with pytest.raises(ValueError, match="expects type 'dict'"):
            self.func.validate_params({"query": "test", "config": "not-a-dict"})

    def test_type_check_bool(self):
        with pytest.raises(ValueError, match="expects type 'bool'"):
            self.func.validate_params({"query": "test", "flag": "yes"})

    def test_type_check_float(self):
        # int should be accepted for float
        result = self.func.validate_params({"query": "test", "score": 1})
        assert result["score"] == 1

    def test_type_check_float_rejects_string(self):
        with pytest.raises(ValueError, match="expects type 'float'"):
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
    """Tests for the type string to JSON Schema mapping."""

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
        schema = ContractGenerator._param_type_to_json_schema(type_str)
        assert schema["type"] == expected_type

    @pytest.mark.parametrize("type_str,expected_items_type", [
        ("list[str]", "string"),
        ("list[dict]", "object"),
        ("list[int]", "integer"),
    ])
    def test_parameterized_list_mapping(self, type_str, expected_items_type):
        schema = ContractGenerator._param_type_to_json_schema(type_str)
        assert schema["type"] == "array"
        assert schema["items"]["type"] == expected_items_type

    def test_unknown_type_defaults_to_string(self):
        schema = ContractGenerator._param_type_to_json_schema("unknown_type")
        assert schema["type"] == "string"
