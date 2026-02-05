# backend/app/functions/llm/generate.py
"""
Generate function - LLM text generation.

Wraps the LLM service to generate text from prompts with configurable
parameters like model, temperature, and max tokens.

Supports collection processing via the `items` parameter - when provided,
the prompt is rendered for each item with {{ item.xxx }} template placeholders.
"""

from typing import Any, Dict, List, Optional
import logging

from jinja2 import Template

from ..base import (
    BaseFunction,
    FunctionMeta,
    FunctionCategory,
    FunctionResult,
    ParameterDoc,
)
from ..context import FunctionContext

logger = logging.getLogger("curatore.functions.llm.generate")


def _render_item_template(template_str: str, item: Any) -> str:
    """Render a Jinja2 template string with item context."""
    template = Template(template_str)
    return template.render(item=item)


class GenerateFunction(BaseFunction):
    """
    Generate text using an LLM.

    This function wraps the LLM service to generate text from prompts.
    Supports system prompts, temperature control, and model selection.

    Example:
        result = await fn.generate(ctx,
            prompt="Summarize the following document...",
            system_prompt="You are a document summarization expert.",
            max_tokens=500,
        )
    """

    meta = FunctionMeta(
        name="llm_generate",
        category=FunctionCategory.LLM,
        description="Generate text using an LLM",
        parameters=[
            ParameterDoc(
                name="prompt",
                type="str",
                description="The prompt to generate from",
                required=True,
                example="Summarize the following document in 3 bullet points...",
            ),
            ParameterDoc(
                name="system_prompt",
                type="str",
                description="System prompt to set context",
                required=False,
                default=None,
                example="You are a helpful assistant.",
            ),
            ParameterDoc(
                name="model",
                type="str",
                description="Model to use (uses default if not specified)",
                required=False,
                default=None,
            ),
            ParameterDoc(
                name="temperature",
                type="float",
                description="Temperature for generation (0-2)",
                required=False,
                default=0.7,
            ),
            ParameterDoc(
                name="max_tokens",
                type="int",
                description="Maximum tokens to generate",
                required=False,
                default=1000,
            ),
            ParameterDoc(
                name="items",
                type="list",
                description="Collection of items to iterate over. When provided, the prompt is rendered for each item with {{ item.xxx }} placeholders replaced by item data.",
                required=False,
                default=None,
                example=[{"title": "Item 1"}, {"title": "Item 2"}],
            ),
        ],
        returns="str: The generated text",
        tags=["llm", "text", "generation"],
        requires_llm=True,
        examples=[
            {
                "description": "Simple generation",
                "params": {"prompt": "Write a haiku about coding"},
            },
            {
                "description": "With system prompt",
                "params": {
                    "prompt": "Explain quantum computing",
                    "system_prompt": "You are a physics teacher explaining to a 10-year-old",
                    "max_tokens": 200,
                },
            },
        ],
    )

    async def execute(self, ctx: FunctionContext, **params) -> FunctionResult:
        """Execute text generation."""
        prompt = params["prompt"]
        system_prompt = params.get("system_prompt")
        model = params.get("model")
        temperature = params.get("temperature", 0.7)
        max_tokens = params.get("max_tokens", 1000)
        items = params.get("items")

        # Check LLM availability
        if not ctx.llm_service.is_available:
            return FunctionResult.failed_result(
                error="LLM service is not available",
                message="Cannot generate: LLM service not configured",
            )

        # Collection mode: iterate over items
        if items and isinstance(items, list):
            return await self._execute_collection(
                ctx=ctx,
                items=items,
                prompt_template=prompt,
                system_prompt=system_prompt,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )

        # Single mode: generate once
        return await self._execute_single(
            ctx=ctx,
            prompt=prompt,
            system_prompt=system_prompt,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    async def _execute_single(
        self,
        ctx: FunctionContext,
        prompt: str,
        system_prompt: Optional[str],
        model: Optional[str],
        temperature: float,
        max_tokens: int,
    ) -> FunctionResult:
        """Execute single text generation."""
        try:
            # Build messages
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            # Generate
            response = ctx.llm_service._client.chat.completions.create(
                model=model or ctx.llm_service._get_model(),
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )

            generated_text = response.choices[0].message.content

            return FunctionResult.success_result(
                data=generated_text,
                message=f"Generated {len(generated_text)} characters",
                metadata={
                    "model": response.model,
                    "prompt_tokens": response.usage.prompt_tokens if response.usage else None,
                    "completion_tokens": response.usage.completion_tokens if response.usage else None,
                },
            )

        except Exception as e:
            logger.exception(f"Generation failed: {e}")
            return FunctionResult.failed_result(
                error=str(e),
                message="LLM generation failed",
            )

    async def _execute_collection(
        self,
        ctx: FunctionContext,
        items: List[Any],
        prompt_template: str,
        system_prompt: Optional[str],
        model: Optional[str],
        temperature: float,
        max_tokens: int,
    ) -> FunctionResult:
        """Execute text generation for each item in collection."""
        results = []
        failed_count = 0
        total_chars = 0

        for idx, item in enumerate(items):
            try:
                # Render prompt with item context
                rendered_prompt = _render_item_template(prompt_template, item)

                # Build messages
                messages = []
                if system_prompt:
                    messages.append({"role": "system", "content": system_prompt})
                messages.append({"role": "user", "content": rendered_prompt})

                # Generate
                response = ctx.llm_service._client.chat.completions.create(
                    model=model or ctx.llm_service._get_model(),
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )

                generated_text = response.choices[0].message.content
                total_chars += len(generated_text) if generated_text else 0

                # Extract item ID if available
                item_id = None
                if isinstance(item, dict):
                    item_id = item.get("id") or item.get("item_id") or str(idx)
                else:
                    item_id = str(idx)

                results.append({
                    "item_id": item_id,
                    "result": generated_text,
                    "success": True,
                })

            except Exception as e:
                logger.warning(f"Generation failed for item {idx}: {e}")
                failed_count += 1
                results.append({
                    "item_id": item.get("id") if isinstance(item, dict) else str(idx),
                    "result": None,
                    "success": False,
                    "error": str(e),
                })

        return FunctionResult.success_result(
            data=results,
            message=f"Generated {len(results) - failed_count}/{len(items)} items ({total_chars} total chars)",
            metadata={
                "mode": "collection",
                "total_items": len(items),
                "successful_items": len(items) - failed_count,
                "failed_items": failed_count,
                "total_chars": total_chars,
            },
            items_processed=len(items),
            items_failed=failed_count,
        )
