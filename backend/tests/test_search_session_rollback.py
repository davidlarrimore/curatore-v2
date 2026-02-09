"""
Tests for search session rollback behavior.

Verifies that when the main search query fails (e.g., due to embedding
dimension mismatch), the session is properly rolled back so that
subsequent queries (like facet aggregations) don't hit
InFailedSQLTransactionError.

Root cause: The embedding model (amazon-titan-embed-text-v2:0) produces
1024-dim vectors, but the database stores 1536-dim vectors. In hybrid/
semantic mode, the dimension mismatch causes a PostgreSQL error. The
search() method must rollback the session before returning empty results,
otherwise search_with_facets() fails on the facet queries.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.core.search.pg_search_service import PgSearchService


# =============================================================================
# FTS Query Escaping Tests
# =============================================================================


class TestFtsQueryEscaping:
    """Tests for _escape_fts_query to verify query sanitization."""

    @pytest.fixture
    def service(self):
        return PgSearchService()

    def test_simple_word(self, service):
        """Single word gets prefix matching."""
        assert service._escape_fts_query("SWIFT") == "SWIFT:*"

    def test_multiple_words(self, service):
        """Multiple words joined with & and prefix matching."""
        assert service._escape_fts_query("hello world") == "hello:* & world:*"

    def test_special_characters_stripped(self, service):
        """Special characters are removed to prevent tsquery injection."""
        assert service._escape_fts_query("test@example.com") == "test:* & example:* & com:*"

    def test_empty_string(self, service):
        """Empty input returns empty string."""
        assert service._escape_fts_query("") == ""

    def test_only_special_chars(self, service):
        """Input with only special chars returns empty string."""
        assert service._escape_fts_query("$$$!!!") == ""

    def test_whitespace_only(self, service):
        """Whitespace-only input returns empty string."""
        assert service._escape_fts_query("   ") == ""

    def test_quotes_stripped(self, service):
        """Quotes and other tsquery-breaking chars are stripped."""
        result = service._escape_fts_query("'hello' \"world\"")
        assert "'" not in result
        assert '"' not in result
        assert "hello:*" in result
        assert "world:*" in result

    def test_parentheses_stripped(self, service):
        """Parentheses that could break tsquery are stripped."""
        result = service._escape_fts_query("test(value)")
        assert "(" not in result
        assert ")" not in result

    def test_colon_stripped(self, service):
        """Colons are stripped (prefix operator is added by the method)."""
        result = service._escape_fts_query("key:value")
        assert result == "key:* & value:*"

    def test_ampersand_stripped(self, service):
        """Ampersands that could break tsquery syntax are stripped."""
        result = service._escape_fts_query("A & B")
        assert result == "A:* & B:*"

    def test_pipe_stripped(self, service):
        """Pipe (OR operator) is stripped."""
        result = service._escape_fts_query("A | B")
        assert result == "A:* & B:*"

    def test_exclamation_stripped(self, service):
        """Exclamation (NOT operator) is stripped."""
        result = service._escape_fts_query("!important")
        assert result == "important:*"


# =============================================================================
# Session Rollback Tests
# =============================================================================


class TestSearchSessionRollback:
    """Tests that search() properly rolls back on failure.

    When the main search query fails (e.g., vector dimension mismatch),
    the session must be rolled back so subsequent queries on the same
    session still work.
    """

    @pytest.fixture
    def service(self):
        return PgSearchService()

    @pytest.fixture
    def org_id(self):
        return uuid4()

    @pytest.fixture
    def mock_session(self):
        """Mock async database session with rollback tracking."""
        session = AsyncMock()
        session.rollback = AsyncMock()
        return session

    @pytest.mark.asyncio
    async def test_search_rolls_back_on_sql_error(self, service, mock_session, org_id):
        """When a SQL query fails, search() must rollback the session."""
        # Simulate a SQL execution error (e.g., vector dimension mismatch)
        mock_session.execute = AsyncMock(
            side_effect=Exception("different vector dimensions 1536 and 1024")
        )

        result = await service.search(
            session=mock_session,
            organization_id=org_id,
            query="SWIFT",
            search_mode="keyword",
        )

        # Should return empty results (not raise)
        assert result.total == 0
        assert result.hits == []
        # Session must be rolled back
        mock_session.rollback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_search_rolls_back_on_embedding_error(self, service, mock_session, org_id):
        """When embedding generation fails, search() must rollback."""
        with patch(
            "app.core.search.pg_search_service.embedding_service"
        ) as mock_embed:
            mock_embed.get_embedding = AsyncMock(
                side_effect=ValueError("OPENAI_API_KEY not set")
            )

            result = await service.search(
                session=mock_session,
                organization_id=org_id,
                query="SWIFT",
                search_mode="hybrid",
            )

            assert result.total == 0
            assert result.hits == []
            mock_session.rollback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_search_no_rollback_on_success(self, service, mock_session, org_id):
        """On success, search() should NOT rollback."""
        # Mock successful count query
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 0

        mock_session.execute = AsyncMock(return_value=mock_count_result)

        # Mock fetchall to return empty results for the search query
        mock_search_result = MagicMock()
        mock_search_result.scalar.return_value = 0
        mock_search_result.fetchall.return_value = []

        # First call returns count, second returns search results
        mock_session.execute = AsyncMock(side_effect=[mock_count_result, mock_search_result])

        result = await service.search(
            session=mock_session,
            organization_id=org_id,
            query="SWIFT",
            search_mode="keyword",
        )

        assert result.total == 0
        # Rollback should NOT be called on success
        mock_session.rollback.assert_not_awaited()


# =============================================================================
# search_with_facets Session Integrity Tests
# =============================================================================


class TestSearchWithFacetsSessionIntegrity:
    """Tests that search_with_facets works after search() failures.

    This is the exact bug scenario: search() fails internally, and
    search_with_facets() must still be able to run facet queries.
    """

    @pytest.fixture
    def service(self):
        return PgSearchService()

    @pytest.fixture
    def org_id(self):
        return uuid4()

    @pytest.mark.asyncio
    async def test_facet_queries_succeed_after_search_failure(self, service, org_id):
        """Facet queries must work even when main search fails.

        This reproduces the original bug: search() swallowed an exception
        without rolling back, causing facet queries to fail with
        InFailedSQLTransactionError.
        """
        mock_session = AsyncMock()
        call_count = 0

        async def execute_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            sql_text = str(args[0]) if args else ""

            # First two calls are from search() -> _keyword_search_generic
            # (count query and search query). Simulate the first one failing.
            if call_count <= 2 and "to_tsquery" in sql_text and "ranked_chunks" not in sql_text and "asset_facets" not in sql_text:
                raise Exception("different vector dimensions 1536 and 1024")

            # After rollback, facet queries should succeed
            mock_result = MagicMock()
            mock_result.fetchall.return_value = []
            mock_result.scalar.return_value = 0
            return mock_result

        mock_session.execute = AsyncMock(side_effect=execute_side_effect)
        mock_session.rollback = AsyncMock()

        # This should NOT raise - facet queries should work
        result = await service.search_with_facets(
            session=mock_session,
            organization_id=org_id,
            query="SWIFT",
            search_mode="keyword",
        )

        # search() should have rolled back after the error
        mock_session.rollback.assert_awaited()
        # The overall call should succeed (not raise InFailedSQLTransactionError)
        assert result is not None

    @pytest.mark.asyncio
    async def test_facets_returned_despite_search_failure(self, service, org_id):
        """Even when search returns 0 results due to error, facets should still populate."""
        mock_session = AsyncMock()
        search_called = False

        async def execute_side_effect(*args, **kwargs):
            nonlocal search_called
            sql_text = str(args[0]) if args else ""

            # The search query (from _keyword_search_generic) fails
            if "ranked_chunks" in sql_text or (not search_called and "COUNT" in sql_text):
                search_called = True
                raise Exception("simulated query error")

            # Facet queries succeed and return data
            mock_result = MagicMock()
            if "asset_facets" in sql_text:
                # Source type facet query
                Row = type("Row", (), {"value": "upload", "count": 10})
                mock_result.fetchall.return_value = [Row()]
            elif "content_type" in sql_text:
                # Content type facet query
                Row = type("Row", (), {"value": "application/pdf", "count": 5})
                mock_result.fetchall.return_value = [Row()]
            else:
                mock_result.fetchall.return_value = []
                mock_result.scalar.return_value = 0
            return mock_result

        mock_session.execute = AsyncMock(side_effect=execute_side_effect)
        mock_session.rollback = AsyncMock()

        result = await service.search_with_facets(
            session=mock_session,
            organization_id=org_id,
            query="SWIFT",
            search_mode="keyword",
        )

        # Should have 0 hits but valid facets
        assert result.total == 0
        assert result.hits == []
        # Facets should be populated from the facet queries
        if result.facets:
            assert "source_type" in result.facets


# =============================================================================
# Embedding Dimension Mismatch Tests
# =============================================================================


class TestEmbeddingDimensionMismatch:
    """Tests for the specific embedding dimension mismatch scenario.

    The configured model (amazon-titan-embed-text-v2:0) returns 1024-dim
    vectors, but the database stores 1536-dim vectors. This causes
    pgvector to reject the query with 'different vector dimensions'.
    """

    def test_embedding_dim_reports_default_for_unknown_model(self):
        """EmbeddingService.embedding_dim falls back to DEFAULT_DIM for unknown models."""
        from app.core.search.embedding_service import EmbeddingService, EMBEDDING_DIMENSIONS

        service = EmbeddingService()
        # If the model isn't in EMBEDDING_DIMENSIONS, it falls back to DEFAULT_DIM
        service._model_name = "amazon-titan-embed-text-v2:0"
        service._embedding_dim = None  # Reset cache

        # The model isn't in the known dimensions dict
        assert "amazon-titan-embed-text-v2:0" not in EMBEDDING_DIMENSIONS
        # So it falls back to DEFAULT_DIM (1536)
        assert service.embedding_dim == 1536

    @pytest.mark.asyncio
    async def test_hybrid_search_with_wrong_dimension_embedding(self):
        """Hybrid search fails gracefully when embedding dimensions don't match DB."""
        service = PgSearchService()
        org_id = uuid4()
        mock_session = AsyncMock()

        # Simulate: embedding service returns 1024-dim vector
        fake_embedding_1024 = [0.1] * 1024

        with patch(
            "app.core.search.pg_search_service.embedding_service"
        ) as mock_embed:
            mock_embed.get_embedding = AsyncMock(return_value=fake_embedding_1024)

            # The SQL execution will fail with dimension mismatch
            mock_session.execute = AsyncMock(
                side_effect=Exception(
                    "(sqlalchemy.dialects.postgresql.asyncpg.Error) "
                    "different vector dimensions 1536 and 1024"
                )
            )
            mock_session.rollback = AsyncMock()

            result = await service.search(
                session=mock_session,
                organization_id=org_id,
                query="SWIFT",
                search_mode="hybrid",
            )

            # Should return empty results, not raise
            assert result.total == 0
            assert result.hits == []
            # Must rollback so session is reusable
            mock_session.rollback.assert_awaited_once()

    def test_embedding_string_format(self):
        """The embedding parameter is formatted as a vector string for pgvector."""
        # This is how _hybrid_search_generic formats the embedding parameter
        embedding = [0.1, 0.2, 0.3]
        param = "[" + ",".join(str(f) for f in embedding) + "]"
        assert param == "[0.1,0.2,0.3]"

    def test_dimension_mismatch_detection(self):
        """Verify the model returns different dimensions than expected."""
        from app.core.search.embedding_service import EmbeddingService

        service = EmbeddingService()
        service._model_name = "amazon-titan-embed-text-v2:0"
        service._embedding_dim = None

        # The service reports 1536 (DEFAULT_DIM fallback)
        reported_dim = service.embedding_dim

        # But amazon-titan-embed-text-v2:0 actually returns 1024
        # This mismatch is the root cause of the search failure
        actual_dim = 1024  # Known actual output dimension

        assert reported_dim != actual_dim, (
            f"Expected dimension mismatch: reported={reported_dim}, "
            f"actual={actual_dim}. If this fails, the model was added to "
            f"EMBEDDING_DIMENSIONS and the mismatch is fixed."
        )
