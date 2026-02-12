# backend/app/cwr/tools/primitives/search/get_forecast_history.py
"""
Get Forecast History function - Retrieve change history for a specific forecast.

Returns the version history snapshots AND computed field-level diffs for a
forecast, showing exactly what changed between each sync.
"""

import logging
from uuid import UUID

from ...base import (
    BaseFunction,
    FunctionCategory,
    FunctionMeta,
    FunctionResult,
)
from ...context import FunctionContext

logger = logging.getLogger("curatore.functions.search.get_forecast_history")


class GetForecastHistoryFunction(BaseFunction):
    """
    Get change history for a specific forecast.

    Returns version history AND computed field-level diffs showing exactly
    what was added, removed, or modified between each version. One call
    returns all history — no iteration or additional calls needed.

    Example:
        result = await fn.get_forecast_history(ctx,
            forecast_id="uuid-here",
        )
    """

    meta = FunctionMeta(
        name="get_forecast_history",
        category=FunctionCategory.SEARCH,
        description=(
            "Get the full change history for a specific acquisition forecast in a single call. "
            "Returns all version snapshots AND pre-computed field-level diffs (added/removed/modified fields) "
            "between consecutive versions. No additional calls or manual comparison needed — "
            "the 'changes' array tells you exactly what changed and when. "
            "Use after search_forecasts to investigate how a forecast evolved across syncs. "
            "If total_versions is 1, the forecast has not changed since first imported. "
            "If total_versions is 0, the forecast predates change tracking."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "forecast_id": {
                    "type": "string",
                    "description": "Forecast UUID to retrieve history for",
                },
                "source_type": {
                    "type": "string",
                    "description": "Optional source type hint (ag, apfs, state) to speed up lookup",
                    "enum": ["ag", "apfs", "state"],
                    "default": None,
                },
            },
            "required": ["forecast_id"],
        },
        output_schema={
            "type": "object",
            "description": "Forecast metadata, version history, and computed changes between versions",
            "properties": {
                "forecast_id": {"type": "string", "description": "Forecast UUID"},
                "source_type": {"type": "string", "description": "Source type (ag, apfs, state)"},
                "title": {"type": "string", "description": "Current forecast title"},
                "first_seen_at": {"type": "string", "description": "When forecast was first seen", "nullable": True},
                "last_updated_at": {"type": "string", "description": "When forecast was last updated", "nullable": True},
                "total_versions": {"type": "integer", "description": "Total number of history versions (0 = predates tracking, 1 = no changes yet)"},
                "history": {
                    "type": "array",
                    "description": "Full version snapshots in chronological order",
                    "items": {
                        "type": "object",
                        "properties": {
                            "version": {"type": "integer", "description": "Version number"},
                            "sync_date": {"type": "string", "description": "ISO date when this version was synced"},
                            "data": {"type": "object", "description": "Snapshot of all tracked fields at this version"},
                        },
                    },
                },
                "changes": {
                    "type": "array",
                    "description": "Pre-computed field-level diffs between consecutive versions. Empty if fewer than 2 versions.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "from_version": {"type": "integer", "description": "Previous version number"},
                            "to_version": {"type": "integer", "description": "New version number"},
                            "sync_date": {"type": "string", "description": "When the new version was synced"},
                            "added": {"type": "object", "description": "Fields that were null/empty before and now have values"},
                            "removed": {"type": "object", "description": "Fields that had values before and are now null/empty"},
                            "modified": {
                                "type": "object",
                                "description": "Fields that changed value, each with {from, to}",
                            },
                            "total_changes": {"type": "integer", "description": "Total number of field changes"},
                        },
                    },
                },
            },
        },
        tags=["search", "forecasts", "history"],
        requires_llm=False,
        side_effects=False,
        is_primitive=True,
        payload_profile="full",
        examples=[
            {
                "description": "Get full history and diffs for a forecast",
                "params": {
                    "forecast_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                },
            },
            {
                "description": "Get history with source type hint for faster lookup",
                "params": {
                    "forecast_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                    "source_type": "apfs",
                },
            },
        ],
    )

    async def execute(self, ctx: FunctionContext, **params) -> FunctionResult:
        """Execute forecast history retrieval."""
        forecast_id = params.get("forecast_id", "").strip()
        source_type = params.get("source_type")

        if not forecast_id:
            return FunctionResult.failed_result(
                error="Missing forecast_id",
                message="forecast_id is required",
            )

        try:
            forecast_uuid = UUID(forecast_id)
        except ValueError:
            return FunctionResult.failed_result(
                error="Invalid UUID",
                message=f"Invalid forecast_id format: {forecast_id}",
            )

        try:
            from app.core.shared.forecast_service import forecast_service

            result = await forecast_service.get_forecast_history(
                session=ctx.session,
                organization_id=ctx.organization_id,
                forecast_id=forecast_uuid,
                source_type=source_type,
            )

            if not result:
                return FunctionResult.failed_result(
                    error="Not found",
                    message=f"Forecast not found: {forecast_id}",
                )

            total = result["total_versions"]
            changes = result.get("changes", [])

            if total == 0:
                summary = f"Forecast '{result['title']}' predates change tracking — no history available."
            elif total == 1:
                summary = f"Forecast '{result['title']}' has 1 version (no changes since first imported)."
            else:
                total_field_changes = sum(c["total_changes"] for c in changes)
                summary = (
                    f"Forecast '{result['title']}' has {total} versions with "
                    f"{total_field_changes} total field change(s) across {len(changes)} update(s). "
                    f"See 'changes' array for field-level diffs."
                )

            return FunctionResult.success_result(
                data=result,
                message=summary,
                metadata={
                    "forecast_id": forecast_id,
                    "source_type": result["source_type"],
                    "total_versions": total,
                    "total_updates": len(changes),
                },
            )

        except Exception as e:
            logger.exception(f"Failed to get forecast history: {e}")
            return FunctionResult.failed_result(
                error=str(e),
                message="Failed to retrieve forecast history",
            )
