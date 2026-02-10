# backend/app/api/v1/routers/metadata.py
"""
Metadata Governance API Router.

Provides endpoints for browsing the metadata catalog: namespaces, field
definitions, facets, and field statistics.

Registered at /api/v1/data/metadata/ to begin the /data namespace migration.
"""

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text

from app.core.database.models import User
from app.dependencies import get_current_user
from app.core.shared.database_service import database_service
from app.core.search.pg_search_service import pg_search_service
from app.core.metadata.registry_service import metadata_registry_service
from app.api.v1.data.schemas import (
    DataSourceTypeResponse,
    DataSourceTypeUpdateRequest,
    FacetAutocompleteResponse,
    FacetCreateRequest,
    FacetDefinitionResponse,
    FacetDiscoverResponse,
    FacetMappingCreateRequest,
    FacetMappingResponse,
    FacetPendingSuggestionsResponse,
    FacetReferenceAliasCreateRequest,
    FacetReferenceValueCreateRequest,
    FacetReferenceValueResponse,
    FacetReferenceValueUpdateRequest,
    FacetUpdateRequest,
    MetadataCatalogResponse,
    MetadataFieldCreateRequest,
    MetadataFieldDefinitionResponse,
    MetadataFieldStatsResponse,
    MetadataFieldUpdateRequest,
    MetadataNamespaceResponse,
)
from app.core.metadata.facet_reference_service import facet_reference_service

logger = logging.getLogger("curatore.api.metadata")

router = APIRouter(prefix="/metadata", tags=["metadata"])


@router.get("/catalog", response_model=MetadataCatalogResponse)
async def get_catalog(current_user: User = Depends(get_current_user)):
    """
    Get the full metadata catalog: all namespaces, fields, and facets.

    Returns the complete governance catalog for the current organization,
    merging global baseline with any org-level overrides.
    """
    org_id = current_user.organization_id

    # Get namespace doc counts (lightweight — no sample value queries)
    async with database_service.get_session() as session:
        doc_counts = await pg_search_service.get_doc_counts(session, org_id)

    registry_namespaces = metadata_registry_service.get_namespaces()
    registry_fields = metadata_registry_service.get_all_fields()
    registry_facets = metadata_registry_service.get_facet_definitions()

    schema_namespaces = doc_counts.get("namespaces", {})

    # Build namespace responses
    ns_responses = []
    for ns_key, ns_def in registry_namespaces.items():
        ns_schema = schema_namespaces.get(ns_key, {})
        ns_fields = registry_fields.get(ns_key, {})

        field_responses = [
            MetadataFieldDefinitionResponse(
                namespace=ns_key,
                field_name=fname,
                data_type=fdef.get("data_type", "string"),
                indexed=fdef.get("indexed", True),
                facetable=fdef.get("facetable", False),
                applicable_content_types=fdef.get("applicable_content_types", []),
                description=fdef.get("description"),
                examples=fdef.get("examples"),
            )
            for fname, fdef in ns_fields.items()
        ]

        ns_responses.append(MetadataNamespaceResponse(
            namespace=ns_key,
            display_name=ns_def.get("display_name", ns_key),
            description=ns_def.get("description"),
            fields=field_responses,
            doc_count=ns_schema.get("doc_count", 0),
        ))

    # Build facet responses
    facet_responses = []
    for facet_name, facet_def in registry_facets.items():
        mappings = [
            FacetMappingResponse(content_type=ct, json_path=jp)
            for ct, jp in facet_def.get("mappings", {}).items()
        ]
        facet_responses.append(FacetDefinitionResponse(
            facet_name=facet_name,
            display_name=facet_def.get("display_name", facet_name),
            data_type=facet_def.get("data_type", "string"),
            description=facet_def.get("description"),
            operators=facet_def.get("operators", ["eq", "in"]),
            mappings=mappings,
        ))

    return MetadataCatalogResponse(
        namespaces=ns_responses,
        facets=facet_responses,
        total_indexed_docs=doc_counts.get("total_indexed_docs", 0),
    )


