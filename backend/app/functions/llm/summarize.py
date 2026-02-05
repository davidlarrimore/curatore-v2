# backend/app/functions/llm/summarize.py
"""
Summarize function - Content summarization using LLM.

Generates summaries of text content with configurable length and style.

Supports collection processing via the `items` parameter - when provided,
the text is rendered for each item with {{ item.xxx }} template placeholders.
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

logger = logging.getLogger("curatore.functions.llm.summarize")


def _render_item_template(template_str: str, item: Any) -> str:
    """Render a Jinja2 template string with item context."""
    template = Template(template_str)
    return template.render(item=item)


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
        name="llm_summarize",
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
            ParameterDoc(
                name="items",
                type="list",
                description="Collection of items to iterate over. When provided, the text is rendered for each item with {{ item.xxx }} placeholders replaced by item data.",
                required=False,
                default=None,
                example=[{"content": "Text 1"}, {"content": "Text 2"}],
            ),
        ],
        returns="str or list: The summary (single) or list of summaries (collection)",
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
        items = params.get("items")

        if not ctx.llm_service.is_available:
            return FunctionResult.failed_result(
                error="LLM service is not available",
                message="Cannot summarize: LLM service not configured",
            )

        # Collection mode: iterate over items
        if items and isinstance(items, list):
            return await self._execute_collection(
                ctx=ctx,
                items=items,
                text_template=text,
                style=style,
                max_length=max_length,
                focus=focus,
                model=model,
            )

        # Single mode: summarize once
        return await self._execute_single(
            ctx=ctx,
            text=text,
            style=style,
            max_length=max_length,
            focus=focus,
            model=model,
        )

    async def _execute_single(
        self,
        ctx: FunctionContext,
        text: str,
        style: str,
        max_length: int,
        focus: Optional[str],
        model: Optional[str],
    ) -> FunctionResult:
        """Execute single summarization."""
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

    async def _execute_collection(
        self,
        ctx: FunctionContext,
        items: List[Any],
        text_template: str,
        style: str,
        max_length: int,
        focus: Optional[str],
        model: Optional[str],
    ) -> FunctionResult:
        """Execute summarization for each item in collection."""
        results = []
        failed_count = 0
        total_chars = 0

        # Build style instruction once
        style_instructions = {
            "paragraph": "Write a concise paragraph summary.",
            "bullets": "Write a bullet-point summary with 3-5 key points.",
            "one_sentence": "Write a single-sentence summary that captures the essence.",
            "key_points": "List the 3-5 most important points or takeaways.",
        }
        style_instruction = style_instructions.get(style, style_instructions["paragraph"])

        system_prompt = """You are a summarization expert. Create clear, accurate summaries that capture the key information.
Be concise and focus on the most important points."""

        for idx, item in enumerate(items):
            try:
                # Render text with item context
                rendered_text = _render_item_template(text_template, item)

                user_prompt = f"""{style_instruction}
{f"Focus on: {focus}" if focus else ""}
Keep the summary under approximately {max_length} characters.

Text to summarize:
---
{rendered_text}
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
                    max_tokens=max(500, max_length // 2),
                )

                summary = response.choices[0].message.content.strip()
                total_chars += len(summary) if summary else 0

                # Extract item ID if available
                item_id = None
                if isinstance(item, dict):
                    item_id = item.get("id") or item.get("item_id") or str(idx)
                else:
                    item_id = str(idx)

                results.append({
                    "item_id": item_id,
                    "result": summary,
                    "success": True,
                })

            except Exception as e:
                logger.warning(f"Summarization failed for item {idx}: {e}")
                failed_count += 1
                results.append({
                    "item_id": item.get("id") if isinstance(item, dict) else str(idx),
                    "result": None,
                    "success": False,
                    "error": str(e),
                })

        return FunctionResult.success_result(
            data=results,
            message=f"Summarized {len(results) - failed_count}/{len(items)} items ({total_chars} total chars)",
            metadata={
                "mode": "collection",
                "style": style,
                "total_items": len(items),
                "successful_items": len(items) - failed_count,
                "failed_items": failed_count,
                "total_chars": total_chars,
            },
            items_processed=len(items),
            items_failed=failed_count,
        )
