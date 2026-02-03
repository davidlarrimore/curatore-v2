# backend/app/functions/llm/summarize.py
"""
Summarize function - Content summarization using LLM.

Generates summaries of text content with configurable length and style.
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

logger = logging.getLogger("curatore.functions.llm.summarize")


class SummarizeFunction(BaseFunction):
    """
    Summarize text content using an LLM.

    Generates summaries with configurable length and format options.

    Example:
        result = await fn.summarize(ctx,
            text="Long document text here...",
            style="bullets",
            max_length=200,
        )
    """

    meta = FunctionMeta(
        name="summarize",
        category=FunctionCategory.LLM,
        description="Summarize text content using an LLM",
        parameters=[
            ParameterDoc(
                name="text",
                type="str",
                description="The text to summarize",
                required=True,
            ),
            ParameterDoc(
                name="style",
                type="str",
                description="Summary style",
                required=False,
                default="paragraph",
                enum_values=["paragraph", "bullets", "one_sentence", "key_points"],
            ),
            ParameterDoc(
                name="max_length",
                type="int",
                description="Target maximum length in characters (approximate)",
                required=False,
                default=500,
            ),
            ParameterDoc(
                name="focus",
                type="str",
                description="What to focus on in the summary",
                required=False,
                default=None,
                example="technical details",
            ),
            ParameterDoc(
                name="model",
                type="str",
                description="Model to use",
                required=False,
                default=None,
            ),
        ],
        returns="str: The summary",
        tags=["llm", "summarization", "text"],
        requires_llm=True,
        examples=[
            {
                "description": "Bullet point summary",
                "params": {
                    "text": "Long document...",
                    "style": "bullets",
                    "max_length": 300,
                },
            },
        ],
    )

    async def execute(self, ctx: FunctionContext, **params) -> FunctionResult:
        """Execute summarization."""
        text = params["text"]
        style = params.get("style", "paragraph")
        max_length = params.get("max_length", 500)
        focus = params.get("focus")
        model = params.get("model")

        if not ctx.llm_service.is_available:
            return FunctionResult.failed_result(
                error="LLM service is not available",
                message="Cannot summarize: LLM service not configured",
            )

        try:
            # Build style instruction
            style_instructions = {
                "paragraph": "Write a concise paragraph summary.",
                "bullets": "Write a bullet-point summary with 3-5 key points.",
                "one_sentence": "Write a single-sentence summary that captures the essence.",
                "key_points": "List the 3-5 most important points or takeaways.",
            }
            style_instruction = style_instructions.get(style, style_instructions["paragraph"])

            system_prompt = """You are a summarization expert. Create clear, accurate summaries that capture the key information.
Be concise and focus on the most important points."""

            user_prompt = f"""{style_instruction}
{f"Focus on: {focus}" if focus else ""}
Keep the summary under approximately {max_length} characters.

Text to summarize:
---
{text}
---

Summary:"""

            # Generate
            response = ctx.llm_service._client.chat.completions.create(
                model=model or ctx.llm_service._get_model(),
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.5,
                max_tokens=max(500, max_length // 2),  # Rough token estimate
            )

            summary = response.choices[0].message.content.strip()

            return FunctionResult.success_result(
                data=summary,
                message=f"Generated {style} summary ({len(summary)} chars)",
                metadata={
                    "model": response.model,
                    "style": style,
                    "input_length": len(text),
                    "output_length": len(summary),
                    "compression_ratio": len(text) / len(summary) if summary else 0,
                },
            )

        except Exception as e:
            logger.exception(f"Summarization failed: {e}")
            return FunctionResult.failed_result(
                error=str(e),
                message="Summarization failed",
            )