@router.get("/namespaces", response_model=List[MetadataNamespaceResponse])
async def list_namespaces(current_user: User = Depends(get_current_user)):
    """List all metadata namespaces with document counts."""
    org_id = current_user.organization_id

    async with database_service.get_session() as session:
        doc_counts = await pg_search_service.get_doc_counts(session, org_id)

    registry_namespaces = metadata_registry_service.get_namespaces()
    schema_namespaces = doc_counts.get("namespaces", {})

    return [
        MetadataNamespaceResponse(
            namespace=ns_key,
            display_name=ns_def.get("display_name", ns_key),
            description=ns_def.get("description"),
            doc_count=schema_namespaces.get(ns_key, {}).get("doc_count", 0),
        )
        for ns_key, ns_def in registry_namespaces.items()
    ]


@router.get("/namespaces/{namespace}/fields", response_model=List[MetadataFieldDefinitionResponse])
async def get_namespace_fields(
    namespace: str,
    current_user: User = Depends(get_current_user),
):
    """Get all field definitions for a namespace."""
    ns_fields = metadata_registry_service.get_namespace_fields(namespace)
    if not ns_fields:
        raise HTTPException(status_code=404, detail=f"Namespace '{namespace}' not found")

    return [
        MetadataFieldDefinitionResponse(
            namespace=namespace,
            field_name=fname,
            data_type=fdef.get("data_type", "string"),
            indexed=fdef.get("indexed", True),
            facetable=fdef.get("facetable", False),
            applicable_content_types=fdef.get("applicable_content_types", []),
            description=fdef.get("description"),
            examples=fdef.get("examples"),
        )
        for fname, fdef in ns_fields.items()
    ]


@router.get("/fields/{namespace}/{field_name}", response_model=MetadataFieldDefinitionResponse)
async def get_field_detail(
    namespace: str,
    field_name: str,
    current_user: User = Depends(get_current_user),
):
    """Get a single field definition."""
    ns_fields = metadata_registry_service.get_namespace_fields(namespace)
    field_def = ns_fields.get(field_name)
    if not field_def:
        raise HTTPException(status_code=404, detail=f"Field '{namespace}.{field_name}' not found")

    return MetadataFieldDefinitionResponse(
        namespace=namespace,
        field_name=field_name,
        data_type=field_def.get("data_type", "string"),
        indexed=field_def.get("indexed", True),
        facetable=field_def.get("facetable", False),
        applicable_content_types=field_def.get("applicable_content_types", []),
        description=field_def.get("description"),
        examples=field_def.get("examples"),
    )


@router.get("/fields/{namespace}/{field_name}/stats", response_model=MetadataFieldStatsResponse)
async def get_field_stats(
    namespace: str,
    field_name: str,
    current_user: User = Depends(get_current_user),
):
    """Get sample values and statistics for a metadata field."""
    org_id = current_user.organization_id
    ns_source_types = metadata_registry_service.get_namespace_source_types().get(namespace, [])

    async with database_service.get_session() as session:
        # Get sample values
        sample_values = await pg_search_service._get_sample_values(
            session, str(org_id), namespace, field_name, ns_source_types, 50
        )

        # Get doc count for this field
        count_sql = text("""
            SELECT COUNT(DISTINCT source_id) as doc_count
            FROM search_chunks
            WHERE organization_id = :org_id
              AND source_type = ANY(:source_types)
              AND metadata->:namespace->>:field IS NOT NULL
        """)
        result = await session.execute(count_sql, {
            "org_id": str(org_id),
            "source_types": ns_source_types,
            "namespace": namespace,
            "field": field_name,
        })
        doc_count = result.scalar() or 0

    return MetadataFieldStatsResponse(
        namespace=namespace,
        field_name=field_name,
        sample_values=sample_values,
        doc_count=doc_count,
    )


