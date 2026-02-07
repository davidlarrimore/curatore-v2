# backend/app/functions/output/log.py
"""
Log function - Print debug messages to the job activity log.

Outputs a message and optional data to the run's activity log for debugging
procedures and pipelines. Useful for inspecting intermediate values during
workflow development.

Example usage in a procedure:
    - name: fetch_notices
      function: query_model
      params:
        model: SamNotice
        filters:
          status: active

    - name: debug_notices
      function: log
      params:
        message: "Fetched notices from database"
        data: "{{ steps.fetch_notices }}"
        label: "fetch_result"

    - name: check_count
      function: log
      params:
        message: "Notice count: {{ steps.fetch_notices | length }}"
        level: INFO
"""

import json
from typing import Any, Dict, List, Optional
import logging

from ..base import (
    BaseFunction,
    FunctionMeta,
    FunctionCategory,
    FunctionResult,
    ParameterDoc,
    OutputFieldDoc,
    OutputSchema,
)
from ..context import FunctionContext

logger = logging.getLogger("curatore.functions.output.log")

# Maximum length for data preview in logs
MAX_DATA_PREVIEW_LENGTH = 2000
MAX_ITEMS_PREVIEW = 10


def _format_data_for_log(data: Any) -> Dict[str, Any]:
    """
    Format data for logging, with type info and preview.

    Handles various data types and truncates large data for readability.
    """
    if data is None:
        return {"type": "null", "value": None}

    data_type = type(data).__name__

    # Handle primitives
    if isinstance(data, (str, int, float, bool)):
        value = data
        if isinstance(data, str) and len(data) > MAX_DATA_PREVIEW_LENGTH:
            value = data[:MAX_DATA_PREVIEW_LENGTH] + f"... (truncated, {len(data)} chars total)"
        return {"type": data_type, "value": value}

    # Handle lists
    if isinstance(data, (list, tuple)):
        count = len(data)
        preview = []
        for i, item in enumerate(data[:MAX_ITEMS_PREVIEW]):
            if isinstance(item, dict):
                # Show keys for dict items
                preview.append({k: _summarize_value(v) for k, v in list(item.items())[:5]})
            else:
                preview.append(_summarize_value(item))

        result = {
            "type": "list",
            "count": count,
            "preview": preview,
        }
        if count > MAX_ITEMS_PREVIEW:
            result["truncated"] = True
            result["showing"] = MAX_ITEMS_PREVIEW
        return result

    # Handle dicts
    if isinstance(data, dict):
        keys = list(data.keys())
        preview = {k: _summarize_value(data[k]) for k in keys[:10]}

        result = {
            "type": "dict",
            "keys": keys[:20],
            "key_count": len(keys),
            "preview": preview,
        }
        if len(keys) > 20:
            result["truncated"] = True
        return result

    # Handle FunctionResult-like objects
    if hasattr(data, "to_dict"):
        try:
            return {"type": data_type, "value": data.to_dict()}
        except Exception:
            pass

    # Handle objects with __dict__
    if hasattr(data, "__dict__"):
        return {
            "type": data_type,
            "attributes": list(vars(data).keys())[:20],
        }

    # Fallback: string representation
    try:
        str_repr = str(data)
        if len(str_repr) > MAX_DATA_PREVIEW_LENGTH:
            str_repr = str_repr[:MAX_DATA_PREVIEW_LENGTH] + "..."
        return {"type": data_type, "value": str_repr}
    except Exception:
        return {"type": data_type, "value": "<unrepresentable>"}


