"""
SAM.gov Summarization Service for LLM-Powered Opportunity Analysis.

Provides LLM-driven summarization and analysis of federal contract opportunities.
Integrates with the AssetMetadata experiment system for comparing different
prompt strategies and models.

Key Features:
- Generate executive summaries of solicitations
- Extract key requirements from SOWs and attachments
- Create compliance checklists for eligibility
- Support multiple summary types (full, executive, technical, compliance)
- Experiment tracking via AssetMetadata
- Promotion mechanics for canonical summaries

Usage:
    from app.services.sam_summarization_service import sam_summarization_service

    # Generate a summary
    summary = await sam_summarization_service.summarize_solicitation(
        session=session,
        solicitation_id=solicitation.id,
        summary_type="executive",
        organization_id=org_id,
    )

    # Generate with custom prompt
    summary = await sam_summarization_service.summarize_with_prompt(
        session=session,
        solicitation_id=solicitation.id,
        prompt_template=custom_prompt,
        model="gpt-4o",
        organization_id=org_id,
    )
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database.models import (
    Asset,
    AssetMetadata,
    ExtractionResult,
    Run,
    SamSolicitation,
    SamSolicitationSummary,
)
from .llm_service import LLMService
from .sam_service import sam_service

logger = logging.getLogger("curatore.sam_summarization_service")


# Default prompt templates for different summary types
PROMPT_TEMPLATES = {
    "executive": """You are an expert federal contracting analyst. Analyze the following federal solicitation and provide a concise executive summary.

SOLICITATION INFORMATION:
Title: {title}
Solicitation Number: {solicitation_number}
Notice Type: {notice_type}
NAICS Code: {naics_code}
Set-Aside: {set_aside}
Response Deadline: {response_deadline}

DESCRIPTION:
{description}

{attachment_content}

Provide your analysis in the following JSON format:
{{
    "executive_summary": "A 2-3 paragraph executive summary covering the opportunity, key requirements, and important dates",
    "opportunity_type": "Brief description of what type of work/service/product is being requested",
    "estimated_value": "Estimated contract value if mentioned, otherwise 'Not specified'",
    "key_dates": [
        {{"event": "Response Deadline", "date": "..."}}
    ],
    "recommendation": "Brief recommendation on whether to pursue this opportunity"
}}

Respond ONLY with valid JSON, no additional text.""",

    "technical": """You are an expert technical analyst for federal contracting. Analyze the following solicitation and extract technical requirements.

SOLICITATION INFORMATION:
Title: {title}
Solicitation Number: {solicitation_number}
NAICS Code: {naics_code}

DESCRIPTION:
{description}

{attachment_content}

Provide your analysis in the following JSON format:
{{
    "technical_summary": "A technical summary of the work required",
    "key_requirements": [
        {{
            "category": "Category (e.g., Technical, Personnel, Security)",
            "requirement": "Description of the requirement",
            "mandatory": true/false,
            "notes": "Any additional notes"
        }}
    ],
    "technical_skills": ["List of technical skills/capabilities required"],
    "certifications_required": ["List of any certifications or clearances required"],
    "deliverables": ["List of expected deliverables"],
    "evaluation_criteria": ["How proposals will be evaluated if mentioned"]
}}

Respond ONLY with valid JSON, no additional text.""",

    "compliance": """You are an expert in federal contracting compliance. Analyze the following solicitation for eligibility requirements.

SOLICITATION INFORMATION:
Title: {title}
Solicitation Number: {solicitation_number}
NAICS Code: {naics_code}
Set-Aside: {set_aside}

DESCRIPTION:
{description}

{attachment_content}

Provide your compliance analysis in the following JSON format:
{{
    "compliance_summary": "Overview of compliance requirements",
    "eligibility_requirements": [
        {{
            "requirement": "Description of eligibility requirement",
            "type": "mandatory/preferred",
            "verification": "How to verify compliance"
        }}
    ],
    "set_aside_analysis": {{
        "type": "Type of set-aside if any",
        "eligible_businesses": "Description of eligible business types",
        "certification_required": true/false
    }},
    "checklist": [
        {{
            "item": "Checklist item description",
            "status": "required/recommended/optional",
            "notes": "Additional notes"
        }}
    ],
    "risks": ["List of potential compliance risks or concerns"]
}}

Respond ONLY with valid JSON, no additional text.""",

    "full": """You are an expert federal contracting analyst. Provide a comprehensive analysis of the following solicitation.

SOLICITATION INFORMATION:
Title: {title}
Solicitation Number: {solicitation_number}
Notice Type: {notice_type}
NAICS Code: {naics_code}
PSC Code: {psc_code}
Set-Aside: {set_aside}
Response Deadline: {response_deadline}
Agency: {agency}