@router.get("/facets", response_model=List[FacetDefinitionResponse])
async def list_facets(current_user: User = Depends(get_current_user)):
    """List all facet definitions with their cross-domain mappings."""
    registry_facets = metadata_registry_service.get_facet_definitions()

    return [
        FacetDefinitionResponse(
            facet_name=facet_name,
            display_name=facet_def.get("display_name", facet_name),
            data_type=facet_def.get("data_type", "string"),
            description=facet_def.get("description"),
            operators=facet_def.get("operators", ["eq", "in"]),
            mappings=[
                FacetMappingResponse(content_type=ct, json_path=jp)
                for ct, jp in facet_def.get("mappings", {}).items()
            ],
        )
        for facet_name, facet_def in registry_facets.items()
    ]


@router.get("/facets/{facet_name}/mappings", response_model=List[FacetMappingResponse])
async def get_facet_mappings(
    facet_name: str,
    current_user: User = Depends(get_current_user),
):
    """Get mappings for a specific facet across content types."""
    mappings = metadata_registry_service.resolve_facet(facet_name)
    if not mappings:
        raise HTTPException(status_code=404, detail=f"Facet '{facet_name}' not found")

    return [
        FacetMappingResponse(content_type=ct, json_path=jp)
        for ct, jp in mappings.items()
    ]


# =============================================================================
# WRITE ENDPOINTS (org-level overrides)
# =============================================================================


@router.post("/fields/{namespace}", status_code=201)
async def create_field(
    namespace: str,
    request: MetadataFieldCreateRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Create an org-level metadata field definition in the specified namespace.

    The namespace must exist in the global baseline. Org-level fields override
    or extend the baseline for the current organization.
    """
    org_id = current_user.organization_id

    async with database_service.get_session() as session:
        try:
            result = await metadata_registry_service.create_field(
                session=session,
                organization_id=org_id,
                namespace=namespace,
                field_name=request.field_name,
                data_type=request.data_type,
                indexed=request.indexed,
                facetable=request.facetable,
                applicable_content_types=request.applicable_content_types,
                description=request.description,
                examples=request.examples,
                sensitivity_tag=request.sensitivity_tag,
            )
            await session.commit()
            return result
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))


@router.patch("/fields/{namespace}/{field_name}")
async def update_field(
    namespace: str,
    field_name: str,
    request: MetadataFieldUpdateRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Update an org-level metadata field definition.

    Only org-level fields (not global baseline) can be modified.
    """
    org_id = current_user.organization_id
    updates = request.model_dump(exclude_none=True)

    async with database_service.get_session() as session:
        try:
            result = await metadata_registry_service.update_field(
                session=session,
                organization_id=org_id,
                namespace=namespace,
                field_name=field_name,
                updates=updates,
            )
            await session.commit()
            return result
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))


@router.delete("/fields/{namespace}/{field_name}")
async def deactivate_field(
    namespace: str,
    field_name: str,
    current_user: User = Depends(get_current_user),
):
    """
    Deactivate (soft-delete) an org-level metadata field.

    Sets status to 'inactive'. The field will no longer appear in the
    effective registry for this organization.
    """
    org_id = current_user.organization_id

    async with database_service.get_session() as session:
        try:
            result = await metadata_registry_service.deactivate_field(
                session=session,
                organization_id=org_id,
                namespace=namespace,
                field_name=field_name,
            )
            await session.commit()
            return result
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))


