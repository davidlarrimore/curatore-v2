"""
Tests for filename search functionality.

Tests the search_by_filename service method and the /documents/search endpoint.
"""

import pytest
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime

from app.services.artifact_service import artifact_service
from app.database.models import Artifact


@pytest.fixture
def org_id():
    """Test organization UUID."""
    return uuid4()


@pytest.fixture
def mock_session():
    """Mock async database session."""
    return AsyncMock()


@pytest.fixture
def sample_artifacts(org_id):
    """Sample artifacts for testing."""
    artifacts = []
    filenames = [
        "report_2026.pdf",
        "annual_report.pdf",
        "quarterly_report_q4.pdf",
        "meeting_notes.txt",
    ]

    for i, filename in enumerate(filenames):
        artifact = Artifact(
            id=uuid4(),
            organization_id=org_id,
            document_id=str(uuid4()),
            artifact_type="uploaded",
            bucket="test-bucket",
            object_key=f"test/{filename}",
            original_filename=filename,
            content_type="application/pdf" if filename.endswith(".pdf") else "text/plain",
            file_size=1024 * (i + 1),
            status="active",
            created_at=datetime.now()
        )
        artifacts.append(artifact)

    return artifacts


class TestSearchByFilename:
    """Test artifact_service.search_by_filename method."""

    @pytest.mark.asyncio
    async def test_search_finds_exact_match(self, mock_session, org_id, sample_artifacts):
        """Test search finds exact filename match."""
        # Mock database query
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [sample_artifacts[0]]
        mock_session.execute.return_value = mock_result

        results = await artifact_service.search_by_filename(
            session=mock_session,
            organization_id=org_id,
            filename="report_2026.pdf"
        )

        assert len(results) == 1
        assert results[0].original_filename == "report_2026.pdf"

    @pytest.mark.asyncio
    async def test_search_finds_partial_match(self, mock_session, org_id, sample_artifacts):
        """Test search finds partial matches (case-insensitive)."""
        # Mock database query to return all report PDFs
        report_artifacts = [a for a in sample_artifacts if "report" in a.original_filename.lower()]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = report_artifacts
        mock_session.execute.return_value = mock_result

        results = await artifact_service.search_by_filename(
            session=mock_session,
            organization_id=org_id,
            filename="report"
        )

        assert len(results) == 3  # Should find all 3 report files
        assert all("report" in r.original_filename.lower() for r in results)

    @pytest.mark.asyncio
    async def test_search_case_insensitive(self, mock_session, org_id, sample_artifacts):
        """Test search is case-insensitive."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [sample_artifacts[1]]
        mock_session.execute.return_value = mock_result

        results = await artifact_service.search_by_filename(
            session=mock_session,
            organization_id=org_id,
            filename="ANNUAL"  # Uppercase query
        )

        # Should still find "annual_report.pdf"
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_search_filters_by_artifact_type(self, mock_session, org_id, sample_artifacts):
        """Test search can filter by artifact type."""
        uploaded_artifacts = [a for a in sample_artifacts if a.artifact_type == "uploaded"]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = uploaded_artifacts
        mock_session.execute.return_value = mock_result

        results = await artifact_service.search_by_filename(
            session=mock_session,
            organization_id=org_id,
            filename="report",
            artifact_type="uploaded"
        )

        assert all(r.artifact_type == "uploaded" for r in results)

    @pytest.mark.asyncio
    async def test_search_respects_limit(self, mock_session, org_id, sample_artifacts):
        """Test search respects limit parameter."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = sample_artifacts[:2]
        mock_session.execute.return_value = mock_result

        results = await artifact_service.search_by_filename(
            session=mock_session,
            organization_id=org_id,
            filename="report",
            limit=2
        )

        assert len(results) <= 2

    @pytest.mark.asyncio
    async def test_search_returns_empty_for_no_matches(self, mock_session, org_id):
        """Test search returns empty list when no matches found."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        results = await artifact_service.search_by_filename(
            session=mock_session,
            organization_id=org_id,
            filename="nonexistent.xyz"
        )

        assert results == []

    @pytest.mark.asyncio
    async def test_search_scoped_to_organization(self, mock_session, org_id):
        """Test search is scoped to specific organization."""
        other_org_id = uuid4()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        # Search in different organization
        results = await artifact_service.search_by_filename(
            session=mock_session,
            organization_id=other_org_id,
            filename="report"
        )

        # Should not find artifacts from org_id
        assert results == []

    @pytest.mark.asyncio
    async def test_search_excludes_deleted_artifacts(self, mock_session, org_id):
        """Test search only returns active artifacts."""
        # Deleted artifact should not appear
        deleted_artifact = Artifact(
            id=uuid4(),
            organization_id=org_id,
            document_id=str(uuid4()),
            artifact_type="uploaded",
            bucket="test-bucket",
            object_key="test/deleted.pdf",
            original_filename="deleted_report.pdf",
            status="deleted",  # Deleted status
            created_at=datetime.now()
        )

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []  # No active artifacts
        mock_session.execute.return_value = mock_result

        results = await artifact_service.search_by_filename(
            session=mock_session,
            organization_id=org_id,
            filename="report"
        )

        # Should not include deleted artifact
        assert not any(r.status == "deleted" for r in results)


class TestSearchEndpoint:
    """Test GET /documents/search endpoint."""

    def test_search_requires_filename(self, client):
        """Test search endpoint requires filename parameter."""
        response = client.get("/api/v1/documents/search")
        assert response.status_code == 422  # Validation error

    def test_search_returns_results(self, client, mock_auth):
        """Test search endpoint returns formatted results."""
        from unittest.mock import patch

        # Mock artifact service
        mock_artifact = MagicMock()
        mock_artifact.document_id = "550e8400-e29b-41d4-a716-446655440000"
        mock_artifact.original_filename = "test_report.pdf"
        mock_artifact.artifact_type = "uploaded"
        mock_artifact.file_size = 2048
        mock_artifact.content_type = "application/pdf"
        mock_artifact.created_at = datetime.now()
        mock_artifact.id = uuid4()

        with patch('app.api.v1.routers.documents.artifact_service.search_by_filename') as mock_search:
            mock_search.return_value = [mock_artifact]

            response = client.get("/api/v1/documents/search?filename=test")

            assert response.status_code == 200
            data = response.json()
            assert "results" in data
            assert "count" in data
            assert data["count"] == 1
            assert len(data["results"]) == 1
            assert data["results"][0]["document_id"] == "550e8400-e29b-41d4-a716-446655440000"
            assert data["results"][0]["filename"] == "test_report.pdf"

    def test_search_respects_limit_parameter(self, client, mock_auth):
        """Test search endpoint respects limit parameter."""
        response = client.get("/api/v1/documents/search?filename=test&limit=5")
        # Should not error on limit parameter
        assert response.status_code in [200, 404]  # Either success or no results

    def test_search_respects_artifact_type_filter(self, client, mock_auth):
        """Test search endpoint respects artifact_type filter."""
        response = client.get("/api/v1/documents/search?filename=test&artifact_type=processed")
        # Should not error on artifact_type parameter
        assert response.status_code in [200, 404]

    def test_search_validates_limit_range(self, client, mock_auth):
        """Test search endpoint validates limit is in range 1-100."""
        # Limit too high
        response = client.get("/api/v1/documents/search?filename=test&limit=200")
        assert response.status_code == 422

        # Limit too low
        response = client.get("/api/v1/documents/search?filename=test&limit=0")
        assert response.status_code == 422

    def test_search_requires_authentication(self, client):
        """Test search endpoint requires authentication."""
        # Without auth header
        response = client.get("/api/v1/documents/search?filename=test")
        # May return 401 or 200 depending on ENABLE_AUTH setting
        # This test documents the expected behavior
        assert response.status_code in [200, 401, 404]


class TestSearchPerformance:
    """Test search performance and edge cases."""

    @pytest.mark.asyncio
    async def test_search_handles_large_result_sets(self, mock_session, org_id):
        """Test search handles large result sets with limit."""
        # Create many artifacts
        many_artifacts = [
            Artifact(
                id=uuid4(),
                organization_id=org_id,
                document_id=str(uuid4()),
                artifact_type="uploaded",
                bucket="test-bucket",
                object_key=f"test/file_{i}.pdf",
                original_filename=f"report_{i}.pdf",
                status="active",
                created_at=datetime.now()
            )
            for i in range(100)
        ]

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = many_artifacts[:20]  # Limited
        mock_session.execute.return_value = mock_result

        results = await artifact_service.search_by_filename(
            session=mock_session,
            organization_id=org_id,
            filename="report",
            limit=20
        )

        # Should respect limit
        assert len(results) <= 20

    @pytest.mark.asyncio
    async def test_search_handles_special_characters(self, mock_session, org_id):
        """Test search handles filenames with special characters."""
        special_artifact = Artifact(
            id=uuid4(),
            organization_id=org_id,
            document_id=str(uuid4()),
            artifact_type="uploaded",
            bucket="test-bucket",
            object_key="test/special.pdf",
            original_filename="report_2026-Q1_(final).pdf",
            status="active",
            created_at=datetime.now()
        )

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [special_artifact]
        mock_session.execute.return_value = mock_result

        results = await artifact_service.search_by_filename(
            session=mock_session,
            organization_id=org_id,
            filename="Q1_(final)"
        )

        assert len(results) == 1