DESCRIPTION:
{description}

{attachment_content}

Provide your comprehensive analysis in the following JSON format:
{{
    "summary": "A comprehensive 3-4 paragraph summary of the opportunity",
    "opportunity_overview": {{
        "type": "Type of opportunity",
        "estimated_value": "Estimated value if available",
        "period_of_performance": "Contract duration if mentioned",
        "place_of_performance": "Location of work"
    }},
    "key_requirements": [
        {{
            "category": "Category name",
            "requirement": "Requirement description",
            "mandatory": true/false,
            "priority": "high/medium/low"
        }}
    ],
    "compliance_checklist": [
        {{
            "item": "Compliance item",
            "required": true/false,
            "notes": "Additional notes"
        }}
    ],
    "key_dates": [
        {{"event": "Event name", "date": "Date"}}
    ],
    "evaluation_factors": ["List of evaluation factors if mentioned"],
    "strengths": ["Reasons why this might be a good opportunity"],
    "risks": ["Potential risks or concerns"],
    "recommendation": "Overall recommendation with reasoning",
    "confidence_score": 0.0-1.0
}}

Respond ONLY with valid JSON, no additional text.""",
}


class SamSummarizationService:
    """
    Service for LLM-powered summarization of SAM.gov solicitations.

    Provides various summary types and integrates with the experiment
    system for comparing different approaches.
    """

    def __init__(self):
        self.llm_service = LLMService()
        self.prompt_templates = PROMPT_TEMPLATES.copy()

    def _build_context(
        self,
        solicitation: SamSolicitation,
        extracted_content: Optional[str] = None,
    ) -> Dict[str, str]:
        """
        Build context dict for prompt formatting.

        Args:
            solicitation: SamSolicitation instance
            extracted_content: Optional extracted content from attachments

        Returns:
            Context dict for prompt formatting
        """
        return {
            "title": solicitation.title or "Untitled",
            "solicitation_number": solicitation.solicitation_number or "N/A",
            "notice_type": solicitation.notice_type or "Unknown",
            "naics_code": solicitation.naics_code or "N/A",
            "psc_code": solicitation.psc_code or "N/A",
            "set_aside": solicitation.set_aside_code or "None",
            "response_deadline": (
                solicitation.response_deadline.strftime("%Y-%m-%d %H:%M UTC")
                if solicitation.response_deadline else "Not specified"
            ),
            "agency": "See details",  # Could be expanded with sub_agency info
            "description": solicitation.description or "No description provided",
            "attachment_content": (
                f"\nATTACHMENT CONTENT:\n{extracted_content}"
                if extracted_content else ""
            ),
        }

    def _parse_llm_response(
        self,
        response: str,
    ) -> Dict[str, Any]:
        """
        Parse LLM response, handling JSON extraction.

        Args:
            response: Raw LLM response

        Returns:
            Parsed JSON dict or empty dict on failure
        """
        try:
            # Try direct JSON parse
            return json.loads(response)
        except json.JSONDecodeError:
            pass

        # Try to extract JSON from markdown code blocks
        import re
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", response)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Try to find JSON object in response
        json_match = re.search(r"\{[\s\S]*\}", response)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass

        logger.warning("Failed to parse LLM response as JSON")
        return {"raw_response": response}

    async def _get_extracted_content(
        self,
        session: AsyncSession,
        solicitation_id: UUID,
        max_length: int = 50000,
    ) -> Optional[str]:
        """
        Get extracted markdown content from solicitation attachments.

        Args:
            session: Database session
            solicitation_id: Solicitation UUID
            max_length: Maximum content length to return

        Returns:
            Combined extracted content or None
        """
        from sqlalchemy import select
        from ..database.models import SamAttachment

        # Get downloaded attachments with assets
        result = await session.execute(
            select(SamAttachment)
            .where(SamAttachment.solicitation_id == solicitation_id)
            .where(SamAttachment.download_status == "downloaded")
            .where(SamAttachment.asset_id.isnot(None))
        )
        attachments = list(result.scalars().all())

        if not attachments:
            return None

        content_parts = []
        total_length = 0

        for attachment in attachments:
            # Get extraction result for asset
            extraction_result = await session.execute(
                select(ExtractionResult)
                .where(ExtractionResult.asset_id == attachment.asset_id)
                .where(ExtractionResult.status == "completed")
                .order_by(ExtractionResult.created_at.desc())
                .limit(1)
            )
            extraction = extraction_result.scalar_one_or_none()

            if not extraction or not extraction.extracted_object_key:
                continue

            # Fetch extracted content from storage
            try:
                from .minio_service import get_minio_service
                minio = get_minio_service()

                content = await minio.download_text(
                    bucket=extraction.extracted_bucket,
                    object_key=extraction.extracted_object_key,
                )

                if content:
                    header = f"\n--- {attachment.filename} ---\n"
                    if total_length + len(header) + len(content) > max_length:
                        # Truncate to fit
                        remaining = max_length - total_length - len(header)
                        if remaining > 100:
                            content_parts.append(header + content[:remaining] + "...")
                        break
                    else:
                        content_parts.append(header + content)
                        total_length += len(header) + len(content)

            except Exception as e:
                logger.warning(f"Failed to fetch extracted content: {e}")
                continue

        return "\n".join(content_parts) if content_parts else None

    async def summarize_solicitation(
        self,
        session: AsyncSession,
        solicitation_id: UUID,
        organization_id: UUID,
        summary_type: str = "executive",
        model: Optional[str] = None,
        include_attachments: bool = True,
        create_experiment: bool = True,
    ) -> Optional[SamSolicitationSummary]:
        """
        Generate a summary for a solicitation.

        Args:
            session: Database session
            solicitation_id: Solicitation UUID
            organization_id: Organization UUID
            summary_type: Type of summary (executive, technical, compliance, full)
            model: LLM model to use (None = default)
            include_attachments: Whether to include extracted attachment content
            create_experiment: Whether to create AssetMetadata experiment record

        Returns:
            Created SamSolicitationSummary or None on failure
        """
        # Get solicitation
        solicitation = await sam_service.get_solicitation(
            session, solicitation_id, include_attachments=True
        )
        if not solicitation:
            logger.error(f"Solicitation not found: {solicitation_id}")
            return None

        # Get prompt template
        prompt_template = self.prompt_templates.get(summary_type)
        if not prompt_template:
            logger.error(f"Unknown summary type: {summary_type}")
            return None

        # Get extracted content if requested
        extracted_content = None
        if include_attachments:
            extracted_content = await self._get_extracted_content(
                session, solicitation_id
            )

        # Build context and format prompt
        context = self._build_context(solicitation, extracted_content)
        prompt = prompt_template.format(**context)

        # Get model from config or use default
        if not model:
            model = getattr(settings, "openai_model", "gpt-4o-mini")

        # Call LLM
        try:
            if not self.llm_service._client:
                logger.error("LLM client not initialized")
                return None

            response = self.llm_service._client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert federal contracting analyst. Provide accurate, professional analysis.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=4000,
            )

            response_text = response.choices[0].message.content
            token_count = response.usage.total_tokens if response.usage else None

        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return None

        # Parse response
        parsed = self._parse_llm_response(response_text)

        # Extract summary text
        summary_text = parsed.get("summary") or parsed.get("executive_summary") or response_text

        # Extract structured data
        key_requirements = parsed.get("key_requirements")
        compliance_checklist = parsed.get("compliance_checklist") or parsed.get("checklist")
        confidence_score = parsed.get("confidence_score")

        # Create AssetMetadata experiment record if requested
        asset_metadata_id = None
        if create_experiment:
            # Find primary asset (first downloaded attachment)
            primary_asset_id = None
            for att in solicitation.attachments:
                if att.asset_id:
                    primary_asset_id = att.asset_id
                    break

            if primary_asset_id:
                asset_metadata = AssetMetadata(
                    asset_id=primary_asset_id,
                    metadata_type=f"sam_summary.{summary_type}.v1",
                    schema_version="1.0",
                    is_canonical=False,
                    status="active",
                    metadata_content={
                        "solicitation_id": str(solicitation_id),
                        "summary_type": summary_type,
                        "model": model,
                        "parsed_response": parsed,
                    },
                )
                session.add(asset_metadata)
                await session.flush()
                asset_metadata_id = asset_metadata.id

        # Create summary record
        summary = await sam_service.create_summary(
            session=session,
            solicitation_id=solicitation_id,
            model=model,
            summary=summary_text,
            summary_type=summary_type,
            prompt_template=prompt_template[:500],  # Store truncated template
            prompt_version="v1",
            key_requirements=key_requirements,
            compliance_checklist=compliance_checklist,
            confidence_score=confidence_score,
            token_count=token_count,
            asset_metadata_id=asset_metadata_id,
            is_canonical=False,
        )

        logger.info(f"Created {summary_type} summary {summary.id} for solicitation {solicitation_id}")

        return summary

    async def summarize_with_custom_prompt(
        self,
        session: AsyncSession,
        solicitation_id: UUID,
        organization_id: UUID,
        prompt_template: str,
        summary_type: str = "custom",
        model: Optional[str] = None,
        include_attachments: bool = True,
    ) -> Optional[SamSolicitationSummary]:
        """
        Generate a summary using a custom prompt template.

        Args:
            session: Database session
            solicitation_id: Solicitation UUID
            organization_id: Organization UUID
            prompt_template: Custom prompt template with {placeholders}
            summary_type: Type label for the summary
            model: LLM model to use
            include_attachments: Whether to include extracted content

        Returns:
            Created SamSolicitationSummary or None on failure
        """
        # Temporarily add custom template
        original_template = self.prompt_templates.get(summary_type)
        self.prompt_templates[summary_type] = prompt_template

        try:
            result = await self.summarize_solicitation(
                session=session,
                solicitation_id=solicitation_id,
                organization_id=organization_id,
                summary_type=summary_type,
                model=model,
                include_attachments=include_attachments,
            )
            return result
        finally:
            # Restore original template
            if original_template:
                self.prompt_templates[summary_type] = original_template
            else:
                del self.prompt_templates[summary_type]

    async def generate_change_summary(
        self,
        session: AsyncSession,
        notice_id: UUID,
        organization_id: UUID,
        model: Optional[str] = None,
    ) -> Optional[str]:
        """
        Generate a summary of changes between notice versions.

        Args:
            session: Database session
            notice_id: SamNotice UUID (the newer notice)
            organization_id: Organization UUID
            model: LLM model to use

        Returns:
            Generated change summary or None
        """
        from ..database.models import SamNotice

        # Get the notice
        notice = await sam_service.get_notice(session, notice_id)
        if not notice:
            return None

        if notice.version_number <= 1:
            return "Original posting - no previous version to compare."

        # Get previous notice
        from sqlalchemy import select
        result = await session.execute(
            select(SamNotice)
            .where(SamNotice.solicitation_id == notice.solicitation_id)
            .where(SamNotice.version_number == notice.version_number - 1)
        )
        previous = result.scalar_one_or_none()

        if not previous:
            return "Previous version not found."

        # Build comparison prompt
        prompt = f"""Compare these two versions of a federal solicitation and summarize the key changes.

