# backend/app/functions/compound/analyze_solicitation.py
"""
Analyze Solicitation function - Analyze a single SAM.gov solicitation.

Compound function that generates a structured analysis of a solicitation
including key requirements, evaluation criteria, and recommendations.
"""

from typing import Any, Dict, Optional
from uuid import UUID
import logging

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..base import (
    BaseFunction,
    FunctionMeta,
    FunctionCategory,
    FunctionResult,
    ParameterDoc,
)
from ..context import FunctionContext

logger = logging.getLogger("curatore.functions.compound.analyze_solicitation")


class AnalyzeSolicitationFunction(BaseFunction):
    """
    Analyze a SAM.gov solicitation for business development.

    Generates a structured analysis including:
    - Executive summary
    - Key requirements
    - Evaluation criteria
    - Compliance checklist
    - Win strategy recommendations

    Example:
        result = await fn.analyze_solicitation(ctx,
            solicitation_id="uuid",
        )
    """

    meta = FunctionMeta(
        name="analyze_solicitation",
        category=FunctionCategory.COMPOUND,
        description="Analyze a SAM.gov solicitation for business development",
        parameters=[
            ParameterDoc(
                name="solicitation_id",
                type="str",
                description="Solicitation ID to analyze",
                required=True,
            ),
            ParameterDoc(
                name="analysis_depth",
                type="str",
                description="Depth of analysis",
                required=False,
                default="standard",
                enum_values=["brief", "standard", "detailed"],
            ),
            ParameterDoc(
                name="focus_areas",
                type="list[str]",
                description="Specific areas to focus on",
                required=False,
                default=None,
                example=["technical_requirements", "pricing", "past_performance"],
            ),
        ],
        returns="dict: Structured analysis including summary, requirements, and recommendations",
        tags=["compound", "sam", "analysis", "bd"],
        requires_llm=True,
        examples=[
            {
                "description": "Standard analysis",
                "params": {
                    "solicitation_id": "uuid",
                    "analysis_depth": "standard",
                },
            },
        ],
    )

    async def execute(self, ctx: FunctionContext, **params) -> FunctionResult:
        """Analyze solicitation."""
        solicitation_id = params["solicitation_id"]
        analysis_depth = params.get("analysis_depth", "standard")
        focus_areas_raw = params.get("focus_areas")

        # Normalize focus_areas to a list of strings or None
        focus_areas = None
        if focus_areas_raw:
            if isinstance(focus_areas_raw, list):
                # Filter out non-strings and empty values, convert any dicts to their string repr
                focus_areas = [
                    str(item) if not isinstance(item, str) else item
                    for item in focus_areas_raw
                    if item  # Filter out None/empty
                ]
            elif isinstance(focus_areas_raw, str):
                focus_areas = [focus_areas_raw]

        logger.debug(f"analyze_solicitation params: solicitation_id={solicitation_id}, depth={analysis_depth}, focus_areas={focus_areas}")

        from ...database.models import SamSolicitation

        try:
            # Get solicitation with summaries eagerly loaded
            sol_uuid = UUID(solicitation_id) if isinstance(solicitation_id, str) else solicitation_id
            query = (
                select(SamSolicitation)
                .options(selectinload(SamSolicitation.summaries))
                .where(
                    SamSolicitation.id == sol_uuid,
                    SamSolicitation.organization_id == ctx.organization_id,
                )
            )
            result = await ctx.session.execute(query)
            solicitation = result.scalar_one_or_none()

            if not solicitation:
                return FunctionResult.failed_result(
                    error="Solicitation not found",
                    message=f"Solicitation {solicitation_id} not found",
                )

            # Check if already has canonical summary (for brief analysis)
            canonical_summary = None
            if solicitation.summaries:
                canonical_summary = next(
                    (s for s in solicitation.summaries if s.is_canonical),
                    None
                )

            if canonical_summary and analysis_depth == "brief":
                return FunctionResult.success_result(
                    data={
                        "solicitation_id": str(solicitation.id),
                        "title": solicitation.title,
                        "summary": canonical_summary.summary,
                        "cached": True,
                    },
                    message="Returned cached summary",
                )

            # Check LLM availability
            if not ctx.llm_service.is_available:
                return FunctionResult.failed_result(
                    error="LLM service not available",
                    message="Cannot analyze: LLM service not configured",
                )

            # Build analysis prompt
            depth_instructions = {
                "brief": "Provide a brief 2-3 sentence summary.",
                "standard": "Provide a comprehensive analysis with key sections.",
                "detailed": "Provide an in-depth analysis with all details and recommendations.",
            }

            focus_section = ""
            if focus_areas and len(focus_areas) > 0:
                focus_section = f"\n\nFocus especially on: {', '.join(focus_areas)}"

            system_prompt = """You are a federal contracting expert analyzing solicitations for business development teams.
Provide actionable insights that help win contracts. Be specific and cite requirements from the solicitation."""

            # Format place of performance if available
            pop_str = "Not specified"
            if solicitation.place_of_performance:
                pop = solicitation.place_of_performance
                if isinstance(pop, dict):
                    pop_parts = []
                    # Handle nested structures - values might be dicts like {"code": "DC", "name": "Washington"}
                    for key in ["city", "state", "country"]:
                        val = pop.get(key)
                        if val:
                            if isinstance(val, dict):
                                # Use "name" field if available, otherwise "code", otherwise str repr
                                pop_parts.append(val.get("name") or val.get("code") or str(val))
                            else:
                                pop_parts.append(str(val))
                    pop_str = ", ".join(pop_parts) if pop_parts else "Not specified"
                else:
                    pop_str = str(pop)

            # Format contracting office
            office_str = solicitation.office_name or solicitation.bureau_name or solicitation.agency_name or "Not specified"

            user_prompt = f"""Analyze this SAM.gov solicitation:

Title: {solicitation.title}
Notice ID: {solicitation.notice_id}
Type: {solicitation.notice_type}
Posted: {solicitation.posted_date}
Response Deadline: {solicitation.response_deadline}
NAICS: {solicitation.naics_code or 'Not specified'}
Set-Aside: {solicitation.set_aside_code or 'None'}
Contracting Office: {office_str}
Place of Performance: {pop_str}

Description:
{solicitation.description or 'No description available'}

{depth_instructions.get(analysis_depth)}
{focus_section}

Structure your response as:
1. **Executive Summary** - 2-3 sentences on what this is and why it matters
2. **Key Requirements** - Bullet list of must-have capabilities
3. **Evaluation Criteria** - What the government will evaluate (if discernible)
4. **Timeline & Milestones** - Key dates and deadlines
5. **Recommendations** - Specific next steps for pursuit

Return your analysis in markdown format."""

            # Generate analysis
            response = ctx.llm_service._client.chat.completions.create(
                model=ctx.llm_service._get_model(),
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                max_tokens=2000 if analysis_depth == "detailed" else 1000,
            )

            analysis = response.choices[0].message.content

            # If brief analysis, save as summary
            if analysis_depth == "brief" and not ctx.dry_run:
                from ...database.models import SamSolicitationSummary
                from datetime import datetime

                # Create new summary record
                summary_record = SamSolicitationSummary(
                    solicitation_id=solicitation.id,
                    summary_type="executive",
                    is_canonical=True,
                    model=response.model,
                    summary=analysis,
                    token_count=response.usage.total_tokens if response.usage else None,
                )
                ctx.session.add(summary_record)

                # Update solicitation status
                solicitation.summary_status = "ready"
                solicitation.summary_generated_at = datetime.utcnow()

                # Mark any existing canonical summaries as non-canonical
                if solicitation.summaries:
                    for existing in solicitation.summaries:
                        if existing.is_canonical and existing.id != summary_record.id:
                            existing.is_canonical = False

            return FunctionResult.success_result(
                data={
                    "solicitation_id": str(solicitation.id),
                    "notice_id": solicitation.notice_id,
                    "title": solicitation.title,
                    "analysis": analysis,
                    "analysis_depth": analysis_depth,
                    "model": response.model,
                },
                message=f"Generated {analysis_depth} analysis",
                items_processed=1,
            )

        except Exception as e:
            logger.exception(f"Analysis failed: {e}")
            return FunctionResult.failed_result(
                error=str(e),
                message="Solicitation analysis failed",
            )
