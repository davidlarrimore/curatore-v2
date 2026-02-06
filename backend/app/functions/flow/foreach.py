# backend/app/functions/flow/foreach.py
"""
Foreach function - Iterate over a list with multi-step logic per item.

Iterates over a list and executes a set of steps for each item. Supports
concurrency control and per-item condition filtering.

This is the flow function upgrade path from the legacy single-step `foreach:`
field. Use this when you need multiple steps per item.

Example usage in a procedure:
    - name: process_documents
      function: foreach
      params:
        items: "{{ steps.search.results }}"
        concurrency: 3
        condition: "{{ item.score > 0.5 }}"
      branches:
        each:
          - name: summarize
            function: llm_summarize
            params:
              text: "{{ item.content }}"
          - name: save
            function: update_metadata
            params:
              id: "{{ item.id }}"
              summary: "{{ steps.summarize.text }}"
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

logger = logging.getLogger("curatore.functions.flow.foreach")


class ForeachFunction(BaseFunction):
    """
    Iterate over a list and execute steps for each item.

    Supports concurrency control and per-item condition filtering. Inside the
    branch steps, `{{ item }}` is the current item and `{{ item_index }}` is
    the 0-based index.

    The items parameter should evaluate to a list. If it evaluates to a non-list,
    it will be wrapped in a single-item list.

    When a condition is provided, it's evaluated per-item with {{ item }} and
    {{ item_index }} in scope. Items where the condition is falsy are skipped.

    Returns a FlowResult with items_to_iterate set to the resolved (and
    optionally filtered) list, and skipped_indices listing filtered items.
    """

    meta = FunctionMeta(
        name="foreach",
        category=FunctionCategory.FLOW,
        description="Iterate over a list and execute steps for each item. REQUIRES 'branches.each' containing the steps to run per item. Supports concurrency control and per-item filtering. Inside branch steps, {{ item }} and {{ item_index }} are available.",
        parameters=[
            ParameterDoc(
                name="items",
                type="list",
                description="List to iterate over. Can be a Jinja2 expression that evaluates to a list.",
                required=True,
                example="{{ steps.search_results.results }}",
            ),
            ParameterDoc(
                name="concurrency",
                type="int",
                description="Max items to process in parallel. 1 = sequential (default). 0 = unlimited. N = up to N at a time.",
                required=False,
                default=1,
                example=3,
            ),
            ParameterDoc(
                name="condition",
                type="str",
                description="Per-item filter. Evaluated with {{ item }} and {{ item_index }} in scope. Items where this is falsy are skipped.",
                required=False,
                default=None,
                example="{{ item.estimated_value > 100000 }}",
            ),
        ],
        returns="FlowResult with items_to_iterate and skipped_indices",
        tags=["flow", "iteration", "loop", "foreach", "batch"],
        requires_llm=False,
        examples=[
            {
                "description": "Process each search result",
                "params": {"items": "{{ steps.search.results }}"},
            },
            {
                "description": "Process with concurrency limit",
                "params": {
                    "items": "{{ steps.search.results }}",
                    "concurrency": 3,
                },
            },
            {
                "description": "Filter high-value items",
                "params": {
                    "items": "{{ steps.fetch_notices.results }}",
                    "condition": "{{ item.estimated_value and item.estimated_value > 100000 }}",
                    "concurrency": 2,
                },
            },
        ],
    )

    async def execute(self, ctx: FunctionContext, **params) -> FlowResult:
        """Resolve items list and apply optional condition filter."""
        items = params.get("items")
        concurrency = params.get("concurrency", 1)
        condition = params.get("condition")

        # Normalize to list
        if items is None:
            items_list = []
        elif isinstance(items, (list, tuple)):
            items_list = list(items)
        else:
            # Single item becomes list of one
            items_list = [items]

        # Apply condition filter if provided
        # Note: The condition has already been rendered for each item by the executor
        # For foreach, we pass the items through and let the executor handle filtering
        # because we need {{ item }} context which isn't available here yet
        skipped_indices = []

        logger.info(
            f"[foreach] {len(items_list)} items, concurrency={concurrency}, "
            f"condition={'set' if condition else 'none'}"
        )

        return FlowResult.success_result(
            data={
                "item_count": len(items_list),
                "concurrency": concurrency,
                "has_condition": condition is not None,
            },
            message=f"Iterating over {len(items_list)} items with concurrency={concurrency}",
            items_to_iterate=items_list,
            skipped_indices=skipped_indices,
            metadata={
                "concurrency": concurrency,
                "condition": condition,
            },
        )