@router.post("/facets", status_code=201)
async def create_facet(
    request: FacetCreateRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Create an org-level facet definition with optional content type mappings.

    Facets define cross-domain filter abstractions that map to different
    JSON paths per content type.
    """
    org_id = current_user.organization_id

    async with database_service.get_session() as session:
        try:
            result = await metadata_registry_service.create_facet(
                session=session,
                organization_id=org_id,
                facet_name=request.facet_name,
                display_name=request.display_name,
                data_type=request.data_type,
                description=request.description,
                operators=request.operators,
                mappings=[m.model_dump() for m in request.mappings],
            )
            await session.commit()
            return result
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))


@router.patch("/facets/{facet_name}")
async def update_facet(
    facet_name: str,
    request: FacetUpdateRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Update an org-level facet definition.

    Only org-level facets (not global baseline) can be modified.
    """
    org_id = current_user.organization_id
    updates = request.model_dump(exclude_none=True)

    async with database_service.get_session() as session:
        try:
            result = await metadata_registry_service.update_facet(
                session=session,
                organization_id=org_id,
                facet_name=facet_name,
                updates=updates,
            )
            await session.commit()
            return result
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))


@router.delete("/facets/{facet_name}")
async def deactivate_facet(
    facet_name: str,
    current_user: User = Depends(get_current_user),
):
    """
    Deactivate (soft-delete) an org-level facet.

    Sets status to 'inactive'. The facet will no longer appear in the
    effective registry for this organization.
    """
    org_id = current_user.organization_id

    async with database_service.get_session() as session:
        try:
            result = await metadata_registry_service.deactivate_facet(
                session=session,
                organization_id=org_id,
                facet_name=facet_name,
            )
            await session.commit()
            return result
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))


@router.post("/facets/{facet_name}/mappings", status_code=201)
async def add_facet_mapping(
    facet_name: str,
    request: FacetMappingCreateRequest,
    current_user: User = Depends(get_current_user),
):
    """Add a content type mapping to an org-level facet."""
    org_id = current_user.organization_id

    async with database_service.get_session() as session:
        try:
            result = await metadata_registry_service.add_facet_mapping(
                session=session,
                organization_id=org_id,
                facet_name=facet_name,
                content_type=request.content_type,
                json_path=request.json_path,
            )
            await session.commit()
            return result
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))


@router.delete("/facets/{facet_name}/mappings/{content_type}")
async def remove_facet_mapping(
    facet_name: str,
    content_type: str,
    current_user: User = Depends(get_current_user),
):
    """Remove a content type mapping from an org-level facet."""
    org_id = current_user.organization_id

    async with database_service.get_session() as session:
        try:
            result = await metadata_registry_service.remove_facet_mapping(
                session=session,
                organization_id=org_id,
                facet_name=facet_name,
                content_type=content_type,
            )
            await session.commit()
            return result
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))


# =============================================================================
# FACET REFERENCE DATA ENDPOINTS
# =============================================================================


@router.get("/facets/{facet_name}/autocomplete", response_model=List[FacetAutocompleteResponse])
async def facet_autocomplete(
    facet_name: str,
    q: str = "",
    limit: int = 10,
    current_user: User = Depends(get_current_user),
):
    """
    Autocomplete suggestions for a facet value.

    Searches across canonical values, display labels, and aliases.
    Returns matches sorted by relevance.
    """
    org_id = current_user.organization_id

    if not q or len(q) < 1:
        return []

    async with database_service.get_session() as session:
        results = await facet_reference_service.autocomplete(
            session, org_id, facet_name, q, limit
        )

    return [FacetAutocompleteResponse(**r) for r in results]


@router.get("/facets/{facet_name}/reference-values", response_model=List[FacetReferenceValueResponse])
async def list_reference_values(
    facet_name: str,
    include_suggested: bool = False,
    current_user: User = Depends(get_current_user),
):
    """List canonical reference values and their aliases for a facet."""
    org_id = current_user.organization_id

    async with database_service.get_session() as session:
        values = await facet_reference_service.list_values(
            session, org_id, facet_name, include_suggested=include_suggested
        )

    return [FacetReferenceValueResponse(**v) for v in values]


