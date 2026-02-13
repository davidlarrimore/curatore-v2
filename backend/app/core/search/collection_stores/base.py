"""
Collection store adapter ABC and data classes.

Defines the interface that all collection vector store backends must implement.
Currently only PgVectorCollectionStore is implemented; external adapters
(Pinecone, OpenSearch, etc.) will follow this same interface.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from uuid import UUID


@dataclass
class ChunkData:
    """Chunk ready to be stored in a collection."""

    chunk_index: int
    content: str
    embedding: List[float]
    title: Optional[str] = None
    source_asset_id: Optional[UUID] = None
    source_chunk_id: Optional[UUID] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class ChunkResult:
    """Chunk returned from a collection search."""

    id: str
    content: str
    score: float
    title: Optional[str] = None
    source_asset_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    keyword_score: Optional[float] = None
    semantic_score: Optional[float] = None
    highlight: Optional[str] = None


class CollectionStoreAdapter(ABC):
    """
    Abstract base class for collection vector store backends.

    Each implementation targets a specific storage backend (local pgvector,
    Pinecone, OpenSearch, etc.) and provides a uniform interface for
    upserting chunks, searching, and managing collection content.
    """

    @abstractmethod
    async def upsert_chunks(
        self, collection_id: UUID, chunks: List[ChunkData]
    ) -> int:
        """
        Insert or update chunks in the collection.

        Uses (collection_id, source_asset_id, chunk_index) as the
        deduplication key. Returns the count of chunks written.
        """

    @abstractmethod
    async def search(
        self,
        collection_id: UUID,
        query: str,
        query_embedding: List[float],
        search_mode: str = "hybrid",
        limit: int = 20,
        semantic_weight: float = 0.5,
    ) -> List[ChunkResult]:
        """
        Hybrid search within a collection.

        Args:
            collection_id: The collection to search
            query: Raw text query (used for keyword search)
            query_embedding: Pre-computed embedding for the query
            search_mode: "keyword", "semantic", or "hybrid"
            limit: Maximum results to return
            semantic_weight: Weight for semantic scores in hybrid mode (0-1)

        Returns:
            Ranked list of ChunkResult objects
        """

    @abstractmethod
    async def delete_by_assets(
        self, collection_id: UUID, asset_ids: List[UUID]
    ) -> int:
        """Delete chunks belonging to specific assets. Returns count deleted."""

    @abstractmethod
    async def clear(self, collection_id: UUID) -> int:
        """Delete all chunks in a collection. Returns count deleted."""

    @abstractmethod
    async def count(self, collection_id: UUID) -> int:
        """Count chunks in a collection."""
