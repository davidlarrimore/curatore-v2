# backend/app/functions/flow/switch_branch.py
"""
Switch Branch function - Multi-way routing based on value.

Routes execution to one of several named branches based on matching a value.
Similar to a switch/case statement in programming languages.

Example usage in a procedure:
    - name: route_by_type
      function: switch_branch
      params:
        value: "{{ steps.classify.category }}"
      branches:
        contract:
          - name: extract_clauses
            function: llm_extract
        invoice:
          - name: extract_line_items
            function: llm_extract
        default:
          - name: generic_summary
            function: llm_summarize
"""

import logging
from typing import Any, List

from ..base import (
    BaseFunction,
    FunctionMeta,
    FunctionCategory,
    FlowResult,
    ParameterDoc,
)
from ..context import FunctionContext

logger = logging.getLogger("curatore.functions.flow.switch_branch")


class SwitchBranchFunction(BaseFunction):
    """
    Route execution to one of several named branches based on a value.

    Evaluates the `value` parameter and matches it against the branch keys
    defined in `branches`. If no match is found, the `default` branch runs
    (if provided).

    Matching is exact and case-sensitive. The value is string-coerced before
    matching against branch names.

    Returns a FlowResult with branch_key set to the matching case key,
    "default", or None if no match and no default.
    """

    meta = FunctionMeta(
        name="switch_branch",
        category=FunctionCategory.FLOW,
        description="Route execution to one of several named branches based on a value. REQUIRES 'branches' with at least one case (e.g., 'branches.contract', 'branches.invoice'). Optional 'branches.default' for fallback. Value is matched against branch keys (exact, case-sensitive).",
        parameters=[
            ParameterDoc(
                name="value",
                type="str",
                description="Expression that produces the routing value. The result is string-coerced and matched against branch keys (exact, case-sensitive).",
                required=True,
                example="{{ steps.classify_document.category }}",
            ),
        ],
        returns="FlowResult with branch_key set to matched case or 'default'",
        tags=["flow", "branching", "routing", "switch", "case"],
        requires_llm=False,
        examples=[
            {
                "description": "Route by document type",
                "params": {"value": "{{ steps.classify.category }}"},
            },
            {
                "description": "Route by status code",
                "params": {"value": "{{ steps.api_call.status }}"},
            },
            {
                "description": "Route by user role",
                "params": {"value": "{{ params.user_role }}"},
            },
        ],
    )

    async def execute(self, ctx: FunctionContext, **params) -> FlowResult:
        """Evaluate value and return matching branch key."""
        value = params.get("value")

        # String-coerce the value for matching
        str_value = str(value) if value is not None else ""

        # Get available branch names from context (will be validated by executor)
        # The function doesn't know about branches - it just returns the value as key
        # The executor will check if that key exists in branches

        logger.info(
            f"[switch_branch] value={value!r} → branch_key={str_value!r}"
        )

        return FlowResult.success_result(
            data={"value": value, "string_value": str_value, "branch": str_value},
            message=f"Routing to branch '{str_value}'",
            branch_key=str_value,
        )
