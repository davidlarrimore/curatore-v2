"""
Collection store adapters — pluggable backends for collection vector stores.

The store adapter pattern allows collections to target either the local
pgvector-backed ``collection_chunks`` table or an external vector store
(Pinecone, OpenSearch, etc.) via a Connection.

Usage:
    from app.core.search.collection_stores import (
        ChunkData,
        ChunkResult,
        CollectionStoreAdapter,
        PgVectorCollectionStore,
    )
"""

from .base import ChunkData, ChunkResult, CollectionStoreAdapter
from .pgvector_store import PgVectorCollectionStore

__all__ = [
    "ChunkData",
    "ChunkResult",
    "CollectionStoreAdapter",
    "PgVectorCollectionStore",
]
