# backend/app/cwr/contracts/tool_contracts.py
"""
Tool Contracts for the Curatore Functions Framework.

Provides formal JSON Schema-based contracts for functions, auto-generated
from FunctionMeta. Contracts include input/output schemas and governance
metadata (side effects, exposure profiles, primitive/compound classification).

Usage:
    from app.cwr.contracts.tool_contracts import ContractGenerator, ToolContract

    contract = ContractGenerator.generate(some_function.meta)
    print(contract.input_schema)  # JSON Schema dict
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..tools.base import FunctionMeta, ParameterDoc, OutputSchema, OutputVariant

logger = logging.getLogger("curatore.functions.contracts")

# Mapping from FunctionMeta type strings to JSON Schema types
_TYPE_MAP: Dict[str, Dict[str, Any]] = {
    "str": {"type": "string"},
    "string": {"type": "string"},
    "int": {"type": "integer"},
    "integer": {"type": "integer"},
    "float": {"type": "number"},
    "number": {"type": "number"},
    "bool": {"type": "boolean"},
    "boolean": {"type": "boolean"},
    "list": {"type": "array"},
    "list[str]": {"type": "array", "items": {"type": "string"}},
    "list[string]": {"type": "array", "items": {"type": "string"}},
    "list[int]": {"type": "array", "items": {"type": "integer"}},
    "list[dict]": {"type": "array", "items": {"type": "object"}},
    "list[object]": {"type": "array", "items": {"type": "object"}},
    "dict": {"type": "object"},
    "object": {"type": "object"},
    "any": {},
}


@dataclass
class ToolContract:
    """
    Formal contract for a Curatore function.

    Provides JSON Schema input/output definitions and governance metadata.
    """
    name: str
    description: str
    category: str
    version: str
    input_schema: Dict[str, Any]
    output_schema: Dict[str, Any]
    side_effects: bool
    is_primitive: bool
    payload_profile: str
    exposure_profile: Dict[str, Any]
    requires_llm: bool
    requires_session: bool
    tags: List[str]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "version": self.version,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "side_effects": self.side_effects,
            "is_primitive": self.is_primitive,
            "payload_profile": self.payload_profile,
            "exposure_profile": self.exposure_profile,
            "requires_llm": self.requires_llm,
            "requires_session": self.requires_session,
            "tags": self.tags,
        }


class ContractGenerator:
    """Generates ToolContract instances from FunctionMeta."""

    @staticmethod
    def generate(meta: FunctionMeta) -> ToolContract:
        """
        Generate a ToolContract from a FunctionMeta instance.

        Args:
            meta: FunctionMeta to convert

        Returns:
            ToolContract with JSON Schema input/output
        """
        input_schema = ContractGenerator._params_to_json_schema(meta.parameters)
        output_schema = ContractGenerator._output_to_json_schema(
            meta.output_schema, meta.output_variants
        )

        return ToolContract(
            name=meta.name,
            description=meta.description,
            category=meta.category.value,
            version=meta.version,
            input_schema=input_schema,
            output_schema=output_schema,
            side_effects=meta.side_effects,
            is_primitive=meta.is_primitive,
            payload_profile=meta.payload_profile,
            exposure_profile=meta.exposure_profile,
            requires_llm=meta.requires_llm,
            requires_session=meta.requires_session,
            tags=list(meta.tags),
        )

    @staticmethod
    def _param_type_to_json_schema(type_str: str) -> Dict[str, Any]:
        """
        Convert a FunctionMeta type string to a JSON Schema type definition.

        Args:
            type_str: Type string (e.g., "str", "list[str]", "dict")

        Returns:
            JSON Schema type definition dict
        """
        normalized = type_str.strip().lower()
        return dict(_TYPE_MAP.get(normalized, {"type": "string"}))

    @staticmethod
    def _params_to_json_schema(params: List[ParameterDoc]) -> Dict[str, Any]:
        """
        Convert a list of ParameterDoc to a JSON Schema object.

        Args:
            params: List of parameter documentation

        Returns:
            JSON Schema dict describing the input object
        """
        if not params:
            return {"type": "object", "properties": {}, "required": []}

        properties: Dict[str, Any] = {}
        required: List[str] = []

        for p in params:
            prop = ContractGenerator._param_type_to_json_schema(p.type)
            prop["description"] = p.description

            if p.default is not None:
                prop["default"] = p.default

            if p.enum_values:
                prop["enum"] = p.enum_values

            if p.example is not None:
                prop["examples"] = [p.example]

            properties[p.name] = prop

            if p.required:
                required.append(p.name)

        schema: Dict[str, Any] = {
            "type": "object",
            "properties": properties,
        }
        if required:
            schema["required"] = required

        return schema

    @staticmethod
    def _output_to_json_schema(
        schema: Optional[OutputSchema],
        variants: Optional[List[OutputVariant]] = None,
    ) -> Dict[str, Any]:
        """
        Convert OutputSchema and OutputVariant list to a JSON Schema.

        Args:
            schema: Primary output schema
            variants: Optional output variants for multi-mode functions

        Returns:
            JSON Schema dict describing the output
        """
        if not schema:
            return {"type": "object", "description": "Function output"}

        result = ContractGenerator._param_type_to_json_schema(schema.type)
        result["description"] = schema.description

        # Add field definitions for object/dict types
        if schema.fields and result.get("type") == "object":
            properties = {}
            for f in schema.fields:
                fprop = ContractGenerator._param_type_to_json_schema(f.type)
                fprop["description"] = f.description
                if f.example is not None:
                    fprop["examples"] = [f.example]
                if f.nullable:
                    fprop["nullable"] = True
                properties[f.name] = fprop
            result["properties"] = properties

        # Add field definitions for array types with object items
        if schema.fields and result.get("type") == "array":
            item_properties = {}
            for f in schema.fields:
                fprop = ContractGenerator._param_type_to_json_schema(f.type)
                fprop["description"] = f.description
                if f.example is not None:
                    fprop["examples"] = [f.example]
                if f.nullable:
                    fprop["nullable"] = True
                item_properties[f.name] = fprop
            result["items"] = {"type": "object", "properties": item_properties}

        if schema.example is not None:
            result["examples"] = [schema.example]

        # Add variants as oneOf if present
        if variants:
            variant_schemas = []
            for v in variants:
                vs = ContractGenerator._param_type_to_json_schema(v.schema.type)
                vs["description"] = f"{v.mode}: {v.condition}"
                if v.schema.fields:
                    if vs.get("type") == "object":
                        vprops = {}
                        for f in v.schema.fields:
                            fprop = ContractGenerator._param_type_to_json_schema(f.type)
                            fprop["description"] = f.description
                            vprops[f.name] = fprop
                        vs["properties"] = vprops
                    elif vs.get("type") == "array" and v.schema.fields:
                        vprops = {}
                        for f in v.schema.fields:
                            fprop = ContractGenerator._param_type_to_json_schema(f.type)
                            fprop["description"] = f.description
                            vprops[f.name] = fprop
                        vs["items"] = {"type": "object", "properties": vprops}
                variant_schemas.append(vs)
            result["variants"] = variant_schemas

        return result
