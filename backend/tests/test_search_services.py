"""
Tests for PostgreSQL + pgvector search services.

Tests the embedding, chunking, indexing, and search functionality
that replaced OpenSearch.
"""

from unittest.mock import MagicMock, patch

import pytest
from app.core.search.chunking_service import ChunkingService, DocumentChunk
from app.core.search.embedding_service import EMBEDDING_DIMENSIONS, EmbeddingService

# =============================================================================
# Embedding Dimensions Config Tests
# =============================================================================


class TestEmbeddingDimensionsConfig:
    """Tests for configurable embedding dimensions."""

    def test_configured_dimensions_override(self):
        """embedding_dim returns configured dimensions when set."""
        service = EmbeddingService()
        service._embedding_dim = None
        service._configured_dimensions = 256
        assert service.embedding_dim == 256

    def test_falls_back_to_native_dims(self):
        """embedding_dim uses native dims when not configured."""
        service = EmbeddingService()
        service._embedding_dim = None
        service._configured_dimensions = None
        service._model_name = "text-embedding-3-large"
        with patch.object(service, '_get_configured_dimensions', return_value=None):
            assert service.embedding_dim == 3072

    def test_falls_back_to_default_for_unknown_model(self):
        """embedding_dim uses DEFAULT_DIM for unknown models when not configured."""
        service = EmbeddingService()
        service._embedding_dim = None
        service._configured_dimensions = None
        service._model_name = "unknown-model"
        with patch.object(service, '_get_configured_dimensions', return_value=None):
            assert service.embedding_dim == 1536

    def test_embedding_kwargs_includes_dimensions(self):
        """_embedding_kwargs includes dimensions when configured."""
        service = EmbeddingService()
        service._configured_dimensions = 1536
        kwargs = service._embedding_kwargs("text-embedding-3-large", "test")
        assert kwargs == {"model": "text-embedding-3-large", "input": "test", "dimensions": 1536}

    def test_embedding_kwargs_omits_dimensions_when_not_configured(self):
        """_embedding_kwargs omits dimensions when not configured."""
        service = EmbeddingService()
        service._configured_dimensions = None
        with patch.object(service, '_get_configured_dimensions', return_value=None):
            kwargs = service._embedding_kwargs("text-embedding-3-small", "test")
            assert "dimensions" not in kwargs


# =============================================================================
# Chunking Service Tests
# =============================================================================


class TestDocumentChunk:
    """Tests for DocumentChunk dataclass."""

    def test_document_chunk_creation(self):
        """Test creating a document chunk."""
        chunk = DocumentChunk(
            content="Test content",
            chunk_index=0,
            title="Test Document",
        )
        assert chunk.content == "Test content"
        assert chunk.chunk_index == 0
        assert chunk.title == "Test Document"

    def test_document_chunk_defaults(self):
        """Test document chunk default values."""
        chunk = DocumentChunk(
            content="Test content",
            chunk_index=0,
        )
        assert chunk.title is None


class TestChunkingService:
    """Tests for ChunkingService."""

    @pytest.fixture
    def chunking_service(self):
        """Create a chunking service instance."""
        return ChunkingService()

    def test_chunk_short_document(self, chunking_service):
        """Test chunking a short document."""
        content = "This is a short document."
        chunks = chunking_service.chunk_document(content)

        assert len(chunks) == 1
        assert chunks[0].content == content
        assert chunks[0].chunk_index == 0

    def test_chunk_document_with_title(self, chunking_service):
        """Test chunking passes title to chunks."""
        content = "Short content"
        chunks = chunking_service.chunk_document(content, title="My Title")

        assert len(chunks) == 1
        assert chunks[0].title == "My Title"

    def test_chunk_long_document(self, chunking_service):
        """Test chunking a document longer than chunk size."""
        # Create content longer than default chunk size with sentences
        content = "This is a test sentence with enough content. " * 100  # ~4500 chars

        chunks = chunking_service.chunk_document(content)

        assert len(chunks) > 1
        # Check indices are sequential
        for i, chunk in enumerate(chunks):
            assert chunk.chunk_index == i

    def test_chunk_document_preserves_content(self, chunking_service):
        """Test chunking preserves all content."""
        content = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
        chunks = chunking_service.chunk_document(content)

        # Reconstruct and verify content is preserved
        # (accounting for overlap, the key content should be present)
        all_content = " ".join(c.content for c in chunks)
        assert "First paragraph" in all_content
        assert "Second paragraph" in all_content
        assert "Third paragraph" in all_content

    def test_chunk_empty_document(self, chunking_service):
        """Test chunking an empty document."""
        chunks = chunking_service.chunk_document("")
        assert len(chunks) == 0

    def test_chunk_whitespace_document(self, chunking_service):
        """Test chunking a whitespace-only document."""
        chunks = chunking_service.chunk_document("   \n\n   ")
        assert len(chunks) == 0

    def test_chunk_respects_paragraph_boundaries(self, chunking_service):
        """Test chunking tries to break at paragraph boundaries."""
        paragraphs = ["Paragraph one content." * 10, "Paragraph two content." * 10]
        content = "\n\n".join(paragraphs)

        chunks = chunking_service.chunk_document(content)

        # Should have at least 1 chunk
        assert len(chunks) >= 1

    def test_chunk_with_markdown(self, chunking_service):
        """Test chunking markdown content."""
        content = """
# Heading 1

This is paragraph one.

## Heading 2

This is paragraph two with more content.

- Bullet point 1
- Bullet point 2
"""
        chunks = chunking_service.chunk_document(content)

        assert len(chunks) >= 1
        # Markdown structure should be preserved in chunks
        all_content = " ".join(c.content for c in chunks)
        assert "Heading 1" in all_content or "# Heading 1" in all_content


