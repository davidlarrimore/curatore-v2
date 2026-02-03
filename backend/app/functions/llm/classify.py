# backend/app/functions/llm/classify.py
"""
Classify function - Multi-class classification using LLM.

Classifies text into one or more categories with confidence scores.
"""

import json
from typing import Any, Dict, List, Optional
import logging

from ..base import (
    BaseFunction,
    FunctionMeta,
    FunctionCategory,
    FunctionResult,
    ParameterDoc,
)
from ..context import FunctionContext

logger = logging.getLogger("curatore.functions.llm.classify")


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
        name="classify",
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
        ],
        returns="dict: Classification result with category, confidence, and optional reasoning",
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
{text[:3000]}  # Limit text length
---

Classification:"""

            # Generate
            response = ctx.llm_service._client.chat.completions.create(
                model=model or ctx.llm_service._get_model(),
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,
                max_tokens=500,
            )

            response_text = response.choices[0].message.content.strip()

            # Parse JSON (handle markdown code blocks)
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

            result = json.loads(response_text)

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
