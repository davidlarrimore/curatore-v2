# backend/app/procedures/executor.py
"""
Procedure Executor - Execute procedure definitions.

Handles:
- Step-by-step execution
- Template rendering for parameters
- Error handling per step
- Run tracking and logging
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from .base import ProcedureDefinition, StepDefinition, OnErrorPolicy
from .loader import procedure_loader
from ..functions import fn, FunctionContext, FunctionResult

logger = logging.getLogger("curatore.procedures.executor")


class ProcedureExecutor:
    """
    Executes procedure definitions.

    Runs through steps sequentially, handling errors according to policy,
    and tracking execution via Run records.
    """

    async def execute(
        self,
        session: AsyncSession,
        organization_id: UUID,
        procedure_slug: str,
        params: Dict[str, Any] = None,
        user_id: Optional[UUID] = None,
        run_id: Optional[UUID] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        Execute a procedure by slug.

        Args:
            session: Database session
            organization_id: Organization context
            procedure_slug: Slug of procedure to execute
            params: Input parameters
            user_id: User who triggered execution
            run_id: Existing run ID (if called from task)
            dry_run: If true, don't make changes

        Returns:
            Execution results including step outputs
        """
        # Load procedure definition
        definition = procedure_loader.get(procedure_slug)
        if not definition:
            return {
                "status": "failed",
                "error": f"Procedure not found: {procedure_slug}",
            }

        return await self.execute_definition(
            session=session,
            organization_id=organization_id,
            definition=definition,
            params=params,
            user_id=user_id,
            run_id=run_id,
            dry_run=dry_run,
        )

    async def execute_definition(
        self,
        session: AsyncSession,
        organization_id: UUID,
        definition: ProcedureDefinition,
        params: Dict[str, Any] = None,
        user_id: Optional[UUID] = None,
        run_id: Optional[UUID] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        Execute a procedure definition.

        Args:
            session: Database session
            organization_id: Organization context
            definition: Procedure definition to execute
            params: Input parameters
            user_id: User who triggered execution
            run_id: Existing run ID
            dry_run: If true, don't make changes

        Returns:
            Execution results
        """
        params = params or {}
        start_time = datetime.utcnow()

        # Validate and apply default parameters
        validated_params = self._validate_params(definition, params)

        # Create function context
        ctx = await FunctionContext.create(
            session=session,
            organization_id=organization_id,
            user_id=user_id,
            run_id=run_id,
            procedure_id=None,  # Will be set if procedure is in DB
            params=validated_params,
            dry_run=dry_run,
        )

        # Log procedure start with input parameters
        await ctx.log_run_event(
            level="INFO",
            event_type="procedure_start",
            message=f"Starting procedure: {definition.name}",
            context={
                "procedure_slug": definition.slug,
                "procedure_version": definition.version,
                "input": self._truncate_for_log(validated_params),
                "steps": [s.name for s in definition.steps],
            },
        )

        # Execute steps
        step_results: Dict[str, Any] = {}
        failed_steps: List[str] = []
        last_error: Optional[str] = None

        for step in definition.steps:
            try:
                # Check step condition
                if step.condition:
                    condition_result = self._evaluate_condition(step.condition, ctx)
                    if not condition_result:
                        logger.info(f"Skipping step {step.name}: condition not met")
                        step_results[step.name] = {"skipped": True, "reason": "condition not met"}
                        ctx.set_step_result(step.name, step_results[step.name])
                        continue

                # Execute step
                result = await self._execute_step(ctx, step)
                step_results[step.name] = result

                # Store result for subsequent steps
                ctx.set_step_result(step.name, result.get("data") if result.get("status") == "success" else None)

                # Handle step failure
                if result.get("status") == "failed":
                    failed_steps.append(step.name)
                    last_error = result.get("error")

                    if step.on_error == OnErrorPolicy.FAIL or (step.on_error == OnErrorPolicy.FAIL and definition.on_error == OnErrorPolicy.FAIL):
                        logger.error(f"Step {step.name} failed, stopping procedure")
                        break
                    elif step.on_error == OnErrorPolicy.SKIP:
                        logger.warning(f"Step {step.name} failed, skipping")
                        continue
                    else:  # CONTINUE
                        logger.warning(f"Step {step.name} failed, continuing")
                        continue

            except Exception as e:
                logger.exception(f"Step {step.name} raised exception: {e}")
                failed_steps.append(step.name)
                last_error = str(e)
                step_results[step.name] = {
                    "status": "failed",
                    "error": str(e),
                }

                if step.on_error == OnErrorPolicy.FAIL:
                    break

        # Determine overall status
        total_steps = len(definition.steps)
        completed_steps = len([r for r in step_results.values() if r.get("status") == "success"])
        skipped_steps = len([r for r in step_results.values() if r.get("skipped")])

        if failed_steps and definition.on_error == OnErrorPolicy.FAIL:
            status = "failed"
        elif failed_steps:
            status = "partial"
        else:
            status = "completed"

        duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

        # Build step summary for logging
        step_summary = {}
        for step_name, step_result in step_results.items():
            step_summary[step_name] = {
                "status": step_result.get("status", "skipped" if step_result.get("skipped") else "unknown"),
                "items_processed": step_result.get("items_processed"),
                "error": step_result.get("error"),
            }

        # Log procedure completion
        await ctx.log_run_event(
            level="INFO" if status == "completed" else "WARN" if status == "partial" else "ERROR",
            event_type="procedure_complete",
            message=f"Procedure {definition.name} {status}",
            context={
                "status": status,
                "total_steps": total_steps,
                "completed_steps": completed_steps,
                "skipped_steps": skipped_steps,
                "failed_steps": failed_steps,
                "duration_ms": duration_ms,
                "step_summary": step_summary,
            },
        )

        return {
            "status": status,
            "procedure_slug": definition.slug,
            "procedure_version": definition.version,
            "step_results": step_results,
            "total_steps": total_steps,
            "completed_steps": completed_steps,
            "skipped_steps": skipped_steps,
            "failed_steps": failed_steps,
            "error": last_error,
            "duration_ms": duration_ms,
        }

    def _validate_params(self, definition: ProcedureDefinition, params: Dict[str, Any]) -> Dict[str, Any]:
        """Validate parameters and apply defaults."""
        validated = {}

        for param_def in definition.parameters:
            if param_def.name in params:
                validated[param_def.name] = params[param_def.name]
            elif param_def.required:
                raise ValueError(f"Missing required parameter: {param_def.name}")
            elif param_def.default is not None:
                validated[param_def.name] = param_def.default

        # Include any extra params not in definition (for flexibility)
        for key, value in params.items():
            if key not in validated:
                validated[key] = value

        return validated

    def _evaluate_condition(self, condition: str, ctx: FunctionContext) -> bool:
        """Evaluate a Jinja2 condition expression."""
        try:
            from jinja2 import Template
            template = Template("{{ " + condition + " }}")
            result = template.render(
                params=ctx.params,
                steps={
                    k.replace("steps.", ""): v
                    for k, v in ctx.variables.items()
                    if k.startswith("steps.")
                },
                # Add common Python functions for convenience
                len=len,
                str=str,
                int=int,
                bool=bool,
            )
            return result.lower() in ("true", "1", "yes")
        except Exception as e:
            logger.warning(f"Failed to evaluate condition '{condition}': {e}")
            return False

    def _serialize_data(self, data: Any) -> Any:
        """
        Serialize data for storage and template access.
        Converts ContentItem objects to dicts so they can be used in Jinja templates.
        """
        from ..functions.content import ContentItem

        if data is None:
            return None
        if isinstance(data, ContentItem):
            return data.to_dict()
        if isinstance(data, (list, tuple)):
            return [self._serialize_data(item) for item in data]
        if isinstance(data, dict):
            return {k: self._serialize_data(v) for k, v in data.items()}
        # Primitives pass through
        return data

    def _truncate_for_log(self, data: Any, max_length: int = 2000) -> Any:
        """Truncate data for logging to avoid huge log entries."""
        # First serialize ContentItem objects
        data = self._serialize_data(data)

        if data is None:
            return None
        if isinstance(data, str):
            if len(data) > max_length:
                return data[:max_length] + f"... [truncated, {len(data)} chars total]"
            return data
        if isinstance(data, (list, tuple)):
            if len(data) > 10:
                # Show first 5 and last 2 items
                truncated = list(data[:5]) + [f"... ({len(data) - 7} more items) ..."] + list(data[-2:])
                return [self._truncate_for_log(item, max_length // 10) for item in truncated]
            return [self._truncate_for_log(item, max_length // len(data) if data else max_length) for item in data]
        if isinstance(data, dict):
            result = {}
            for key, value in data.items():
                result[key] = self._truncate_for_log(value, max_length // max(len(data), 1))
            return result
        # For other types, convert to string if too long
        str_repr = str(data)
        if len(str_repr) > max_length:
            return str_repr[:max_length] + f"... [truncated]"
        return data

    async def _execute_step(self, ctx: FunctionContext, step: StepDefinition) -> Dict[str, Any]:
        """Execute a single step (or iterate if foreach is set)."""
        logger.info(f"Executing step: {step.name} (function: {step.function})")

        # Get function first to validate it exists
        func = fn.get_or_none(step.function)
        if not func:
            error_msg = f"Function not found: {step.function}"
            await ctx.log_run_event(
                level="ERROR",
                event_type="step_error",
                message=error_msg,
                context={
                    "step": step.name,
                    "function": step.function,
                },
            )
            return {
                "status": "failed",
                "error": error_msg,
            }

        # Check for foreach iteration
        if step.foreach:
            return await self._execute_step_foreach(ctx, step, func)

        # Standard single execution
        return await self._execute_step_single(ctx, step, func)

    async def _execute_step_single(
        self,
        ctx: FunctionContext,
        step: StepDefinition,
        func: Any,
        item: Any = None,
        item_index: int = None,
    ) -> Dict[str, Any]:
        """Execute a single function call (optionally with item context)."""
        # Render parameters with templates, including item if provided
        rendered_params = ctx.render_params(step.params, item=item)

        # Build log context
        log_context = {
            "step": step.name,
            "function": step.function,
            "input": self._truncate_for_log(rendered_params),
        }
        if item_index is not None:
            log_context["item_index"] = item_index

        # Log step start (only for non-foreach or first item)
        if item_index is None or item_index == 0:
            await ctx.log_run_event(
                level="INFO",
                event_type="step_start",
                message=f"Starting step: {step.name}" + (f" (foreach, {item_index + 1} items)" if item_index == 0 else ""),
                context=log_context,
            )

        # Execute function
        try:
            result: FunctionResult = await func(ctx, **rendered_params)

            # Serialize data for storage and template access
            serialized_data = self._serialize_data(result.data)

            # Log step completion (only for non-foreach calls)
            if item_index is None:
                await ctx.log_run_event(
                    level="INFO" if result.success else "ERROR",
                    event_type="step_complete",
                    message=f"Step {step.name}: {result.status.value}",
                    context={
                        "step": step.name,
                        "status": result.status.value,
                        "items_processed": result.items_processed,
                        "duration_ms": result.duration_ms,
                        "output": self._truncate_for_log(serialized_data),
                        "message": result.message,
                    },
                )

            # Return dict with full serialized data for subsequent steps
            return {
                "status": result.status.value,
                "data": serialized_data,
                "message": result.message,
                "error": result.error,
                "items_processed": result.items_processed,
                "items_failed": result.items_failed,
                "duration_ms": result.duration_ms,
                "metadata": result.metadata,
            }

        except Exception as e:
            logger.exception(f"Step {step.name} failed: {e}")
            if item_index is None:
                await ctx.log_run_event(
                    level="ERROR",
                    event_type="step_error",
                    message=f"Step {step.name} failed with exception: {str(e)}",
                    context={
                        "step": step.name,
                        "function": step.function,
                        "input": self._truncate_for_log(rendered_params),
                        "error_type": type(e).__name__,
                    },
                )
            return {
                "status": "failed",
                "error": str(e),
            }

    async def _execute_step_foreach(
        self,
        ctx: FunctionContext,
        step: StepDefinition,
        func: Any,
    ) -> Dict[str, Any]:
        """Execute a step with foreach iteration."""
        # Evaluate the foreach expression to get items
        items = ctx.render_params({"_foreach": step.foreach}).get("_foreach")

        # Normalize to list
        if items is None:
            items = []
        elif not isinstance(items, list):
            items = [items]  # Single item → list of one

        # Log foreach start
        await ctx.log_run_event(
            level="INFO",
            event_type="step_start",
            message=f"Starting step: {step.name} (foreach: {len(items)} items)",
            context={
                "step": step.name,
                "function": step.function,
                "foreach_count": len(items),
            },
        )

        if not items:
            # No items - return empty result
            await ctx.log_run_event(
                level="INFO",
                event_type="step_complete",
                message=f"Step {step.name}: skipped (no items)",
                context={
                    "step": step.name,
                    "status": "success",
                    "items_processed": 0,
                },
            )
            return {
                "status": "success",
                "data": [],
                "message": "No items to process",
                "items_processed": 0,
                "items_failed": 0,
            }

        # Execute for each item
        results = []
        failed_count = 0
        total_duration_ms = 0
        start_time = datetime.utcnow()

        for idx, item in enumerate(items):
            # Execute function with item in context
            item_result = await self._execute_step_single(ctx, step, func, item=item, item_index=idx)

            # Extract item ID if available
            item_id = None
            if isinstance(item, dict):
                item_id = item.get("id") or item.get("item_id") or str(idx)
            else:
                item_id = str(idx)

            # Collect result
            results.append({
                "item_id": item_id,
                "success": item_result.get("status") == "success",
                "result": item_result.get("data"),
                "error": item_result.get("error"),
            })

            if item_result.get("status") != "success":
                failed_count += 1

            if item_result.get("duration_ms"):
                total_duration_ms += item_result.get("duration_ms", 0)

        # Calculate total duration
        total_duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

        # Determine overall status
        if failed_count == len(items):
            status = "failed"
        elif failed_count > 0:
            status = "partial"
        else:
            status = "success"

        # Log foreach completion
        await ctx.log_run_event(
            level="INFO" if status == "success" else "WARN" if status == "partial" else "ERROR",
            event_type="step_complete",
            message=f"Step {step.name}: {status} ({len(items) - failed_count}/{len(items)} succeeded)",
            context={
                "step": step.name,
                "status": status,
                "items_processed": len(items),
                "items_failed": failed_count,
                "duration_ms": total_duration_ms,
            },
        )

        return {
            "status": status,
            "data": results,
            "message": f"Processed {len(items) - failed_count}/{len(items)} items",
            "items_processed": len(items),
            "items_failed": failed_count,
            "duration_ms": total_duration_ms,
        }


# Global executor instance
procedure_executor = ProcedureExecutor()
