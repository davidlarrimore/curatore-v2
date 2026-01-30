"""
Artifact Service for Object Storage File Tracking.

Provides CRUD operations for the Artifact model, which tracks files
stored in MinIO/S3 object storage. Replaces filesystem-based metadata
tracking with database-backed tracking.

Usage:
    from app.services.artifact_service import artifact_service

    # Create artifact
    artifact = await artifact_service.create_artifact(
        session=session,
        organization_id=org_id,
        document_id=doc_id,
        artifact_type="uploaded",
        bucket="curatore-uploads",
        object_key="org/doc/file.pdf",
        original_filename="file.pdf",
    )

    # Get artifact by document
    artifact = await artifact_service.get_artifact_by_document(
        session=session,
        document_id=doc_id,
        artifact_type="processed",
    )
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from uuid import UUID

from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import Artifact
from ..config import settings

logger = logging.getLogger("curatore.artifact_service")


class ArtifactService:
    """
    Service for managing Artifact records in the database.

    Handles CRUD operations, queries, and status management for files
    stored in object storage (MinIO/S3).
    """

    # =========================================================================
    # CREATE OPERATIONS
    # =========================================================================

    async def create_artifact(
        self,
        session: AsyncSession,
        organization_id: UUID,
        document_id: str,
        artifact_type: str,
        bucket: str,
        object_key: str,
        original_filename: str,
        content_type: Optional[str] = None,
        file_size: Optional[int] = None,
        etag: Optional[str] = None,
        file_hash: Optional[str] = None,
        status: str = "pending",
        file_metadata: Optional[Dict[str, Any]] = None,
        expires_at: Optional[datetime] = None,
    ) -> Artifact:
        """
        Create a new artifact record.

        Args:
            session: Database session
            organization_id: Organization UUID
            document_id: Document identifier
            artifact_type: Type (uploaded, processed, temp)
            bucket: Object storage bucket
            object_key: Full object key/path
            original_filename: Original filename
            content_type: MIME type
            file_size: Size in bytes
            etag: Object storage ETag
            file_hash: SHA-256 hash
            status: Initial status (default: pending)
            file_metadata: Additional metadata dict
            expires_at: Expiration timestamp

        Returns:
            Created Artifact instance
        """
        artifact = Artifact(
            organization_id=organization_id,
            document_id=document_id,
            artifact_type=artifact_type,
            bucket=bucket,
            object_key=object_key,
            original_filename=original_filename,
            content_type=content_type,
            file_size=file_size,
            etag=etag,
            file_hash=file_hash,
            status=status,
            file_metadata=file_metadata or {},
            expires_at=expires_at,
        )
        session.add(artifact)
        await session.flush()
        logger.debug(
            f"Created artifact {artifact.id} for document {document_id} "
            f"(type={artifact_type}, bucket={bucket})"
        )
        return artifact

    async def upsert_artifact(
        self,
        session: AsyncSession,
        organization_id: UUID,
        document_id: str,
        artifact_type: str,
        bucket: str,
        object_key: str,
        original_filename: str,
        content_type: Optional[str] = None,
        file_size: Optional[int] = None,
        etag: Optional[str] = None,
        file_hash: Optional[str] = None,
        status: str = "pending",
        file_metadata: Optional[Dict[str, Any]] = None,
        expires_at: Optional[datetime] = None,
    ) -> Artifact:
        """
        Create or update an artifact record.

        If an artifact with the same (bucket, object_key) exists, updates it.
        Otherwise, creates a new artifact record.

        Args:
            session: Database session
            organization_id: Organization UUID
            document_id: Document identifier
            artifact_type: Type (uploaded, processed, temp)
            bucket: Object storage bucket
            object_key: Full object key/path
            original_filename: Original filename
            content_type: MIME type
            file_size: Size in bytes
            etag: Object storage ETag
            file_hash: SHA-256 hash
            status: Status (default: pending)
            file_metadata: Additional metadata dict
            expires_at: Expiration timestamp

        Returns:
            Created or updated Artifact instance
        """
        # Check if artifact already exists
        result = await session.execute(
            select(Artifact).where(
                and_(
                    Artifact.bucket == bucket,
                    Artifact.object_key == object_key,
                    Artifact.deleted_at.is_(None),
                )
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            # Update existing artifact
            existing.organization_id = organization_id
            existing.document_id = document_id
            existing.artifact_type = artifact_type
            existing.original_filename = original_filename
            existing.content_type = content_type
            existing.file_size = file_size
            existing.etag = etag
            existing.file_hash = file_hash
            existing.status = status
            existing.file_metadata = file_metadata or {}
            existing.expires_at = expires_at
            existing.updated_at = datetime.utcnow()
            await session.flush()
            logger.debug(
                f"Updated artifact {existing.id} for document {document_id} "
                f"(bucket={bucket}, key={object_key})"
            )
            return existing
        else:
            # Create new artifact
            return await self.create_artifact(
                session=session,
                organization_id=organization_id,
                document_id=document_id,
                artifact_type=artifact_type,
                bucket=bucket,
                object_key=object_key,
                original_filename=original_filename,
                content_type=content_type,
                file_size=file_size,
                etag=etag,
                file_hash=file_hash,
                status=status,
                file_metadata=file_metadata,
                expires_at=expires_at,
            )

    # =========================================================================
    # READ OPERATIONS
    # =========================================================================

    async def get_artifact(
        self, session: AsyncSession, artifact_id: UUID
    ) -> Optional[Artifact]:
        """
        Get an artifact by ID.

        Args:
            session: Database session
            artifact_id: Artifact UUID

        Returns:
            Artifact or None if not found
        """
        result = await session.execute(
            select(Artifact).where(
                and_(
                    Artifact.id == artifact_id,
                    Artifact.deleted_at.is_(None),
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_artifact_by_document(
        self,
        session: AsyncSession,
        document_id: str,
        artifact_type: str,
        organization_id: Optional[UUID] = None,
    ) -> Optional[Artifact]:
        """
        Get an artifact by document ID and type.

        Args:
            session: Database session
            document_id: Document identifier
            artifact_type: Type (uploaded, processed, temp)
            organization_id: Optional organization filter

        Returns:
            Artifact or None if not found
        """
        conditions = [
            Artifact.document_id == document_id,
            Artifact.artifact_type == artifact_type,
            Artifact.deleted_at.is_(None),
        ]
        if organization_id:
            conditions.append(Artifact.organization_id == organization_id)

        result = await session.execute(
            select(Artifact).where(and_(*conditions))
        )
        return result.scalar_one_or_none()

    async def get_artifacts_by_document(
        self,
        session: AsyncSession,
        document_id: str,
        organization_id: Optional[UUID] = None,
    ) -> List[Artifact]:
        """
        Get all artifacts for a document.

        Args:
            session: Database session
            document_id: Document identifier
            organization_id: Optional organization filter

        Returns:
            List of artifacts
        """
        conditions = [
            Artifact.document_id == document_id,
            Artifact.deleted_at.is_(None),
        ]
        if organization_id:
            conditions.append(Artifact.organization_id == organization_id)

        result = await session.execute(
            select(Artifact).where(and_(*conditions)).order_by(Artifact.created_at)
        )
        return list(result.scalars().all())

    # NOTE: get_artifact_by_document_and_job and list_artifacts_by_job have been removed.
    # The Job system was deprecated - use Run-based tracking instead.

    async def list_artifacts_by_organization(
        self,
        session: AsyncSession,
        organization_id: UUID,
        artifact_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Artifact]:
        """
        List artifacts for an organization with optional filters.

        Args:
            session: Database session
            organization_id: Organization UUID
            artifact_type: Optional type filter
            status: Optional status filter
            limit: Maximum results
            offset: Pagination offset

        Returns:
            List of artifacts
        """
        conditions = [
            Artifact.organization_id == organization_id,
            Artifact.deleted_at.is_(None),
        ]
        if artifact_type:
            conditions.append(Artifact.artifact_type == artifact_type)
        if status:
            conditions.append(Artifact.status == status)

        result = await session.execute(
            select(Artifact)
            .where(and_(*conditions))
            .order_by(Artifact.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    # =========================================================================
    # UPDATE OPERATIONS
    # =========================================================================

    async def update_artifact_status(
        self,
        session: AsyncSession,
        artifact_id: UUID,
        status: str,
        **kwargs,
    ) -> Optional[Artifact]:
        """
        Update artifact status and optional fields.

        Args:
            session: Database session
            artifact_id: Artifact UUID
            status: New status
            **kwargs: Additional fields to update (file_size, etag, etc.)

        Returns:
            Updated artifact or None if not found
        """
        artifact = await self.get_artifact(session, artifact_id)
        if not artifact:
            return None

        artifact.status = status
        artifact.updated_at = datetime.utcnow()

        # Update optional fields
        for key, value in kwargs.items():
            if hasattr(artifact, key) and value is not None:
                setattr(artifact, key, value)

        await session.flush()
        logger.debug(f"Updated artifact {artifact_id} status to {status}")
        return artifact

    async def update_artifact_file_metadata(
        self,
        session: AsyncSession,
        artifact_id: UUID,
        file_metadata: Dict[str, Any],
        merge: bool = True,
    ) -> Optional[Artifact]:
        """
        Update artifact file metadata.

        Args:
            session: Database session
            artifact_id: Artifact UUID
            file_metadata: Metadata to update
            merge: If True, merge with existing; if False, replace

        Returns:
            Updated artifact or None if not found
        """
        artifact = await self.get_artifact(session, artifact_id)
        if not artifact:
            return None

        if merge:
            artifact.file_metadata = {**artifact.file_metadata, **file_metadata}
        else:
            artifact.file_metadata = file_metadata

        artifact.updated_at = datetime.utcnow()
        await session.flush()
        return artifact

    # =========================================================================
    # DELETE OPERATIONS
    # =========================================================================

    async def soft_delete_artifact(
        self, session: AsyncSession, artifact_id: UUID
    ) -> bool:
        """
        Soft delete an artifact (set deleted_at timestamp).

        Args:
            session: Database session
            artifact_id: Artifact UUID

        Returns:
            True if deleted, False if not found
        """
        artifact = await self.get_artifact(session, artifact_id)
        if not artifact:
            return False

        artifact.deleted_at = datetime.utcnow()
        artifact.status = "deleted"
        await session.flush()
        logger.debug(f"Soft deleted artifact {artifact_id}")
        return True

    async def hard_delete_artifact(
        self, session: AsyncSession, artifact_id: UUID
    ) -> bool:
        """
        Permanently delete an artifact record.

        Note: This does NOT delete the object from storage.
        Use this after confirming the object has been deleted.

        Args:
            session: Database session
            artifact_id: Artifact UUID

        Returns:
            True if deleted, False if not found
        """
        artifact = await session.get(Artifact, artifact_id)
        if not artifact:
            return False

        await session.delete(artifact)
        await session.flush()
        logger.debug(f"Hard deleted artifact {artifact_id}")
        return True

    # =========================================================================
    # UTILITY METHODS
    # =========================================================================

    async def get_expired_artifacts(
        self, session: AsyncSession, limit: int = 1000
    ) -> List[Artifact]:
        """
        Get artifacts past their expiration date.

        Args:
            session: Database session
            limit: Maximum results

        Returns:
            List of expired artifacts
        """
        now = datetime.utcnow()
        result = await session.execute(
            select(Artifact)
            .where(
                and_(
                    Artifact.expires_at.isnot(None),
                    Artifact.expires_at < now,
                    Artifact.deleted_at.is_(None),
                )
            )
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_artifacts(
        self,
        session: AsyncSession,
        organization_id: UUID,
        artifact_type: Optional[str] = None,
        status: Optional[str] = None,
    ) -> int:
        """
        Count artifacts matching criteria.

        Args:
            session: Database session
            organization_id: Organization UUID
            artifact_type: Optional type filter
            status: Optional status filter

        Returns:
            Count of matching artifacts
        """
        from sqlalchemy import func

        conditions = [
            Artifact.organization_id == organization_id,
            Artifact.deleted_at.is_(None),
        ]
        if artifact_type:
            conditions.append(Artifact.artifact_type == artifact_type)
        if status:
            conditions.append(Artifact.status == status)

        result = await session.execute(
            select(func.count(Artifact.id)).where(and_(*conditions))
        )
        return result.scalar_one()

    async def get_storage_usage(
        self, session: AsyncSession, organization_id: UUID
    ) -> Dict[str, int]:
        """
        Get storage usage statistics for an organization.

        Args:
            session: Database session
            organization_id: Organization UUID

        Returns:
            Dict with usage by artifact type (bytes)
        """
        from sqlalchemy import func

        result = await session.execute(
            select(
                Artifact.artifact_type,
                func.sum(Artifact.file_size).label("total_size"),
                func.count(Artifact.id).label("count"),
            )
            .where(
                and_(
                    Artifact.organization_id == organization_id,
                    Artifact.deleted_at.is_(None),
                    Artifact.file_size.isnot(None),
                )
            )
            .group_by(Artifact.artifact_type)
        )

        usage = {}
        for row in result:
            usage[row.artifact_type] = {
                "total_bytes": row.total_size or 0,
                "count": row.count,
            }
        return usage

    async def search_by_filename(
        self,
        session: AsyncSession,
        organization_id: UUID,
        filename: str,
        artifact_type: Optional[str] = None,
        limit: int = 20
    ) -> List[Artifact]:
        """
        Search for artifacts by filename within an organization.

        Provides a way to find documents by their original filename without
        using the filename as a document_id. This is the recommended way to
        look up documents when you only have the filename.

        Args:
            session: Database session
            organization_id: Organization UUID for tenant isolation
            filename: Filename to search for (case-insensitive partial match)
            artifact_type: Optional artifact type filter ('uploaded', 'processed', 'temp')
            limit: Maximum number of results to return (default: 20)

        Returns:
            List[Artifact]: List of matching artifacts, ordered by creation date (newest first)

        Example:
            # Search for all PDFs uploaded by an organization
            artifacts = await artifact_service.search_by_filename(
                session=session,
                organization_id=org_id,
                filename="report.pdf",
                artifact_type="uploaded"
            )

            for artifact in artifacts:
                print(f"Found: {artifact.document_id} - {artifact.original_filename}")

        Security:
            - Always scoped to a single organization (tenant isolation)
            - Returns only artifacts the organization owns
            - No cross-tenant data leakage

        Performance:
            - Uses ILIKE for case-insensitive search (PostgreSQL)
            - Limited to 20 results by default to prevent large result sets
            - Consider adding database index on original_filename for better performance
        """
        query = (
            select(Artifact)
            .where(Artifact.organization_id == organization_id)
            .where(Artifact.original_filename.ilike(f"%{filename}%"))
            .where(Artifact.status == "active")  # Exclude deleted artifacts
        )

        # Filter by artifact type if specified
        if artifact_type:
            query = query.where(Artifact.artifact_type == artifact_type)

        # Order by creation date (newest first) and limit results
        query = query.order_by(Artifact.created_at.desc()).limit(limit)

        result = await session.execute(query)
        artifacts = result.scalars().all()

        logger.debug(
            f"Filename search for '{filename}' in org {organization_id}: "
            f"found {len(artifacts)} results"
        )

        return list(artifacts)


# Global service instance
artifact_service = ArtifactService()
