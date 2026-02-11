# backend/app/functions/llm/extract.py
"""
Extract function - Structured data extraction using LLM.

Extracts structured data from text using an LLM with JSON schema validation.

Supports collection processing via the `items` parameter - when provided,
the text is rendered for each item with {{ item.xxx }} template placeholders.
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

logger = logging.getLogger("curatore.functions.llm.extract")


def _render_item_template(template_str: str, item: Any) -> str:
    """Render a Jinja2 template string with item context."""
    template = Template(template_str)
    return template.render(item=item)


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
        name="llm_extract",
        category=FunctionCategory.LLM,
        description="Extract structured data from text using an LLM",
        input_schema={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The text to extract from",
                },
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Fields to extract",
                    "examples": [["name", "email", "phone"]],
                },
                "field_descriptions": {
                    "type": "object",
                    "description": "Optional descriptions for each field",
                    "default": None,
                },
                "instructions": {
                    "type": "string",
                    "description": "Additional extraction instructions",
                    "default": None,
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
                },
            },
            "required": ["text", "fields"],
        },
        output_schema={
            "type": "object",
            "description": "Dictionary with extracted field values (keys match requested fields)",
            "properties": {
                "<field_name>": {
                    "type": "string",
                    "description": "Each requested field is returned as a key. Value is null if not found.",
                    "nullable": True,
                    "examples": ["John Smith"],
                },
            },
            "examples": [{"name": "John Smith", "email": "john@example.com", "phone": "555-1234"}],
            "variants": [
                {
                    "type": "array",
                    "description": "collection: when `items` parameter is provided",
                    "items": {
                        "type": "object",
                        "properties": {
                            "item_id": {"type": "string", "description": "ID of the processed item"},
                            "result": {"type": "object", "description": "Extracted fields dictionary"},
                            "success": {"type": "boolean", "description": "Whether extraction succeeded"},
                            "error": {"type": "string", "description": "Error message if failed", "nullable": True},
                        },
                    },
                },
            ],
        },
        tags=["llm", "extraction", "structured"],
        requires_llm=True,
        side_effects=False,
        is_primitive=True,
        payload_profile="full",
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
        items = params.get("items")

        if not ctx.llm_service.is_available:
            return FunctionResult.failed_result(
                error="LLM service is not available",
                message="Cannot extract: LLM service not configured",
            )

        # Collection mode: iterate over items
        if items and isinstance(items, list):
            return await self._execute_collection(
                ctx=ctx,
                items=items,
                text_template=text,
                fields=fields,
                field_descriptions=field_descriptions,
                instructions=instructions,
                model=model,
            )

        # Single mode: extract once
        return await self._execute_single(
            ctx=ctx,
            text=text,
            fields=fields,
            field_descriptions=field_descriptions,
            instructions=instructions,
            model=model,
        )

    def _parse_json_response(self, response_text: str) -> dict:
        """Parse JSON from response, handling markdown code blocks."""
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
        return json.loads(response_text)

    async def _execute_single(
        self,
        ctx: FunctionContext,
        text: str,
        fields: List[str],
        field_descriptions: Dict[str, str],
        instructions: Optional[str],
        model: Optional[str],
    ) -> FunctionResult:
        """Execute single extraction."""
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

            # Get model and temperature from task type routing (STANDARD for extraction)
            task_config = config_loader.get_task_type_config(LLMTaskType.STANDARD)
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
                max_tokens=1000,
            )

            response_text = response.choices[0].message.content.strip()
            extracted = self._parse_json_response(response_text)

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

    async def _execute_collection(
        self,
        ctx: FunctionContext,
        items: List[Any],
        text_template: str,
        fields: List[str],
        field_descriptions: Dict[str, str],
        instructions: Optional[str],
        model: Optional[str],
    ) -> FunctionResult:
        """Execute extraction for each item in collection."""
        results = []
        failed_count = 0

        # Build field list once
        field_list = "\n".join([
            f"- {field}: {field_descriptions.get(field, 'Extract this field')}"
            for field in fields
        ])

        system_prompt = """You are a data extraction assistant. Extract the requested fields from the text.
Return ONLY a valid JSON object with the extracted fields. If a field cannot be found, use null.
Do not include any explanation or markdown formatting."""

        # Get model and temperature from task type routing (BULK for collection mode)
        task_config = config_loader.get_task_type_config(LLMTaskType.BULK)
        resolved_model = model or task_config.model
        temperature = task_config.temperature if task_config.temperature is not None else 0.1

        for idx, item in enumerate(items):
            try:
                # Render text with item context
                rendered_text = _render_item_template(text_template, item)

                user_prompt = f"""Extract the following fields from the text:

{field_list}

{f"Additional instructions: {instructions}" if instructions else ""}

Text to extract from:
---
{rendered_text}
---

Return ONLY the JSON object:"""

                # Generate
                response = ctx.llm_service._client.chat.completions.create(
                    model=resolved_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=temperature,
                    max_tokens=1000,
                )

                response_text = response.choices[0].message.content.strip()
                extracted = self._parse_json_response(response_text)

                # Ensure all requested fields are present
                for field in fields:
                    if field not in extracted:
                        extracted[field] = None

                # Extract item ID if available
                item_id = None
                if isinstance(item, dict):
                    item_id = item.get("id") or item.get("item_id") or str(idx)
                else:
                    item_id = str(idx)

                results.append({
                    "item_id": item_id,
                    "result": extracted,
                    "success": True,
                })

            except json.JSONDecodeError as e:
                logger.warning(f"Extraction failed for item {idx}: invalid JSON - {e}")
                failed_count += 1
                results.append({
                    "item_id": item.get("id") if isinstance(item, dict) else str(idx),
                    "result": None,
                    "success": False,
                    "error": f"Invalid JSON response: {e}",
                })
            except Exception as e:
                logger.warning(f"Extraction failed for item {idx}: {e}")
                failed_count += 1
                results.append({
                    "item_id": item.get("id") if isinstance(item, dict) else str(idx),
                    "result": None,
                    "success": False,
                    "error": str(e),
                })

        return FunctionResult.success_result(
            data=results,
            message=f"Extracted {len(results) - failed_count}/{len(items)} items",
            metadata={
                "mode": "collection",
                "fields": fields,
                "total_items": len(items),
                "successful_items": len(items) - failed_count,
                "failed_items": failed_count,
            },
            items_processed=len(items),
            items_failed=failed_count,
        )
