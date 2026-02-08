# backend/app/functions/flow/parallel.py
"""
Parallel function - Execute multiple branches simultaneously.

Runs multiple independent branches concurrently. Use when steps have no
dependencies on each other and can safely run at the same time.

Example usage in a procedure:
    - name: enrich
      function: parallel
      params:
        max_concurrency: 3
      branches:
        entities:
          - name: extract_entities
            function: llm_extract
        sentiment:
          - name: analyze_sentiment
            function: llm_generate
        classification:
          - name: classify_topics
            function: llm_classify
"""

import logging
from typing import List

from ...base import (
    BaseFunction,
    FunctionMeta,
    FunctionCategory,
    FlowResult,
    ParameterDoc,
    OutputFieldDoc,
    OutputSchema,
)
from ...context import FunctionContext

logger = logging.getLogger("curatore.functions.flow.parallel")


class ParallelFunction(BaseFunction):
    """
    Execute multiple named branches simultaneously.

    Use when steps have no dependencies on each other and can safely run
    at the same time. All branches must complete before the procedure continues.

    Each branch executes its steps sequentially within itself, but all branches
    run concurrently with each other.

    Branches cannot reference each other's step outputs - each branch sees only
    the shared context from before the parallel step, plus its own internal
    step outputs.

    Returns a FlowResult with branches_to_run listing all branch names.
    The executor handles the actual concurrent execution.
    """

    meta = FunctionMeta(
        name="parallel",
        category=FunctionCategory.FLOW,
        description="Execute multiple named branches simultaneously. REQUIRES 'branches' with at least 2 named branches (e.g., 'branches.task_a', 'branches.task_b'). Use when steps have no dependencies on each other. All branches must complete before continuing.",
        parameters=[
            ParameterDoc(
                name="max_concurrency",
                type="int",
                description="Maximum number of branches to run simultaneously. 0 or omitted = no limit.",
                required=False,
                default=0,
                example=2,
            ),
        ],
        returns="FlowResult with branches_to_run listing all branch names",
        output_schema=OutputSchema(
            type="FlowResult",
            description="Flow control result for parallel branch execution",
            fields=[
                OutputFieldDoc(name="max_concurrency", type="int",
                              description="Maximum number of branches to run simultaneously (0 = unlimited)"),
            ],
        ),
        tags=["flow", "parallel", "concurrent", "branching"],
        requires_llm=False,
        side_effects=False,
        is_primitive=True,
        payload_profile="full",
        examples=[
            {
                "description": "Run three analyses in parallel",
                "params": {},
            },
            {
                "description": "Rate-limited parallel with max 2 concurrent",
                "params": {"max_concurrency": 2},
            },
        ],
    )

    async def execute(self, ctx: FunctionContext, **params) -> FlowResult:
        """Return all branch names for parallel execution."""
        max_concurrency = params.get("max_concurrency", 0)

        # The function doesn't know the branch names - those are in the step definition
        # We return a special marker that tells the executor to run ALL branches
        # The executor will enumerate the branches from step.branches

        logger.info(
            f"[parallel] max_concurrency={max_concurrency} → executor will run all branches concurrently"
        )

        return FlowResult.success_result(
            data={"max_concurrency": max_concurrency},
            message="Executing all branches in parallel",
            branches_to_run=[],  # Empty list signals "run all branches"
            metadata={"max_concurrency": max_concurrency},
        )
