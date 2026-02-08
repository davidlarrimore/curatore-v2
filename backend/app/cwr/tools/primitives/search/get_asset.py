# backend/app/functions/search/get_asset.py
"""
Get Asset function - Retrieve a single asset by UUID.

Gets asset metadata and optionally its content (markdown or source file).
"""

from typing import Any, Dict, Optional
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

logger = logging.getLogger("curatore.functions.search.get_asset")


class GetAssetFunction(BaseFunction):
    """
    Get a single asset by UUID.

    Retrieves asset metadata and optionally its content. By default returns
    the extracted markdown, but can also return the source file or just metadata.

    Example:
        # Get markdown content (default)
        result = await fn.get_asset(ctx, asset_id="uuid")

        # Get source file
        result = await fn.get_asset(ctx, asset_id="uuid", content_type="source")

        # Get metadata only (no file content)
        result = await fn.get_asset(ctx, asset_id="uuid", content_type="metadata_only")
    """

    meta = FunctionMeta(
        name="get_asset",
        category=FunctionCategory.SEARCH,
        description="Get a single asset by UUID with optional content retrieval",
        parameters=[
            ParameterDoc(
                name="asset_id",
                type="str",
                description="Asset UUID to retrieve",
                required=True,
            ),
            ParameterDoc(
                name="content_type",
                type="str",
                description="Type of content to retrieve",
                required=False,
                default="markdown",
                enum_values=[
                    "markdown|Extracted Markdown",
                    "source|Original Source File",
                    "metadata_only|Metadata Only (no content)",
                ],
            ),
            ParameterDoc(
                name="max_content_length",
                type="int",
                description="Maximum content length (truncate if longer). Only applies to markdown.",
                required=False,
                default=None,
            ),
        ],
        returns="dict: Asset metadata and content",
        tags=["search", "assets", "content"],
        requires_llm=False,
        side_effects=False,
        is_primitive=True,
        payload_profile="thin",
        examples=[
            {
                "description": "Get markdown content",
                "params": {
                    "asset_id": "uuid",
                    "content_type": "markdown",
                },
            },
            {
                "description": "Get source file",
                "params": {
                    "asset_id": "uuid",
                    "content_type": "source",
                },
            },
        ],
    )

    async def execute(self, ctx: FunctionContext, **params) -> FunctionResult:
        """Get asset by ID."""
        asset_id = params["asset_id"]
        content_type = params.get("content_type", "markdown")
        max_content_length = params.get("max_content_length")

        # Validate and convert asset_id
        try:
            asset_uuid = UUID(asset_id) if isinstance(asset_id, str) else asset_id
        except ValueError as e:
            return FunctionResult.failed_result(
                error=f"Invalid asset ID: {e}",
                message="Asset ID must be a valid UUID",
            )

        from app.core.database.models import Asset, ExtractionResult

        try:
            # Query asset
            query = select(Asset).where(
                Asset.id == asset_uuid,
                Asset.organization_id == ctx.organization_id,
            )
            result = await ctx.session.execute(query)
            asset = result.scalar_one_or_none()

            if not asset:
                return FunctionResult.failed_result(
                    error="Asset not found",
                    message=f"No asset found with ID {asset_id}",
                )

            # Build base response with metadata
            response = {
                "asset_id": str(asset.id),
                "filename": asset.original_filename,
                "status": asset.status,
                "source_type": asset.source_type,
                "content_type": asset.content_type,
                "file_size": asset.file_size,
                "created_at": asset.created_at.isoformat() if asset.created_at else None,
                "updated_at": asset.updated_at.isoformat() if asset.updated_at else None,
                "indexed_at": asset.indexed_at.isoformat() if asset.indexed_at else None,
                "source_metadata": asset.source_metadata or {},
            }

            # Return early if metadata only requested
            if content_type == "metadata_only":
                return FunctionResult.success_result(
                    data=response,
                    message=f"Retrieved metadata for asset: {asset.original_filename}",
                )

            # Get content based on content_type
            if content_type == "source":
                # Get source file from raw storage
                if asset.raw_bucket and asset.raw_object_key:
                    try:
                        content_io = ctx.minio_service.get_object(
                            bucket=asset.raw_bucket,
                            key=asset.raw_object_key,
                        )
                        if content_io:
                            content_bytes = content_io.read()
                            # Try to decode as text, otherwise return base64
                            try:
                                content = content_bytes.decode("utf-8")
                                response["content"] = content
                                response["content_encoding"] = "utf-8"
                            except UnicodeDecodeError:
                                import base64
                                response["content"] = base64.b64encode(content_bytes).decode("ascii")
                                response["content_encoding"] = "base64"
                            response["content_length"] = len(content_bytes)
                            response["content_source"] = "raw"
                    except Exception as e:
                        logger.warning(f"Failed to get source file for asset {asset.id}: {e}")
                        return FunctionResult.failed_result(
                            error=str(e),
                            message="Failed to retrieve source file",
                            data=response,
                        )
                else:
                    return FunctionResult.failed_result(
                        error="Source file not found",
                        message="Asset does not have a source file stored",
                        data=response,
                    )

            else:  # markdown (default)
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
                    try:
                        content_io = ctx.minio_service.get_object(
                            bucket=extraction.extracted_bucket,
                            key=extraction.extracted_object_key,
                        )
                        if content_io:
                            content = content_io.read()
                            content = content.decode("utf-8") if isinstance(content, bytes) else content

                            # Add extraction metadata
                            response["extraction_tier"] = extraction.extraction_tier
                            response["triage_engine"] = extraction.triage_engine
                            response["triage_complexity"] = extraction.triage_complexity

                            # Truncate if needed
                            original_length = len(content)
                            if max_content_length and len(content) > max_content_length:
                                content = content[:max_content_length] + "\n\n... [truncated]"
                                response["truncated"] = True

                            response["content"] = content
                            response["content_length"] = original_length
                            response["content_source"] = "extracted"
                    except Exception as e:
                        logger.warning(f"Failed to get markdown for asset {asset.id}: {e}")
                        return FunctionResult.failed_result(
                            error=str(e),
                            message="Failed to retrieve markdown content",
                            data=response,
                        )
                else:
                    # No extraction available
                    if not extraction:
                        error_msg = "No completed extraction found"
                    else:
                        error_msg = "Extraction result missing storage location"

                    return FunctionResult.failed_result(
                        error=error_msg,
                        message=f"Markdown content not available: {error_msg}",
                        data=response,
                    )

            return FunctionResult.success_result(
                data=response,
                message=f"Retrieved {content_type} for asset: {asset.original_filename}",
            )

        except Exception as e:
            logger.exception(f"Failed to get asset: {e}")
            return FunctionResult.failed_result(
                error=str(e),
                message="Failed to retrieve asset",
            )
