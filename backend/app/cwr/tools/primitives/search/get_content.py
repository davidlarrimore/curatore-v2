# backend/app/functions/search/get_content.py
"""
Get Content function - Retrieve extracted markdown content.

Gets the extracted markdown content for assets.
"""

import logging
from uuid import UUID

from sqlalchemy import select

from ...base import (
    BaseFunction,
    FunctionCategory,
    FunctionMeta,
    FunctionResult,
)
from ...context import FunctionContext

logger = logging.getLogger("curatore.functions.search.get_content")


class GetContentFunction(BaseFunction):
    """
    Get extracted markdown content for assets.

    Retrieves the extracted markdown content from object storage
    for one or more assets.

    Example:
        result = await fn.get_content(ctx,
            asset_ids=["uuid1", "uuid2"],
        )
        # result.data = [{"asset_id": "uuid1", "content": "...", ...}, ...]
    """

    meta = FunctionMeta(
        name="get_content",
        category=FunctionCategory.SEARCH,
        description=(
            "Get extracted markdown content for document assets (files uploaded, synced from SharePoint, "
            "or scraped from the web). Only accepts asset IDs from search_assets results. "
            "Do NOT pass solicitation IDs, forecast IDs, or Salesforce record IDs — those are not assets."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "asset_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Asset IDs (from search_assets results) to get content for. Must be document asset UUIDs -- solicitation, forecast, and Salesforce IDs will not work.",
                },
                "include_metadata": {
                    "type": "boolean",
                    "description": "Include asset metadata in response",
                    "default": True,
                },
                "max_content_length": {
                    "type": "integer",
                    "description": "Maximum content length per asset (truncate if longer)",
                    "default": None,
                },
            },
            "required": ["asset_ids"],
        },
        output_schema={
            "type": "array",
            "description": "List of asset content objects",
            "items": {
                "type": "object",
                "properties": {
                    "asset_id": {"type": "string"},
                    "filename": {"type": "string"},
                    "status": {"type": "string"},
                    "content": {"type": "string", "nullable": True},
                    "content_length": {"type": "integer"},
                    "content_error": {"type": "string", "nullable": True},
                    "source_type": {"type": "string"},
                    "content_type": {"type": "string"},
                    "file_size": {"type": "integer"},
                    "file_path": {"type": "string", "description": "Object storage path for the raw file"},
                    "created_at": {"type": "string"},
                },
            },
        },
        tags=["search", "content", "assets"],
        requires_llm=False,
        side_effects=False,
        is_primitive=True,
        payload_profile="thin",
        examples=[
            {
                "description": "Get content for assets",
                "params": {
                    "asset_ids": ["uuid1", "uuid2"],
                    "include_metadata": True,
                },
            },
        ],
    )

    async def execute(self, ctx: FunctionContext, **params) -> FunctionResult:
        """Get content for assets."""
        asset_ids = params["asset_ids"]
        include_metadata = params.get("include_metadata", True)
        max_content_length = params.get("max_content_length")

        if not asset_ids:
            return FunctionResult.success_result(
                data=[],
                message="No asset IDs provided",
            )

        # Convert string IDs to UUIDs
        try:
            uuid_ids = [UUID(aid) if isinstance(aid, str) else aid for aid in asset_ids]
        except ValueError as e:
            return FunctionResult.failed_result(
                error=f"Invalid asset ID: {e}",
                message="One or more asset IDs are invalid",
            )

        from app.core.database.models import Asset, ExtractionResult

        try:
            # Query assets with their extraction results
            query = (
                select(Asset)
                .where(
                    Asset.id.in_(uuid_ids),
                    Asset.organization_id == ctx.organization_id,
                )
            )

            result = await ctx.session.execute(query)
            assets = result.scalars().all()

            # Build response
            results = []
            for asset in assets:
                item = {
                    "asset_id": str(asset.id),
                    "filename": asset.original_filename,
                    "status": asset.status,
                    "content": None,
                }

                if include_metadata:
                    item.update({
                        "source_type": asset.source_type,
                        "content_type": asset.content_type,
                        "file_size": asset.file_size,
                        "created_at": asset.created_at.isoformat() if asset.created_at else None,
                        "file_path": asset.raw_object_key,
                    })

                # Get latest extraction result
                extraction_query = (
                    select(ExtractionResult)
                    .where(
                        ExtractionResult.asset_id == asset.id,
                        ExtractionResult.status == "completed",
                    )
                    .order_by(ExtractionResult.created_at.desc())
                    .limit(1)
                )

                extraction_result = await ctx.session.execute(extraction_query)
                extraction = extraction_result.scalar_one_or_none()

                if extraction and extraction.extracted_bucket and extraction.extracted_object_key:
                    # Get content from object storage
                    try:
                        content_io = ctx.minio_service.get_object(
                            bucket=extraction.extracted_bucket,
                            key=extraction.extracted_object_key,
                        )
                        if content_io:
                            content = content_io.read()
                            content = content.decode("utf-8") if isinstance(content, bytes) else content
                            if max_content_length and len(content) > max_content_length:
                                content = content[:max_content_length] + "..."
                            item["content"] = content
                            item["content_length"] = len(content)
                    except Exception as e:
                        logger.warning(f"Failed to get content for asset {asset.id}: {e}")
                        item["content_error"] = str(e)
                else:
                    if not extraction:
                        item["content_error"] = "No completed extraction found"
                    else:
                        item["content_error"] = "Extraction result missing storage location"

                results.append(item)

            # Track assets not found
            found_ids = {str(a.id) for a in assets}
            missing = [aid for aid in asset_ids if str(aid) not in found_ids]

            # Count successes and failures
            with_content = len([r for r in results if r.get("content")])
            with_errors = len([r for r in results if r.get("content_error")])

            # Determine overall status based on results
            if with_content == 0 and len(results) > 0:
                # All assets failed to retrieve content
                return FunctionResult.failed_result(
                    error="Failed to retrieve content for all assets",
                    message=f"Could not retrieve content for any of the {len(results)} assets",
                    data=results,
                    metadata={
                        "requested": len(asset_ids),
                        "found": len(results),
                        "missing": missing,
                        "with_content": 0,
                        "with_errors": with_errors,
                    },
                    items_processed=len(results),
                    items_failed=with_errors,
                )
            elif with_errors > 0:
                # Partial success - some assets have content, some don't
                return FunctionResult.partial_result(
                    data=results,
                    items_processed=len(results),
                    items_failed=with_errors,
                    message=f"Retrieved content for {with_content} of {len(results)} assets ({with_errors} failed)",
                    metadata={
                        "requested": len(asset_ids),
                        "found": len(results),
                        "missing": missing,
                        "with_content": with_content,
                        "with_errors": with_errors,
                    },
                )
            else:
                # Full success
                return FunctionResult.success_result(
                    data=results,
                    message=f"Retrieved content for {len(results)} assets",
                    metadata={
                        "requested": len(asset_ids),
                        "found": len(results),
                        "missing": missing,
                        "with_content": with_content,
                    },
                    items_processed=len(results),
                )

        except Exception as e:
            logger.exception(f"Failed to get content: {e}")
            return FunctionResult.failed_result(
                error=str(e),
                message="Failed to retrieve content",
            )
