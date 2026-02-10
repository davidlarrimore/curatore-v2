# backend/app/core/metadata/registry_service.py
"""
Metadata Registry Service — loads, caches, and resolves metadata field and facet
definitions from the YAML baseline and database overrides.

The effective registry for an organization merges the global baseline
(organization_id=NULL) with any org-level overrides from the database.

Usage:
    from app.core.metadata.registry_service import metadata_registry_service

    # Load baseline at app startup
    await metadata_registry_service.load_baseline(session)

    # Resolve facet for search
    paths = metadata_registry_service.resolve_facet(org_id, "agency", ["sam_notice"])
"""

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

import yaml
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("curatore.core.metadata.registry")

# Path to YAML baseline files
_REGISTRY_DIR = Path(__file__).parent / "registry"


class MetadataRegistryService:
    """
    Singleton service for metadata field and facet governance.

    Provides:
    - YAML baseline loading and DB seeding
    - Effective registry resolution (global + org overrides)
    - Facet-to-JSON-path resolution for search queries
    - In-memory cache with TTL
    """

    CACHE_TTL = 300  # 5 minutes

    def __init__(self):
        self._namespaces: Dict[str, Dict[str, Any]] = {}
        self._fields: Dict[str, Dict[str, Dict[str, Any]]] = {}  # ns → field → def
        self._facets: Dict[str, Dict[str, Any]] = {}
        self._data_sources: Dict[str, Dict[str, Any]] = {}  # source_type → definition
        self._loaded = False

        # Cache: org_id → (timestamp, effective_registry)
        self._cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        # Separate cache for data source catalog: org_id → (timestamp, catalog)
        self._ds_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}

    # =========================================================================
    # YAML Loading
    # =========================================================================

    def _load_yaml(self) -> None:
        """Parse YAML baseline files into memory."""
        # Namespaces
        ns_path = _REGISTRY_DIR / "namespaces.yaml"
        if ns_path.exists():
            with open(ns_path) as f:
                data = yaml.safe_load(f)
            self._namespaces = data.get("namespaces", {})

        # Fields
        fields_path = _REGISTRY_DIR / "fields.yaml"
        if fields_path.exists():
            with open(fields_path) as f:
                data = yaml.safe_load(f)
            self._fields = data.get("fields", {})

        # Facets
        facets_path = _REGISTRY_DIR / "facets.yaml"
        if facets_path.exists():
            with open(facets_path) as f:
                data = yaml.safe_load(f)
            self._facets = data.get("facets", {})

        # Data sources
        ds_path = _REGISTRY_DIR / "data_sources.yaml"
        if ds_path.exists():
            with open(ds_path) as f:
                data = yaml.safe_load(f)
            self._data_sources = data.get("source_types", {})

        self._loaded = True
        logger.info(
            f"Loaded metadata registry: {len(self._namespaces)} namespaces, "
            f"{sum(len(v) for v in self._fields.values())} fields, "
            f"{len(self._facets)} facets, "
            f"{len(self._data_sources)} data source types"
        )

    def _ensure_loaded(self) -> None:
        """Ensure YAML baseline is loaded."""
        if not self._loaded:
            self._load_yaml()

    # =========================================================================
    # DB Seeding
    # =========================================================================

    async def load_baseline(self, session: AsyncSession) -> Dict[str, int]:
        """
        Sync YAML baseline to DB by deleting all global records and re-inserting.

        This keeps the DB perfectly in sync with YAML on every startup.
        Org-level overrides (non-NULL organization_id) are untouched.

        Returns dict with counts of synced records.
        """
        self._ensure_loaded()

        from ..database.models import (
            FacetDefinition,
            FacetMapping,
            MetadataFieldDefinition,
        )

        counts = {"fields": 0, "facets": 0, "mappings": 0}

        # Delete all global baseline records (org_id IS NULL).
        # FacetMapping cascades from FacetDefinition via FK ondelete=CASCADE.
        await session.execute(
            text("DELETE FROM facet_definitions WHERE organization_id IS NULL")
        )
        await session.execute(
            text("DELETE FROM metadata_field_definitions WHERE organization_id IS NULL")
        )
        await session.flush()

        # Re-insert field definitions from YAML
        for ns, ns_fields in self._fields.items():
            for field_name, field_def in ns_fields.items():
                record = MetadataFieldDefinition(
                    organization_id=None,
                    namespace=ns,
                    field_name=field_name,
                    data_type=field_def.get("data_type", "string"),
                    indexed=field_def.get("indexed", True),
                    facetable=field_def.get("facetable", False),
                    applicable_content_types=field_def.get("applicable_content_types", []),
                    description=field_def.get("description"),
                    examples=field_def.get("examples"),
                )
                session.add(record)
                counts["fields"] += 1

        # Re-insert facet definitions + mappings from YAML
        for facet_name, facet_def in self._facets.items():
            facet_record = FacetDefinition(
                organization_id=None,
                facet_name=facet_name,
                display_name=facet_def.get("display_name", facet_name),
                data_type=facet_def.get("data_type", "string"),
                description=facet_def.get("description"),
                operators=facet_def.get("operators", ["eq", "in"]),
            )
            session.add(facet_record)
            await session.flush()  # Get the ID
            counts["facets"] += 1

            for content_type, json_path in facet_def.get("mappings", {}).items():
                mapping = FacetMapping(
                    facet_definition_id=facet_record.id,
                    content_type=content_type,
                    json_path=json_path,
                )
                session.add(mapping)
                counts["mappings"] += 1

        await session.flush()

        # Clear caches so in-memory state reflects new DB state
        self.invalidate_cache()

        logger.info(f"Registry baseline synced: {counts}")
        return counts

    # =========================================================================
    # Effective Registry
    # =========================================================================

    def get_namespaces(self) -> Dict[str, Dict[str, Any]]:
        """Return all namespace definitions from YAML baseline."""
        self._ensure_loaded()
        return dict(self._namespaces)

    def get_namespace_fields(self, namespace: str) -> Dict[str, Dict[str, Any]]:
        """Return field definitions for a namespace from YAML baseline."""
        self._ensure_loaded()
        return dict(self._fields.get(namespace, {}))

    def get_all_fields(self) -> Dict[str, Dict[str, Dict[str, Any]]]:
        """Return all field definitions grouped by namespace."""
        self._ensure_loaded()
        return {ns: dict(fields) for ns, fields in self._fields.items()}

    def get_facet_definitions(self) -> Dict[str, Dict[str, Any]]:
        """Return all facet definitions from YAML baseline."""
        self._ensure_loaded()
        return dict(self._facets)

    async def get_effective_registry(
        self,
        session: AsyncSession,
        organization_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        """
        Return the complete effective registry for an organization.

        Merges global baseline (org_id=NULL) with org-level overrides.
        Results are cached for CACHE_TTL seconds.
        """
        self._ensure_loaded()

        cache_key = str(organization_id) if organization_id else "__global__"
        now = time.time()

        if cache_key in self._cache:
            cached_at, cached_registry = self._cache[cache_key]
            if now - cached_at < self.CACHE_TTL:
                return cached_registry

        registry = await self._build_effective_registry(session, organization_id)
        self._cache[cache_key] = (now, registry)
        return registry

    async def _build_effective_registry(
        self,
        session: AsyncSession,
        organization_id: Optional[UUID],
    ) -> Dict[str, Any]:
        """Build effective registry by merging global + org overrides."""
        from ..database.models import (
            FacetDefinition,
            FacetMapping,
            MetadataFieldDefinition,
        )

        # Start with YAML baseline
        namespaces = dict(self._namespaces)
        fields: Dict[str, Dict[str, Dict[str, Any]]] = {
            ns: dict(ns_fields) for ns, ns_fields in self._fields.items()
        }
        facets = dict(self._facets)

        if organization_id is None:
            return {
                "namespaces": namespaces,
                "fields": fields,
                "facets": facets,
            }

        # Load org-level field overrides from DB
        org_fields_q = select(MetadataFieldDefinition).where(
            MetadataFieldDefinition.organization_id == organization_id,
            MetadataFieldDefinition.status == "active",
        )
        result = await session.execute(org_fields_q)
        for record in result.scalars():
            ns = record.namespace
            if ns not in fields:
                fields[ns] = {}
            fields[ns][record.field_name] = {
                "data_type": record.data_type,
                "indexed": record.indexed,
                "facetable": record.facetable,
                "applicable_content_types": record.applicable_content_types or [],
                "description": record.description,
                "examples": record.examples,
                "sensitivity_tag": record.sensitivity_tag,
            }

        # Load org-level facet overrides from DB
        org_facets_q = (
            select(FacetDefinition)
            .where(
                FacetDefinition.organization_id == organization_id,
                FacetDefinition.status == "active",
            )
        )
        result = await session.execute(org_facets_q)
        for facet_record in result.scalars():
            mappings_q = select(FacetMapping).where(
                FacetMapping.facet_definition_id == facet_record.id
            )
            mappings_result = await session.execute(mappings_q)
            mapping_dict = {
                m.content_type: m.json_path for m in mappings_result.scalars()
            }

            facets[facet_record.facet_name] = {
                "display_name": facet_record.display_name,
                "data_type": facet_record.data_type,
                "description": facet_record.description,
                "operators": facet_record.operators or ["eq", "in"],
                "mappings": mapping_dict,
            }

        return {
            "namespaces": namespaces,
            "fields": fields,
            "facets": facets,
        }

    # =========================================================================
    # Facet Resolution
    # =========================================================================

    def resolve_facet(
        self,
        facet_name: str,
        content_types: Optional[List[str]] = None,
    ) -> Dict[str, str]:
        """
        Resolve a facet to its JSON paths across content types.

        Args:
            facet_name: The facet name (e.g., "agency")
            content_types: Optional filter for specific content types

        Returns:
            Dict mapping content_type → json_path (e.g., {"sam_notice": "sam.agency"})
        """
        self._ensure_loaded()

        facet_def = self._facets.get(facet_name)
        if not facet_def:
            return {}

        mappings = facet_def.get("mappings", {})
        if content_types:
            return {ct: jp for ct, jp in mappings.items() if ct in content_types}
        return dict(mappings)

    def resolve_facet_operators(self, facet_name: str) -> List[str]:
        """Return supported operators for a facet."""
        self._ensure_loaded()
        facet_def = self._facets.get(facet_name)
        if not facet_def:
            return []
        return facet_def.get("operators", ["eq", "in"])

    def get_all_content_types_for_facets(
        self, facet_names: List[str]
    ) -> List[str]:
        """Return all content types referenced by the given facets."""
        self._ensure_loaded()
        content_types = set()
        for fname in facet_names:
            facet_def = self._facets.get(fname, {})
            for ct in facet_def.get("mappings", {}).keys():
                content_types.add(ct)
        return list(content_types)

    # =========================================================================
    # Namespace ↔ Source Type Mapping
    # =========================================================================

    def get_namespace_source_types(self) -> Dict[str, List[str]]:
        """
        Build namespace → source_types mapping from field definitions.

        Derived from applicable_content_types across all fields in a namespace.
        """
        self._ensure_loaded()
        ns_types: Dict[str, set] = {}
        for ns, ns_fields in self._fields.items():
            types = set()
            for field_def in ns_fields.values():
                for ct in field_def.get("applicable_content_types", []):
                    types.add(ct)
            ns_types[ns] = types

        return {ns: sorted(types) for ns, types in ns_types.items()}

    def get_filterable_fields(self) -> Dict[str, List[str]]:
        """
        Build namespace → filterable field names mapping.

        Derived from fields with facetable=true.
        """
        self._ensure_loaded()
        result: Dict[str, List[str]] = {}
        for ns, ns_fields in self._fields.items():
            facetable = [
                fname for fname, fdef in ns_fields.items()
                if fdef.get("facetable", False)
            ]
            if facetable:
                result[ns] = facetable
        return result

    # =========================================================================
    # Write Operations (Org-Level Overrides)
    # =========================================================================

    VALID_DATA_TYPES = {"string", "number", "boolean", "date", "enum", "array", "object"}

    async def create_field(
        self,
        session: AsyncSession,
        organization_id: UUID,
        namespace: str,
        field_name: str,
        data_type: str,
        indexed: bool = True,
        facetable: bool = False,
        applicable_content_types: Optional[List[str]] = None,
        description: Optional[str] = None,
        examples: Optional[list] = None,
        sensitivity_tag: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create an org-level field definition override."""
        from ..database.models import MetadataFieldDefinition

        self._ensure_loaded()

        # Validate namespace exists in baseline
        if namespace not in self._namespaces:
            raise ValueError(f"Namespace '{namespace}' not found in global baseline")

        if data_type not in self.VALID_DATA_TYPES:
            raise ValueError(f"Invalid data_type '{data_type}'. Must be one of: {self.VALID_DATA_TYPES}")

        record = MetadataFieldDefinition(
            organization_id=organization_id,
            namespace=namespace,
            field_name=field_name,
            data_type=data_type,
            indexed=indexed,
            facetable=facetable,
            applicable_content_types=applicable_content_types or [],
            description=description,
            examples=examples,
            sensitivity_tag=sensitivity_tag,
        )
        session.add(record)
        await session.flush()
        self.invalidate_cache(organization_id)

        return {
            "id": str(record.id),
            "namespace": namespace,
            "field_name": field_name,
            "data_type": data_type,
        }

    async def update_field(
        self,
        session: AsyncSession,
        organization_id: UUID,
        namespace: str,
        field_name: str,
        updates: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Update an org-level field definition."""
        from ..database.models import MetadataFieldDefinition

        query = select(MetadataFieldDefinition).where(
            MetadataFieldDefinition.organization_id == organization_id,
            MetadataFieldDefinition.namespace == namespace,
            MetadataFieldDefinition.field_name == field_name,
        )
        result = await session.execute(query)
        record = result.scalar_one_or_none()
        if not record:
            raise ValueError(f"Org-level field '{namespace}.{field_name}' not found")

        allowed_fields = {"indexed", "facetable", "applicable_content_types", "description", "examples", "sensitivity_tag", "status"}
        for key, value in updates.items():
            if key in allowed_fields and value is not None:
                setattr(record, key, value)

        await session.flush()
        self.invalidate_cache(organization_id)

        return {"namespace": namespace, "field_name": field_name, "updated": True}

    async def deactivate_field(
        self,
        session: AsyncSession,
        organization_id: UUID,
        namespace: str,
        field_name: str,
    ) -> Dict[str, Any]:
        """Soft-delete an org-level field definition."""
        from ..database.models import MetadataFieldDefinition

        query = select(MetadataFieldDefinition).where(
            MetadataFieldDefinition.organization_id == organization_id,
            MetadataFieldDefinition.namespace == namespace,
            MetadataFieldDefinition.field_name == field_name,
        )
        result = await session.execute(query)
        record = result.scalar_one_or_none()
        if not record:
            raise ValueError(f"Org-level field '{namespace}.{field_name}' not found")

        record.status = "inactive"
        await session.flush()
        self.invalidate_cache(organization_id)

        return {"namespace": namespace, "field_name": field_name, "status": "inactive"}

    async def create_facet(
        self,
        session: AsyncSession,
        organization_id: UUID,
        facet_name: str,
        display_name: str,
        data_type: str,
        description: Optional[str] = None,
        operators: Optional[List[str]] = None,
        mappings: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """Create an org-level facet definition with optional mappings."""
        from ..database.models import FacetDefinition, FacetMapping

        if data_type not in self.VALID_DATA_TYPES:
            raise ValueError(f"Invalid data_type '{data_type}'. Must be one of: {self.VALID_DATA_TYPES}")

        facet_record = FacetDefinition(
            organization_id=organization_id,
            facet_name=facet_name,
            display_name=display_name,
            data_type=data_type,
            description=description,
            operators=operators or ["eq", "in"],
        )
        session.add(facet_record)
        await session.flush()

        # Add mappings
        mapping_count = 0
        for m in (mappings or []):
            mapping = FacetMapping(
                facet_definition_id=facet_record.id,
                content_type=m["content_type"],
                json_path=m["json_path"],
            )
            session.add(mapping)
            mapping_count += 1

        await session.flush()
        self.invalidate_cache(organization_id)

        return {
            "id": str(facet_record.id),
            "facet_name": facet_name,
            "mappings_created": mapping_count,
        }

    async def update_facet(
        self,
        session: AsyncSession,
        organization_id: UUID,
        facet_name: str,
        updates: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Update an org-level facet definition."""
        from ..database.models import FacetDefinition

        query = select(FacetDefinition).where(
            FacetDefinition.organization_id == organization_id,
            FacetDefinition.facet_name == facet_name,
        )
        result = await session.execute(query)
        record = result.scalar_one_or_none()
        if not record:
            raise ValueError(f"Org-level facet '{facet_name}' not found")

        allowed_fields = {"display_name", "description", "operators", "status"}
        for key, value in updates.items():
            if key in allowed_fields and value is not None:
                setattr(record, key, value)

        await session.flush()
        self.invalidate_cache(organization_id)

        return {"facet_name": facet_name, "updated": True}

    async def deactivate_facet(
        self,
        session: AsyncSession,
        organization_id: UUID,
        facet_name: str,
    ) -> Dict[str, Any]:
        """Soft-delete an org-level facet definition."""
        from ..database.models import FacetDefinition

        query = select(FacetDefinition).where(
            FacetDefinition.organization_id == organization_id,
            FacetDefinition.facet_name == facet_name,
        )
        result = await session.execute(query)
        record = result.scalar_one_or_none()
        if not record:
            raise ValueError(f"Org-level facet '{facet_name}' not found")

        record.status = "inactive"
        await session.flush()
        self.invalidate_cache(organization_id)

        return {"facet_name": facet_name, "status": "inactive"}

    async def add_facet_mapping(
        self,
        session: AsyncSession,
        organization_id: UUID,
        facet_name: str,
        content_type: str,
        json_path: str,
    ) -> Dict[str, Any]:
        """Add a content type mapping to an org-level facet."""
        from ..database.models import FacetDefinition, FacetMapping

        query = select(FacetDefinition).where(
            FacetDefinition.organization_id == organization_id,
            FacetDefinition.facet_name == facet_name,
        )
        result = await session.execute(query)
        facet_record = result.scalar_one_or_none()
        if not facet_record:
            raise ValueError(f"Org-level facet '{facet_name}' not found")

        mapping = FacetMapping(
            facet_definition_id=facet_record.id,
            content_type=content_type,
            json_path=json_path,
        )
        session.add(mapping)
        await session.flush()
        self.invalidate_cache(organization_id)

        return {"facet_name": facet_name, "content_type": content_type, "json_path": json_path}

    async def remove_facet_mapping(
        self,
        session: AsyncSession,
        organization_id: UUID,
        facet_name: str,
        content_type: str,
    ) -> Dict[str, Any]:
        """Remove a content type mapping from an org-level facet."""
        from ..database.models import FacetDefinition, FacetMapping

        query = select(FacetDefinition).where(
            FacetDefinition.organization_id == organization_id,
            FacetDefinition.facet_name == facet_name,
        )
        result = await session.execute(query)
        facet_record = result.scalar_one_or_none()
        if not facet_record:
            raise ValueError(f"Org-level facet '{facet_name}' not found")

        mapping_query = select(FacetMapping).where(
            FacetMapping.facet_definition_id == facet_record.id,
            FacetMapping.content_type == content_type,
        )
        mapping_result = await session.execute(mapping_query)
        mapping = mapping_result.scalar_one_or_none()
        if not mapping:
            raise ValueError(f"Mapping for content_type '{content_type}' not found on facet '{facet_name}'")

        await session.delete(mapping)
        await session.flush()
        self.invalidate_cache(organization_id)

        return {"facet_name": facet_name, "content_type": content_type, "removed": True}

    # =========================================================================
    # Data Source Type Registry
    # =========================================================================

    def get_data_source_types(self) -> Dict[str, Dict[str, Any]]:
        """Return all data source type definitions from YAML baseline."""
        self._ensure_loaded()
        return {k: dict(v) for k, v in self._data_sources.items()}

    def get_data_source_type(self, source_type: str) -> Optional[Dict[str, Any]]:
        """Return a single data source type definition."""
        self._ensure_loaded()
        defn = self._data_sources.get(source_type)
        return dict(defn) if defn else None

    async def get_data_source_catalog(
        self,
        session: AsyncSession,
        organization_id: Optional[UUID] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Return the effective data source catalog for an organization.

        Merges YAML baseline with org-level overrides from DB.
        Cached for CACHE_TTL seconds.
        """
        self._ensure_loaded()

        cache_key = f"ds_{organization_id}" if organization_id else "ds___global__"
        now = time.time()

        if cache_key in self._ds_cache:
            cached_at, cached_catalog = self._ds_cache[cache_key]
            if now - cached_at < self.CACHE_TTL:
                return cached_catalog

        catalog = await self._build_data_source_catalog(session, organization_id)
        self._ds_cache[cache_key] = (now, catalog)
        return catalog

    async def _build_data_source_catalog(
        self,
        session: AsyncSession,
        organization_id: Optional[UUID],
    ) -> Dict[str, Dict[str, Any]]:
        """Build effective data source catalog by merging baseline + org overrides."""
        from ..database.models import DataSourceTypeOverride

        # Start with YAML baseline (deep copy)
        catalog = {}
        for key, defn in self._data_sources.items():
            catalog[key] = dict(defn)
            # Deep copy lists to avoid mutating YAML
            for list_field in ("data_contains", "capabilities", "example_questions", "search_tools"):
                if list_field in catalog[key]:
                    catalog[key][list_field] = list(catalog[key][list_field])

        if organization_id is None:
            return catalog

        # Load org-level overrides
        try:
            result = await session.execute(
                select(DataSourceTypeOverride).where(
                    DataSourceTypeOverride.organization_id == organization_id
                )
            )
            for override in result.scalars():
                key = override.source_type
                if key not in catalog:
                    continue

                # Apply non-null overrides
                if override.display_name:
                    catalog[key]["display_name"] = override.display_name
                if override.description:
                    catalog[key]["description"] = override.description
                if override.capabilities:
                    catalog[key]["capabilities"] = override.capabilities
                if not override.is_active:
                    catalog[key]["is_active"] = False
        except Exception as e:
            logger.warning(f"Failed to load data source overrides: {e}")

        return catalog

    async def upsert_data_source_override(
        self,
        session: AsyncSession,
        organization_id: UUID,
        source_type: str,
        display_name: Optional[str] = None,
        description: Optional[str] = None,
        capabilities: Optional[List[str]] = None,
        is_active: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Create or update an org-level data source type override."""
        from ..database.models import DataSourceTypeOverride

        self._ensure_loaded()

        if source_type not in self._data_sources:
            raise ValueError(f"Unknown source_type '{source_type}'. Must be one of: {list(self._data_sources.keys())}")

        # Look for existing override
        result = await session.execute(
            select(DataSourceTypeOverride).where(
                DataSourceTypeOverride.organization_id == organization_id,
                DataSourceTypeOverride.source_type == source_type,
            )
        )
        record = result.scalar_one_or_none()

        if record:
            if display_name is not None:
                record.display_name = display_name
            if description is not None:
                record.description = description
            if capabilities is not None:
                record.capabilities = capabilities
            if is_active is not None:
                record.is_active = is_active
        else:
            record = DataSourceTypeOverride(
                organization_id=organization_id,
                source_type=source_type,
                display_name=display_name,
                description=description,
                capabilities=capabilities,
                is_active=is_active if is_active is not None else True,
            )
            session.add(record)

        await session.flush()
        self._ds_cache.pop(f"ds_{organization_id}", None)

        return {
            "source_type": source_type,
            "display_name": record.display_name,
            "description": record.description,
            "capabilities": record.capabilities,
            "is_active": record.is_active,
        }

    # =========================================================================
    # Cache Management
    # =========================================================================

    def invalidate_cache(self, organization_id: Optional[UUID] = None) -> None:
        """Clear cached effective registry for an organization (or all)."""
        if organization_id is None:
            self._cache.clear()
            self._ds_cache.clear()
        else:
            self._cache.pop(str(organization_id), None)
            self._ds_cache.pop(f"ds_{organization_id}", None)

    def reload_yaml(self) -> None:
        """Force-reload YAML baseline files and clear all caches."""
        self._loaded = False
        self._cache.clear()
        self._ds_cache.clear()
        self._load_yaml()


# Singleton
metadata_registry_service = MetadataRegistryService()
