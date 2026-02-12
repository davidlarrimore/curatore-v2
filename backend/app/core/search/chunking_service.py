# ============================================================================
# backend/app/services/chunking_service.py
# ============================================================================
"""
Chunking Service for Curatore v2 - Document Splitting for Search

This module splits documents into searchable chunks for hybrid search.
Proper chunking is essential for effective semantic search as embeddings
work best on coherent, reasonably-sized text segments.

Key Features:
    - Paragraph-aware splitting (preserves document structure)
    - Configurable chunk size and overlap
    - Maintains context with overlapping chunks
    - Handles various document formats gracefully
    - Returns chunk metadata for reconstruction

Chunking Strategy:
    1. Split on paragraph boundaries (double newlines)
    2. Merge small paragraphs to reach target chunk size
    3. Split large paragraphs at sentence boundaries
    4. Add overlap between consecutive chunks for context

Usage:
    from app.core.search.chunking_service import chunking_service

    chunks = chunking_service.chunk_document(
        content="Full document text...",
        title="Document Title",
    )
    for chunk in chunks:
        print(f"Chunk {chunk.chunk_index}: {len(chunk.content)} chars")

Author: Curatore v2 Development Team
Version: 2.0.0
"""

import logging
import re
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger("curatore.chunking_service")


@dataclass
class DocumentChunk:
    """
    Represents a chunk of a document for indexing.

    Attributes:
        content: The text content of this chunk
        chunk_index: Zero-based index of this chunk in the document
        title: Document title (inherited from parent)
        char_start: Character offset where this chunk starts in original
        char_end: Character offset where this chunk ends in original
    """

    content: str
    chunk_index: int
    title: Optional[str] = None
    char_start: int = 0
    char_end: int = 0


