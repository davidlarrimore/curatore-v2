# backend/app/functions/llm/classify.py
"""
Classify function - Multi-class classification using LLM.

Classifies text into one or more categories with confidence scores.

Supports collection processing via the `items` parameter - when provided,
the text is rendered for each item with {{ item.xxx }} template placeholders.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from jinja2 import Template

from app.core.models.llm_models import LLMTaskType
from app.core.shared.config_loader import config_loader

from ...base import (
    BaseFunction,
    FunctionCategory,
    FunctionMeta,
    FunctionResult,
)
from ...context import FunctionContext

logger = logging.getLogger("curatore.functions.llm.classify")


def _render_item_template(template_str: str, item: Any) -> str:
    """Render a Jinja2 template string with item context."""
    template = Template(template_str)
    return template.render(item=item)


class ClassifyFunction(BaseFunction):
    """
    Classify text into categories using an LLM.

    Returns classification results with confidence scores.

    Example:
        result = await fn.classify(ctx,
            text="This product is terrible, worst purchase ever!",
            categories=["positive", "negative", "neutral"],
        )
        # result.data = {"category": "negative", "confidence": 0.95, "reasoning": "..."}
    """

    meta = FunctionMeta(
        name="llm_classify",
        category=FunctionCategory.LLM,
        description="Classify text into one or more categories using an LLM. Pass the text directly — use get_content first to fetch document content by asset ID.",
        input_schema={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The text content to classify. For documents, first call get_content with the asset ID, then pass the returned text here.",
                },
                "categories": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of possible categories",
                    "examples": [["positive", "negative", "neutral"]],
                },
                "category_descriptions": {
                    "type": "object",
                    "description": "Optional descriptions for each category",
                    "default": None,
                },
                "multi_label": {
                    "type": "boolean",
                    "description": "Allow multiple categories (default: single category)",
                    "default": False,
                },
                "include_reasoning": {
                    "type": "boolean",
                    "description": "Include reasoning for the classification",
                    "default": True,
                },
                "model": {
                    "type": "string",
                    "description": "Model to use",
                    "default": None,
                },
                "items": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Collection of items to iterate over. When provided, the text is rendered for each item with {{ item.xxx }} placeholders replaced by item data.",
                    "default": None,
                    "examples": [[{"content": "Text 1"}, {"content": "Text 2"}]],
                    "x-procedure-only": True,
                },
            },
            "required": ["text", "categories"],
        },
        output_schema={
            "type": "object",
            "description": "Classification result with category, confidence, and optional reasoning",
            "properties": {
                "category": {"type": "string", "description": "The assigned category name", "examples": ["technology"]},
                "confidence": {"type": "number", "description": "Confidence score (0.0-1.0)", "examples": [0.92]},
                "reasoning": {"type": "string", "description": "Explanation for the classification", "nullable": True},
            },
            "variants": [
                {
                    "type": "object",
                    "description": "multi_label: when `multi_label` parameter is true",
                    "properties": {
                        "categories": {"type": "array", "items": {"type": "object"}, "description": "List of {name, confidence} for each matching category"},
                        "reasoning": {"type": "string", "description": "Explanation for the classifications", "nullable": True},
                    },
                },
                {
                    "type": "array",
                    "description": "collection: when `items` parameter is provided",
                    "items": {
                        "type": "object",
                        "properties": {
                            "item_id": {"type": "string", "description": "ID of the processed item"},
                            "result": {"type": "object", "description": "Classification result (category, confidence, reasoning)"},
                            "success": {"type": "boolean", "description": "Whether classification succeeded"},
                            "error": {"type": "string", "description": "Error message if failed", "nullable": True},
                        },
                    },
                },
            ],
        },
        tags=["llm", "classification", "categorization"],
        requires_llm=True,
        side_effects=False,
        is_primitive=True,
        payload_profile="full",
        examples=[
            {
                "description": "Sentiment classification",
                "params": {
                    "text": "I love this product!",
                    "categories": ["positive", "negative", "neutral"],
                },
            },
            {
                "description": "Multi-label classification",
                "params": {
                    "text": "Technical document about AI in healthcare",
                    "categories": ["technology", "healthcare", "finance", "legal"],
                    "multi_label": True,
                },
            },
        ],
    )

    async def execute(self, ctx: FunctionContext, **params) -> FunctionResult:
        """Execute classification."""
        text = params["text"]
        categories = params["categories"]
        category_descriptions = params.get("category_descriptions") or {}
        multi_label = params.get("multi_label", False)
        include_reasoning = params.get("include_reasoning", True)
        model = params.get("model")
        items = params.get("items")

        if not ctx.llm_service.is_available:
            return FunctionResult.failed_result(
                error="LLM service is not available",
                message="Cannot classify: LLM service not configured",
            )

        if not categories:
            return FunctionResult.failed_result(
                error="No categories provided",
                message="At least one category is required",
            )

        # Collection mode: iterate over items
        if items and isinstance(items, list):
            return await self._execute_collection(
                ctx=ctx,
                items=items,
                text_template=text,
                categories=categories,
                category_descriptions=category_descriptions,
                multi_label=multi_label,
                include_reasoning=include_reasoning,
                model=model,
            )

        # Single mode: classify once
        return await self._execute_single(
            ctx=ctx,
            text=text,
            categories=categories,
            category_descriptions=category_descriptions,
            multi_label=multi_label,
            include_reasoning=include_reasoning,
            model=model,
        )

    def _parse_json_response(self, response_text: str) -> dict:
        """Parse JSON from response, handling markdown code blocks."""
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            json_lines = []
            in_block = False
            for line in lines:
                if line.startswith("```"):
                    in_block = not in_block
                    continue
                if in_block:
                    json_lines.append(line)
            response_text = "\n".join(json_lines)
        return json.loads(response_text)

    async def _execute_single(
        self,
        ctx: FunctionContext,
        text: str,
        categories: List[str],
        category_descriptions: Dict[str, str],
        multi_label: bool,
        include_reasoning: bool,
        model: Optional[str],
    ) -> FunctionResult:
        """Execute single classification."""
        try:
            # Build category list
            category_list = "\n".join([
                f"- {cat}: {category_descriptions.get(cat, 'No description')}"
                for cat in categories
            ])

            if multi_label:
                output_format = """Return JSON: {"categories": [{"name": "category", "confidence": 0.0-1.0}], "reasoning": "explanation"}"""
            else:
                output_format = """Return JSON: {"category": "category_name", "confidence": 0.0-1.0, "reasoning": "explanation"}"""

            system_prompt = f"""You are a document classification system. You MUST classify the text into EXACTLY ONE of the provided categories.

