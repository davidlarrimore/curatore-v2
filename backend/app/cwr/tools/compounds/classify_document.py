# backend/app/functions/compound/classify_document.py
"""
Classify Document function - Classify documents using rules and LLM.

Applies rule-based classification first, then uses LLM for uncertain cases.
"""

from typing import Any, Dict, List, Optional
from uuid import UUID
import re
import logging

from sqlalchemy import select

from ..base import (
    BaseFunction,
    FunctionMeta,
    FunctionCategory,
    FunctionResult,
)
from ..context import FunctionContext

logger = logging.getLogger("curatore.functions.compound.classify_document")


# Rule-based classification patterns
CLASSIFICATION_RULES = {
    "proposal": {
        "filename_patterns": [r"(?i)proposal", r"(?i)rfp[-_]response", r"(?i)bid"],
        "content_patterns": [r"(?i)executive\s+summary", r"(?i)technical\s+approach"],
        "path_patterns": [r"(?i)/proposals?/"],
    },
    "contract": {
        "filename_patterns": [r"(?i)contract", r"(?i)agreement", r"(?i)^[A-Z]{2,5}-\d+"],
        "content_patterns": [r"(?i)terms\s+and\s+conditions", r"(?i)scope\s+of\s+work"],
        "path_patterns": [r"(?i)/contracts?/"],
    },
    "report": {
        "filename_patterns": [r"(?i)report", r"(?i)analysis", r"(?i)summary"],
        "content_patterns": [r"(?i)findings", r"(?i)recommendations", r"(?i)conclusion"],
        "path_patterns": [r"(?i)/reports?/"],
    },
    "presentation": {
        "filename_patterns": [r"(?i)\.pptx?$", r"(?i)deck", r"(?i)slides"],
        "content_patterns": [],
        "path_patterns": [r"(?i)/presentations?/"],
    },
    "spreadsheet": {
        "filename_patterns": [r"(?i)\.xlsx?$", r"(?i)data", r"(?i)budget"],
        "content_patterns": [],
        "path_patterns": [r"(?i)/data/", r"(?i)/financials?/"],
    },
    "policy": {
        "filename_patterns": [r"(?i)policy", r"(?i)procedure", r"(?i)sop"],
        "content_patterns": [r"(?i)policy\s+statement", r"(?i)effective\s+date"],
        "path_patterns": [r"(?i)/policies/", r"(?i)/procedures/"],
    },
}


