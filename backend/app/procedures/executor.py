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

        # Log procedure start
        await ctx.log_run_event(
            level="INFO",
            event_type="procedure_start",
            message=f"Starting procedure: {definition.name}",
            context={
                "procedure_slug": definition.slug,
                "parameters": list(validated_params.keys()),
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

        # Log procedure completion
        await ctx.log_run_event(
            level="INFO" if status == "completed" else "WARN" if status == "partial" else "ERROR",
            event_type="procedure_complete",
            message=f"Procedure {definition.name} {status}",
            context={
                "status": status,
                "total_steps": total_steps,
                "completed_steps": completed_steps,
                "failed_steps": failed_steps,
                "duration_ms": duration_ms,
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
            )
            return result.lower() in ("true", "1", "yes")
        except Exception as e:
            logger.warning(f"Failed to evaluate condition '{condition}': {e}")
            return False

    async def _execute_step(self, ctx: FunctionContext, step: StepDefinition) -> Dict[str, Any]:
        """Execute a single step."""
        logger.info(f"Executing step: {step.name} (function: {step.function})")

        # Get function
        func = fn.get_or_none(step.function)
        if not func:
            return {
                "status": "failed",
                "error": f"Function not found: {step.function}",
            }

        # Render parameters with templates
        rendered_params = ctx.render_params(step.params)

        # Log step start
        await ctx.log_run_event(
            level="INFO",
            event_type="step_start",
            message=f"Starting step: {step.name}",
            context={
                "step": step.name,
                "function": step.function,
                "params_keys": list(rendered_params.keys()),
            },
        )

        # Execute function
        try:
            result: FunctionResult = await func(ctx, **rendered_params)

            # Log step completion
            await ctx.log_run_event(
                level="INFO" if result.success else "ERROR",
                event_type="step_complete",
                message=f"Step {step.name}: {result.status.value}",
                context={
                    "step": step.name,
                    "status": result.status.value,
                    "items_processed": result.items_processed,
                    "duration_ms": result.duration_ms,
                },
            )

            return result.to_dict()

        except Exception as e:
            logger.exception(f"Step {step.name} failed: {e}")
            return {
                "status": "failed",
                "error": str(e),
            }


# Global executor instance
procedure_executor = ProcedureExecutor()
