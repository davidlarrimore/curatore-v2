# backend/app/functions/search/get_content.py
"""
Get Content function - Retrieve extracted markdown content.

Gets the extracted markdown content for assets.
"""

from typing import Any, Dict, List, Optional, Union
from uuid import UUID
import logging

from sqlalchemy import select

from ...base import (
    BaseFunction,
    FunctionMeta,
    FunctionCategory,
    FunctionResult,
    ParameterDoc,
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
        description="Get extracted markdown content for assets",
        parameters=[
            ParameterDoc(
                name="asset_ids",
                type="list[str]",
                description="Asset IDs to get content for",
                required=True,
            ),
            ParameterDoc(
                name="include_metadata",
                type="bool",
                description="Include asset metadata in response",
                required=False,
                default=True,
            ),
            ParameterDoc(
                name="max_content_length",
                type="int",
                description="Maximum content length per asset (truncate if longer)",
                required=False,
                default=None,
            ),
        ],
        returns="list[dict]: Content and metadata for each asset",
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
