# backend/app/cwr/tools/compounds/classify_document.py
"""
Classify Document compound — Compose primitives to classify + persist.

Composes three existing primitives:
  1. get_content — fetch extracted markdown
  2. llm_classify — LLM-based classification
  3. update_source_metadata — persist to file.document_type and propagate to search

Default categories are loaded from the metadata registry (fields.yaml →
file.document_type.examples) so the compound stays in sync with the catalog.
"""

import logging

from ..base import (
    BaseFunction,
    FunctionCategory,
    FunctionMeta,
    FunctionResult,
)
from ..context import FunctionContext

logger = logging.getLogger("curatore.functions.compound.classify_document")


class ClassifyDocumentFunction(BaseFunction):
    """
    Classify a document by type using LLM and optionally persist to
    searchable metadata (file.document_type).

    Composes get_content → llm_classify → update_source_metadata.

    Example:
        result = await fn.classify_document(ctx, asset_id="uuid")
    """

    meta = FunctionMeta(
        name="classify_document",
        category=FunctionCategory.COMPOUND,
        description="Classify a document by type using LLM and optionally persist to searchable metadata",
        input_schema={
            "type": "object",
            "properties": {
                "asset_id": {
                    "type": "string",
                    "description": "Asset ID to classify",
                },
                "persist": {
                    "type": "boolean",
                    "description": "Write classification to file.document_type metadata and propagate to search",
                    "default": True,
                },
                "item": {
                    "type": "object",
                    "description": "Pipeline item (provides asset_id when called from pipeline transform stage)",
                    "default": None,
                },
            },
            "required": ["asset_id"],
        },
        output_schema={
            "type": "object",
            "description": "Classification result with updated metadata",
            "properties": {
                "asset_id": {
                    "type": "string",
                    "description": "UUID of classified asset",
                },
                "filename": {
                    "type": "string",
                    "description": "Original filename",
                },
                "file_path": {
                    "type": "string",
                    "description": "Object storage path for the raw file",
                },
                "category": {
                    "type": "string",
                    "description": "Assigned category",
                },
                "confidence": {
                    "type": "number",
                    "description": "Classification confidence (0.0-1.0)",
                },
                "method": {
                    "type": "string",
                    "description": "Classification method (llm)",
                },
                "document_type": {
                    "type": "string",
                    "description": "Same as category (pipeline filter compat)",
                },
                "metadata_updated": {
                    "type": "object",
                    "description": "Metadata persistence details",
                    "properties": {
                        "namespace": {"type": "string"},
                        "fields": {"type": "object"},
                        "persisted": {"type": "boolean"},
                        "propagated_to_search": {"type": "boolean"},
                    },
                },
            },
        },
        tags=["compound", "classification", "document"],
        requires_llm=True,
        side_effects=True,
        is_primitive=False,
        payload_profile="full",
        examples=[
            {
                "description": "Classify and persist",
                "params": {
                    "asset_id": "uuid",
                },
            },
            {
                "description": "Classify without persisting",
                "params": {
                    "asset_id": "uuid",
                    "persist": False,
                },
            },
        ],
    )

    async def execute(self, ctx: FunctionContext, **params) -> FunctionResult:
        """Classify document by composing get_content → llm_classify → update_source_metadata."""

        # ── Resolve asset_id ────────────────────────────────────────────
        asset_id = params.get("asset_id")
        item = params.get("item")
        if not asset_id and item and isinstance(item, dict):
            asset_id = item.get("asset_id") or item.get("id")
        if not asset_id:
            return FunctionResult.failed_result(
                error="No asset_id provided",
                message="asset_id is required (directly or via item)",
            )

        persist = params.get("persist", True)

        # ── Load categories and descriptions from registry ──────────────
        categories = None
        category_descriptions = None
        try:
            from app.core.metadata.registry_service import metadata_registry_service

            all_fields = metadata_registry_service.get_all_fields()
            doc_type_def = all_fields.get("file", {}).get("document_type", {})
            categories = doc_type_def.get("examples")
            category_descriptions = doc_type_def.get("value_descriptions")
        except Exception as e:
            logger.warning(f"Failed to load categories from registry: {e}")

        if not categories:
            # Hardcoded fallback — kept minimal; full list lives in fields.yaml
            categories = [
                "Proposal Response", "Solicitation", "White Paper",
                "Capability Statement", "Past Performance", "RFI Response",
                "Contract", "Task Order", "Statement of Work",
                "Correspondence", "Presentation", "Other",
            ]

        # ── Step 1: get_content ─────────────────────────────────────────
        from ..primitives.search.get_content import GetContentFunction

        get_content_fn = GetContentFunction()
        content_result = await get_content_fn.execute(
            ctx, asset_ids=[asset_id], include_metadata=True,
        )

        if content_result.failed:
            return FunctionResult.failed_result(
                error=content_result.error or "Failed to retrieve content",
                message=f"get_content failed for asset {asset_id}",
            )

        # Extract content and filename from the first (only) item
        items = content_result.data or []
        if not items:
            return FunctionResult.failed_result(
                error="Asset not found",
                message=f"No content returned for asset {asset_id}",
            )

        asset_item = items[0]
        content = asset_item.get("content") or ""
        filename = asset_item.get("filename", "")
        file_path = asset_item.get("file_path", "")

        if not content:
            return FunctionResult.failed_result(
                error=asset_item.get("content_error", "No extracted content available"),
                message=f"No content available for asset {asset_id}",
            )

        # ── Step 2: llm_classify ────────────────────────────────────────
        from ..primitives.llm.classify import ClassifyFunction

        classify_fn = ClassifyFunction()
        classify_params = {
            "text": content,
            "categories": categories,
            "include_reasoning": False,
        }
        if category_descriptions:
            classify_params["category_descriptions"] = category_descriptions

        classify_result = await classify_fn.execute(ctx, **classify_params)

        if classify_result.failed:
            return FunctionResult.failed_result(
                error=classify_result.error or "Classification failed",
                message=f"llm_classify failed for asset {asset_id}",
            )

        classification = classify_result.data or {}
        category = classification.get("category", "Other")
        confidence = classification.get("confidence", 0.0)

        # ── Step 3: update_source_metadata (if persist=True) ────────────
        metadata_updated = {
            "namespace": "file",
            "fields": {"document_type": category},
            "persisted": False,
            "propagated_to_search": False,
        }

        if persist:
            from ..primitives.output.update_source_metadata import UpdateSourceMetadataFunction

            update_fn = UpdateSourceMetadataFunction()
            update_result = await update_fn.execute(
                ctx,
                asset_id=asset_id,
                namespace="file",
                fields={"document_type": category},
                propagate_to_search=True,
            )

            if update_result.failed:
                logger.warning(
                    f"Metadata persistence failed for asset {asset_id}: "
                    f"{update_result.error}"
                )
                # Classification still succeeded — return partial success info
            else:
                update_data = update_result.data or {}
                metadata_updated["persisted"] = True
                metadata_updated["propagated_to_search"] = update_data.get(
                    "propagated", False
                )
                logger.info(
                    f"Metadata update for asset {asset_id}: "
                    f"persisted=True, propagated={update_data.get('propagated')}, "
                    f"fields_updated={update_data.get('fields_updated')}"
                )

        # ── Build canonical result ──────────────────────────────────────
        return FunctionResult.success_result(
            data={
                "asset_id": str(asset_id),
                "filename": filename,
                "file_path": file_path,
                "category": category,
                "confidence": confidence,
                "method": "llm",
                "document_type": category,
                "metadata_updated": metadata_updated,
            },
            message=f"Classified '{filename}' as '{category}' ({confidence:.0%}) — {file_path}",
            items_processed=1,
        )
