# backend/app/core/metadata/validation_service.py
"""
Metadata Validation Service — validates that metadata builders, YAML field
definitions, and facet mappings are consistent with each other.

Run at startup to catch drift between what builders actually index and what
the YAML registry declares.
"""

import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("curatore.core.metadata.validation")


class MetadataValidationService:
    """
    Validates consistency between metadata builders and the YAML registry.

    Checks:
    1. Builder -> YAML field coverage (every builder field exists in fields.yaml)
    2. YAML -> Builder field coverage (every YAML field with a builder content type is declared)
    3. Facet mapping validity (facet content types have builders, referenced fields exist)
    """

    def validate_all(
        self,
        builder_registry,  # MetadataBuilderRegistry
        registry_service,  # MetadataRegistryService
    ) -> Tuple[List[str], List[str]]:
        """
        Run all validation checks.

        Returns:
            (warnings, errors) — lists of human-readable messages.
        """
        warnings: List[str] = []
        errors: List[str] = []

        # Gather builder schemas: {source_type: {namespace: [fields]}}
        builder_schemas: Dict[str, Dict[str, List[str]]] = {}
        builder_source_types: set = set()
        for builder in builder_registry.list_builders():
            builder_source_types.add(builder.source_type)
            schema = builder.get_schema()
            if schema is not None:
                builder_schemas[builder.source_type] = schema

        # Load YAML data
        all_fields = registry_service.get_all_fields()  # {ns: {field: def}}
        facet_defs = registry_service.get_facet_definitions()  # {facet: def}

        # Build reverse index: (namespace, field) -> set of applicable content types
        yaml_field_content_types: Dict[Tuple[str, str], set] = {}
        for ns, ns_fields in all_fields.items():
            for field_name, field_def in ns_fields.items():
                cts = set(field_def.get("applicable_content_types", []))
                yaml_field_content_types[(ns, field_name)] = cts

        # =====================================================================
        # Check 1: Builder -> YAML field coverage
        # Every field a builder declares should exist in fields.yaml with the
        # builder's source_type in applicable_content_types.
        # =====================================================================
        for source_type, schema in builder_schemas.items():
            for ns, fields in schema.items():
                for field_name in fields:
                    key = (ns, field_name)
                    if key not in yaml_field_content_types:
                        errors.append(
                            f"Builder '{source_type}' writes {ns}.{field_name} "
                            f"but it is not declared in fields.yaml"
                        )
                    elif source_type not in yaml_field_content_types[key]:
                        warnings.append(
                            f"Builder '{source_type}' writes {ns}.{field_name} "
                            f"but '{source_type}' is not in its applicable_content_types "
                            f"(has: {sorted(yaml_field_content_types[key])})"
                        )

        # =====================================================================
        # Check 2: YAML -> Builder field coverage
        # Every field in fields.yaml that lists a content type with a known
        # builder schema should be declared in that builder's schema.
        # =====================================================================
        for ns, ns_fields in all_fields.items():
            for field_name, field_def in ns_fields.items():
                for ct in field_def.get("applicable_content_types", []):
                    if ct not in builder_schemas:
                        # No schema for this content type (passthrough or unknown)
                        continue
                    schema = builder_schemas[ct]
                    schema_fields = schema.get(ns, [])
                    if field_name not in schema_fields:
                        warnings.append(
                            f"fields.yaml declares {ns}.{field_name} for "
                            f"content type '{ct}', but builder '{ct}' does not "
                            f"include it in get_schema()"
                        )

        # =====================================================================
        # Check 3: Facet mapping validity
        # Every content type in facet mappings should have a registered builder,
        # and the referenced namespace.field should exist in fields.yaml.
        # =====================================================================
        for facet_name, facet_def in facet_defs.items():
            for content_type, json_path in facet_def.get("mappings", {}).items():
                # Check builder exists
                if content_type not in builder_source_types:
                    warnings.append(
                        f"Facet '{facet_name}' maps content type '{content_type}' "
                        f"but no builder is registered for it"
                    )

                # Check referenced field exists
                parts = json_path.split(".", 1)
                if len(parts) != 2:
                    errors.append(
                        f"Facet '{facet_name}' mapping for '{content_type}' has "
                        f"invalid json_path '{json_path}' (expected namespace.field)"
                    )
                    continue

                ns, field_name = parts
                key = (ns, field_name)
                if key not in yaml_field_content_types:
                    errors.append(
                        f"Facet '{facet_name}' references {ns}.{field_name} for "
                        f"'{content_type}' but field is not in fields.yaml"
                    )
                elif content_type not in yaml_field_content_types[key]:
                    warnings.append(
                        f"Facet '{facet_name}' references {ns}.{field_name} for "
                        f"'{content_type}' but '{content_type}' is not in the "
                        f"field's applicable_content_types"
                    )

        return warnings, errors


# Singleton
metadata_validation_service = MetadataValidationService()