@router.post("/facets/{facet_name}/reference-values", response_model=dict)
async def create_reference_value(
    facet_name: str,
    request: FacetReferenceValueCreateRequest,
    current_user: User = Depends(get_current_user),
):
    """Create a new canonical reference value for a facet."""
    org_id = current_user.organization_id

    async with database_service.get_session() as session:
        try:
            result = await facet_reference_service.create_canonical(
                session=session,
                org_id=org_id,
                facet_name=facet_name,
                canonical_value=request.canonical_value,
                display_label=request.display_label,
                description=request.description,
                aliases=request.aliases,
            )
            await session.commit()
            return result
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))


@router.patch("/facets/{facet_name}/reference-values/{value_id}", response_model=dict)
async def update_reference_value(
    facet_name: str,
    value_id: str,
    request: FacetReferenceValueUpdateRequest,
    current_user: User = Depends(get_current_user),
):
    """Update a canonical reference value."""
    org_id = current_user.organization_id

    async with database_service.get_session() as session:
        result = await facet_reference_service.update_canonical(
            session=session,
            reference_value_id=UUID(value_id),
            org_id=org_id,
            canonical_value=request.canonical_value,
            display_label=request.display_label,
            description=request.description,
            sort_order=request.sort_order,
            status=request.status,
        )
        if not result:
            raise HTTPException(status_code=404, detail="Reference value not found")
        await session.commit()
        return result


@router.delete("/facets/{facet_name}/reference-values/{value_id}", response_model=dict)
async def deactivate_reference_value(
    facet_name: str,
    value_id: str,
    current_user: User = Depends(get_current_user),
):
    """Soft-delete (deactivate) a canonical reference value."""
    org_id = current_user.organization_id

    async with database_service.get_session() as session:
        result = await facet_reference_service.update_canonical(
            session=session,
            reference_value_id=UUID(value_id),
            org_id=org_id,
            status="inactive",
        )
        if not result:
            raise HTTPException(status_code=404, detail="Reference value not found")
        await session.commit()
        return {"status": "deactivated", "id": value_id}


@router.post("/facets/{facet_name}/reference-values/{value_id}/aliases", response_model=dict)
async def add_reference_alias(
    facet_name: str,
    value_id: str,
    request: FacetReferenceAliasCreateRequest,
    current_user: User = Depends(get_current_user),
):
    """Add an alias to a canonical reference value."""
    async with database_service.get_session() as session:
        try:
            result = await facet_reference_service.add_alias(
                session=session,
                reference_value_id=UUID(value_id),
                alias_value=request.alias_value,
                source_hint=request.source_hint,
            )
            await session.commit()
            return result
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))


@router.delete("/facets/{facet_name}/reference-values/{value_id}/aliases/{alias_id}", response_model=dict)
async def remove_reference_alias(
    facet_name: str,
    value_id: str,
    alias_id: str,
    current_user: User = Depends(get_current_user),
):
    """Remove an alias from a canonical reference value."""
    org_id = current_user.organization_id

    async with database_service.get_session() as session:
        success = await facet_reference_service.delete_alias(
            session, UUID(alias_id), org_id
        )
        if not success:
            raise HTTPException(status_code=404, detail="Alias not found")
        await session.commit()
        return {"status": "deleted", "id": alias_id}


@router.post("/facets/{facet_name}/discover", response_model=FacetDiscoverResponse)
async def discover_facet_values(
    facet_name: str,
    current_user: User = Depends(get_current_user),
):
    """
    AI-powered discovery: scan indexed data for unmapped values and
    suggest canonical groupings using LLM.

    This endpoint may take 10-30 seconds depending on data volume and LLM latency.
    """
    org_id = current_user.organization_id

    async with database_service.get_session() as session:
        unmapped = await facet_reference_service.discover_unmapped(
            session, org_id, facet_name
        )
        suggestions = []
        llm_error = None
        if unmapped:
            result = await facet_reference_service.suggest_groupings(
                session, org_id, facet_name
            )
            suggestions = result.get("suggestions", [])
            llm_error = result.get("error")
            await session.commit()

    return FacetDiscoverResponse(
        facet_name=facet_name,
        unmapped_count=len(unmapped),
        unmapped_values=unmapped,
        suggestions=suggestions,
        error=llm_error,
    )


