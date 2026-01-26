"""
API middleware for request validation and security.

Provides middleware functions for:
- Document ownership validation (organization isolation)
- Access control and authorization
- Request validation and sanitization

Usage:
    from app.api.v1.middleware import validate_document_access

    @router.get("/documents/{document_id}")
    async def get_document(
        document_id: str,
        user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_db_session)
    ):
        # Validate document belongs to user's organization
        await validate_document_access(document_id, user.organization_id, session)
        # Proceed with document retrieval
"""

import logging
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...database.models import Artifact, User

logger = logging.getLogger("curatore.middleware")


async def validate_document_access(
    document_id: str,
    organization_id: UUID,
    session: AsyncSession,
    require_exists: bool = True
) -> Optional[Artifact]:
    """
    Validate that a document belongs to the specified organization.

    This function enforces organization-level isolation by checking that the
    document_id is associated with at least one artifact owned by the organization.
    This prevents cross-tenant data access.

    Args:
        document_id: Document ID to validate (UUID or legacy format)
        organization_id: UUID of the organization to check against
        session: Database session for queries
        require_exists: If True, raises 404 if document not found. If False, returns None.

    Returns:
        Artifact: The first artifact found for the document (typically the uploaded artifact)
        None: If require_exists=False and no artifact found

    Raises:
        HTTPException: 404 if document not found (when require_exists=True)
        HTTPException: 403 if document exists but belongs to different organization

    Example:
        from app.dependencies import get_current_user
        from app.services.database_service import database_service

        @router.get("/documents/{document_id}")
        async def get_document(
            document_id: str = Depends(validate_document_id_param),
            user: User = Depends(get_current_user)
        ):
            async with database_service.get_session() as session:
                # Validate access
                artifact = await validate_document_access(
                    document_id,
                    user.organization_id,
                    session
                )
                # Proceed with document operations
                return {"document_id": artifact.document_id}

    Security Notes:
        - Always call this function AFTER validating document_id format
        - This function prevents cross-tenant data leakage
        - Uses database query to verify ownership (not just client claims)
        - Logs access denial attempts for security monitoring
    """
    # Query for any artifact with this document_id and organization_id
    result = await session.execute(
        select(Artifact)
        .where(Artifact.document_id == document_id)
        .where(Artifact.organization_id == organization_id)
        .limit(1)
    )
    artifact = result.scalar_one_or_none()

    if not artifact:
        # Check if document exists at all (for better error messages)
        result_any_org = await session.execute(
            select(Artifact)
            .where(Artifact.document_id == document_id)
            .limit(1)
        )
        exists_in_other_org = result_any_org.scalar_one_or_none() is not None

        if exists_in_other_org:
            # Document exists but belongs to different organization
            logger.warning(
                f"Access denied: Document {document_id} exists but not in organization {organization_id}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this document"
            )
        else:
            # Document doesn't exist at all
            if require_exists:
                logger.debug(f"Document {document_id} not found")
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Document not found"
                )
            else:
                return None

    logger.debug(
        f"Document access validated: {document_id} for organization {organization_id}"
    )
    return artifact


async def validate_document_ownership(
    document_id: str,
    user: User,
    session: AsyncSession
) -> Artifact:
    """
    Convenience wrapper around validate_document_access that uses a User object.

    Args:
        document_id: Document ID to validate
        user: Current user (must have organization_id)
        session: Database session

    Returns:
        Artifact: The artifact if validation succeeds

    Raises:
        HTTPException: 403/404 if validation fails

    Example:
        @router.delete("/documents/{document_id}")
        async def delete_document(
            document_id: str = Depends(validate_document_id_param),
            user: User = Depends(get_current_user)
        ):
            async with database_service.get_session() as session:
                await validate_document_ownership(document_id, user, session)
                # Proceed with deletion
    """
    return await validate_document_access(
        document_id,
        user.organization_id,
        session,
        require_exists=True
    )


async def check_document_exists(
    document_id: str,
    organization_id: UUID,
    session: AsyncSession
) -> bool:
    """
    Check if a document exists in the specified organization.

    Non-raising version of validate_document_access for conditional logic.

    Args:
        document_id: Document ID to check
        organization_id: Organization UUID
        session: Database session

    Returns:
        bool: True if document exists and belongs to organization, False otherwise

    Example:
        if await check_document_exists(doc_id, org_id, session):
            # Document exists, proceed
            pass
        else:
            # Document doesn't exist, create it
            pass
    """
    artifact = await validate_document_access(
        document_id,
        organization_id,
        session,
        require_exists=False
    )
    return artifact is not None