RULES:
1. You MUST select from the provided categories list — do NOT invent new categories.
2. If the text doesn't clearly match any category, select "Other" (or the closest match).
3. Confidence should be between 0.0 and 1.0.
4. Return ONLY valid JSON, no explanation or markdown.

{"You may select multiple categories if they apply." if multi_label else ""}
{output_format}"""

            user_prompt = f"""Categories:
{category_list}

Text to classify:
---
{text[:3000]}
---

Classification:"""

            # Get model and temperature from task type routing (QUICK for classification)
            task_config = config_loader.get_task_type_config(LLMTaskType.QUICK)
            resolved_model = model or task_config.model
            temperature = task_config.temperature if task_config.temperature is not None else 0.1

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]

            # Generate
            response = ctx.llm_service._client.chat.completions.create(
                model=resolved_model,
                messages=messages,
                temperature=temperature,
                max_tokens=500,
            )

            response_text = response.choices[0].message.content.strip()

            # Parse JSON with retry on malformed response
            try:
                result = self._parse_json_response(response_text)
            except json.JSONDecodeError:
                # Retry once asking for valid JSON
                retry_response = ctx.llm_service._client.chat.completions.create(
                    model=resolved_model,
                    messages=messages + [
                        {"role": "assistant", "content": response_text},
                        {"role": "user", "content": "That was not valid JSON. Return ONLY a JSON object, no markdown or explanation."},
                    ],
                    temperature=0.0,
                    max_tokens=500,
                )
                retry_text = retry_response.choices[0].message.content.strip()
                result = self._parse_json_response(retry_text)  # If this fails, exception propagates

            # Validate and normalize result
            if multi_label:
                if "categories" not in result:
                    result["categories"] = []
                # Validate categories are in allowed list
                result["categories"] = [
                    c for c in result["categories"]
                    if c.get("name") in categories
                ]
            else:
                if "category" not in result or result["category"] not in categories:
                    # Retry once with correction feedback
                    retry_response = ctx.llm_service._client.chat.completions.create(
                        model=resolved_model,
                        messages=messages + [
                            {"role": "assistant", "content": response_text},
                            {"role": "user", "content": (
                                f"Invalid response. You returned '{result.get('category')}' which is not in the "
                                f"allowed categories: {', '.join(categories)}. "
                                "Please select EXACTLY ONE category from the list and return valid JSON."
                            )},
                        ],
                        temperature=0.0,
                        max_tokens=500,
                    )
                    retry_text = retry_response.choices[0].message.content.strip()
                    try:
                        result = self._parse_json_response(retry_text)
                    except json.JSONDecodeError:
                        pass  # Fall through to fallback below

                    # Final fallback if retry also failed
                    if "category" not in result or result["category"] not in categories:
                        logger.warning(
                            f"Classification fallback: LLM returned '{result.get('category')}', "
                            f"expected one of {categories}. Defaulting to 'Other'."
                        )
                        other_cat = "Other" if "Other" in categories else categories[-1]
                        result["category"] = other_cat
                        result["confidence"] = 0.0
                        result["_fallback"] = True

            if not include_reasoning:
                result.pop("reasoning", None)

            return FunctionResult.success_result(
                data=result,
                message=f"Classified as: {result.get('category') or result.get('categories')}",
                metadata={
                    "model": response.model,
                    "multi_label": multi_label,
                    "num_categories": len(categories),
                },
            )

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse classification response: {e}")
            return FunctionResult.failed_result(
                error=f"Invalid JSON response: {e}",
                message="LLM did not return valid JSON",
            )
        except Exception as e:
            logger.exception(f"Classification failed: {e}")
            return FunctionResult.failed_result(
                error=str(e),
                message="Classification failed",
            )

    async def _execute_collection(
        self,
        ctx: FunctionContext,
        items: List[Any],
        text_template: str,
        categories: List[str],
        category_descriptions: Dict[str, str],
        multi_label: bool,
        include_reasoning: bool,
        model: Optional[str],
    ) -> FunctionResult:
        """Execute classification for each item in collection."""
        results = []
        failed_count = 0

        # Build category list and prompts once
        category_list = "\n".join([
            f"- {cat}: {category_descriptions.get(cat, 'No description')}"
            for cat in categories
        ])

        if multi_label:
            output_format = """Return JSON: {"categories": [{"name": "category", "confidence": 0.0-1.0}], "reasoning": "explanation"}"""
        else:
            output_format = """Return JSON: {"category": "category_name", "confidence": 0.0-1.0, "reasoning": "explanation"}"""

        system_prompt = f"""You are a document classification system. You MUST classify the text into EXACTLY ONE of the provided categories.

