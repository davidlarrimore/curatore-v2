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
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

import asyncio

from ..store.definitions import ProcedureDefinition, StepDefinition, OnErrorPolicy
from ..store.loader import procedure_loader
from app.cwr.tools import fn, FunctionContext, FunctionResult
from app.cwr.tools.base import FlowResult
from app.core.shared.database_service import database_service

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

        Loads the procedure definition from:
        1. YAML files (via procedure_loader) - for system/file-based procedures
        2. Database (via Procedure model) - for user-created procedures

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
        # Try YAML loader first (for system/file-based procedures)
        definition = procedure_loader.get(procedure_slug)

        # Fall back to database (for user-created procedures)
        if not definition:
            definition = await self._load_from_database(session, organization_id, procedure_slug)

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

    async def _load_from_database(
        self,
        session: AsyncSession,
        organization_id: UUID,
        procedure_slug: str,
    ) -> Optional[ProcedureDefinition]:
        """
        Load a procedure definition from the database.

        Used for user-created procedures that don't have YAML files.
        """
        from sqlalchemy import select
        from app.core.database.procedures import Procedure

        try:
            query = select(Procedure).where(
                Procedure.organization_id == organization_id,
                Procedure.slug == procedure_slug,
                Procedure.is_active == True,
            )
            result = await session.execute(query)
            procedure = result.scalar_one_or_none()

            if not procedure or not procedure.definition:
                return None

            # Convert database definition to ProcedureDefinition
            return ProcedureDefinition.from_dict(
                data=procedure.definition,
                source_type=procedure.source_type,
                source_path=procedure.source_path,
            )
        except Exception as e:
            logger.warning(f"Failed to load procedure {procedure_slug} from database: {e}")
            return None

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

        # Propagate trace context: if run exists, ensure it has a trace_id
        trace_id = None
        if run_id:
            try:
                from sqlalchemy import select, update
                from app.core.database.models import Run
                run_result = await session.execute(
                    select(Run.trace_id).where(Run.id == run_id)
                )
                trace_id = run_result.scalar_one_or_none()
                if not trace_id:
                    # First run in a trace — use the run_id as trace root
                    trace_id = str(run_id)
                    await session.execute(
                        update(Run).where(Run.id == run_id).values(trace_id=trace_id)
                    )
                    await session.flush()
                ctx.set_variable("_trace_id", trace_id)
            except Exception as e:
                logger.warning(f"Failed to propagate trace context: {e}")

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

        # Build step summary for logging and results_summary
        step_fn_map = {s.name: s.function for s in definition.steps}
        step_summary = {}
        for step_name, step_result in step_results.items():
            step_summary[step_name] = {
                "function": step_fn_map.get(step_name),
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

        # Update trigger timestamps for cron triggers (regardless of success/failure)
        await self._update_trigger_timestamps(session, organization_id, definition.slug)

        # Build lean results_summary — full step output lives in individual log events
        result = {
            "status": status,
            "procedure_slug": definition.slug,
            "procedure_version": definition.version,
            "step_summary": step_summary,
            "total_steps": total_steps,
            "completed_steps": completed_steps,
            "skipped_steps": skipped_steps,
            "failed_steps": failed_steps,
            "error": last_error,
            "duration_ms": duration_ms,
        }

        side_effect_steps = [
            step_name
            for step_name, step_result in step_results.items()
            if step_result.get("side_effects")
        ]
        if side_effect_steps:
            result["governance"] = {
                "side_effect_steps": side_effect_steps,
                "total_side_effects": len(side_effect_steps),
            }

        return result

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
        from app.cwr.tools.content import ContentItem

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

        # Governance: check exposure_profile
        exposure = getattr(func.meta, 'exposure_profile', {})
        if not exposure.get("procedure", True):
            error_msg = f"Function '{step.function}' is not available in procedure context"
            await ctx.log_run_event(
                level="ERROR",
                event_type="governance_violation",
                message=error_msg,
                context={"step": step.name, "function": step.function},
            )
            return {
                "status": "failed",
                "error": error_msg,
            }

        # Governance: log side-effect usage
        if func.meta.side_effects:
            await ctx.log_run_event(
                level="INFO",
                event_type="governance",
                message=f"Step '{step.name}' uses function '{step.function}' with side_effects=True",
                context={
                    "step": step.name,
                    "function": step.function,
                    "side_effects": True,
                    "payload_profile": func.meta.payload_profile,
                },
            )

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
            step_start = time.monotonic()
            result: FunctionResult = await func(ctx, **rendered_params)
            step_duration_ms = int((time.monotonic() - step_start) * 1000)

            # Check if this is a FlowResult with branches to execute
            if isinstance(result, FlowResult) and step.branches:
                flow_result = await self._execute_flow(ctx, step, result, item=item, item_index=item_index)
                # Log step completion for flow functions
                flow_log_context = {
                    "step": step.name,
                    "status": flow_result.get("status"),
                    "flow_type": step.function,
                    "duration_ms": flow_result.get("duration_ms"),
                    "output": flow_result.get("data"),
                }
                if item_index is not None:
                    flow_log_context["item_index"] = item_index
                await ctx.log_run_event(
                    level="INFO" if flow_result.get("status") == "success" else "ERROR",
                    event_type="step_complete",
                    message=f"Step {step.name}: {flow_result.get('status')}" + (f" (item {item_index})" if item_index is not None else ""),
                    context=flow_log_context,
                )
                return flow_result

            # Serialize data for storage and template access
            serialized_data = self._serialize_data(result.data)

            # Log step completion
            log_context = {
                "step": step.name,
                "function": step.function,
                "status": result.status.value,
                "items_processed": result.items_processed,
                "duration_ms": step_duration_ms,
                "output": serialized_data,
                "message": result.message,
                "payload_profile": func.meta.payload_profile,
                "side_effects": func.meta.side_effects,
            }
            if item_index is not None:
                log_context["item_index"] = item_index
            await ctx.log_run_event(
                level="INFO" if result.success else "ERROR",
                event_type="step_complete",
                message=f"Step {step.name}: {result.status.value}" + (f" (item {item_index})" if item_index is not None else ""),
                context=log_context,
            )

            # Return dict with full serialized data for subsequent steps
            return {
                "status": result.status.value,
                "data": serialized_data,
                "message": result.message,
                "error": result.error,
                "items_processed": result.items_processed,
                "items_failed": result.items_failed,
                "duration_ms": step_duration_ms,
                "metadata": result.metadata,
                "side_effects": func.meta.side_effects,
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

    async def _execute_flow(
        self,
        ctx: FunctionContext,
        step: StepDefinition,
        flow_result: FlowResult,
        item: Any = None,
        item_index: int = None,
    ) -> Dict[str, Any]:
        """
        Execute branches based on FlowResult from a flow control function.

        Handles:
        - branch_key (if_branch, switch_branch): run a single named branch
        - branches_to_run (parallel): run multiple branches concurrently
        - items_to_iterate (foreach): iterate over items with the 'each' branch
        """
        start_time = datetime.utcnow()

        # if_branch / switch_branch: single branch by key
        if flow_result.branch_key is not None:
            return await self._execute_single_branch(
                ctx, step, flow_result.branch_key, item=item, item_index=item_index
            )

        # parallel: run all branches concurrently (empty list means "all")
        if flow_result.branches_to_run is not None:
            max_concurrency = flow_result.metadata.get("max_concurrency", 0) if flow_result.metadata else 0
            return await self._execute_parallel_branches(
                ctx, step, max_concurrency, on_error=step.on_error
            )

        # foreach: iterate over items
        if flow_result.items_to_iterate is not None:
            concurrency = flow_result.metadata.get("concurrency", 1) if flow_result.metadata else 1
            condition = flow_result.metadata.get("condition") if flow_result.metadata else None
            return await self._execute_foreach_branches(
                ctx, step, flow_result.items_to_iterate, concurrency, condition, on_error=step.on_error
            )

        # No flow control directive - return the flow result data as-is
        return {
            "status": "success",
            "data": flow_result.data,
            "message": flow_result.message,
            "duration_ms": int((datetime.utcnow() - start_time).total_seconds() * 1000),
        }

    async def _execute_single_branch(
        self,
        ctx: FunctionContext,
        step: StepDefinition,
        branch_key: str,
        item: Any = None,
        item_index: int = None,
    ) -> Dict[str, Any]:
        """Execute a single named branch (for if_branch, switch_branch)."""
        start_time = datetime.utcnow()

        branch_steps = step.branches.get(branch_key) if step.branches else None

        if not branch_steps:
            # No matching branch - check for default (switch_branch)
            branch_steps = step.branches.get("default") if step.branches else None
            if branch_steps:
                branch_key = "default"
                logger.info(f"[{step.function} {step.name}] no match for '{branch_key}', using default")
            else:
                # No branch to run - this is a no-op
                logger.info(f"[{step.function} {step.name}] no branch '{branch_key}' and no default → no-op")
                return {
                    "status": "success",
                    "data": None,
                    "message": f"No matching branch '{branch_key}'",
                    "duration_ms": int((datetime.utcnow() - start_time).total_seconds() * 1000),
                }

        logger.info(f"[{step.function} {step.name}] executing branch '{branch_key}' ({len(branch_steps)} steps)")

        # Execute branch steps sequentially
        result = await self._execute_branch_steps(ctx, branch_steps, item=item, item_index=item_index)

        return {
            "status": result.get("status", "success"),
            "data": result.get("data"),
            "message": f"Executed branch '{branch_key}'",
            "branch": branch_key,
            "duration_ms": int((datetime.utcnow() - start_time).total_seconds() * 1000),
            "error": result.get("error"),
        }

    async def _execute_parallel_branches(
        self,
        ctx: FunctionContext,
        step: StepDefinition,
        max_concurrency: int = 0,
        on_error: OnErrorPolicy = OnErrorPolicy.FAIL,
    ) -> Dict[str, Any]:
        """Execute multiple branches concurrently (for parallel)."""
        start_time = datetime.utcnow()

        if not step.branches:
            return {
                "status": "failed",
                "error": "No branches defined for parallel",
                "duration_ms": 0,
            }

        branch_names = list(step.branches.keys())
        logger.info(f"[parallel {step.name}] running {len(branch_names)} branches: {branch_names}")

        # Create semaphore for concurrency control
        semaphore = asyncio.Semaphore(max_concurrency) if max_concurrency > 0 else None

        async def run_branch(branch_name: str) -> tuple:
            """Run a single branch with its own database session."""
            try:
                async with database_service.get_session() as branch_session:
                    # Create a new context with its own session for this branch
                    branch_ctx = await FunctionContext.create(
                        session=branch_session,
                        organization_id=ctx.organization_id,
                        user_id=ctx.user_id,
                        run_id=ctx.run_id,
                        dry_run=ctx.dry_run,
                    )
                    # Copy step results from parent context
                    for key, value in ctx.variables.items():
                        if key.startswith("steps."):
                            branch_ctx.variables[key] = value

                    if semaphore:
                        async with semaphore:
                            result = await self._execute_branch_steps(branch_ctx, step.branches[branch_name])
                    else:
                        result = await self._execute_branch_steps(branch_ctx, step.branches[branch_name])
                    return branch_name, result
            except Exception as e:
                logger.exception(f"[parallel {step.name}] branch '{branch_name}' raised exception: {e}")
                return branch_name, {"status": "failed", "error": str(e), "data": None}

        # Run all branches concurrently
        tasks = [run_branch(name) for name in branch_names]

        if on_error == OnErrorPolicy.FAIL:
            # If any branch fails, we want to know immediately
            # Use gather with return_exceptions to collect all results
            results = await asyncio.gather(*tasks, return_exceptions=True)
        else:
            # Continue on error - collect all results
            results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        branch_results = {}
        failed_branches = []
        for item in results:
            if isinstance(item, Exception):
                # An exception occurred in the coroutine
                logger.error(f"[parallel {step.name}] branch failed with exception: {item}")
                failed_branches.append("unknown")
                continue
            branch_name, result = item
            branch_results[branch_name] = result.get("data")
            if result.get("status") == "failed":
                failed_branches.append(branch_name)
                logger.warning(f"[parallel {step.name}] branch '{branch_name}' failed: {result.get('error')}")

        # Determine status
        if failed_branches and on_error == OnErrorPolicy.FAIL:
            status = "failed"
        elif failed_branches:
            status = "partial"
        else:
            status = "success"

        return {
            "status": status,
            "data": branch_results,
            "message": f"Executed {len(branch_names)} branches ({len(failed_branches)} failed)",
            "branches_executed": branch_names,
            "branches_failed": failed_branches,
            "duration_ms": int((datetime.utcnow() - start_time).total_seconds() * 1000),
        }

    async def _execute_foreach_branches(
        self,
        ctx: FunctionContext,
        step: StepDefinition,
        items: List[Any],
        concurrency: int = 1,
        condition: Optional[str] = None,
        on_error: OnErrorPolicy = OnErrorPolicy.FAIL,
    ) -> Dict[str, Any]:
        """Execute 'each' branch for every item in the list (for foreach)."""
        start_time = datetime.utcnow()

        # Get the 'each' branch
        each_steps = step.branches.get("each") if step.branches else None
        if not each_steps:
            return {
                "status": "failed",
                "error": "foreach requires 'branches.each' with at least one step",
                "duration_ms": 0,
            }

        logger.info(f"[foreach {step.name}] {len(items)} items, concurrency={concurrency}")

        # Apply condition filter if present
        filtered_items = []
        skipped_indices = []
        for idx, item in enumerate(items):
            if condition:
                # Evaluate condition with item context
                cond_result = self._evaluate_condition_with_item(condition, ctx, item, idx)
                if not cond_result:
                    skipped_indices.append(idx)
                    continue
            filtered_items.append((idx, item))

        if skipped_indices:
            logger.info(f"[foreach {step.name}] filtered to {len(filtered_items)} items (skipped {len(skipped_indices)})")

        if not filtered_items:
            return {
                "status": "success",
                "data": [],
                "message": "No items to process (all filtered)",
                "items_processed": 0,
                "items_skipped": len(skipped_indices),
                "items_failed": 0,
                "duration_ms": int((datetime.utcnow() - start_time).total_seconds() * 1000),
            }

        # Execute for each item
        results = [None] * len(items)  # Preserve original indices
        failed_count = 0

        if concurrency == 1:
            # Sequential execution
            for orig_idx, item in filtered_items:
                result = await self._execute_branch_steps(ctx, each_steps, item=item, item_index=orig_idx)
                results[orig_idx] = result.get("data")
                if result.get("status") == "failed":
                    failed_count += 1
                    if on_error == OnErrorPolicy.FAIL:
                        break
        else:
            # Concurrent execution - each task gets its own database session
            # to avoid SQLAlchemy async session conflicts
            semaphore = asyncio.Semaphore(concurrency) if concurrency > 0 else None

            async def run_item(orig_idx: int, item: Any) -> tuple:
                """Run a single foreach item with its own database session."""
                try:
                    async with database_service.get_session() as item_session:
                        # Create a new context with its own session for this item
                        item_ctx = await FunctionContext.create(
                            session=item_session,
                            organization_id=ctx.organization_id,
                            user_id=ctx.user_id,
                            run_id=ctx.run_id,
                            dry_run=ctx.dry_run,
                        )
                        # Copy step results from parent context so templates can reference them
                        for key, value in ctx.variables.items():
                            if key.startswith("steps."):
                                item_ctx.variables[key] = value

                        if semaphore:
                            async with semaphore:
                                result = await self._execute_branch_steps(item_ctx, each_steps, item=item, item_index=orig_idx)
                        else:
                            result = await self._execute_branch_steps(item_ctx, each_steps, item=item, item_index=orig_idx)
                        return orig_idx, result
                except Exception as e:
                    logger.exception(f"[foreach {step.name}] item {orig_idx} raised exception: {e}")
                    return orig_idx, {"status": "failed", "error": str(e), "data": None}

            tasks = [run_item(orig_idx, item) for orig_idx, item in filtered_items]
            task_results = await asyncio.gather(*tasks, return_exceptions=True)

            for task_result in task_results:
                if isinstance(task_result, Exception):
                    logger.error(f"[foreach {step.name}] concurrent task exception: {task_result}")
                    failed_count += 1
                    continue
                orig_idx, result = task_result
                results[orig_idx] = result.get("data")
                if result.get("status") == "failed":
                    logger.warning(f"[foreach {step.name}] item {orig_idx} failed: {result.get('error', 'unknown')}")
                    failed_count += 1

        # Determine status
        if failed_count == len(filtered_items):
            status = "failed"
        elif failed_count > 0:
            status = "partial"
        else:
            status = "success"

        return {
            "status": status,
            "data": results,
            "message": f"Processed {len(filtered_items) - failed_count}/{len(filtered_items)} items",
            "items_processed": len(filtered_items),
            "items_skipped": len(skipped_indices),
            "items_failed": failed_count,
            "duration_ms": int((datetime.utcnow() - start_time).total_seconds() * 1000),
        }

    async def _execute_branch_steps(
        self,
        ctx: FunctionContext,
        steps: List[StepDefinition],
        item: Any = None,
        item_index: int = None,
    ) -> Dict[str, Any]:
        """Execute a list of steps sequentially, return result of last step."""
        result = None
        last_data = None

        for branch_step in steps:
            # Check step condition
            if branch_step.condition:
                cond_result = self._evaluate_condition_with_item(branch_step.condition, ctx, item, item_index)
                if not cond_result:
                    logger.debug(f"Skipping branch step {branch_step.name}: condition not met")
                    continue

            # Get function
            func = fn.get_or_none(branch_step.function)
            if not func:
                return {
                    "status": "failed",
                    "error": f"Function not found: {branch_step.function}",
                }

            # Check for legacy foreach on branch step
            if branch_step.foreach:
                result = await self._execute_step_foreach(ctx, branch_step, func)
            else:
                result = await self._execute_step_single(ctx, branch_step, func, item=item, item_index=item_index)

            # Store result for subsequent steps in this branch
            ctx.set_step_result(branch_step.name, result.get("data") if result.get("status") == "success" else None)
            last_data = result.get("data")

            # Handle errors
            if result.get("status") == "failed":
                if branch_step.on_error == OnErrorPolicy.FAIL:
                    return result
                elif branch_step.on_error == OnErrorPolicy.SKIP:
                    continue
                # CONTINUE - keep going

        return {
            "status": "success" if result is None or result.get("status") == "success" else result.get("status"),
            "data": last_data,
            "error": result.get("error") if result else None,
        }

    def _evaluate_condition_with_item(
        self,
        condition: str,
        ctx: FunctionContext,
        item: Any = None,
        item_index: int = None,
    ) -> bool:
        """Evaluate a Jinja2 condition with item context."""
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
                item=item,
                item_index=item_index,
                len=len,
                str=str,
                int=int,
                bool=bool,
            )
            return result.lower() in ("true", "1", "yes")
        except Exception as e:
            logger.warning(f"Failed to evaluate condition '{condition}': {e}")
            return False

    async def _execute_step_foreach(
        self,
        ctx: FunctionContext,
        step: StepDefinition,
        func: Any,
    ) -> Dict[str, Any]:
        """Execute a step with foreach iteration (legacy single-step foreach)."""
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

    async def _update_trigger_timestamps(
        self,
        session: AsyncSession,
        organization_id: UUID,
        procedure_slug: str,
    ) -> None:
        """
        Update trigger timestamps after procedure execution.

        Sets last_triggered_at to now and recalculates next_trigger_at
        for all active cron triggers of this procedure.
        """
        from croniter import croniter
        from sqlalchemy import select
        from app.core.database.procedures import Procedure, ProcedureTrigger

        try:
            # Find the procedure
            proc_query = select(Procedure).where(
                Procedure.organization_id == organization_id,
                Procedure.slug == procedure_slug,
            )
            result = await session.execute(proc_query)
            procedure = result.scalar_one_or_none()

            if not procedure:
                logger.debug(f"No procedure found for slug {procedure_slug}, skipping trigger update")
                return

            # Get active cron triggers
            trigger_query = select(ProcedureTrigger).where(
                ProcedureTrigger.procedure_id == procedure.id,
                ProcedureTrigger.is_active == True,
                ProcedureTrigger.trigger_type == "cron",
            )
            result = await session.execute(trigger_query)
            triggers = result.scalars().all()

            if not triggers:
                return

            now = datetime.utcnow()

            for trigger in triggers:
                # Update last_triggered_at
                trigger.last_triggered_at = now
                trigger.trigger_count = (trigger.trigger_count or 0) + 1

                # Calculate next trigger time
                if trigger.cron_expression:
                    try:
                        cron = croniter(trigger.cron_expression, now)
                        trigger.next_trigger_at = cron.get_next(datetime)
                    except Exception as e:
                        logger.warning(f"Failed to calculate next trigger time: {e}")

            await session.commit()
            logger.debug(f"Updated {len(triggers)} trigger(s) for procedure {procedure_slug}")

        except Exception as e:
            logger.warning(f"Failed to update trigger timestamps for {procedure_slug}: {e}")
            # Don't fail the procedure execution due to trigger update failure


# Global executor instance
procedure_executor = ProcedureExecutor()
