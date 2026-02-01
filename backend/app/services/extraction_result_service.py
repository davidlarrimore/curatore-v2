"""
Extraction Result Service for Extraction Tracking.

Provides CRUD operations for the ExtractionResult model, which tracks
document extraction attempts. Extraction is automatic platform infrastructure
in Curatore's Phase 0 architecture.

Note: This is NOT the extraction_client.py (which calls extraction services).
This service manages extraction result records in the database.

Usage:
    from app.services.extraction_result_service import extraction_result_service

    # Create extraction result
    extraction = await extraction_result_service.create_extraction_result(
        session=session,
        asset_id=asset_id,
        run_id=run_id,
        extractor_version="markitdown-1.0",
    )

    # Record successful extraction
    await extraction_result_service.record_extraction_success(
        session=session,
        extraction_id=extraction.id,
        bucket="curatore-processed",
        key="org/asset/extracted/file.md",
        extraction_time_seconds=2.5,
    )
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from uuid import UUID

from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import ExtractionResult, Asset
from ..config import settings

logger = logging.getLogger("curatore.extraction_result_service")


class ExtractionResultService:
    """
    Service for managing ExtractionResult records in the database.

    Handles CRUD operations and status tracking for document extraction
    attempts. Every asset should have at least one extraction result.
    """

    # =========================================================================
    # CREATE OPERATIONS
    # =========================================================================

    async def create_extraction_result(
        self,
        session: AsyncSession,
        asset_id: UUID,
        run_id: UUID,
        extractor_version: str,
        asset_version_id: Optional[UUID] = None,  # Phase 1: Link to specific version
    ) -> ExtractionResult:
        """
        Create a new extraction result record (Phase 1: with version tracking).

        Args:
            session: Database session
            asset_id: Asset UUID being extracted
            run_id: Run UUID performing the extraction
            extractor_version: Version string (e.g., "markitdown-1.0")
            asset_version_id: AssetVersion UUID (Phase 1, optional for backward compat)

        Returns:
            Created ExtractionResult instance
        """
        extraction = ExtractionResult(
            asset_id=asset_id,
            run_id=run_id,
            extractor_version=extractor_version,
            asset_version_id=asset_version_id,  # Phase 1
            status="pending",
        )

        session.add(extraction)
        await session.flush()  # Flush to get ID without committing - let caller control transaction
        await session.refresh(extraction)

        version_info = f", version_id: {asset_version_id}" if asset_version_id else ""
        logger.info(
            f"Created extraction result {extraction.id} "
            f"(asset: {asset_id}, run: {run_id}, extractor: {extractor_version}{version_info})"
        )

        return extraction

    # =========================================================================
    # READ OPERATIONS
    # =========================================================================

    async def get_extraction_result(
        self,
        session: AsyncSession,
        extraction_id: UUID,
    ) -> Optional[ExtractionResult]:
        """
        Get extraction result by ID.

        Args:
            session: Database session
            extraction_id: ExtractionResult UUID

        Returns:
            ExtractionResult instance or None
        """
        result = await session.execute(
            select(ExtractionResult).where(ExtractionResult.id == extraction_id)
        )
        return result.scalar_one_or_none()

    async def get_latest_extraction_for_asset(
        self,
        session: AsyncSession,
        asset_id: UUID,
    ) -> Optional[ExtractionResult]:
        """
        Get the most recent extraction result for an asset.

        Args:
            session: Database session
            asset_id: Asset UUID

        Returns:
            Latest ExtractionResult instance or None
        """
        result = await session.execute(
            select(ExtractionResult)
            .where(ExtractionResult.asset_id == asset_id)
            .order_by(ExtractionResult.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_successful_extraction_for_asset(
        self,
        session: AsyncSession,
        asset_id: UUID,
    ) -> Optional[ExtractionResult]:
        """
        Get the most recent successful extraction for an asset.

        Args:
            session: Database session
            asset_id: Asset UUID

        Returns:
            Latest successful ExtractionResult or None
        """
        result = await session.execute(
            select(ExtractionResult)
            .where(
                and_(
                    ExtractionResult.asset_id == asset_id,
                    ExtractionResult.status == "completed",
                )
            )
            .order_by(ExtractionResult.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_extractions_by_run(
        self,
        session: AsyncSession,
        run_id: UUID,
    ) -> List[ExtractionResult]:
        """
        Get all extraction results for a run.

        Args:
            session: Database session
            run_id: Run UUID

        Returns:
            List of ExtractionResult instances
        """
        result = await session.execute(
            select(ExtractionResult)
            .where(ExtractionResult.run_id == run_id)
            .order_by(ExtractionResult.created_at.asc())
        )
        return list(result.scalars().all())

    async def count_extractions_by_status(
        self,
        session: AsyncSession,
        asset_id: UUID,
    ) -> Dict[str, int]:
        """
        Count extraction results by status for an asset.

        Args:
            session: Database session
            asset_id: Asset UUID

        Returns:
            Dict mapping status to count (e.g., {"completed": 1, "failed": 2})
        """
        result = await session.execute(
            select(
                ExtractionResult.status,
                func.count(ExtractionResult.id)
            )
            .where(ExtractionResult.asset_id == asset_id)
            .group_by(ExtractionResult.status)
        )

        return {row[0]: row[1] for row in result.all()}

    # =========================================================================
    # UPDATE OPERATIONS
    # =========================================================================

    async def update_extraction_status(
        self,
        session: AsyncSession,
        extraction_id: UUID,
        status: str,
    ) -> Optional[ExtractionResult]:
        """
        Update extraction status.

        Status transitions:
        - pending → running (extraction started)
        - running → completed (extraction successful)
        - running → failed (extraction failed)

        Args:
            session: Database session
            extraction_id: ExtractionResult UUID
            status: New status (pending, running, completed, failed)

        Returns:
            Updated ExtractionResult instance or None if not found
        """
        extraction = await self.get_extraction_result(session, extraction_id)
        if not extraction:
            return None

        old_status = extraction.status
        extraction.status = status

        await session.commit()
        await session.refresh(extraction)

        logger.info(
            f"Updated extraction {extraction_id} status: {old_status} → {status}"
        )

        return extraction

    async def record_extraction_success(
        self,
        session: AsyncSession,
        extraction_id: UUID,
        bucket: str,
        key: str,
        extraction_time_seconds: Optional[float] = None,
        structure_metadata: Optional[Dict[str, Any]] = None,
        warnings: Optional[List[str]] = None,
    ) -> Optional[ExtractionResult]:
        """
        Record successful extraction with result details.

        Args:
            session: Database session
            extraction_id: ExtractionResult UUID
            bucket: Object storage bucket for extracted content
            key: Object storage key for extracted markdown
            extraction_time_seconds: Time taken to extract
            structure_metadata: Structural info (sections, pages, etc.)
            warnings: List of non-fatal warnings

        Returns:
            Updated ExtractionResult instance or None if not found
        """
        extraction = await self.get_extraction_result(session, extraction_id)
        if not extraction:
            return None

        extraction.status = "completed"
        extraction.extracted_bucket = bucket
        extraction.extracted_object_key = key
        extraction.extraction_time_seconds = extraction_time_seconds

        if structure_metadata:
            extraction.structure_metadata = structure_metadata

        if warnings:
            extraction.warnings = warnings

        await session.commit()
        await session.refresh(extraction)

        logger.info(
            f"Recorded successful extraction {extraction_id} "
            f"(bucket: {bucket}, key: {key})"
        )

        return extraction

    async def record_extraction_failure(
        self,
        session: AsyncSession,
        extraction_id: UUID,
        errors: List[str],
        extraction_time_seconds: Optional[float] = None,
    ) -> Optional[ExtractionResult]:
        """
        Record failed extraction with error details.

        Args:
            session: Database session
            extraction_id: ExtractionResult UUID
            errors: List of error messages
            extraction_time_seconds: Time taken before failure

        Returns:
            Updated ExtractionResult instance or None if not found
        """
        extraction = await self.get_extraction_result(session, extraction_id)
        if not extraction:
            return None

        extraction.status = "failed"
        extraction.errors = errors
        extraction.extraction_time_seconds = extraction_time_seconds

        await session.commit()
        await session.refresh(extraction)

        logger.warning(
            f"Recorded failed extraction {extraction_id}: {errors}"
        )

        return extraction

    async def add_extraction_warning(
        self,
        session: AsyncSession,
        extraction_id: UUID,
        warning: str,
    ) -> Optional[ExtractionResult]:
        """
        Add a warning to an extraction result.

        Args:
            session: Database session
            extraction_id: ExtractionResult UUID
            warning: Warning message

        Returns:
            Updated ExtractionResult instance or None if not found
        """
        extraction = await self.get_extraction_result(session, extraction_id)
        if not extraction:
            return None

        # Append to warnings array
        extraction.warnings = extraction.warnings + [warning]

        await session.commit()
        await session.refresh(extraction)

        return extraction


# Singleton instance
extraction_result_service = ExtractionResultService()
