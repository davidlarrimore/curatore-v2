# backend/app/functions/llm/classify.py
"""
Classify function - Multi-class classification using LLM.

Classifies text into one or more categories with confidence scores.

Supports collection processing via the `items` parameter - when provided,
the text is rendered for each item with {{ item.xxx }} template placeholders.
"""

import json
from typing import Any, Dict, List, Optional
import logging

from jinja2 import Template

from ..base import (
    BaseFunction,
    FunctionMeta,
    FunctionCategory,
    FunctionResult,
    ParameterDoc,
    OutputFieldDoc,
    OutputSchema,
    OutputVariant,
)
from ..context import FunctionContext
from ...models.llm_models import LLMTaskType
from ...services.config_loader import config_loader

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
        description="Classify text into categories using an LLM",
        parameters=[
            ParameterDoc(
                name="text",
                type="str",
                description="The text to classify",
                required=True,
            ),
            ParameterDoc(
                name="categories",
                type="list[str]",
                description="List of possible categories",
                required=True,
                example=["positive", "negative", "neutral"],
            ),
            ParameterDoc(
                name="category_descriptions",
                type="dict[str, str]",
                description="Optional descriptions for each category",
                required=False,
                default=None,
            ),
            ParameterDoc(
                name="multi_label",
                type="bool",
                description="Allow multiple categories (default: single category)",
                required=False,
                default=False,
            ),
            ParameterDoc(
                name="include_reasoning",
                type="bool",
                description="Include reasoning for the classification",
                required=False,
                default=True,
            ),
            ParameterDoc(
                name="model",
                type="str",
                description="Model to use",
                required=False,
                default=None,
            ),
            ParameterDoc(
                name="items",
                type="list",
                description="Collection of items to iterate over. When provided, the text is rendered for each item with {{ item.xxx }} placeholders replaced by item data.",
                required=False,
                default=None,
                example=[{"content": "Text 1"}, {"content": "Text 2"}],
            ),
        ],
        returns="dict or list: Classification result (single) or list of classifications (collection)",
        output_schema=OutputSchema(
            type="dict",
            description="Classification result with category, confidence, and optional reasoning",
            fields=[
                OutputFieldDoc(name="category", type="str",
                              description="The assigned category name",
                              example="technology"),
                OutputFieldDoc(name="confidence", type="float",
                              description="Confidence score (0.0-1.0)",
                              example=0.92),
                OutputFieldDoc(name="reasoning", type="str",
                              description="Explanation for the classification",
                              nullable=True),
            ],
        ),
        output_variants=[
            OutputVariant(
                mode="multi_label",
                condition="when `multi_label` parameter is true",
                schema=OutputSchema(
                    type="dict",
                    description="Multi-label classification with multiple categories",
                    fields=[
                        OutputFieldDoc(name="categories", type="list[dict]",
                                      description="List of {name, confidence} for each matching category"),
                        OutputFieldDoc(name="reasoning", type="str",
                                      description="Explanation for the classifications",
                                      nullable=True),
                    ],
                ),
            ),
            OutputVariant(
                mode="collection",
                condition="when `items` parameter is provided",
                schema=OutputSchema(
                    type="list[dict]",
                    description="List of classification results for each item",
                    fields=[
                        OutputFieldDoc(name="item_id", type="str",
                                      description="ID of the processed item"),
                        OutputFieldDoc(name="result", type="dict",
                                      description="Classification result (category, confidence, reasoning)"),
                        OutputFieldDoc(name="success", type="bool",
                                      description="Whether classification succeeded"),
                        OutputFieldDoc(name="error", type="str",
                                      description="Error message if failed", nullable=True),
                    ],
                ),
            ),
        ],
        tags=["llm", "classification", "categorization"],
        requires_llm=True,
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

            system_prompt = f"""You are a text classification expert. Classify the given text into the most appropriate category.
{"You may select multiple categories if they apply." if multi_label else "Select exactly one category."}
Confidence should be between 0.0 and 1.0.
{output_format}
Return ONLY valid JSON, no explanation or markdown."""

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

            # Generate
            response = ctx.llm_service._client.chat.completions.create(
                model=resolved_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                max_tokens=500,
            )

            response_text = response.choices[0].message.content.strip()
            result = self._parse_json_response(response_text)

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
                    # Fall back to first category if invalid
                    result["category"] = categories[0]
                    result["confidence"] = 0.5

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

        system_prompt = f"""You are a text classification expert. Classify the given text into the most appropriate category.
{"You may select multiple categories if they apply." if multi_label else "Select exactly one category."}
Confidence should be between 0.0 and 1.0.
{output_format}
Return ONLY valid JSON, no explanation or markdown."""

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

                # Generate
                response = ctx.llm_service._client.chat.completions.create(
                    model=resolved_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=temperature,
                    max_tokens=500,
                )

                response_text = response.choices[0].message.content.strip()
                classification = self._parse_json_response(response_text)

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
                        classification["category"] = categories[0]
                        classification["confidence"] = 0.5

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
