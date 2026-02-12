# backend/app/functions/flow/if_branch.py
"""
If Branch function - Conditional branching in procedures.

Evaluates a condition and routes execution to either the `then` or `else` branch.
The condition has already been rendered by the executor via Jinja2, so this
function simply evaluates the truthiness of the rendered value.

Example usage in a procedure:
    - name: check_results
      function: if_branch
      params:
        condition: "{{ steps.search.total > 0 }}"
      branches:
        then:
          - name: send_results
            function: send_email
            params:
              subject: "Results found"
        else:
          - name: send_empty
            function: send_email
            params:
              subject: "No results"
"""

import logging
from typing import Any

from ...base import (
    BaseFunction,
    FlowResult,
    FunctionCategory,
    FunctionMeta,
)
from ...context import FunctionContext

logger = logging.getLogger("curatore.functions.flow.if_branch")


class IfBranchFunction(BaseFunction):
    """
    Evaluate a condition and execute one of two branches.

    If the condition is truthy, the `then` branch runs.
    If falsy, the `else` branch runs (if provided).

    The condition parameter is a Jinja2 expression that gets rendered by the
    procedure executor before being passed to this function. The function
    evaluates the rendered value for truthiness using Python semantics.

    Falsy values: None, False, 0, "", [], {}, "false", "False", "0", "none", "None", "null"
    Everything else is truthy.

    Returns a FlowResult with branch_key="then" or branch_key="else" to tell
    the executor which branch to run.
    """

    meta = FunctionMeta(
        name="if_branch",
        category=FunctionCategory.FLOW,
        description="Evaluate a condition and execute one of two branches. REQUIRES 'branches.then' containing steps to run when truthy. Optional 'branches.else' runs when falsy.",
        input_schema={
            "type": "object",
            "properties": {
                "condition": {
                    "type": "string",
                    "description": "Jinja2 expression that evaluates to truthy/falsy. Truthy → then branch. Falsy → else branch. Follows Python truthiness rules.",
                    "examples": ["{{ steps.search_results.total > 0 }}"],
                },
            },
            "required": ["condition"],
        },
        output_schema={
            "type": "object",
            "description": "Flow control result indicating which branch to execute",
            "properties": {
                "condition_value": {
                    "description": "The rendered condition value that was evaluated",
                },
                "evaluated": {
                    "type": "boolean",
                    "description": "True if condition was truthy, False if falsy",
                },
                "branch": {
                    "type": "string",
                    "description": "Branch to execute: 'then' or 'else'",
                    "examples": ["then"],
                },
            },
        },
        tags=["flow", "branching", "conditional", "if", "else"],
        requires_llm=False,
        side_effects=False,
        is_primitive=True,
        payload_profile="full",
        examples=[
            {
                "description": "Branch based on search results",
                "params": {"condition": "{{ steps.search.total > 0 }}"},
            },
            {
                "description": "Check if list is not empty",
                "params": {"condition": "{{ steps.fetch_items | length > 0 }}"},
            },
            {
                "description": "Check a boolean flag",
                "params": {"condition": "{{ params.should_notify }}"},
            },
        ],
    )

    async def execute(self, ctx: FunctionContext, **params) -> FlowResult:
        """Evaluate condition and return branch key."""
        condition_value = params.get("condition")

        # Evaluate truthiness
        # The condition has already been rendered by the executor
        # We check for common falsy string representations as well as Python falsy values
        is_truthy = self._is_truthy(condition_value)

        branch_key = "then" if is_truthy else "else"

        logger.info(
            f"[if_branch] condition={condition_value!r} evaluated={is_truthy} → branch={branch_key}"
        )

        return FlowResult.success_result(
            data={"condition_value": condition_value, "evaluated": is_truthy, "branch": branch_key},
            message=f"Condition is {is_truthy}, executing '{branch_key}' branch",
            branch_key=branch_key,
        )

    def _is_truthy(self, value: Any) -> bool:
        """
        Evaluate truthiness of a value using Python semantics plus string handling.

        Falsy values:
        - Python falsy: None, False, 0, "", [], {}
        - String falsy: "false", "False", "0", "none", "None", "null", ""
        """
        if value is None:
            return False
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            # Empty string is falsy
            if not value:
                return False
            # Common string representations of false
            if value.lower() in ("false", "0", "none", "null", "no", "n"):
                return False
            return True
        if isinstance(value, (list, tuple, dict, set)):
            return len(value) > 0
        # Default: truthy
        return bool(value)
