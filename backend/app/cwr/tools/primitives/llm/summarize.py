# backend/app/functions/llm/summarize.py
"""
Summarize function - Content summarization using LLM.

Generates summaries of text content with configurable length and style.

Features:
- Automatic chunking for large documents (map-reduce pattern)
- Collection processing via `items` parameter
- Configurable models for map phase (BULK) vs reduce phase (STANDARD)

For large documents that exceed the LLM context window, the function
automatically chunks the document and uses a map-reduce approach:
1. Map phase: Summarize each chunk independently (using BULK task type)
2. Reduce phase: Combine chunk summaries into final summary (using STANDARD task type)
"""

import asyncio
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
from app.core.search.document_chunker import document_chunker

logger = logging.getLogger("curatore.functions.llm.summarize")

# Maximum tokens for single-pass summarization (leave room for output)
MAX_SINGLE_PASS_TOKENS = 80000


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
        input_schema={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The text to summarize",
                },
                "style": {
                    "type": "string",
                    "description": "Summary style",
                    "default": "paragraph",
                    "enum": ["paragraph", "bullets", "one_sentence", "key_points"],
                },
                "max_length": {
                    "type": "integer",
                    "description": "Target maximum length in characters (approximate)",
                    "default": 500,
                },
                "focus": {
                    "type": "string",
                    "description": "What to focus on in the summary",
                    "default": None,
                    "examples": ["technical details"],
                },
                "model": {
                    "type": "string",
                    "description": "Model to use (overrides task type default)",
                    "default": None,
                },
                "auto_chunk": {
                    "type": "boolean",
                    "description": "Automatically chunk large documents that exceed context window (default: True)",
                    "default": True,
                },
                "chunk_size": {
                    "type": "integer",
                    "description": "Target tokens per chunk for large document processing (default: 8000)",
                    "default": 8000,
                },
                "map_model": {
                    "type": "string",
                    "description": "Model to use for map phase (chunk summaries). Uses BULK task type if not specified.",
                    "default": None,
                },
                "reduce_model": {
                    "type": "string",
                    "description": "Model to use for reduce phase (final summary). Uses STANDARD task type if not specified.",
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
            "required": ["text"],
        },
        output_schema={
            "type": "string",
            "description": "The generated summary text",
            "examples": ["Key findings include: 1) The project is on track..."],
            "variants": [
                {
                    "type": "array",
                    "description": "collection: when `items` parameter is provided",
                    "items": {
                        "type": "object",
                        "properties": {
                            "item_id": {"type": "string", "description": "ID of the processed item"},
                            "result": {"type": "string", "description": "Summary text for this item"},
                            "success": {"type": "boolean", "description": "Whether summarization succeeded"},
                            "error": {"type": "string", "description": "Error message if failed", "nullable": True},
                        },
                    },
                },
            ],
        },
        tags=["llm", "summarization", "text"],
        requires_llm=True,
        side_effects=False,
        is_primitive=True,
        payload_profile="full",
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
        auto_chunk = params.get("auto_chunk", True)
        chunk_size = params.get("chunk_size", 8000)
        map_model = params.get("map_model")
        reduce_model = params.get("reduce_model")
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

        # Check if chunking is needed for large documents
        if auto_chunk and document_chunker.needs_chunking(text, max_tokens=MAX_SINGLE_PASS_TOKENS):
            token_count = document_chunker.count_tokens(text)
            logger.info(
                f"Document exceeds single-pass limit ({token_count} tokens > {MAX_SINGLE_PASS_TOKENS}), "
                f"using chunked map-reduce summarization"
            )
            return await self._execute_chunked(
                ctx=ctx,
                text=text,
                style=style,
                max_length=max_length,
                focus=focus,
                chunk_size=chunk_size,
                map_model=map_model or model,
                reduce_model=reduce_model or model,
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

            # Get model and temperature from task type routing
            task_config = config_loader.get_task_type_config(LLMTaskType.STANDARD)
            resolved_model = model or task_config.model
            temperature = task_config.temperature if task_config.temperature is not None else 0.5

            # Generate
            response = ctx.llm_service._client.chat.completions.create(
                model=resolved_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
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

    async def _execute_chunked(
        self,
        ctx: FunctionContext,
        text: str,
        style: str,
        max_length: int,
        focus: Optional[str],
        chunk_size: int,
        map_model: Optional[str],
        reduce_model: Optional[str],
    ) -> FunctionResult:
        """
        Execute map-reduce summarization for large documents.

        Process:
        1. Chunk the document into manageable pieces
        2. Map phase: Summarize each chunk in parallel (using BULK task type)
        3. Reduce phase: Combine chunk summaries into final summary (using STANDARD task type)
        4. If combined summaries still too large, recurse
        """
        try:
            # Chunk the document
            chunks = document_chunker.chunk_document(text, chunk_size=chunk_size)
            logger.info(f"Chunked document into {len(chunks)} chunks for map-reduce summarization")

            # Get model configs for map and reduce phases
            map_task_config = config_loader.get_task_type_config(LLMTaskType.BULK)
            reduce_task_config = config_loader.get_task_type_config(LLMTaskType.STANDARD)

            resolved_map_model = map_model or map_task_config.model
            resolved_reduce_model = reduce_model or reduce_task_config.model
            map_temperature = map_task_config.temperature if map_task_config.temperature is not None else 0.3
            reduce_temperature = reduce_task_config.temperature if reduce_task_config.temperature is not None else 0.5

            # Map phase: summarize each chunk
            system_prompt = """You are a summarization expert. Create a clear, accurate summary of this document section.
Focus on the key information and main points. This is part of a larger document that will be combined later."""

            chunk_summaries = []
            failed_chunks = 0

            # Process chunks in parallel (batch of 5 to avoid rate limits)
            batch_size = 5
            for batch_start in range(0, len(chunks), batch_size):
                batch = chunks[batch_start:batch_start + batch_size]

                async def summarize_chunk(chunk):
                    try:
                        user_prompt = f"""Summarize this section of a larger document:

Section {chunk.chunk_index + 1} of {chunk.total_chunks}
---
{chunk.content}
---

Provide a concise summary focusing on the key information:"""

                        response = ctx.llm_service._client.chat.completions.create(
                            model=resolved_map_model,
                            messages=[
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_prompt},
                            ],
                            temperature=map_temperature,
                            max_tokens=1000,  # Each chunk summary should be concise
                        )
                        return response.choices[0].message.content.strip()
                    except Exception as e:
                        logger.warning(f"Chunk {chunk.chunk_index} summarization failed: {e}")
                        return None

                # Run batch in parallel
                batch_results = await asyncio.gather(
                    *[asyncio.to_thread(lambda c=c: asyncio.run(summarize_chunk(c))) for c in batch],
                    return_exceptions=True
                )

                # Actually, the above won't work because we're mixing sync OpenAI with async
                # Let's do sequential processing with the sync client
                for chunk in batch:
                    try:
                        user_prompt = f"""Summarize this section of a larger document:

Section {chunk.chunk_index + 1} of {chunk.total_chunks}
---
{chunk.content}
---

Provide a concise summary focusing on the key information:"""

                        response = ctx.llm_service._client.chat.completions.create(
                            model=resolved_map_model,
                            messages=[
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_prompt},
                            ],
                            temperature=map_temperature,
                            max_tokens=1000,
                        )
                        chunk_summaries.append(response.choices[0].message.content.strip())
                    except Exception as e:
                        logger.warning(f"Chunk {chunk.chunk_index} summarization failed: {e}")
                        failed_chunks += 1
                        chunk_summaries.append(None)

            # Filter out failed chunks
            successful_summaries = [s for s in chunk_summaries if s]

            if not successful_summaries:
                return FunctionResult.failed_result(
                    error="All chunk summarizations failed",
                    message="Could not summarize any document chunks",
                )

            # Combine summaries
            combined = "\n\n---\n\n".join([
                f"**Section {i+1}:**\n{summary}"
                for i, summary in enumerate(successful_summaries)
            ])

            # Check if we need another reduce level
            combined_tokens = document_chunker.count_tokens(combined)
            if combined_tokens > MAX_SINGLE_PASS_TOKENS:
                logger.info(
                    f"Combined summaries still too large ({combined_tokens} tokens), "
                    f"applying recursive reduction"
                )
                return await self._execute_chunked(
                    ctx=ctx,
                    text=combined,
                    style=style,
                    max_length=max_length,
                    focus=focus,
                    chunk_size=chunk_size,
                    map_model=map_model,
                    reduce_model=reduce_model,
                )

            # Reduce phase: create final summary from chunk summaries
            style_instructions = {
                "paragraph": "Write a concise paragraph summary.",
                "bullets": "Write a bullet-point summary with 3-5 key points.",
                "one_sentence": "Write a single-sentence summary that captures the essence.",
                "key_points": "List the 3-5 most important points or takeaways.",
            }
            style_instruction = style_instructions.get(style, style_instructions["paragraph"])

            reduce_system_prompt = """You are a summarization expert. You are creating a final summary from section summaries of a larger document.
Synthesize the key information into a cohesive summary that covers the entire document."""

            reduce_user_prompt = f"""{style_instruction}
{f"Focus on: {focus}" if focus else ""}
Keep the summary under approximately {max_length} characters.

Here are the section summaries from different parts of the document:

{combined}

Create a final, unified summary:"""

            response = ctx.llm_service._client.chat.completions.create(
                model=resolved_reduce_model,
                messages=[
                    {"role": "system", "content": reduce_system_prompt},
                    {"role": "user", "content": reduce_user_prompt},
                ],
                temperature=reduce_temperature,
                max_tokens=max(500, max_length // 2),
            )

            final_summary = response.choices[0].message.content.strip()

            return FunctionResult.success_result(
                data=final_summary,
                message=f"Generated {style} summary using map-reduce ({len(chunks)} chunks)",
                metadata={
                    "mode": "chunked",
                    "map_model": resolved_map_model,
                    "reduce_model": resolved_reduce_model,
                    "style": style,
                    "input_length": len(text),
                    "input_tokens": document_chunker.count_tokens(text),
                    "output_length": len(final_summary),
                    "chunks_processed": len(chunks),
                    "chunks_failed": failed_chunks,
                    "compression_ratio": len(text) / len(final_summary) if final_summary else 0,
                },
            )

        except Exception as e:
            logger.exception(f"Chunked summarization failed: {e}")
            return FunctionResult.failed_result(
                error=str(e),
                message="Chunked summarization failed",
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

        # Get model and temperature from task type routing (BULK for collection mode)
        task_config = config_loader.get_task_type_config(LLMTaskType.BULK)
        resolved_model = model or task_config.model
        temperature = task_config.temperature if task_config.temperature is not None else 0.3

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
                    model=resolved_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=temperature,
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