PREVIOUS VERSION (v{previous.version_number}):
Title: {previous.title or 'N/A'}
Description: {(previous.description or 'N/A')[:2000]}
Response Deadline: {previous.response_deadline or 'N/A'}

CURRENT VERSION (v{notice.version_number}):
Title: {notice.title or 'N/A'}
Description: {(notice.description or 'N/A')[:2000]}
Response Deadline: {notice.response_deadline or 'N/A'}

Provide a concise bullet-point summary of the key changes. Focus on:
- Changes to requirements or scope
- Changes to deadlines
- Changes to eligibility
- Any other significant modifications

Keep the summary brief and actionable."""

        # Get model
        if not model:
            model = getattr(settings, "openai_model", "gpt-4o-mini")

        try:
            if not self.llm_service._client:
                return None

            response = self.llm_service._client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a federal contracting analyst."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=1000,
            )

            summary = response.choices[0].message.content

            # Update notice with changes summary
            await sam_service.update_notice_changes_summary(
                session, notice_id, summary
            )

            return summary

        except Exception as e:
            logger.error(f"Failed to generate change summary: {e}")
            return None

    async def batch_summarize(
        self,
        session: AsyncSession,
        search_id: UUID,
        organization_id: UUID,
        summary_type: str = "executive",
        model: Optional[str] = None,
        limit: int = 10,
    ) -> Dict[str, Any]:
        """
        Generate summaries for multiple solicitations in a search.

        Args:
            session: Database session
            search_id: SamSearch UUID
            organization_id: Organization UUID
            summary_type: Type of summary to generate
            model: LLM model to use
            limit: Maximum number of solicitations to summarize

        Returns:
            Batch results summary
        """
        # Get solicitations without canonical summaries of this type
        solicitations, total = await sam_service.list_solicitations(
            session, organization_id, search_id=search_id, limit=limit
        )

        results = {
            "total_candidates": total,
            "processed": 0,
            "success": 0,
            "failed": 0,
            "errors": [],
        }

        for sol in solicitations:
            # Check if canonical summary exists
            existing = await sam_service.get_canonical_summary(
                session, sol.id, summary_type
            )
            if existing:
                continue

            try:
                summary = await self.summarize_solicitation(
                    session=session,
                    solicitation_id=sol.id,
                    organization_id=organization_id,
                    summary_type=summary_type,
                    model=model,
                )

                if summary:
                    results["success"] += 1
                else:
                    results["failed"] += 1

            except Exception as e:
                results["failed"] += 1
                results["errors"].append({
                    "solicitation_id": str(sol.id),
                    "error": str(e),
                })

            results["processed"] += 1

        return results


# Singleton instance
sam_summarization_service = SamSummarizationService()
