# backend/app/functions/llm/extract.py
"""
Extract function - Structured data extraction using LLM.

Extracts structured data from text using an LLM with JSON schema validation.
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

logger = logging.getLogger("curatore.functions.llm.extract")


class ExtractFunction(BaseFunction):
    """
    Extract structured data from text using an LLM.

    This function uses an LLM to extract specific fields or entities
    from text, returning structured JSON data.

    Example:
        result = await fn.extract(ctx,
            text="Contact John Smith at john@example.com or call 555-1234",
            fields=["name", "email", "phone"],
        )
        # result.data = {"name": "John Smith", "email": "john@example.com", "phone": "555-1234"}
    """

    meta = FunctionMeta(
        name="extract",
        category=FunctionCategory.LLM,
        description="Extract structured data from text using an LLM",
        parameters=[
            ParameterDoc(
                name="text",
                type="str",
                description="The text to extract from",
                required=True,
            ),
            ParameterDoc(
                name="fields",
                type="list[str]",
                description="Fields to extract",
                required=True,
                example=["name", "email", "phone"],
            ),
            ParameterDoc(
                name="field_descriptions",
                type="dict[str, str]",
                description="Optional descriptions for each field",
                required=False,
                default=None,
            ),
            ParameterDoc(
                name="instructions",
                type="str",
                description="Additional extraction instructions",
                required=False,
                default=None,
            ),
            ParameterDoc(
                name="model",
                type="str",
                description="Model to use",
                required=False,
                default=None,
            ),
        ],
        returns="dict: Extracted fields as JSON",
        tags=["llm", "extraction", "structured"],
        requires_llm=True,
        examples=[
            {
                "description": "Extract contact info",
                "params": {
                    "text": "John Smith (john@example.com)",
                    "fields": ["name", "email"],
                },
            },
        ],
    )

    async def execute(self, ctx: FunctionContext, **params) -> FunctionResult:
        """Execute structured extraction."""
        text = params["text"]
        fields = params["fields"]
        field_descriptions = params.get("field_descriptions") or {}
        instructions = params.get("instructions")
        model = params.get("model")

        if not ctx.llm_service.is_available:
            return FunctionResult.failed_result(
                error="LLM service is not available",
                message="Cannot extract: LLM service not configured",
            )

        try:
            # Build extraction prompt
            field_list = "\n".join([
                f"- {field}: {field_descriptions.get(field, 'Extract this field')}"
                for field in fields
            ])

            system_prompt = """You are a data extraction assistant. Extract the requested fields from the text.
Return ONLY a valid JSON object with the extracted fields. If a field cannot be found, use null.
Do not include any explanation or markdown formatting."""

            user_prompt = f"""Extract the following fields from the text:

{field_list}

{f"Additional instructions: {instructions}" if instructions else ""}

Text to extract from:
---
{text}
---

Return ONLY the JSON object:"""

            # Generate
            response = ctx.llm_service._client.chat.completions.create(
                model=model or ctx.llm_service._get_model(),
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,  # Low temperature for consistent extraction
                max_tokens=1000,
            )

            response_text = response.choices[0].message.content.strip()

            # Parse JSON (handle markdown code blocks)
            if response_text.startswith("```"):
                # Extract from code block
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

            extracted = json.loads(response_text)

            # Ensure all requested fields are present
            for field in fields:
                if field not in extracted:
                    extracted[field] = None

            return FunctionResult.success_result(
                data=extracted,
                message=f"Extracted {len([v for v in extracted.values() if v])} fields",
                metadata={
                    "model": response.model,
                    "fields_found": len([v for v in extracted.values() if v]),
                    "fields_null": len([v for v in extracted.values() if v is None]),
                },
            )

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse extraction response: {e}")
            return FunctionResult.failed_result(
                error=f"Invalid JSON response: {e}",
                message="LLM did not return valid JSON",
            )
        except Exception as e:
            logger.exception(f"Extraction failed: {e}")
            return FunctionResult.failed_result(
                error=str(e),
                message="Extraction failed",
            )
