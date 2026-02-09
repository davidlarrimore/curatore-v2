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
    from app.core.search.embedding_service import embedding_service

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
      task_types:
        embedding:
          model: text-embedding-3-small  # 1536 dimensions

Author: Curatore v2 Development Team
Version: 2.0.0
"""

import asyncio
import logging
import os
import time
from functools import lru_cache
from typing import List, Optional

logger = logging.getLogger("curatore.embedding_service")

# Rate limit handling constants
MAX_RETRIES = 5
INITIAL_BACKOFF_SECONDS = 0.5
MAX_BACKOFF_SECONDS = 10.0
BACKOFF_MULTIPLIER = 2.0

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
            from app.core.shared.config_loader import config_loader
            return config_loader.get_llm_config()
        except Exception:
            return None

    def _get_model_name(self) -> str:
        """Get the embedding model name from config or default."""
        if self._model_name:
            return self._model_name

        try:
            from app.core.shared.config_loader import config_loader
            self._model_name = config_loader.get_embedding_model()
        except Exception:
            self._model_name = self.DEFAULT_MODEL

        return self._model_name

    def _is_rate_limit_error(self, error: Exception) -> bool:
        """Check if an exception is a rate limit error."""
        error_str = str(error).lower()
        return (
            "rate limit" in error_str
            or "429" in error_str
            or "ratelimit" in error_str
            or "too many requests" in error_str
        )

    def _get_retry_after(self, error: Exception) -> float:
        """Extract retry-after time from error message if available."""
        error_str = str(error)
        # Look for patterns like "try again in 1.049s" or "retry after 2 seconds"
        import re

        match = re.search(r"try again in (\d+\.?\d*)s", error_str)
        if match:
            return float(match.group(1))
        match = re.search(r"retry.?after.?(\d+)", error_str, re.IGNORECASE)
        if match:
            return float(match.group(1))
        return INITIAL_BACKOFF_SECONDS

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

        Includes exponential backoff retry for rate limit errors.

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
            batch_embeddings = self._embed_batch_with_retry(client, model, batch)
            all_embeddings.extend(batch_embeddings)

        return all_embeddings

    def _embed_batch_with_retry(
        self, client, model: str, batch: List[str]
    ) -> List[List[float]]:
        """
        Embed a batch of texts with exponential backoff retry for rate limits.

        Args:
            client: OpenAI client
            model: Model name
            batch: List of texts to embed

        Returns:
            List of embeddings for the batch
        """
        backoff = INITIAL_BACKOFF_SECONDS

        for attempt in range(MAX_RETRIES):
            try:
                response = client.embeddings.create(model=model, input=batch)
                # Response data is in same order as input
                return [item.embedding for item in response.data]

            except Exception as e:
                if self._is_rate_limit_error(e):
                    if attempt < MAX_RETRIES - 1:
                        # Get retry time from error or use exponential backoff
                        wait_time = self._get_retry_after(e)
                        wait_time = max(wait_time, backoff)
                        wait_time = min(wait_time, MAX_BACKOFF_SECONDS)

                        logger.warning(
                            f"Rate limit hit, waiting {wait_time:.1f}s before retry "
                            f"(attempt {attempt + 1}/{MAX_RETRIES})"
                        )
                        time.sleep(wait_time)
                        backoff = min(backoff * BACKOFF_MULTIPLIER, MAX_BACKOFF_SECONDS)
                        continue
                    else:
                        logger.error(
                            f"Rate limit persists after {MAX_RETRIES} retries, "
                            f"falling back to individual requests"
                        )
                else:
                    logger.warning(f"Batch embedding failed: {e}")

                # Fall back to one-at-a-time processing
                return self._embed_individually_with_retry(client, model, batch)

        # Should not reach here, but return zeros as fallback
        return [[0.0] * self.embedding_dim for _ in batch]

    def _embed_individually_with_retry(
        self, client, model: str, texts: List[str]
    ) -> List[List[float]]:
        """
        Embed texts one at a time with rate limit handling.

        Args:
            client: OpenAI client
            model: Model name
            texts: List of texts to embed

        Returns:
            List of embeddings
        """
        results = []
        backoff = INITIAL_BACKOFF_SECONDS

        for text in texts:
            embedding = None

            for attempt in range(MAX_RETRIES):
                try:
                    response = client.embeddings.create(model=model, input=text)
                    embedding = response.data[0].embedding
                    # Reset backoff on success
                    backoff = INITIAL_BACKOFF_SECONDS
                    break

                except Exception as e:
                    if self._is_rate_limit_error(e):
                        if attempt < MAX_RETRIES - 1:
                            wait_time = self._get_retry_after(e)
                            wait_time = max(wait_time, backoff)
                            wait_time = min(wait_time, MAX_BACKOFF_SECONDS)

                            logger.debug(
                                f"Rate limit on single embed, waiting {wait_time:.1f}s"
                            )
                            time.sleep(wait_time)
                            backoff = min(
                                backoff * BACKOFF_MULTIPLIER, MAX_BACKOFF_SECONDS
                            )
                            continue
                    else:
                        logger.error(f"Single embedding failed: {e}")
                        break

            if embedding is None:
                # Use zero vector for failed embeddings
                embedding = [0.0] * self.embedding_dim

            results.append(embedding)

        return results

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

    async def get_embeddings_batch_concurrent(
        self,
        texts: List[str],
        max_concurrent: int = 10,
        batch_size: int = 50,
    ) -> List[List[float]]:
        """
        Generate embeddings for many texts using concurrent API calls.

        Splits texts into sub-batches and fires them concurrently (bounded
        by a semaphore) via run_in_executor. This achieves true concurrency
        since each call runs in its own thread. Useful for large re-index
        operations where hundreds/thousands of texts need embedding.

        Args:
            texts: List of texts to embed
            max_concurrent: Maximum number of concurrent API calls
            batch_size: Number of texts per API call (default 50)

        Returns:
            List of embeddings, one per input text, in the same order
        """
        if not texts:
            return []

        # Split into sub-batches
        batches = [texts[i:i + batch_size] for i in range(0, len(texts), batch_size)]
        results: List[Optional[List[List[float]]]] = [None] * len(batches)

        loop = asyncio.get_event_loop()
        semaphore = asyncio.Semaphore(max_concurrent)

        async def _embed_batch(idx: int, batch: List[str]):
            async with semaphore:
                try:
                    embeddings = await loop.run_in_executor(
                        None, self._generate_embeddings_batch_sync, batch
                    )
                    results[idx] = embeddings
                except Exception as e:
                    logger.warning(
                        f"Concurrent batch {idx} failed ({len(batch)} texts): {e}"
                    )
                    results[idx] = None

        # Fire all batches concurrently
        tasks = [_embed_batch(i, batch) for i, batch in enumerate(batches)]
        await asyncio.gather(*tasks)

        # Collect results; retry failed batches sequentially as fallback
        all_embeddings: List[List[float]] = []
        for idx, batch_result in enumerate(results):
            if batch_result is not None:
                all_embeddings.extend(batch_result)
            else:
                # Retry this batch sequentially
                logger.info(f"Retrying batch {idx} sequentially")
                batch = batches[idx]
                try:
                    fallback = await loop.run_in_executor(
                        None, self._generate_embeddings_batch_sync, batch
                    )
                    all_embeddings.extend(fallback)
                except Exception as e:
                    logger.error(f"Sequential retry of batch {idx} also failed: {e}")
                    # Use zero vectors for the entire failed batch
                    all_embeddings.extend(
                        [[0.0] * self.embedding_dim for _ in batch]
                    )

        return all_embeddings

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
