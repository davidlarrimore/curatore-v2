# backend/app/functions/llm/route.py
"""
Route function - Multi-branch decision routing using LLM.

Evaluates data and routes it to one of several possible branches/paths.
Unlike llm_decide (binary yes/no), this allows for multiple discrete
outcomes, similar to a switch/case statement.

Example usage in a procedure:
    - name: route_inquiry
      function: llm_route
      params:
        data: "{{ item.message }}"
        routes:
          - name: sales
            description: "Customer interested in purchasing, pricing questions"
          - name: support
            description: "Technical issues, bugs, how-to questions"
          - name: billing
            description: "Invoice, payment, refund related"
          - name: general
            description: "General inquiries, feedback, other"
        default_route: general

    - name: handle_sales
      function: send_to_sales_queue
      condition: "steps.route_inquiry.route == 'sales'"
"""

import json
from typing import Any, Dict, List, Optional
import logging

from jinja2 import Template

from ...base import (
    BaseFunction,
    FunctionMeta,
    FunctionCategory,
    FunctionResult,
)
from ...context import FunctionContext
from app.core.models.llm_models import LLMTaskType
from app.core.shared.config_loader import config_loader

logger = logging.getLogger("curatore.functions.llm.route")


def _render_item_template(template_str: str, item: Any) -> str:
    """Render a Jinja2 template string with item context."""
    template = Template(template_str)
    return template.render(item=item)


