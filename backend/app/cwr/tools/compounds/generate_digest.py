# backend/app/functions/compound/generate_digest.py
"""
Generate Digest function - Generate a formatted digest/report.

Creates formatted reports from structured data with optional AI enhancement.
"""

from typing import Any, Dict, List, Optional
from datetime import datetime
import logging

from ..base import (
    BaseFunction,
    FunctionMeta,
    FunctionCategory,
    FunctionResult,
    ParameterDoc,
    OutputFieldDoc,
    OutputSchema,
)
from ..context import FunctionContext

logger = logging.getLogger("curatore.functions.compound.generate_digest")


class GenerateDigestFunction(BaseFunction):
    """
    Generate a formatted digest or report from data.

    Creates structured reports with optional AI-powered narrative.

    Example:
        result = await fn.generate_digest(ctx,
            title="SAM.gov Daily Digest",
            items=solicitation_list,
            template="sam_digest",
        )
    """

    meta = FunctionMeta(
        name="generate_digest",
        category=FunctionCategory.COMPOUND,
        description="Generate a formatted digest or report from data",
        parameters=[
            ParameterDoc(
                name="title",
                type="str",
                description="Digest title",
                required=True,
            ),
            ParameterDoc(
                name="items",
                type="list[dict]",
                description="Items to include in the digest",
                required=True,
            ),
            ParameterDoc(
                name="template",
                type="str",
                description="Template to use",
                required=False,
                default="default",
                enum_values=["default", "sam_digest", "asset_report", "executive_summary"],
            ),
            ParameterDoc(
                name="include_ai_summary",
                type="bool",
                description="Include AI-generated executive summary",
                required=False,
                default=True,
            ),
            ParameterDoc(
                name="format",
                type="str",
                description="Output format",
                required=False,
                default="markdown",
                enum_values=["markdown", "html", "text"],
            ),
        ],
        returns="str: Formatted digest content",
        output_schema=OutputSchema(
            type="str",
            description="Formatted digest content in markdown, HTML, or plain text",
            example="# Daily Opportunities\n\n**Total Opportunities: 5**\n\n...",
        ),
        tags=["compound", "report", "digest"],
        requires_llm=False,  # LLM is optional
        side_effects=False,
        is_primitive=False,
        payload_profile="full",
        examples=[
            {
                "description": "SAM digest",
                "params": {
                    "title": "Daily Opportunities",
                    "items": [{"title": "...", "deadline": "..."}],
                    "template": "sam_digest",
                },
            },
        ],
    )

    async def execute(self, ctx: FunctionContext, **params) -> FunctionResult:
        """Generate digest."""
        title = params["title"]
        items = params["items"]
        template = params.get("template", "default")
        include_ai_summary = params.get("include_ai_summary", True)
        output_format = params.get("format", "markdown")

        if not items:
            return FunctionResult.success_result(
                data=f"# {title}\n\nNo items to report.",
                message="Generated empty digest",
            )

        try:
            # Generate digest based on template
            if template == "sam_digest":
                digest = self._generate_sam_digest(title, items)
            elif template == "asset_report":
                digest = self._generate_asset_report(title, items)
            elif template == "executive_summary":
                digest = self._generate_executive_summary(title, items)
            else:
                digest = self._generate_default_digest(title, items)

            # Add AI summary if requested and available
            if include_ai_summary and ctx.llm_service.is_available:
                ai_summary = await self._generate_ai_summary(ctx, title, items)
                if ai_summary:
                    digest = self._insert_ai_summary(digest, ai_summary)

            # Convert format if needed
            if output_format == "html":
                try:
                    import markdown
                    digest = markdown.markdown(digest)
                except ImportError:
                    pass  # Keep markdown
            elif output_format == "text":
                # Strip markdown formatting
                import re
                digest = re.sub(r'#+ ', '', digest)
                digest = re.sub(r'\*\*([^*]+)\*\*', r'\1', digest)
                digest = re.sub(r'\*([^*]+)\*', r'\1', digest)

            return FunctionResult.success_result(
                data=digest,
                message=f"Generated {template} digest with {len(items)} items",
                metadata={
                    "template": template,
                    "format": output_format,
                    "items_count": len(items),
                    "has_ai_summary": include_ai_summary and ctx.llm_service.is_available,
                },
                items_processed=len(items),
            )

        except Exception as e:
            logger.exception(f"Digest generation failed: {e}")
            return FunctionResult.failed_result(
                error=str(e),
                message="Digest generation failed",
            )

    def _generate_sam_digest(self, title: str, items: List[Dict]) -> str:
        """Generate SAM.gov digest."""
        lines = [
            f"# {title}",
            f"*Generated: {datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')}*",
            "",
            f"**Total Opportunities: {len(items)}**",
            "",
            "---",
            "",
            "## Opportunities",
            "",
        ]

        for i, item in enumerate(items, 1):
            deadline = item.get("response_deadline") or item.get("deadline") or "Not specified"
            lines.extend([
                f"### {i}. {item.get('title', 'Untitled')}",
                "",
                f"- **Notice ID:** {item.get('notice_id', 'N/A')}",
                f"- **Type:** {item.get('type', 'N/A')}",
                f"- **Deadline:** {deadline}",
                f"- **Set-Aside:** {item.get('set_aside_type') or 'None'}",
            ])

            if item.get("description"):
                desc = item["description"][:300] + "..." if len(item["description"]) > 300 else item["description"]
                lines.append(f"- **Description:** {desc}")

            if item.get("sam_url"):
                lines.append(f"- **Link:** [{item['notice_id']}]({item['sam_url']})")

            lines.append("")

        return "\n".join(lines)

    def _generate_asset_report(self, title: str, items: List[Dict]) -> str:
        """Generate asset report."""
        lines = [
            f"# {title}",
            f"*Generated: {datetime.utcnow().strftime('%B %d, %Y')}*",
            "",
            f"**Total Assets: {len(items)}**",
            "",
            "| Filename | Status | Source | Size |",
            "|----------|--------|--------|------|",
        ]

        for item in items:
            size = item.get("file_size", 0)
            size_str = f"{size / 1024:.1f} KB" if size else "N/A"
            lines.append(
                f"| {item.get('filename', 'Unknown')} | {item.get('status', 'N/A')} | "
                f"{item.get('source_type', 'N/A')} | {size_str} |"
            )

        return "\n".join(lines)

    def _generate_executive_summary(self, title: str, items: List[Dict]) -> str:
        """Generate executive summary format."""
        lines = [
            f"# {title}",
            "",
            "## Executive Summary",
            "",
            "*[AI Summary will be inserted here]*",
            "",
            "## Key Metrics",
            "",
            f"- Total items: {len(items)}",
            "",
            "## Details",
            "",
        ]

        for item in items:
            lines.append(f"- {item.get('title') or item.get('name', 'Item')}")

        return "\n".join(lines)

    def _generate_default_digest(self, title: str, items: List[Dict]) -> str:
        """Generate default digest format."""
        lines = [
            f"# {title}",
            f"*Generated: {datetime.utcnow().strftime('%B %d, %Y')}*",
            "",
            f"## Items ({len(items)})",
            "",
        ]

        for i, item in enumerate(items, 1):
            item_title = item.get("title") or item.get("name") or f"Item {i}"
            lines.append(f"{i}. **{item_title}**")

            for key, value in item.items():
                if key not in ["title", "name"] and value:
                    lines.append(f"   - {key}: {value}")

            lines.append("")

        return "\n".join(lines)

    async def _generate_ai_summary(self, ctx: FunctionContext, title: str, items: List[Dict]) -> Optional[str]:
        """Generate AI-powered executive summary."""
        try:
            # Build items summary for context
            items_text = "\n".join([
                f"- {item.get('title') or item.get('name', 'Item')}"
                for item in items[:20]  # Limit for context
            ])

            response = ctx.llm_service._client.chat.completions.create(
                model=ctx.llm_service._get_model(),
                messages=[
                    {
                        "role": "system",
                        "content": "You write concise executive summaries. Be direct and actionable."
                    },
                    {
                        "role": "user",
                        "content": f"Write a 2-3 sentence executive summary for this report titled '{title}' with {len(items)} items:\n\n{items_text}"
                    }
                ],
                temperature=0.5,
                max_tokens=150,
            )

            return response.choices[0].message.content.strip()

        except Exception as e:
            logger.warning(f"Failed to generate AI summary: {e}")
            return None

    def _insert_ai_summary(self, digest: str, ai_summary: str) -> str:
        """Insert AI summary into digest."""
        placeholder = "*[AI Summary will be inserted here]*"
        if placeholder in digest:
            return digest.replace(placeholder, ai_summary)

        # Insert after first heading
        lines = digest.split("\n")
        for i, line in enumerate(lines):
            if line.startswith("## ") and "Summary" not in line:
                lines.insert(i, f"\n## Executive Summary\n\n{ai_summary}\n")
                break

        return "\n".join(lines)
