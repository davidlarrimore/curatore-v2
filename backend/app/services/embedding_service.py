# ============================================================================
# backend/app/services/embedding_service.py
# ============================================================================
"""
Embedding Service for Curatore v2 - OpenAI API Embeddings

This module provides embedding generation using OpenAI's text-embedding API
for semantic search capabilities. Uses the model configured in llm.models.embedding.

Key Features:
    - Fast API-based embedding generation
    - Batch processing for efficient indexing
    - Uses LLM connection settings from config.yml
    - Cost-effective (~$0.02 per 1M tokens for text-embedding-3-small)

Usage:
    from app.services.embedding_service import embedding_service

    # Single embedding
    embedding = await embedding_service.get_embedding("Document text...")

    # Batch embeddings (more efficient)
    embeddings = await embedding_service.get_embeddings_batch([
        "Document 1 text...",
        "Document 2 text...",
    ])

Configuration (config.yml):
    llm:
      api_key: ${OPENAI_API_KEY}
      base_url: https://api.openai.com/v1
      models:
        embedding:
          model: text-embedding-3-small  # 1536 dimensions

Author: Curatore v2 Development Team
Version: 2.0.0
"""

import asyncio
import logging
import os
from functools import lru_cache
from typing import List, Optional

logger = logging.getLogger("curatore.embedding_service")

# Known embedding dimensions for common models
EMBEDDING_DIMENSIONS = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}