RULES:
1. You MUST select from the provided categories list — do NOT invent new categories.
2. If the text doesn't clearly match any category, select "Other" (or the closest match).
3. Confidence should be between 0.0 and 1.0.
4. Return ONLY valid JSON, no explanation or markdown.

{"You may select multiple categories if they apply." if multi_label else ""}
{output_format}"""

        # Get model and temperature from task type routing (BULK for collection mode)
        task_config = config_loader.get_task_type_config(LLMTaskType.BULK)
        resolved_model = model or task_config.model
        temperature = task_config.temperature if task_config.temperature is not None else 0.1

        for idx, item in enumerate(items):
            try:
                # Render text with item context
                rendered_text = _render_item_template(text_template, item)

                user_prompt = f"""Categories:
{category_list}

Text to classify:
---
{rendered_text[:3000]}
---

Classification:"""

                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ]

                # Generate
                response = ctx.llm_service._client.chat.completions.create(
                    model=resolved_model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=500,
                )

                response_text = response.choices[0].message.content.strip()

                # Parse JSON with retry on malformed response
                try:
                    classification = self._parse_json_response(response_text)
                except json.JSONDecodeError:
                    retry_response = ctx.llm_service._client.chat.completions.create(
                        model=resolved_model,
                        messages=messages + [
                            {"role": "assistant", "content": response_text},
                            {"role": "user", "content": "That was not valid JSON. Return ONLY a JSON object, no markdown or explanation."},
                        ],
                        temperature=0.0,
                        max_tokens=500,
                    )
                    retry_text = retry_response.choices[0].message.content.strip()
                    classification = self._parse_json_response(retry_text)

                # Validate and normalize result
                if multi_label:
                    if "categories" not in classification:
                        classification["categories"] = []
                    classification["categories"] = [
                        c for c in classification["categories"]
                        if c.get("name") in categories
                    ]
                else:
                    if "category" not in classification or classification["category"] not in categories:
                        # Retry once with correction feedback
                        retry_response = ctx.llm_service._client.chat.completions.create(
                            model=resolved_model,
                            messages=messages + [
                                {"role": "assistant", "content": response_text},
                                {"role": "user", "content": (
                                    f"Invalid response. You returned '{classification.get('category')}' which is not in the "
                                    f"allowed categories: {', '.join(categories)}. "
                                    "Please select EXACTLY ONE category from the list and return valid JSON."
                                )},
                            ],
                            temperature=0.0,
                            max_tokens=500,
                        )
                        retry_text = retry_response.choices[0].message.content.strip()
                        try:
                            classification = self._parse_json_response(retry_text)
                        except json.JSONDecodeError:
                            pass  # Fall through to fallback below

                        # Final fallback if retry also failed
                        if "category" not in classification or classification["category"] not in categories:
                            logger.warning(
                                f"Classification fallback for item {idx}: LLM returned "
                                f"'{classification.get('category')}', expected one of {categories}."
                            )
                            other_cat = "Other" if "Other" in categories else categories[-1]
                            classification["category"] = other_cat
                            classification["confidence"] = 0.0
                            classification["_fallback"] = True

                if not include_reasoning:
                    classification.pop("reasoning", None)

                # Extract item ID if available
                item_id = None
                if isinstance(item, dict):
                    item_id = item.get("id") or item.get("item_id") or str(idx)
                else:
                    item_id = str(idx)

                results.append({
                    "item_id": item_id,
                    "result": classification,
                    "success": True,
                })

            except json.JSONDecodeError as e:
                logger.warning(f"Classification failed for item {idx}: invalid JSON - {e}")
                failed_count += 1
                results.append({
                    "item_id": item.get("id") if isinstance(item, dict) else str(idx),
                    "result": None,
                    "success": False,
                    "error": f"Invalid JSON response: {e}",
                })
            except Exception as e:
                logger.warning(f"Classification failed for item {idx}: {e}")
                failed_count += 1
                results.append({
                    "item_id": item.get("id") if isinstance(item, dict) else str(idx),
                    "result": None,
                    "success": False,
                    "error": str(e),
                })

        return FunctionResult.success_result(
            data=results,
            message=f"Classified {len(results) - failed_count}/{len(items)} items",
            metadata={
                "mode": "collection",
                "categories": categories,
                "multi_label": multi_label,
                "total_items": len(items),
                "successful_items": len(items) - failed_count,
                "failed_items": failed_count,
            },
            items_processed=len(items),
            items_failed=failed_count,
        )