@router.post("/facets/{facet_name}/reference-values/{value_id}/approve", response_model=dict)
async def approve_reference_value(
    facet_name: str,
    value_id: str,
    current_user: User = Depends(get_current_user),
):
    """Approve a suggested canonical value (promotes to active)."""
    org_id = current_user.organization_id

    async with database_service.get_session() as session:
        success = await facet_reference_service.approve(
            session, UUID(value_id), org_id
        )
        if not success:
            raise HTTPException(status_code=404, detail="Reference value not found")
        await session.commit()
        return {"status": "approved", "id": value_id}


@router.post("/facets/{facet_name}/reference-values/{value_id}/reject", response_model=dict)
async def reject_reference_value(
    facet_name: str,
    value_id: str,
    current_user: User = Depends(get_current_user),
):
    """Reject a suggested canonical value (sets to inactive)."""
    org_id = current_user.organization_id

    async with database_service.get_session() as session:
        success = await facet_reference_service.reject(
            session, UUID(value_id), org_id
        )
        if not success:
            raise HTTPException(status_code=404, detail="Reference value not found")
        await session.commit()
        return {"status": "rejected", "id": value_id}


@router.get("/facets/pending-suggestions", response_model=FacetPendingSuggestionsResponse)
async def get_pending_suggestions(
    current_user: User = Depends(get_current_user),
):
    """Get count of pending suggestions across all facets (for admin badge)."""
    org_id = current_user.organization_id

    async with database_service.get_session() as session:
        counts = await facet_reference_service.get_pending_suggestion_count(
            session, org_id
        )

    return FacetPendingSuggestionsResponse(**counts)


# =============================================================================
# DATA SOURCE TYPE ENDPOINTS
# =============================================================================


@router.get("/data-sources", response_model=List[DataSourceTypeResponse])
async def list_data_source_types(current_user: User = Depends(get_current_user)):
    """
    List all data source type definitions with org-level overrides applied.

    Returns the curated knowledge about each data source type (what it is,
    what it contains, how to search it) merged with any org customizations.
    """
    org_id = current_user.organization_id

    async with database_service.get_session() as session:
        catalog = await metadata_registry_service.get_data_source_catalog(session, org_id)

    return [
        DataSourceTypeResponse(
            source_type=key,
            display_name=defn.get("display_name", key),
            description=defn.get("description"),
            data_contains=defn.get("data_contains"),
            capabilities=defn.get("capabilities"),
            example_questions=defn.get("example_questions"),
            search_tools=defn.get("search_tools"),
            note=defn.get("note"),
            is_active=defn.get("is_active", True),
        )
        for key, defn in catalog.items()
    ]


@router.patch("/data-sources/{source_type}", response_model=dict)
async def update_data_source_type(
    source_type: str,
    request: DataSourceTypeUpdateRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Create or update an org-level data source type override.

    Allows admins to customize how a data source type is described for their
    organization, or hide source types that are not relevant.
    """
    org_id = current_user.organization_id

    async with database_service.get_session() as session:
        try:
            result = await metadata_registry_service.upsert_data_source_override(
                session=session,
                organization_id=org_id,
                source_type=source_type,
                display_name=request.display_name,
                description=request.description,
                capabilities=request.capabilities,
                is_active=request.is_active,
            )
            await session.commit()
            return result
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))


@router.post("/cache/invalidate")
async def invalidate_cache(
    current_user: User = Depends(get_current_user),
):
    """Force cache invalidation for the current organization's metadata registry."""
    org_id = current_user.organization_id
    metadata_registry_service.invalidate_cache(org_id)
    return {"status": "cache_invalidated", "organization_id": str(org_id)}