def _summarize_value(value: Any) -> Any:
    """Create a brief summary of a value for nested previews."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        if isinstance(value, str) and len(value) > 100:
            return value[:100] + "..."
        return value
    if isinstance(value, (list, tuple)):
        return f"[{len(value)} items]"
    if isinstance(value, dict):
        return f"{{{len(value)} keys}}"
    return f"<{type(value).__name__}>"


class LogFunction(BaseFunction):
    """
    Print a debug message to the job activity log.

    Outputs a message and optional data to the run's activity log for debugging.
    When executing within a procedure or pipeline, logs are visible in the
    Job Activity Monitor. When no run context exists, logs go to the application
    logger.

    Supports:
    - Simple text messages
    - Data inspection from prior step results ({{ steps.xxx }})
    - Multiple log levels (INFO, WARN, ERROR)
    - Custom labels for organizing log entries

    Example:
        result = await fn.log(ctx,
            message="Processing complete",
            data={"items_processed": 10, "errors": 0},
            level="INFO",
            label="processing_summary",
        )
    """

    meta = FunctionMeta(
        name="log",
        category=FunctionCategory.OUTPUT,
        description="Print a debug message to the job activity log",
        parameters=[
            ParameterDoc(
                name="message",
                type="str",
                description="The message to log. Supports Jinja2 templates like {{ steps.xxx }}",
                required=True,
                example="Processed {{ steps.fetch.count }} items",
            ),
            ParameterDoc(
                name="data",
                type="any",
                description="Optional data to include in the log. Can be a step result ({{ steps.xxx }}), a variable, or any value to inspect",
                required=False,
                default=None,
                example="{{ steps.fetch_notices }}",
            ),
            ParameterDoc(
                name="level",
                type="str",
                description="Log level: INFO, WARN, or ERROR",
                required=False,
                default="INFO",
                enum_values=["INFO", "WARN", "ERROR"],
            ),
            ParameterDoc(
                name="label",
                type="str",
                description="Optional label/tag for the log entry (appears in event_type as 'debug:{label}')",
                required=False,
                default=None,
                example="fetch_result",
            ),
        ],
        returns="dict: {message: str, level: str, logged: bool}",
        output_schema=OutputSchema(
            type="dict",
            description="Log operation result with status information",
            fields=[
                OutputFieldDoc(name="message", type="str",
                              description="The message that was logged"),
                OutputFieldDoc(name="level", type="str",
                              description="Log level (INFO, WARN, ERROR)",
                              example="INFO"),
                OutputFieldDoc(name="label", type="str",
                              description="Custom label/tag for the log entry",
                              nullable=True),
                OutputFieldDoc(name="logged_to_run", type="bool",
                              description="Whether the message was logged to the run activity log"),
                OutputFieldDoc(name="has_data", type="bool",
                              description="Whether data was included in the log entry"),
            ],
        ),
        tags=["output", "debug", "logging", "inspect"],
        requires_llm=False,
        examples=[
            {
                "description": "Simple debug message",
                "params": {
                    "message": "Starting data processing",
                },
            },
            {
                "description": "Log data from a prior step",
                "params": {
                    "message": "Query results",
                    "data": "{{ steps.fetch_notices }}",
                    "label": "query_data",
                },
            },
            {
                "description": "Warning with context",
                "params": {
                    "message": "Low results count, may need adjustment",
                    "data": {"count": 5, "expected": 20},
                    "level": "WARN",
                },
            },
            {
                "description": "Error logging",
                "params": {
                    "message": "Validation failed for input data",
                    "data": {"field": "email", "error": "Invalid format"},
                    "level": "ERROR",
                    "label": "validation",
                },
            },
        ],
    )

    async def execute(self, ctx: FunctionContext, **params) -> FunctionResult:
        """Execute the log function."""
        message = params["message"]
        data = params.get("data")
        level = params.get("level", "INFO").upper()
        label = params.get("label")

        # Validate level
        if level not in ("INFO", "WARN", "ERROR"):
            level = "INFO"

        # Build event type
        event_type = "debug"
        if label:
            event_type = f"debug:{label}"

        # Format data for logging context
        log_context: Dict[str, Any] = {}
        if data is not None:
            log_context["data"] = _format_data_for_log(data)

        # Log to run activity log if run_id exists
        logged_to_run = False
        if ctx.run_id:
            try:
                await ctx.log_run_event(
                    level=level,
                    event_type=event_type,
                    message=message,
                    context=log_context if log_context else None,
                )
                logged_to_run = True
            except Exception as e:
                logger.warning(f"Failed to log to run: {e}")

        # Always log to application logger as well
        log_func = {
            "INFO": logger.info,
            "WARN": logger.warning,
            "ERROR": logger.error,
        }.get(level, logger.info)

        log_msg = f"[{event_type}] {message}"
        if data is not None:
            # Add abbreviated data to app log
            try:
                data_str = json.dumps(_format_data_for_log(data), default=str)
                if len(data_str) > 500:
                    data_str = data_str[:500] + "..."
                log_msg += f" | data: {data_str}"
            except Exception:
                log_msg += f" | data: <{type(data).__name__}>"

        log_func(log_msg)

        return FunctionResult.success_result(
            data={
                "message": message,
                "level": level,
                "label": label,
                "logged_to_run": logged_to_run,
                "has_data": data is not None,
            },
            message=f"Logged [{level}]: {message[:100]}{'...' if len(message) > 100 else ''}",
            metadata={
                "event_type": event_type,
                "run_id": str(ctx.run_id) if ctx.run_id else None,
            },
        )