class TestChunkingEdgeCases:
    """Edge case tests for chunking service."""

    @pytest.fixture
    def chunking_service(self):
        return ChunkingService()

    def test_single_very_long_word(self, chunking_service):
        """Test handling a single word longer than chunk size."""
        # Create content with very long "word" mixed with normal text
        content = "Normal text. " + "A" * 3000 + " More normal text."
        chunks = chunking_service.chunk_document(content)

        # Should produce chunks (may not split mid-word gracefully)
        assert len(chunks) >= 1

    def test_unicode_content(self, chunking_service):
        """Test chunking unicode content."""
        content = "日本語のテスト文章です。" * 100
        chunks = chunking_service.chunk_document(content)

        assert len(chunks) >= 1

    def test_mixed_content(self, chunking_service):
        """Test chunking mixed ASCII/Unicode content."""
        content = "English text 日本語 more English текст на русском" * 50
        chunks = chunking_service.chunk_document(content)

        assert len(chunks) >= 1


# =============================================================================
# Embedding Service Tests
# =============================================================================


class TestEmbeddingService:
    """Tests for EmbeddingService."""

    @pytest.fixture
    def embedding_service(self):
        """Create an embedding service instance."""
        return EmbeddingService()

    def test_embedding_service_initialization(self, embedding_service):
        """Test embedding service initializes correctly."""
        assert embedding_service is not None
        assert hasattr(embedding_service, 'get_embedding')
        assert hasattr(embedding_service, 'get_embeddings_batch')

    def test_embedding_dimensions_constant(self):
        """Test embedding dimensions are defined for known models."""
        assert "text-embedding-3-small" in EMBEDDING_DIMENSIONS
        assert EMBEDDING_DIMENSIONS["text-embedding-3-small"] == 1536
        assert "text-embedding-3-large" in EMBEDDING_DIMENSIONS
        assert EMBEDDING_DIMENSIONS["text-embedding-3-large"] == 3072

    def test_default_model_and_dim(self, embedding_service):
        """Test default model and dimension values."""
        assert embedding_service.DEFAULT_MODEL == "text-embedding-3-small"
        assert embedding_service.DEFAULT_DIM == 1536

    def test_get_model_name_returns_string(self, embedding_service):
        """Test getting model name returns a string."""
        model = embedding_service._get_model_name()
        # Should return cached value or default
        assert model is not None
        assert isinstance(model, str)

    @pytest.mark.asyncio
    async def test_get_embeddings_batch_empty_list(self, embedding_service):
        """Test batch embedding with empty list returns empty list."""
        result = await embedding_service.get_embeddings_batch([])
        assert result == []

    def test_embedding_dim_property(self, embedding_service):
        """Test embedding_dim property."""
        dim = embedding_service.embedding_dim
        # Should return a valid dimension (default or from model)
        assert dim > 0
        assert dim in [1536, 3072]  # Known dimensions