class ChunkingService:
    """
    Service for splitting documents into searchable chunks.

    Chunks are created to optimize semantic search performance while
    maintaining document coherence. The service attempts to split on
    natural boundaries (paragraphs, sentences) rather than arbitrary
    character positions.

    Configuration:
        MAX_CHUNK_SIZE: Target maximum characters per chunk (default 1500)
        MIN_CHUNK_SIZE: Minimum characters to form a chunk (default 100)
        OVERLAP_SIZE: Characters of overlap between chunks (default 200)

    The overlap ensures that content near chunk boundaries is searchable
    from multiple chunks, preventing information loss at boundaries.
    """

    # Chunk size configuration
    MAX_CHUNK_SIZE = 1500  # Target max characters per chunk
    MIN_CHUNK_SIZE = 100  # Minimum chunk size
    OVERLAP_SIZE = 200  # Overlap between consecutive chunks

    def __init__(
        self,
        max_chunk_size: int = None,
        min_chunk_size: int = None,
        overlap_size: int = None,
    ):
        """
        Initialize the chunking service with optional custom parameters.

        Args:
            max_chunk_size: Maximum characters per chunk
            min_chunk_size: Minimum characters per chunk
            overlap_size: Characters of overlap between chunks
        """
        self.max_chunk_size = max_chunk_size or self.MAX_CHUNK_SIZE
        self.min_chunk_size = min_chunk_size or self.MIN_CHUNK_SIZE
        self.overlap_size = overlap_size or self.OVERLAP_SIZE

    def chunk_document(
        self,
        content: str,
        title: Optional[str] = None,
    ) -> List[DocumentChunk]:
        """
        Split a document into chunks for search indexing.

        The chunking process:
        1. Normalize whitespace and split into paragraphs
        2. Process paragraphs into appropriately-sized chunks
        3. Add overlap between consecutive chunks
        4. Return list of DocumentChunk objects

        Args:
            content: Full document text
            title: Optional document title (passed to each chunk)

        Returns:
            List of DocumentChunk objects ready for indexing

        Note:
            Empty or very short documents may return a single chunk
            or an empty list.
        """
        if not content or not content.strip():
            return []

        # Normalize content
        content = self._normalize_content(content)

        # Split into paragraphs
        paragraphs = self._split_into_paragraphs(content)

        if not paragraphs:
            return []

        # Build chunks from paragraphs
        chunks = self._build_chunks(paragraphs, title)

        # Add overlap between chunks
        if len(chunks) > 1:
            chunks = self._add_overlap(chunks, content, title)

        logger.debug(f"Created {len(chunks)} chunks from {len(content)} chars")
        return chunks

    def _normalize_content(self, content: str) -> str:
        """
        Normalize document content for consistent chunking.

        - Normalize line endings
        - Remove excessive whitespace
        - Preserve paragraph structure
        """
        # Normalize line endings
        content = content.replace("\r\n", "\n").replace("\r", "\n")

        # Collapse multiple blank lines into double newlines (paragraph breaks)
        content = re.sub(r"\n{3,}", "\n\n", content)

        # Collapse multiple spaces
        content = re.sub(r" +", " ", content)

        return content.strip()

    def _split_into_paragraphs(self, content: str) -> List[str]:
        """
        Split content into paragraphs.

        Paragraphs are separated by blank lines (double newlines).
        Single newlines within paragraphs are preserved.
        """
        paragraphs = content.split("\n\n")
        # Clean up and filter empty paragraphs
        return [p.strip() for p in paragraphs if p.strip()]

    def _split_long_paragraph(self, paragraph: str) -> List[str]:
        """
        Split a long paragraph into sentence-based segments.

        Used when a paragraph exceeds max_chunk_size.
        Attempts to split on sentence boundaries.
        """
        # Sentence boundary regex (handles common abbreviations)
        sentence_pattern = r"(?<=[.!?])\s+(?=[A-Z])"

        sentences = re.split(sentence_pattern, paragraph)
        segments = []
        current_segment = ""

        for sentence in sentences:
            if len(current_segment) + len(sentence) + 1 <= self.max_chunk_size:
                if current_segment:
                    current_segment += " " + sentence
                else:
                    current_segment = sentence
            else:
                if current_segment:
                    segments.append(current_segment)
                # If single sentence is too long, we have to split it arbitrarily
                if len(sentence) > self.max_chunk_size:
                    # Split at word boundaries
                    words = sentence.split()
                    current_segment = ""
                    for word in words:
                        if len(current_segment) + len(word) + 1 <= self.max_chunk_size:
                            if current_segment:
                                current_segment += " " + word
                            else:
                                current_segment = word
                        else:
                            if current_segment:
                                segments.append(current_segment)
                            current_segment = word
                else:
                    current_segment = sentence

        if current_segment:
            segments.append(current_segment)

        return segments

    def _build_chunks(
        self, paragraphs: List[str], title: Optional[str]
    ) -> List[DocumentChunk]:
        """
        Build chunks from paragraphs, merging small ones and splitting large ones.
        """
        chunks = []
        current_content = ""
        current_start = 0
        char_position = 0

        for paragraph in paragraphs:
            para_len = len(paragraph)

            # If paragraph alone exceeds max size, split it
            if para_len > self.max_chunk_size:
                # First, save current accumulated content as a chunk
                if current_content and len(current_content) >= self.min_chunk_size:
                    chunks.append(
                        DocumentChunk(
                            content=current_content.strip(),
                            chunk_index=len(chunks),
                            title=title,
                            char_start=current_start,
                            char_end=char_position,
                        )
                    )
                    current_content = ""

                # Split the long paragraph
                segments = self._split_long_paragraph(paragraph)
                for segment in segments:
                    if segment:
                        chunks.append(
                            DocumentChunk(
                                content=segment.strip(),
                                chunk_index=len(chunks),
                                title=title,
                                char_start=char_position,
                                char_end=char_position + len(segment),
                            )
                        )
                current_start = char_position + para_len + 2  # +2 for paragraph break
                char_position = current_start

            # If adding paragraph would exceed max, save current and start new
            elif len(current_content) + para_len + 2 > self.max_chunk_size:
                if current_content and len(current_content) >= self.min_chunk_size:
                    chunks.append(
                        DocumentChunk(
                            content=current_content.strip(),
                            chunk_index=len(chunks),
                            title=title,
                            char_start=current_start,
                            char_end=char_position,
                        )
                    )
                current_content = paragraph
                current_start = char_position
                char_position += para_len + 2

            # Otherwise, add to current chunk
            else:
                if current_content:
                    current_content += "\n\n" + paragraph
                else:
                    current_content = paragraph
                    current_start = char_position
                char_position += para_len + 2

        # Don't forget the last chunk
        if current_content and len(current_content) >= self.min_chunk_size:
            chunks.append(
                DocumentChunk(
                    content=current_content.strip(),
                    chunk_index=len(chunks),
                    title=title,
                    char_start=current_start,
                    char_end=char_position,
                )
            )

        # Handle edge case: if we have content but it's under min_size
        # and we have no chunks yet, include it anyway
        if not chunks and current_content:
            chunks.append(
                DocumentChunk(
                    content=current_content.strip(),
                    chunk_index=0,
                    title=title,
                    char_start=0,
                    char_end=len(current_content),
                )
            )

        return chunks

    def _add_overlap(
        self, chunks: List[DocumentChunk], original_content: str, title: Optional[str]
    ) -> List[DocumentChunk]:
        """
        Add overlap between consecutive chunks for better search coverage.

        Takes content from the end of the previous chunk and prepends it
        to the current chunk, improving search recall at chunk boundaries.
        """
        if len(chunks) <= 1:
            return chunks

        overlapped_chunks = [chunks[0]]  # First chunk stays the same

        for i in range(1, len(chunks)):
            prev_chunk = chunks[i - 1]
            curr_chunk = chunks[i]

            # Get overlap from end of previous chunk
            prev_content = prev_chunk.content
            if len(prev_content) > self.overlap_size:
                # Try to split at word boundary
                overlap_text = prev_content[-self.overlap_size :]
                # Find first word boundary in overlap
                first_space = overlap_text.find(" ")
                if first_space > 0:
                    overlap_text = overlap_text[first_space + 1 :]
            else:
                overlap_text = prev_content

            # Prepend overlap to current chunk
            new_content = overlap_text + " " + curr_chunk.content
            overlapped_chunks.append(
                DocumentChunk(
                    content=new_content.strip(),
                    chunk_index=i,
                    title=title,
                    char_start=curr_chunk.char_start - len(overlap_text),
                    char_end=curr_chunk.char_end,
                )
            )

        return overlapped_chunks

    def estimate_chunk_count(self, content: str) -> int:
        """
        Estimate the number of chunks that will be created.

        Useful for progress tracking before actual chunking.

        Args:
            content: Document content

        Returns:
            Estimated number of chunks
        """
        if not content:
            return 0
        content_len = len(content)
        effective_chunk_size = self.max_chunk_size - self.overlap_size
        return max(1, (content_len + effective_chunk_size - 1) // effective_chunk_size)


# Global service instance with default settings
chunking_service = ChunkingService()


def get_chunking_service(
    max_chunk_size: int = None,
    min_chunk_size: int = None,
    overlap_size: int = None,
) -> ChunkingService:
    """
    Get a chunking service instance with optional custom settings.

    Args:
        max_chunk_size: Maximum characters per chunk
        min_chunk_size: Minimum characters per chunk
        overlap_size: Characters of overlap between chunks

    Returns:
        ChunkingService instance (global singleton for default settings)
    """
    if max_chunk_size or min_chunk_size or overlap_size:
        return ChunkingService(max_chunk_size, min_chunk_size, overlap_size)
    return chunking_service
