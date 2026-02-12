# backend/app/cwr/tools/primitives/output/extract_asset.py
"""
Extract Asset function - Trigger document extraction for an asset.

Supports two modes:
- async (default): Fire-and-forget. Queues extraction and returns immediately
  with a run_id for tracking.
- sync: Waits for extraction to complete and returns the extracted content.

Use this when a procedure needs to:
- Re-extract a failed asset
- Extract a newly created asset before analyzing it
- Force re-extraction with a different engine
"""

import asyncio
import logging
import time
from uuid import UUID

from sqlalchemy import select

from ...base import (
    BaseFunction,
    FunctionCategory,
    FunctionMeta,
    FunctionResult,
)
from ...context import FunctionContext

logger = logging.getLogger("curatore.functions.output.extract_asset")


class ExtractAssetFunction(BaseFunction):
    """
    Trigger document extraction for an asset.

    Two execution modes:

    **async** (default): Queues extraction and returns immediately with a
    run_id. Use when the procedure doesn't need the content right away, or
    when processing many assets in a foreach loop.

    **sync**: Waits for extraction to complete and returns extracted markdown.
    Use when the next step needs the content (e.g., feeding it to an LLM).

    Skips extraction if the asset already has status "ready" unless force=True.

    Example (async - fire and forget):
        result = await fn.extract_asset(ctx,
            asset_id="<uuid>",
            mode="async",
        )
        # result.data = {status: "queued", run_id: "..."}

    Example (sync - wait for content):
        result = await fn.extract_asset(ctx,
            asset_id="<uuid>",
            mode="sync",
            timeout_seconds=120,
        )
        # result.data = {status: "completed", content: "# Extracted markdown..."}

    Example (force re-extraction):
        result = await fn.extract_asset(ctx,
            asset_id="<uuid>",
            mode="sync",
            force=True,
        )
    """

    meta = FunctionMeta(
        name="extract_asset",
        category=FunctionCategory.OUTPUT,
        description=(
            "Trigger document extraction for an asset. "
            "Supports async (fire-and-forget, returns run_id) and sync "
            "(wait for completion, returns extracted markdown) modes. "
            "Skips if already extracted unless force=True."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "asset_id": {
                    "type": "string",
                    "description": "Asset UUID to extract",
                },
                "mode": {
                    "type": "string",
                    "enum": ["async", "sync"],
                    "default": "async",
                    "description": (
                        "async = fire-and-forget (returns run_id immediately); "
                        "sync = wait for extraction to complete and return content"
                    ),
                },
                "force": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "Re-extract even if asset already has status 'ready'. "
                        "Ignored if extraction is already in progress."
                    ),
                },
                "timeout_seconds": {
                    "type": "integer",
                    "default": 300,
                    "description": "Max seconds to wait in sync mode. Ignored in async mode.",
                },
                "include_content": {
                    "type": "boolean",
                    "default": True,
                    "description": (
                        "In sync mode, include extracted markdown in response. "
                        "Set false to get metadata only."
                    ),
                },
            },
            "required": ["asset_id"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "asset_id": {"type": "string"},
                "run_id": {"type": "string", "nullable": True},
                "status": {
                    "type": "string",
                    "description": (
                        "queued, already_ready, completed, failed, "
                        "timed_out, skipped"
                    ),
                },
                "extraction_tier": {"type": "string", "nullable": True},
                "content": {
                    "type": "string",
                    "nullable": True,
                    "description": "Extracted markdown (sync mode with include_content only)",
                },
                "content_length": {"type": "integer", "nullable": True},
                "extraction_time_seconds": {"type": "number", "nullable": True},
                "filename": {"type": "string"},
                "message": {"type": "string"},
            },
        },
        tags=["extraction", "document", "processing"],
        requires_llm=False,
        side_effects=True,
        is_primitive=True,
        payload_profile="full",
        exposure_profile={"procedure": True, "agent": False},
        examples=[
            {
                "description": "Async extraction (fire-and-forget)",
                "params": {
                    "asset_id": "uuid",
                    "mode": "async",
                },
            },
            {
                "description": "Sync extraction with content",
                "params": {
                    "asset_id": "uuid",
                    "mode": "sync",
                    "timeout_seconds": 120,
                },
            },
            {
                "description": "Force re-extraction",
                "params": {
                    "asset_id": "uuid",
                    "mode": "sync",
                    "force": True,
                },
            },
        ],
    )

    async def execute(self, ctx: FunctionContext, **params) -> FunctionResult:
        """Trigger extraction for an asset."""
        asset_id_str = params["asset_id"]
        mode = params.get("mode", "async")
        force = params.get("force", False)
        timeout_seconds = params.get("timeout_seconds", 300)
        include_content = params.get("include_content", True)

        # Validate asset_id
        try:
            asset_uuid = UUID(asset_id_str) if isinstance(asset_id_str, str) else asset_id_str
        except ValueError as e:
            return FunctionResult.failed_result(
                error=f"Invalid asset ID: {e}",
                message="Asset ID must be a valid UUID",
            )

        from app.core.database.models import Asset, ExtractionResult

        try:
            # Fetch asset and verify org ownership
            query = select(Asset).where(
                Asset.id == asset_uuid,
                Asset.organization_id == ctx.organization_id,
            )
            result = await ctx.session.execute(query)
            asset = result.scalar_one_or_none()

            if not asset:
                return FunctionResult.failed_result(
                    error="Asset not found",
                    message=f"No asset found with ID {asset_id_str} in this organization",
                )

            filename = asset.original_filename

            # If already ready and not forcing, return existing content
            if asset.status == "ready" and not force:
                response = {
                    "asset_id": str(asset.id),
                    "run_id": None,
                    "status": "already_ready",
                    "extraction_tier": asset.extraction_tier,
                    "filename": filename,
                    "message": f"Asset already extracted ({asset.extraction_tier or 'unknown'} tier)",
                }

                # In sync mode with include_content, fetch the markdown
                if mode == "sync" and include_content:
                    content = await self._fetch_extracted_content(ctx, asset)
                    if content is not None:
                        response["content"] = content
                        response["content_length"] = len(content)

                return FunctionResult.success_result(
                    data=response,
                    message=response["message"],
                )

            # Dry run - show what would happen
            if ctx.dry_run:
                return FunctionResult.success_result(
                    data={
                        "asset_id": str(asset.id),
                        "status": "dry_run",
                        "filename": filename,
                        "would_extract": True,
                        "mode": mode,
                        "force": force,
                        "message": f"Would queue extraction for {filename} (mode={mode})",
                    },
                    message=f"Dry run: would extract {filename}",
                )

            # Create RunGroup for parent-child tracking
            from app.core.shared.run_group_service import run_group_service

            group = await run_group_service.create_group(
                session=ctx.session,
                organization_id=ctx.organization_id,
                group_type="extract_asset",
                parent_run_id=ctx.run_id,
            )

            # Queue extraction
            from app.core.ingestion.extraction_queue_service import extraction_queue_service

            run, extraction, queue_status = await extraction_queue_service.queue_extraction_for_asset(
                session=ctx.session,
                asset_id=asset_uuid,
                user_id=ctx.user_id,
                skip_content_type_check=force,
                group_id=group.id,
            )

            # Handle queue responses that indicate extraction won't happen
            if queue_status in ("skipped_content_type", "skipped_unsupported_type", "asset_not_found"):
                return FunctionResult.success_result(
                    data={
                        "asset_id": str(asset.id),
                        "run_id": None,
                        "status": "skipped",
                        "filename": filename,
                        "message": f"Extraction skipped: {queue_status}",
                    },
                    message=f"Skipped: {queue_status}",
                )

            # Finalize the group (signals no more children coming)
            await run_group_service.finalize_group(ctx.session, group.id)

            run_id_str = str(run.id) if run else None

            # Handle already_pending
            if queue_status == "already_pending":
                if mode == "async":
                    return FunctionResult.success_result(
                        data={
                            "asset_id": str(asset.id),
                            "run_id": run_id_str,
                            "status": "already_pending",
                            "filename": filename,
                            "message": "Extraction already in progress",
                        },
                        message=f"Extraction already in progress for {filename}",
                    )
                # In sync mode, fall through to poll the existing run

            # Async mode - return immediately
            if mode == "async":
                return FunctionResult.success_result(
                    data={
                        "asset_id": str(asset.id),
                        "run_id": run_id_str,
                        "status": "queued",
                        "filename": filename,
                        "message": f"Extraction queued for {filename}",
                    },
                    message=f"Queued extraction for {filename}",
                    items_processed=1,
                )

            # Sync mode - poll until complete or timeout
            start_time = time.monotonic()
            poll_interval = 2  # seconds

            while True:
                elapsed = time.monotonic() - start_time
                if elapsed >= timeout_seconds:
                    return FunctionResult.success_result(
                        data={
                            "asset_id": str(asset.id),
                            "run_id": run_id_str,
                            "status": "timed_out",
                            "filename": filename,
                            "extraction_time_seconds": round(elapsed, 2),
                            "message": (
                                f"Extraction timed out after {timeout_seconds}s. "
                                f"The extraction may still complete - track run_id={run_id_str}"
                            ),
                        },
                        message=f"Extraction timed out for {filename}",
                    )

                await asyncio.sleep(poll_interval)

                # Refresh the group status
                await ctx.session.expire_all()
                group = await run_group_service.get_group(ctx.session, group.id)

                if not group:
                    return FunctionResult.failed_result(
                        error="Run group disappeared",
                        message="Internal error tracking extraction progress",
                    )

                if group.status in ("completed", "failed", "partial"):
                    elapsed = time.monotonic() - start_time

                    if group.status == "completed":
                        # Fetch the extraction result
                        await ctx.session.expire_all()
                        response = {
                            "asset_id": str(asset.id),
                            "run_id": run_id_str,
                            "status": "completed",
                            "filename": filename,
                            "extraction_time_seconds": round(elapsed, 2),
                            "message": f"Extraction completed in {elapsed:.1f}s",
                        }

                        # Refresh asset to get extraction_tier
                        refreshed_asset = await ctx.session.get(Asset, asset_uuid)
                        if refreshed_asset:
                            response["extraction_tier"] = refreshed_asset.extraction_tier

                        # Fetch extracted content if requested
                        if include_content:
                            content = await self._fetch_extracted_content(ctx, refreshed_asset or asset)
                            if content is not None:
                                response["content"] = content
                                response["content_length"] = len(content)

                        return FunctionResult.success_result(
                            data=response,
                            message=response["message"],
                            items_processed=1,
                        )
                    else:
                        # Failed or partial
                        return FunctionResult.failed_result(
                            error=f"Extraction {group.status}",
                            message=f"Extraction {group.status} for {filename}",
                            data={
                                "asset_id": str(asset.id),
                                "run_id": run_id_str,
                                "status": group.status,
                                "filename": filename,
                                "extraction_time_seconds": round(elapsed, 2),
                                "group_results": group.results_summary,
                            },
                        )

        except Exception as e:
            logger.exception(f"Failed to extract asset: {e}")
            return FunctionResult.failed_result(
                error=str(e),
                message=f"Unexpected error: {type(e).__name__}",
            )

    async def _fetch_extracted_content(
        self,
        ctx: FunctionContext,
        asset,
    ) -> str | None:
        """
        Fetch extracted markdown content for an asset from object storage.

        Follows the same pattern as get_asset.py for content retrieval.
        """
        from app.core.database.models import ExtractionResult

        try:
            extraction_query = (
                select(ExtractionResult)
                .where(
                    ExtractionResult.asset_id == asset.id,
                    ExtractionResult.status == "completed",
                )
                .order_by(ExtractionResult.created_at.desc())
                .limit(1)
            )
            result = await ctx.session.execute(extraction_query)
            extraction = result.scalar_one_or_none()

            if extraction and extraction.extracted_bucket and extraction.extracted_object_key:
                content_io = ctx.minio_service.get_object(
                    bucket=extraction.extracted_bucket,
                    key=extraction.extracted_object_key,
                )
                if content_io:
                    content = content_io.read()
                    return content.decode("utf-8") if isinstance(content, bytes) else content
        except Exception as e:
            logger.warning(f"Failed to fetch extracted content for asset {asset.id}: {e}")

        return None