class ClassifyDocumentFunction(BaseFunction):
    """
    Classify a document using rules and optionally LLM.

    First applies rule-based classification using filename, path, and content
    patterns. If confidence is low, uses LLM for more accurate classification.

    Example:
        result = await fn.classify_document(ctx,
            asset_id="uuid",
            categories=["proposal", "contract", "report", "other"],
        )
    """

    meta = FunctionMeta(
        name="classify_document",
        category=FunctionCategory.COMPOUND,
        description="Classify a document using rules and optionally LLM",
        input_schema={
            "type": "object",
            "properties": {
                "asset_id": {
                    "type": "string",
                    "description": "Asset ID to classify",
                },
                "categories": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Categories to classify into",
                    "default": None,
                },
                "use_llm": {
                    "type": "boolean",
                    "description": "Use LLM for uncertain cases",
                    "default": True,
                },
                "confidence_threshold": {
                    "type": "number",
                    "description": "Minimum confidence for rule-based classification",
                    "default": 0.7,
                },
            },
            "required": ["asset_id"],
        },
        output_schema={
            "type": "object",
            "description": "Document classification result with confidence scores",
            "properties": {
                "asset_id": {
                    "type": "string",
                    "description": "UUID of the classified asset",
                },
                "category": {
                    "type": "string",
                    "description": "Assigned category name",
                    "examples": ["contract"],
                },
                "confidence": {
                    "type": "number",
                    "description": "Confidence score (0.0-1.0)",
                    "examples": [0.85],
                },
                "all_scores": {
                    "type": "object",
                    "description": "Confidence scores for all categories",
                },
                "method": {
                    "type": "string",
                    "description": "Classification method used (rules or llm)",
                    "examples": ["rules"],
                },
            },
        },
        tags=["compound", "classification", "document"],
        requires_llm=False,  # LLM is optional
        side_effects=False,
        is_primitive=False,
        payload_profile="full",
        examples=[
            {
                "description": "Classify document",
                "params": {
                    "asset_id": "uuid",
                    "categories": ["proposal", "contract", "report"],
                },
            },
        ],
    )

    async def execute(self, ctx: FunctionContext, **params) -> FunctionResult:
        """Classify document."""
        asset_id = params["asset_id"]
        categories = params.get("categories") or list(CLASSIFICATION_RULES.keys())
        use_llm = params.get("use_llm", True)
        confidence_threshold = params.get("confidence_threshold", 0.7)

        from app.core.database.models import Asset, ExtractionResult

        try:
            # Get asset
            asset_uuid = UUID(asset_id) if isinstance(asset_id, str) else asset_id
            query = select(Asset).where(
                Asset.id == asset_uuid,
                Asset.organization_id == ctx.organization_id,
            )
            result = await ctx.session.execute(query)
            asset = result.scalar_one_or_none()

            if not asset:
                return FunctionResult.failed_result(
                    error="Asset not found",
                    message=f"Asset {asset_id} not found",
                )

            # Get source path if available
            source_path = ""
            if asset.source_metadata:
                source_path = asset.source_metadata.get("path", "") or asset.source_metadata.get("url", "")

            # Get content preview
            content_preview = ""
            extraction_query = select(ExtractionResult).where(
                ExtractionResult.asset_id == asset.id,
                ExtractionResult.status == "completed",
            ).order_by(ExtractionResult.created_at.desc()).limit(1)

            extraction_result = await ctx.session.execute(extraction_query)
            extraction = extraction_result.scalar_one_or_none()

            if extraction and extraction.extracted_bucket:
                try:
                    content = ctx.minio_service.get_object_content(
                        bucket=extraction.extracted_bucket,
                        object_key=extraction.extracted_object_key,
                    )
                    if content:
                        content_preview = content.decode("utf-8")[:2000] if isinstance(content, bytes) else content[:2000]
                except Exception as e:
                    logger.warning(f"Failed to get content: {e}")

            # Apply rule-based classification
            scores = {}
            for category in categories:
                if category not in CLASSIFICATION_RULES:
                    scores[category] = 0.0
                    continue

                rules = CLASSIFICATION_RULES[category]
                score = 0.0

                # Check filename patterns
                for pattern in rules.get("filename_patterns", []):
                    if re.search(pattern, asset.original_filename):
                        score += 0.4

                # Check path patterns
                for pattern in rules.get("path_patterns", []):
                    if re.search(pattern, source_path):
                        score += 0.3

                # Check content patterns
                for pattern in rules.get("content_patterns", []):
                    if content_preview and re.search(pattern, content_preview):
                        score += 0.3

                scores[category] = min(score, 1.0)

            # Find best category
            best_category = max(scores, key=scores.get) if scores else "other"
            best_confidence = scores.get(best_category, 0.0)

            # Use LLM if confidence is low
            llm_used = False
            if use_llm and best_confidence < confidence_threshold and ctx.llm_service.is_available:
                llm_result = await self._classify_with_llm(
                    ctx, asset.original_filename, source_path, content_preview, categories
                )
                if llm_result:
                    best_category = llm_result["category"]
                    best_confidence = llm_result["confidence"]
                    llm_used = True

            return FunctionResult.success_result(
                data={
                    "asset_id": str(asset.id),
                    "category": best_category,
                    "confidence": best_confidence,
                    "all_scores": scores,
                    "method": "llm" if llm_used else "rules",
                },
                message=f"Classified as '{best_category}' ({best_confidence:.0%})",
                items_processed=1,
            )

        except Exception as e:
            logger.exception(f"Classification failed: {e}")
            return FunctionResult.failed_result(
                error=str(e),
                message="Document classification failed",
            )

    async def _classify_with_llm(
        self,
        ctx: FunctionContext,
        filename: str,
        path: str,
        content: str,
        categories: List[str],
    ) -> Optional[Dict[str, Any]]:
        """Classify using LLM."""
        try:
            import json

            system_prompt = """You are a document classifier. Classify documents into categories based on their filename, path, and content.
Return JSON: {"category": "category_name", "confidence": 0.0-1.0, "reasoning": "brief explanation"}"""

            user_prompt = f"""Classify this document into one of: {', '.join(categories)}

Filename: {filename}
Path: {path}
Content preview: {content[:1000] if content else 'No content available'}

Return only JSON:"""

            response = ctx.llm_service._client.chat.completions.create(
                model=ctx.llm_service._get_model(),
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,
                max_tokens=200,
            )

            result_text = response.choices[0].message.content.strip()

            # Parse JSON
            if result_text.startswith("```"):
                result_text = result_text.split("```")[1]
                if result_text.startswith("json"):
                    result_text = result_text[4:]

            result = json.loads(result_text)

            # Validate category
            if result.get("category") not in categories:
                result["category"] = "other"

            return result

        except Exception as e:
            logger.warning(f"LLM classification failed: {e}")
            return None
