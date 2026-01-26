"""
Tests for security validation and organization isolation.

Tests the middleware functions that enforce organization-level access control
and prevent cross-tenant data leakage.
"""

import pytest
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.middleware import (
    validate_document_access,
    validate_document_ownership,
    check_document_exists,
)
from app.database.models import Artifact, User
from fastapi import HTTPException


@pytest.fixture
def org1_id():
    """Organization 1 UUID."""
    return uuid4()


@pytest.fixture
def org2_id():
    """Organization 2 UUID."""
    return uuid4()


@pytest.fixture
def document_id():
    """Test document ID."""
    return str(uuid4())


@pytest.fixture
def mock_session():
    """Mock async database session."""
    session = AsyncMock(spec=AsyncSession)
    return session


@pytest.fixture
def mock_artifact(org1_id, document_id):
    """Mock artifact owned by org1."""
    artifact = MagicMock(spec=Artifact)
    artifact.id = uuid4()
    artifact.organization_id = org1_id
    artifact.document_id = document_id
    artifact.original_filename = "test.pdf"
    artifact.artifact_type = "uploaded"
    return artifact


class TestValidateDocumentAccess:
    """Test validate_document_access function."""

    @pytest.mark.asyncio
    async def test_access_granted_same_org(self, mock_session, org1_id, document_id, mock_artifact):
        """Test access is granted when document belongs to organization."""
        # Mock query result
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_artifact
        mock_session.execute.return_value = mock_result

        # Should not raise exception
        result = await validate_document_access(
            document_id=document_id,
            organization_id=org1_id,
            session=mock_session
        )

        assert result == mock_artifact

    @pytest.mark.asyncio
    async def test_access_denied_different_org(self, mock_session, org1_id, org2_id, document_id, mock_artifact):
        """Test access is denied when document belongs to different organization."""
        # First query (org2) returns None
        mock_result_org2 = MagicMock()
        mock_result_org2.scalar_one_or_none.return_value = None

        # Second query (any org) returns artifact from org1
        mock_result_any = MagicMock()
        mock_result_any.scalar_one_or_none.return_value = mock_artifact

        mock_session.execute.side_effect = [mock_result_org2, mock_result_any]

        # Should raise 403 Forbidden
        with pytest.raises(HTTPException) as exc_info:
            await validate_document_access(
                document_id=document_id,
                organization_id=org2_id,
                session=mock_session
            )

        assert exc_info.value.status_code == 403
        assert "permission" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_document_not_found_require_exists(self, mock_session, org1_id, document_id):
        """Test 404 is raised when document doesn't exist and require_exists=True."""
        # Both queries return None (document doesn't exist)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        # Should raise 404 Not Found
        with pytest.raises(HTTPException) as exc_info:
            await validate_document_access(
                document_id=document_id,
                organization_id=org1_id,
                session=mock_session,
                require_exists=True
            )

        assert exc_info.value.status_code == 404
        assert "not found" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_document_not_found_no_require(self, mock_session, org1_id, document_id):
        """Test None is returned when document doesn't exist and require_exists=False."""
        # Both queries return None
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        # Should return None without raising
        result = await validate_document_access(
            document_id=document_id,
            organization_id=org1_id,
            session=mock_session,
            require_exists=False
        )

        assert result is None


class TestValidateDocumentOwnership:
    """Test validate_document_ownership convenience function."""

    @pytest.mark.asyncio
    async def test_ownership_validated_with_user(self, mock_session, org1_id, document_id, mock_artifact):
        """Test ownership validation using User object."""
        # Create mock user
        mock_user = MagicMock(spec=User)
        mock_user.organization_id = org1_id

        # Mock query result
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_artifact
        mock_session.execute.return_value = mock_result

        # Should not raise exception
        result = await validate_document_ownership(
            document_id=document_id,
            user=mock_user,
            session=mock_session
        )

        assert result == mock_artifact


class TestCheckDocumentExists:
    """Test check_document_exists function."""

    @pytest.mark.asyncio
    async def test_returns_true_when_exists(self, mock_session, org1_id, document_id, mock_artifact):
        """Test returns True when document exists."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_artifact
        mock_session.execute.return_value = mock_result

        result = await check_document_exists(
            document_id=document_id,
            organization_id=org1_id,
            session=mock_session
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_not_exists(self, mock_session, org1_id, document_id):
        """Test returns False when document doesn't exist."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        result = await check_document_exists(
            document_id=document_id,
            organization_id=org1_id,
            session=mock_session
        )

        assert result is False


class TestOrganizationIsolation:
    """Test that organization isolation is properly enforced."""

    @pytest.mark.asyncio
    async def test_cannot_access_other_org_documents(self, mock_session, org1_id, org2_id, document_id):
        """Test user from org2 cannot access org1's documents."""
        # Setup: document exists in org1
        artifact_org1 = MagicMock(spec=Artifact)
        artifact_org1.organization_id = org1_id
        artifact_org1.document_id = document_id

        # User from org2 tries to access
        mock_result_org2 = MagicMock()
        mock_result_org2.scalar_one_or_none.return_value = None  # Not found in org2

        mock_result_any = MagicMock()
        mock_result_any.scalar_one_or_none.return_value = artifact_org1  # But exists in org1

        mock_session.execute.side_effect = [mock_result_org2, mock_result_any]

        # Should raise 403
        with pytest.raises(HTTPException) as exc_info:
            await validate_document_access(
                document_id=document_id,
                organization_id=org2_id,
                session=mock_session
            )

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_can_access_own_org_documents(self, mock_session, org1_id, document_id):
        """Test user can access their own organization's documents."""
        artifact = MagicMock(spec=Artifact)
        artifact.organization_id = org1_id
        artifact.document_id = document_id

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = artifact
        mock_session.execute.return_value = mock_result

        # Should not raise
        result = await validate_document_access(
            document_id=document_id,
            organization_id=org1_id,
            session=mock_session
        )

        assert result.organization_id == org1_id


class TestEdgeCases:
    """Test edge cases and error conditions."""

    @pytest.mark.asyncio
    async def test_handles_database_errors_gracefully(self, mock_session, org1_id, document_id):
        """Test database errors are handled gracefully."""
        # Simulate database error
        mock_session.execute.side_effect = Exception("Database connection lost")

        # Should raise the exception (not swallow it)
        with pytest.raises(Exception, match="Database connection lost"):
            await validate_document_access(
                document_id=document_id,
                organization_id=org1_id,
                session=mock_session
            )

    @pytest.mark.asyncio
    async def test_handles_malformed_document_ids(self, mock_session, org1_id):
        """Test handles malformed document IDs."""
        # Note: Validation should happen before this middleware is called
        # But test defensive behavior anyway
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        # Should handle gracefully (return not found)
        with pytest.raises(HTTPException) as exc_info:
            await validate_document_access(
                document_id="invalid/path/file.pdf",
                organization_id=org1_id,
                session=mock_session,
                require_exists=True
            )

        assert exc_info.value.status_code == 404