class RouteFunction(BaseFunction):
    """
    Route data to one of several branches using LLM analysis.

    Analyzes content and selects the most appropriate route from a set
    of named options, each with a description. Returns the selected route
    with a confidence score and reasoning.

    The function returns:
    - route: str (name of selected route)
    - confidence: float (0.0-1.0)
    - reasoning: str (explanation for the selection)
    - alternatives: list (optional runner-up routes)
    """

    meta = FunctionMeta(
        name="llm_route",
        category=FunctionCategory.LOGIC,
        description="Route data to one of several branches using LLM analysis",
        input_schema={
            "type": "object",
            "properties": {
                "data": {
                    "type": "string",
                    "description": "The data/content to analyze for routing",
                    "examples": ["Customer message or document content..."],
                },
                "routes": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "List of possible routes with 'name' and 'description' fields",
                    "examples": [[
                        {"name": "sales", "description": "Sales and pricing inquiries"},
                        {"name": "support", "description": "Technical support requests"},
                    ]],
                },
                "default_route": {
                    "type": "string",
                    "description": "Default route if no match meets confidence threshold",
                    "default": "default",
                },
                "confidence_threshold": {
                    "type": "number",
                    "description": "Minimum confidence to select a route (0.0-1.0)",
                    "default": 0.5,
                },
                "include_alternatives": {
                    "type": "boolean",
                    "description": "Include alternative routes with their confidences",
                    "default": False,
                },
                "system_prompt": {
                    "type": "string",
                    "description": "Custom system prompt to override the default",
                    "default": None,
                },
                "model": {
                    "type": "string",
                    "description": "Model to use (uses default if not specified)",
                    "default": None,
                },
                "items": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Collection of items to route. When provided, data is rendered for each item with {{ item.xxx }} placeholders.",
                    "default": None,
                    "examples": [[{"title": "Item 1", "desc": "..."}, {"title": "Item 2", "desc": "..."}]],
                },
            },
            "required": ["data", "routes"],
        },
        output_schema={
            "type": "object",
            "description": "Routing decision result with confidence and reasoning",
            "properties": {
                "route": {"type": "string", "description": "Name of the selected route", "examples": ["support"]},
                "confidence": {"type": "number", "description": "Confidence score (0.0-1.0)", "examples": [0.87]},
                "reasoning": {"type": "string", "description": "Explanation for the routing decision", "nullable": True},
                "below_threshold": {"type": "boolean", "description": "True if confidence was below threshold and default was used", "nullable": True},
                "alternatives": {"type": "array", "items": {"type": "object"}, "description": "Alternative routes with their confidences", "nullable": True},
            },
            "variants": [
                {
                    "type": "array",
                    "description": "collection: when `items` parameter is provided",
                    "items": {
                        "type": "object",
                        "properties": {
                            "item_id": {"type": "string", "description": "ID of the processed item"},
                            "route": {"type": "string", "description": "Selected route name"},
                            "confidence": {"type": "number", "description": "Confidence score (0.0-1.0)"},
                            "reasoning": {"type": "string", "description": "Explanation", "nullable": True},
                            "success": {"type": "boolean", "description": "Whether routing succeeded"},
                            "error": {"type": "string", "description": "Error message if failed", "nullable": True},
                        },
                    },
                },
            ],
        },
        tags=["llm", "routing", "branching", "decision"],
        requires_llm=True,
        side_effects=False,
        is_primitive=True,
        payload_profile="full",
        examples=[
            {
                "description": "Route customer inquiry",
                "params": {
                    "data": "I'm having trouble logging into my account",
                    "routes": [
                        {"name": "support", "description": "Technical issues"},
                        {"name": "sales", "description": "Pricing and purchases"},
                        {"name": "billing", "description": "Payment issues"},
                    ],
                },
            },
            {
                "description": "Route with confidence threshold",
                "params": {
                    "data": "Tell me about your cloud migration services",
                    "routes": [
                        {"name": "sales", "description": "Sales inquiries"},
                        {"name": "support", "description": "Technical support"},
                        {"name": "general", "description": "General inquiries"},
                    ],
                    "confidence_threshold": 0.7,
                    "default_route": "general",
                    "include_alternatives": True,
                },
            },
        ],
    )

    async def execute(self, ctx: FunctionContext, **params) -> FunctionResult:
        """Execute routing decision."""
        data = params["data"]
        routes = params["routes"]
        default_route = params.get("default_route", "default")
        confidence_threshold = params.get("confidence_threshold", 0.5)
        include_alternatives = params.get("include_alternatives", False)
        system_prompt = params.get("system_prompt")
        model = params.get("model")
        items = params.get("items")

        if not ctx.llm_service.is_available:
            return FunctionResult.failed_result(
                error="LLM service is not available",
                message="Cannot route: LLM service not configured",
            )

        # Collection mode: iterate over items
        if items and isinstance(items, list):
            return await self._execute_collection(
                ctx=ctx,
                items=items,
                routes=routes,
                data_template=data,
                default_route=default_route,
                confidence_threshold=confidence_threshold,
                include_alternatives=include_alternatives,
                system_prompt=system_prompt,
                model=model,
            )

        # Single mode: route once
        return await self._execute_single(
            ctx=ctx,
            data=data,
            routes=routes,
            default_route=default_route,
            confidence_threshold=confidence_threshold,
            include_alternatives=include_alternatives,
            system_prompt=system_prompt,
            model=model,
        )

    def _build_system_prompt(
        self,
        custom_prompt: Optional[str],
        routes: List[Dict[str, Any]],
    ) -> str:
        """Build the system prompt for routing."""
        if custom_prompt:
            return custom_prompt

        route_descriptions = "\n".join(
            f"  - {r['name']}: {r.get('description', 'No description')}"
            for r in routes
        )

        return f"""You are a precise routing assistant. Your task is to analyze the provided data and select the most appropriate route from the available options.

AVAILABLE ROUTES:
{route_descriptions}

IMPORTANT RULES:
1. You MUST respond with valid JSON only - no markdown, no explanation outside the JSON
2. The "route" field MUST be exactly one of the route names listed above
3. The "confidence" field MUST be a number between 0.0 and 1.0
4. Be decisive - choose the single best matching route
5. If the data doesn't clearly match any route, assign low confidence

OUTPUT FORMAT (respond with ONLY this JSON structure):
{{"route": "route_name", "confidence": 0.85, "reasoning": "Brief explanation", "alternatives": [{{"route": "other_route", "confidence": 0.10}}]}}"""

    def _parse_route_response(self, response_text: str, route_names: List[str]) -> dict:
        """Parse JSON from response, handling various formats."""
        # Strip markdown code blocks if present
        text = response_text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            json_lines = []
            in_block = False
            for line in lines:
                if line.startswith("```"):
                    in_block = not in_block
                    continue
                if in_block:
                    json_lines.append(line)
            text = "\n".join(json_lines)

        result = json.loads(text)

        # Validate route name exists
        route = result.get("route", "")
        if route not in route_names:
            # Try case-insensitive match
            route_lower = route.lower()
            for name in route_names:
                if name.lower() == route_lower:
                    result["route"] = name
                    break

        # Ensure confidence is a float
        confidence = result.get("confidence", 0.5)
        if isinstance(confidence, str):
            try:
                confidence = float(confidence)
            except ValueError:
                confidence = 0.5
        result["confidence"] = max(0.0, min(1.0, float(confidence)))

        # Normalize alternatives
        alternatives = result.get("alternatives", [])
        if isinstance(alternatives, list):
            normalized = []
            for alt in alternatives:
                if isinstance(alt, dict) and "route" in alt:
                    alt_conf = alt.get("confidence", 0.0)
                    if isinstance(alt_conf, str):
                        try:
                            alt_conf = float(alt_conf)
                        except ValueError:
                            alt_conf = 0.0
                    normalized.append({
                        "route": alt["route"],
                        "confidence": max(0.0, min(1.0, float(alt_conf))),
                    })
            result["alternatives"] = sorted(normalized, key=lambda x: x["confidence"], reverse=True)

        return result

    async def _execute_single(
        self,
        ctx: FunctionContext,
        data: str,
        routes: List[Dict[str, Any]],
        default_route: str,
        confidence_threshold: float,
        include_alternatives: bool,
        system_prompt: Optional[str],
        model: Optional[str],
    ) -> FunctionResult:
        """Execute single routing decision."""
        route_names = [r["name"] for r in routes]

        try:
            final_system_prompt = self._build_system_prompt(system_prompt, routes)

            user_prompt = f"""DATA TO ROUTE:
---
{data[:5000]}
---

Select the best matching route and respond with JSON only:"""

            # Get model and temperature from task type routing
            task_config = config_loader.get_task_type_config(LLMTaskType.QUICK)
            resolved_model = model or task_config.model
            temperature = task_config.temperature if task_config.temperature is not None else 0.1

            response = ctx.llm_service._client.chat.completions.create(
                model=resolved_model,
                messages=[
                    {"role": "system", "content": final_system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                max_tokens=500,
            )

            response_text = response.choices[0].message.content.strip()
            result = self._parse_route_response(response_text, route_names)

            # Validate route is in provided names
            if result["route"] not in route_names:
                logger.warning(
                    f"LLM returned unknown route '{result['route']}', using default '{default_route}'"
                )
                result["route"] = default_route
                result["confidence"] = 0.0
                result["below_threshold"] = True

            # Apply confidence threshold
            if result["confidence"] < confidence_threshold:
                logger.info(
                    f"Route confidence {result['confidence']:.2f} below threshold "
                    f"{confidence_threshold}, using default '{default_route}'"
                )
                result["route"] = default_route
                result["below_threshold"] = True

            if not include_alternatives:
                result.pop("alternatives", None)

            return FunctionResult.success_result(
                data=result,
                message=f"Routed to '{result['route']}' (confidence: {result['confidence']:.2f})",
                metadata={
                    "model": response.model,
                    "routes_provided": len(routes),
                    "data_length": len(data) if data else 0,
                },
            )

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse route response: {e}")
            return FunctionResult.success_result(
                data={
                    "route": default_route,
                    "confidence": 0.0,
                    "reasoning": f"Failed to parse LLM response, using default: {default_route}",
                    "parse_error": True,
                },
                message=f"Routed to '{default_route}' (default due to parse error)",
            )
        except Exception as e:
            logger.exception(f"Routing failed: {e}")
            return FunctionResult.failed_result(
                error=str(e),
                message="Routing evaluation failed",
            )

    async def _execute_collection(
        self,
        ctx: FunctionContext,
        items: List[Any],
        routes: List[Dict[str, Any]],
        data_template: str,
        default_route: str,
        confidence_threshold: float,
        include_alternatives: bool,
        system_prompt: Optional[str],
        model: Optional[str],
    ) -> FunctionResult:
        """Execute routing for each item in collection."""
        results = []
        failed_count = 0
        route_counts: Dict[str, int] = {}
        route_names = [r["name"] for r in routes]

        final_system_prompt = self._build_system_prompt(system_prompt, routes)

        # Get model and temperature from task type routing (BULK for collection)
        task_config = config_loader.get_task_type_config(LLMTaskType.BULK)
        resolved_model = model or task_config.model
        temperature = task_config.temperature if task_config.temperature is not None else 0.1

        for idx, item in enumerate(items):
            try:
                # Render data with item context
                rendered_data = _render_item_template(data_template, item)

                user_prompt = f"""DATA TO ROUTE:
---
{rendered_data[:5000]}
---

Select the best matching route and respond with JSON only:"""

                response = ctx.llm_service._client.chat.completions.create(
                    model=resolved_model,
                    messages=[
                        {"role": "system", "content": final_system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=temperature,
                    max_tokens=500,
                )

                response_text = response.choices[0].message.content.strip()
                route_result = self._parse_route_response(response_text, route_names)

                # Validate route
                if route_result["route"] not in route_names:
                    route_result["route"] = default_route
                    route_result["confidence"] = 0.0

                # Apply confidence threshold
                if route_result["confidence"] < confidence_threshold:
                    route_result["route"] = default_route
                    route_result["below_threshold"] = True

                selected = route_result["route"]
                route_counts[selected] = route_counts.get(selected, 0) + 1

                # Extract item ID
                item_id = None
                if isinstance(item, dict):
                    item_id = item.get("id") or item.get("item_id") or str(idx)
                else:
                    item_id = str(idx)

                entry = {
                    "item_id": item_id,
                    "route": selected,
                    "confidence": route_result["confidence"],
                    "reasoning": route_result.get("reasoning"),
                    "success": True,
                }
                if include_alternatives and route_result.get("alternatives"):
                    entry["alternatives"] = route_result["alternatives"]

                results.append(entry)

            except json.JSONDecodeError as e:
                logger.warning(f"Route failed for item {idx}: invalid JSON - {e}")
                failed_count += 1
                item_id = item.get("id") if isinstance(item, dict) else str(idx)
                route_counts[default_route] = route_counts.get(default_route, 0) + 1
                results.append({
                    "item_id": item_id,
                    "route": default_route,
                    "confidence": 0.0,
                    "success": False,
                    "error": f"Invalid JSON response: {e}",
                })
            except Exception as e:
                logger.warning(f"Route failed for item {idx}: {e}")
                failed_count += 1
                item_id = item.get("id") if isinstance(item, dict) else str(idx)
                route_counts[default_route] = route_counts.get(default_route, 0) + 1
                results.append({
                    "item_id": item_id,
                    "route": default_route,
                    "confidence": 0.0,
                    "success": False,
                    "error": str(e),
                })

        return FunctionResult.success_result(
            data=results,
            message=f"Routed {len(results)} items: {', '.join(f'{k}={v}' for k, v in sorted(route_counts.items()))}",
            metadata={
                "mode": "collection",
                "total_items": len(items),
                "successful_items": len(items) - failed_count,
                "failed_items": failed_count,
                "route_distribution": route_counts,
            },
            items_processed=len(items),
            items_failed=failed_count,
        )