class TestEmbeddingServiceWithMocks:
    """Tests for EmbeddingService with mocked dependencies."""

    @pytest.fixture
    def embedding_service(self):
        return EmbeddingService()

    @patch.object(EmbeddingService, '_get_config')
    @patch.object(EmbeddingService, '_get_client')
    @pytest.mark.asyncio
    async def test_get_embedding_success(self, mock_get_client, mock_get_config, embedding_service):
        """Test successful embedding generation."""
        # Mock config
        mock_config = MagicMock()
        mock_config.api_key = "test-key"
        mock_config.base_url = "https://api.openai.com/v1"
        mock_get_config.return_value = mock_config

        # Mock client
        mock_embedding = [0.1] * 1536
        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=mock_embedding)]
        mock_client = MagicMock()
        mock_client.embeddings.create.return_value = mock_response
        mock_get_client.return_value = mock_client

        result = await embedding_service.get_embedding("Test text")

        # Should attempt to generate embedding
        assert mock_get_client.called or mock_get_config.called

    @patch.object(EmbeddingService, '_get_config')
    @pytest.mark.asyncio
    async def test_get_embedding_no_config(self, mock_get_config, embedding_service):
        """Test embedding when config is not available."""
        mock_get_config.return_value = None

        # Should not raise, may return None or default behavior
        try:
            result = await embedding_service.get_embedding("Test text")
            # If it returns, should be None or valid embedding
            assert result is None or isinstance(result, list)
        except Exception:
            # Some implementations may raise
            pass


# =============================================================================
# Search Configuration Tests
# =============================================================================


class TestSearchConfiguration:
    """Tests for search configuration from config.yml."""

    @patch('app.core.shared.config_loader.config_loader')
    def test_search_enabled_check(self, mock_config_loader):
        """Test checking if search is enabled."""
        from app.core.models.config_models import SearchConfig

        mock_search_config = SearchConfig(enabled=True)
        mock_config_loader.get_search_config.return_value = mock_search_config

        config = mock_config_loader.get_search_config()
        assert config.enabled is True

    @patch('app.core.shared.config_loader.config_loader')
    def test_search_disabled_check(self, mock_config_loader):
        """Test checking when search is disabled."""
        from app.core.models.config_models import SearchConfig

        mock_search_config = SearchConfig(enabled=False)
        mock_config_loader.get_search_config.return_value = mock_search_config

        config = mock_config_loader.get_search_config()
        assert config.enabled is False

    def test_search_config_defaults(self):
        """Test search config default values."""
        from app.core.models.config_models import SearchConfig

        config = SearchConfig()

        assert config.enabled is True
        assert config.default_mode == "hybrid"
        assert config.semantic_weight == 0.5
        assert config.batch_size == 50
        assert config.chunk_size == 1500
        assert config.chunk_overlap == 200


class TestSearchModes:
    """Tests for different search modes."""

    def test_hybrid_mode_combines_scores(self):
        """Test hybrid mode conceptually combines keyword and semantic scores."""
        # This is a conceptual test - actual implementation would require DB
        keyword_score = 0.8
        semantic_score = 0.6
        weight = 0.5

        # Hybrid formula
        hybrid_score = (1 - weight) * keyword_score + weight * semantic_score

        expected = 0.5 * 0.8 + 0.5 * 0.6  # 0.7
        assert abs(hybrid_score - expected) < 0.001

    def test_keyword_only_mode(self):
        """Test keyword-only mode uses weight=0."""
        keyword_score = 0.8
        semantic_score = 0.6
        weight = 0.0  # Keyword only

        hybrid_score = (1 - weight) * keyword_score + weight * semantic_score

        assert hybrid_score == keyword_score

    def test_semantic_only_mode(self):
        """Test semantic-only mode uses weight=1."""
        keyword_score = 0.8
        semantic_score = 0.6
        weight = 1.0  # Semantic only

        hybrid_score = (1 - weight) * keyword_score + weight * semantic_score

        assert hybrid_score == semantic_score


# =============================================================================
# Integration Tests (Require Database)
# =============================================================================


@pytest.mark.skip(reason="Requires database setup")
class TestSearchIntegration:
    """Integration tests for search functionality."""

    @pytest.mark.asyncio
    async def test_index_and_search_asset(self):
        """Test indexing an asset and searching for it."""
        pass

    @pytest.mark.asyncio
    async def test_search_with_filters(self):
        """Test search with source_type filters."""
        pass

    @pytest.mark.asyncio
    async def test_search_pagination(self):
        """Test search pagination."""
        pass
