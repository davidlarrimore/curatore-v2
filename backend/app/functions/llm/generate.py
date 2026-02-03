# backend/app/functions/llm/generate.py
"""
Generate function - LLM text generation.

Wraps the LLM service to generate text from prompts with configurable
parameters like model, temperature, and max tokens.
"""

from typing import Any, Dict, Optional
import logging

from ..base import (
    BaseFunction,
    FunctionMeta,
    FunctionCategory,
    FunctionResult,
    ParameterDoc,
)
from ..context import FunctionContext

logger = logging.getLogger("curatore.functions.llm.generate")


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
        name="generate",
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

        # Check LLM availability
        if not ctx.llm_service.is_available:
            return FunctionResult.failed_result(
                error="LLM service is not available",
                message="Cannot generate: LLM service not configured",
            )

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
