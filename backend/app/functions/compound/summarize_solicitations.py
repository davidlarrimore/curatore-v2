# backend/app/functions/compound/summarize_solicitations.py
"""
Summarize Solicitations function - Batch summarize SAM.gov solicitations.

Generates summaries for multiple solicitations efficiently.
"""

from typing import Any, Dict, List, Optional
from uuid import UUID
import logging

from sqlalchemy import select, and_

from ..base import (
    BaseFunction,
    FunctionMeta,
    FunctionCategory,
    FunctionResult,
    ParameterDoc,
)
from ..context import FunctionContext

logger = logging.getLogger("curatore.functions.compound.summarize_solicitations")


class SummarizeSolicitationsFunction(BaseFunction):
    """
    Batch summarize SAM.gov solicitations.

    Generates AI summaries for solicitations that don't have them yet.

    Example:
        result = await fn.summarize_solicitations(ctx,
            search_id="uuid",
            limit=20,
        )
    """

    meta = FunctionMeta(
        name="summarize_solicitations",
        category=FunctionCategory.COMPOUND,
        description="Batch summarize SAM.gov solicitations",
        parameters=[
            ParameterDoc(
                name="search_id",
                type="str",
                description="Filter by SAM search ID",
                required=False,
                default=None,
            ),
            ParameterDoc(
                name="only_missing",
                type="bool",
                description="Only summarize solicitations without summaries",
                required=False,
                default=True,
            ),
            ParameterDoc(
                name="limit",
                type="int",
                description="Maximum solicitations to summarize",
                required=False,
                default=20,
            ),
        ],
        returns="dict: Summary of summarization results",
        tags=["compound", "sam", "batch", "summarization"],
        requires_llm=True,
        examples=[
            {
                "description": "Summarize recent unsummarized",
                "params": {
                    "only_missing": True,
                    "limit": 10,
                },
            },
        ],
    )

    async def execute(self, ctx: FunctionContext, **params) -> FunctionResult:
        """Batch summarize solicitations."""
        search_id = params.get("search_id")
        only_missing = params.get("only_missing", True)
        limit = min(params.get("limit", 20), 100)

        from ...database.models import SamSolicitation

        if not ctx.llm_service.is_available:
            return FunctionResult.failed_result(
                error="LLM service not available",
                message="Cannot summarize: LLM service not configured",
            )

        try:
            # Build query
            conditions = [SamSolicitation.organization_id == ctx.organization_id]

            if search_id:
                conditions.append(SamSolicitation.sam_search_id == UUID(search_id))

            if only_missing:
                conditions.append(SamSolicitation.summary.is_(None))

            query = select(SamSolicitation).where(and_(*conditions)).limit(limit)

            result = await ctx.session.execute(query)
            solicitations = result.scalars().all()

            if not solicitations:
                return FunctionResult.skipped_result(
                    message="No solicitations to summarize",
                )

            if ctx.dry_run:
                return FunctionResult.success_result(
                    data={"count": len(solicitations)},
                    message=f"Dry run: would summarize {len(solicitations)} solicitations",
                )

            # Process each solicitation
            processed = 0
            failed = 0
            summaries = []

            for sol in solicitations:
                try:
                    # Generate summary
                    system_prompt = "You are a federal contracting expert. Summarize solicitations concisely for business development teams."

                    user_prompt = f"""Summarize this solicitation in 2-3 sentences:

Title: {sol.title}
Type: {sol.type}
NAICS: {sol.naics_codes}
Set-Aside: {sol.set_aside_type or 'None'}
Deadline: {sol.response_deadline}

Description:
{(sol.description or 'No description')[:2000]}

Summary (2-3 sentences):"""

                    response = ctx.llm_service._client.chat.completions.create(
                        model=ctx.llm_service._get_model(),
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        temperature=0.3,
                        max_tokens=200,
                    )

                    summary = response.choices[0].message.content.strip()

                    # Update solicitation
                    sol.summary = summary
                    sol.summary_status = "completed"

                    summaries.append({
                        "id": str(sol.id),
                        "notice_id": sol.notice_id,
                        "summary": summary,
                    })
                    processed += 1

                except Exception as e:
                    logger.warning(f"Failed to summarize {sol.id}: {e}")
                    sol.summary_status = "failed"
                    failed += 1

            # Flush changes
            await ctx.session.flush()

            if failed > 0 and processed > 0:
                return FunctionResult.partial_result(
                    data={
                        "processed": processed,
                        "failed": failed,
                        "summaries": summaries,
                    },
                    items_processed=processed,
                    items_failed=failed,
                )
            elif failed > 0:
                return FunctionResult.failed_result(
                    error=f"All {failed} summarizations failed",
                )
            else:
                return FunctionResult.success_result(
                    data={
                        "processed": processed,
                        "summaries": summaries,
                    },
                    message=f"Summarized {processed} solicitations",
                    items_processed=processed,
                )

        except Exception as e:
            logger.exception(f"Batch summarization failed: {e}")
            return FunctionResult.failed_result(
                error=str(e),
                message="Batch summarization failed",
            )
