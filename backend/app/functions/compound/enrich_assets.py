# backend/app/functions/compound/enrich_assets.py
"""
Enrich Assets function - Auto-enrich assets with metadata.

Rules-only V1 implementation. ML-based enrichment deferred.
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
    ParameterDoc,
    OutputFieldDoc,
    OutputSchema,
)
from ..context import FunctionContext

logger = logging.getLogger("curatore.functions.compound.enrich_assets")


# Source-specific enrichment rules
SOURCE_RULES = {
    "sharepoint": {
        "path_rules": [
            {"pattern": r"(?i)/proposals?/", "metadata": {"category": "proposal", "document_type": "proposal"}},
            {"pattern": r"(?i)/contracts?/", "metadata": {"category": "contract", "document_type": "contract"}},
            {"pattern": r"(?i)/reports?/", "metadata": {"category": "report", "document_type": "report"}},
            {"pattern": r"(?i)/policies/", "metadata": {"category": "policy", "document_type": "policy"}},
            {"pattern": r"(?i)/hr/", "metadata": {"department": "hr"}},
            {"pattern": r"(?i)/finance/", "metadata": {"department": "finance"}},
            {"pattern": r"(?i)/legal/", "metadata": {"department": "legal"}},
            {"pattern": r"(?i)/marketing/", "metadata": {"department": "marketing"}},
            {"pattern": r"(?i)/engineering/", "metadata": {"department": "engineering"}},
        ],
        "filename_rules": [
            {"pattern": r"(?i)^draft[-_]", "metadata": {"status": "draft"}},
            {"pattern": r"(?i)[-_]final$", "metadata": {"status": "final"}},
            {"pattern": r"(?i)[-_]v(\d+)", "metadata": {"has_version": True}},
            {"pattern": r"(?i)^(\d{4})[-_]", "metadata": {"has_year": True}},
        ],
    },
    "web_scrape": {
        "url_rules": [
            {"pattern": r"(?i)/blog/", "metadata": {"content_type": "blog_post"}},
            {"pattern": r"(?i)/news/", "metadata": {"content_type": "news_article"}},
            {"pattern": r"(?i)/docs/", "metadata": {"content_type": "documentation"}},
            {"pattern": r"(?i)/api/", "metadata": {"content_type": "api_documentation"}},
        ],
    },
    "upload": {
        "filename_rules": [
            {"pattern": r"(?i)\.pdf$", "metadata": {"format": "pdf"}},
            {"pattern": r"(?i)\.(docx?|rtf)$", "metadata": {"format": "word"}},
            {"pattern": r"(?i)\.(xlsx?|csv)$", "metadata": {"format": "spreadsheet"}},
            {"pattern": r"(?i)\.(pptx?)$", "metadata": {"format": "presentation"}},
        ],
    },
}


class EnrichAssetsFunction(BaseFunction):
    """
    Auto-enrich assets with derived metadata.

    Rules-only V1 implementation that extracts metadata based on:
    - Source path patterns
    - Filename patterns
    - Content type

    ML-based enrichment (keywords, entities, language detection) is deferred.

    Example:
        result = await fn.enrich_assets(ctx,
            asset_ids=["uuid1", "uuid2"],
        )
    """

    meta = FunctionMeta(
        name="enrich_assets",
        category=FunctionCategory.COMPOUND,
        description="Auto-enrich assets with derived metadata using rules",
        parameters=[
            ParameterDoc(
                name="asset_ids",
                type="list[str]",
                description="Asset IDs to enrich (if empty, enrich recent unenriched)",
                required=False,
                default=None,
            ),
            ParameterDoc(
                name="limit",
                type="int",
                description="Maximum assets to enrich",
                required=False,
                default=50,
            ),
            ParameterDoc(
                name="force",
                type="bool",
                description="Re-enrich even if already enriched",
                required=False,
                default=False,
            ),
        ],
        returns="dict: Enrichment results",
        output_schema=OutputSchema(
            type="dict",
            description="Asset enrichment operation results",
            fields=[
                OutputFieldDoc(name="processed", type="int",
                              description="Number of assets processed"),
                OutputFieldDoc(name="enriched", type="int",
                              description="Number of assets that received new metadata"),
                OutputFieldDoc(name="skipped", type="int",
                              description="Number of assets skipped (already enriched)"),
            ],
        ),
        tags=["compound", "enrichment", "metadata"],
        requires_llm=False,
        examples=[
            {
                "description": "Enrich specific assets",
                "params": {
                    "asset_ids": ["uuid1", "uuid2"],
                },
            },
            {
                "description": "Enrich recent unenriched",
                "params": {
                    "limit": 100,
                },
            },
        ],
    )

    async def execute(self, ctx: FunctionContext, **params) -> FunctionResult:
        """Enrich assets."""
        asset_ids = params.get("asset_ids")
        limit = min(params.get("limit", 50), 500)
        force = params.get("force", False)

        from ...database.models import Asset, AssetMetadata

        try:
            # Build query
            query = select(Asset).where(
                Asset.organization_id == ctx.organization_id,
                Asset.status == "ready",
            )

            if asset_ids:
                uuids = [UUID(aid) if isinstance(aid, str) else aid for aid in asset_ids]
                query = query.where(Asset.id.in_(uuids))

            query = query.limit(limit)

            result = await ctx.session.execute(query)
            assets = result.scalars().all()

            if not assets:
                return FunctionResult.skipped_result(
                    message="No assets to enrich",
                )

            if ctx.dry_run:
                return FunctionResult.success_result(
                    data={"count": len(assets)},
                    message=f"Dry run: would enrich {len(assets)} assets",
                )

            # Process each asset
            processed = 0
            enriched = 0
            skipped = 0

            for asset in assets:
                try:
                    # Check if already enriched
                    if not force:
                        existing_query = select(AssetMetadata).where(
                            AssetMetadata.asset_id == asset.id,
                            AssetMetadata.metadata_type == "auto_enrich.v1",
                            AssetMetadata.status == "active",
                        )
                        existing_result = await ctx.session.execute(existing_query)
                        if existing_result.scalar_one_or_none():
                            skipped += 1
                            continue

                    # Extract metadata using rules
                    metadata = self._extract_metadata(asset)

                    if metadata:
                        # Create metadata record
                        meta_record = AssetMetadata(
                            asset_id=asset.id,
                            metadata_type="auto_enrich.v1",
                            schema_version="1.0",
                            producer_run_id=ctx.run_id,
                            is_canonical=False,
                            status="active",
                            metadata_content=metadata,
                        )
                        ctx.session.add(meta_record)
                        enriched += 1

                    processed += 1

                except Exception as e:
                    logger.warning(f"Failed to enrich {asset.id}: {e}")

            await ctx.session.flush()

            return FunctionResult.success_result(
                data={
                    "processed": processed,
                    "enriched": enriched,
                    "skipped": skipped,
                },
                message=f"Enriched {enriched} of {processed} assets ({skipped} skipped)",
                items_processed=processed,
            )

        except Exception as e:
            logger.exception(f"Enrichment failed: {e}")
            return FunctionResult.failed_result(
                error=str(e),
                message="Asset enrichment failed",
            )

    def _extract_metadata(self, asset) -> Dict[str, Any]:
        """Extract metadata using rules."""
        metadata = {
            "source_type": asset.source_type,
            "original_filename": asset.original_filename,
            "content_type": asset.content_type,
        }

        # Get source path
        source_path = ""
        source_url = ""
        if asset.source_metadata:
            source_path = asset.source_metadata.get("path", "") or ""
            source_url = asset.source_metadata.get("url", "") or ""

        # Apply source-specific rules
        rules = SOURCE_RULES.get(asset.source_type, {})

        # Path rules
        path_to_check = source_path or source_url
        for rule in rules.get("path_rules", []) + rules.get("url_rules", []):
            if re.search(rule["pattern"], path_to_check):
                metadata.update(rule["metadata"])

        # Filename rules
        for rule in rules.get("filename_rules", []):
            match = re.search(rule["pattern"], asset.original_filename)
            if match:
                metadata.update(rule["metadata"])
                # Extract captured groups if any
                if match.groups():
                    metadata["extracted_version"] = match.group(1)

        # Apply upload rules for any source
        for rule in SOURCE_RULES.get("upload", {}).get("filename_rules", []):
            if re.search(rule["pattern"], asset.original_filename):
                metadata.update(rule["metadata"])

        # ML-based enrichment stubs (deferred)
        # These would use NLP libraries when implemented
        metadata["keywords"] = self._extract_keywords(asset)
        metadata["entities"] = self._extract_entities(asset)
        metadata["language"] = self._detect_language(asset)

        return metadata

    def _extract_keywords(self, asset) -> List[str]:
        """Stub for keyword extraction. ML implementation deferred."""
        # Would use rake-nltk or similar when implemented
        return []

    def _extract_entities(self, asset) -> Dict[str, List[str]]:
        """Stub for entity extraction. ML implementation deferred."""
        # Would use spacy when implemented
        return {}

    def _detect_language(self, asset) -> str:
        """Stub for language detection. ML implementation deferred."""
        # Would use langdetect when implemented
        return "en"