class EmbeddingService:
    """
    OpenAI API-based embedding generation.

    This service provides semantic embeddings for document chunks using
    OpenAI's embedding models. Uses the LLM connection settings from config.yml.

    Attributes:
        model_name: OpenAI model identifier (from llm.models.embedding.model)
        embedding_dim: Dimension of output embeddings (auto-detected)

    Thread Safety:
        The service uses the OpenAI sync client with asyncio executor.
    """

    DEFAULT_MODEL = "text-embedding-3-small"
    DEFAULT_DIM = 1536

    def __init__(self):
        """Initialize the embedding service."""
        self._client = None
        self._model_name = None
        self._embedding_dim = None

    def _get_config(self):
        """Get embedding configuration from config_loader."""
        try:
            from .config_loader import config_loader
            return config_loader.get_llm_config()
        except Exception:
            return None

    def _get_model_name(self) -> str:
        """Get the embedding model name from config or default."""
        if self._model_name:
            return self._model_name

        try:
            from .config_loader import config_loader
            self._model_name = config_loader.get_embedding_model()
        except Exception:
            self._model_name = self.DEFAULT_MODEL

        return self._model_name

    def _get_client(self):
        """
        Get or create the OpenAI client using LLM config.

        Returns:
            OpenAI client instance
        """
        if self._client is None:
            try:
                from openai import OpenAI

                llm_config = self._get_config()

                # Get API key from config or environment
                api_key = None
                base_url = None

                if llm_config:
                    api_key = llm_config.api_key
                    base_url = llm_config.base_url

                # Fallback to environment variables
                if not api_key:
                    api_key = os.getenv("OPENAI_API_KEY")
                if not base_url:
                    base_url = os.getenv("OPENAI_BASE_URL")

                if not api_key:
                    raise ValueError(
                        "OPENAI_API_KEY not set. Configure in config.yml or environment."
                    )

                # Create client with configured endpoint
                client_kwargs = {"api_key": api_key}
                if base_url:
                    client_kwargs["base_url"] = base_url

                self._client = OpenAI(**client_kwargs)
                logger.info(f"OpenAI client initialized for embeddings (model: {self._get_model_name()})")

            except ImportError:
                logger.error("openai package not installed. Run: pip install openai")
                raise
            except Exception as e:
                logger.error(f"Failed to initialize OpenAI client: {e}")
                raise

        return self._client

    def _generate_embedding_sync(self, text: str) -> List[float]:
        """
        Generate embedding synchronously.

        Args:
            text: Text to embed

        Returns:
            List of floats representing the embedding
        """
        client = self._get_client()
        model = self._get_model_name()

        # Truncate very long texts (OpenAI has 8191 token limit)
        # ~4 chars per token, so ~30000 chars is safe
        max_chars = 30000
        if len(text) > max_chars:
            text = text[:max_chars]

        # Handle empty text
        if not text.strip():
            text = "empty"

        response = client.embeddings.create(model=model, input=text)
        return response.data[0].embedding

    def _generate_embeddings_batch_sync(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for multiple texts synchronously.

        OpenAI supports batching up to 2048 inputs per request, but also has
        a token limit per request (~300K tokens). We use smaller batches to
        stay safely under the limit.

        Args:
            texts: List of texts to embed

        Returns:
            List of embeddings, one per input text
        """
        client = self._get_client()
        model = self._get_model_name()

        # Truncate texts more aggressively to avoid token limits
        # ~4 chars per token, 8000 tokens per text max = ~32000 chars
        # But use 8000 chars to be safe and leave room for batching
        max_chars = 8000
        cleaned_texts = []
        for t in texts:
            if len(t) > max_chars:
                t = t[:max_chars]
            if not t.strip():
                t = "empty"
            cleaned_texts.append(t)

        # Use smaller batch size to stay under token limits
        # 50 texts * 8000 chars / 4 chars/token = ~100K tokens per batch (safe)
        all_embeddings = []
        batch_size = 50

        for i in range(0, len(cleaned_texts), batch_size):
            batch = cleaned_texts[i : i + batch_size]
            try:
                response = client.embeddings.create(model=model, input=batch)
                # Response data is in same order as input
                batch_embeddings = [item.embedding for item in response.data]
                all_embeddings.extend(batch_embeddings)
            except Exception as e:
                # If batch fails, try one at a time
                logger.warning(f"Batch embedding failed, trying one at a time: {e}")
                for text in batch:
                    try:
                        response = client.embeddings.create(model=model, input=text)
                        all_embeddings.append(response.data[0].embedding)
                    except Exception as e2:
                        logger.error(f"Single embedding failed: {e2}")
                        # Return zeros for failed embeddings
                        all_embeddings.append([0.0] * self.embedding_dim)

        return all_embeddings

    async def get_embedding(self, text: str) -> List[float]:
        """
        Generate embedding for a single text.

        Args:
            text: Text to generate embedding for

        Returns:
            List of floats representing the embedding (dimensions depend on model)

        Raises:
            ValueError: If API key is not configured
            Exception: If API call fails
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._generate_embedding_sync, text)

    async def get_embeddings_batch(
        self, texts: List[str], batch_size: int = 100
    ) -> List[List[float]]:
        """
        Generate embeddings for multiple texts efficiently.

        OpenAI's API supports batching natively, making this very efficient.

        Args:
            texts: List of texts to embed
            batch_size: Ignored (OpenAI handles batching internally)

        Returns:
            List of embeddings, one per input text

        Raises:
            ValueError: If API key is not configured
            Exception: If API call fails
        """
        if not texts:
            return []

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._generate_embeddings_batch_sync, texts
        )

    @property
    def embedding_dim(self) -> int:
        """Return the dimension of the embeddings based on model."""
        if self._embedding_dim:
            return self._embedding_dim

        model = self._get_model_name()
        self._embedding_dim = EMBEDDING_DIMENSIONS.get(model, self.DEFAULT_DIM)
        return self._embedding_dim

    @property
    def model_name(self) -> str:
        """Return the model name being used."""
        return self._get_model_name()

    @property
    def is_available(self) -> bool:
        """Check if the embedding service is available."""
        try:
            llm_config = self._get_config()
            if llm_config and llm_config.api_key:
                return True
            return bool(os.getenv("OPENAI_API_KEY"))
        except Exception:
            return False


# Global service instance
embedding_service = EmbeddingService()


@lru_cache(maxsize=1)
def get_embedding_service() -> EmbeddingService:
    """
    Get the global embedding service instance.

    Returns:
        Singleton EmbeddingService instance
    """
    return embedding_service
