# backend/app/services/document_chunker.py
"""
Document Chunker Service - Semantic document chunking with overlap.

Provides intelligent document splitting for map-reduce summarization and
other large document processing tasks. Uses tiktoken for accurate token
counting compatible with OpenAI models.

Key Features:
- Token-based chunking with configurable overlap
- Paragraph-aware splitting (prefers breaking at paragraph boundaries)
- Token counting for context window management
- Support for different tokenizers (cl100k_base for GPT-4/Claude)

Usage:
    from app.services.document_chunker import document_chunker

    # Count tokens
    token_count = document_chunker.count_tokens(text)

    # Check if chunking needed
    if document_chunker.needs_chunking(text, max_tokens=100000):
        chunks = document_chunker.chunk_document(text, chunk_size=8000)

    # Process chunks with map-reduce
    chunk_summaries = await process_chunks_parallel(chunks)
    final_summary = await reduce_summaries(chunk_summaries)
"""

import logging
import re
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger("curatore.services.document_chunker")

# Approximate characters per token (conservative estimate)
# Claude/GPT-4 averages ~4 chars/token for English text
CHARS_PER_TOKEN = 4


@dataclass
class DocumentChunk:
    """A chunk of document content with metadata."""
    content: str
    chunk_index: int
    total_chunks: int
    token_count: int
    start_char: int
    end_char: int

    @property
    def is_first(self) -> bool:
        return self.chunk_index == 0

    @property
    def is_last(self) -> bool:
        return self.chunk_index == self.total_chunks - 1


class DocumentChunker:
    """
    Semantic document chunking with token-aware splitting.

    Splits documents into chunks suitable for LLM processing while
    maintaining context through overlap and preferring natural
    break points (paragraphs, sentences).

    Attributes:
        default_chunk_size: Default tokens per chunk (8000)
        default_overlap: Default overlap percentage (0.15 = 15%)
        max_context_tokens: Maximum tokens before chunking is required
    """

    DEFAULT_CHUNK_SIZE = 8000  # tokens
    DEFAULT_OVERLAP = 0.15  # 15% overlap
    MAX_CONTEXT_TOKENS = 100000  # ~400K chars, safe for most models

    def __init__(self):
        """Initialize the document chunker."""
        self._tokenizer = None

    def _get_tokenizer(self):
        """
        Get or create the tiktoken tokenizer.

        Uses cl100k_base encoding (GPT-4, Claude-compatible).
        Falls back to character-based estimation if tiktoken unavailable.
        """
        if self._tokenizer is None:
            try:
                import tiktoken
                self._tokenizer = tiktoken.get_encoding("cl100k_base")
                logger.debug("Using tiktoken cl100k_base tokenizer")
            except ImportError:
                logger.warning("tiktoken not installed, using character-based estimation")
                self._tokenizer = "fallback"
        return self._tokenizer

    def count_tokens(self, text: str) -> int:
        """
        Count tokens in text using tiktoken or character estimation.

        Args:
            text: Text to count tokens for

        Returns:
            Estimated token count
        """
        if not text:
            return 0

        tokenizer = self._get_tokenizer()

        if tokenizer == "fallback":
            # Character-based estimation
            return len(text) // CHARS_PER_TOKEN

        try:
            return len(tokenizer.encode(text))
        except Exception as e:
            logger.warning(f"Tokenization failed, using fallback: {e}")
            return len(text) // CHARS_PER_TOKEN

    def needs_chunking(self, text: str, max_tokens: Optional[int] = None) -> bool:
        """
        Check if document needs to be chunked for processing.

        Args:
            text: Document text
            max_tokens: Maximum tokens allowed (defaults to MAX_CONTEXT_TOKENS)

        Returns:
            True if document exceeds token limit
        """
        max_tokens = max_tokens or self.MAX_CONTEXT_TOKENS
        token_count = self.count_tokens(text)
        return token_count > max_tokens

    def chunk_document(
        self,
        text: str,
        chunk_size: Optional[int] = None,
        overlap: Optional[float] = None,
    ) -> List[DocumentChunk]:
        """
        Split document into overlapping chunks.

        Uses paragraph-aware splitting to maintain semantic coherence.
        Each chunk overlaps with the previous by the specified percentage
        to preserve context across chunk boundaries.

        Args:
            text: Document text to chunk
            chunk_size: Target tokens per chunk (default: 8000)
            overlap: Overlap percentage 0.0-0.5 (default: 0.15)

        Returns:
            List of DocumentChunk objects
        """
        chunk_size = chunk_size or self.DEFAULT_CHUNK_SIZE
        overlap = overlap if overlap is not None else self.DEFAULT_OVERLAP

        # Clamp overlap to reasonable range
        overlap = max(0.0, min(0.5, overlap))

        # Calculate overlap in tokens
        overlap_tokens = int(chunk_size * overlap)
        step_size = chunk_size - overlap_tokens

        # Split into paragraphs first (prefer breaking at paragraphs)
        paragraphs = self._split_into_paragraphs(text)

        chunks: List[DocumentChunk] = []
        current_chunk_paragraphs: List[str] = []
        current_token_count = 0
        char_position = 0

        for para in paragraphs:
            para_tokens = self.count_tokens(para)

            # If single paragraph exceeds chunk size, split it further
            if para_tokens > chunk_size:
                # Flush current chunk if any
                if current_chunk_paragraphs:
                    chunk_text = "\n\n".join(current_chunk_paragraphs)
                    chunks.append(DocumentChunk(
                        content=chunk_text,
                        chunk_index=len(chunks),
                        total_chunks=0,  # Will update at end
                        token_count=current_token_count,
                        start_char=char_position - len(chunk_text),
                        end_char=char_position,
                    ))
                    current_chunk_paragraphs = []
                    current_token_count = 0

                # Split large paragraph by sentences
                sub_chunks = self._chunk_large_paragraph(para, chunk_size, overlap_tokens)
                for sub_chunk in sub_chunks:
                    chunks.append(DocumentChunk(
                        content=sub_chunk,
                        chunk_index=len(chunks),
                        total_chunks=0,
                        token_count=self.count_tokens(sub_chunk),
                        start_char=char_position,
                        end_char=char_position + len(sub_chunk),
                    ))
                char_position += len(para) + 2  # +2 for paragraph separator
                continue

            # Check if adding this paragraph exceeds chunk size
            if current_token_count + para_tokens > chunk_size and current_chunk_paragraphs:
                # Create chunk from accumulated paragraphs
                chunk_text = "\n\n".join(current_chunk_paragraphs)
                chunk_start = char_position - len(chunk_text) - (len(current_chunk_paragraphs) - 1) * 2
                chunks.append(DocumentChunk(
                    content=chunk_text,
                    chunk_index=len(chunks),
                    total_chunks=0,
                    token_count=current_token_count,
                    start_char=max(0, chunk_start),
                    end_char=char_position,
                ))

                # Keep overlap paragraphs for next chunk
                overlap_paras = self._get_overlap_paragraphs(
                    current_chunk_paragraphs, overlap_tokens
                )
                current_chunk_paragraphs = overlap_paras
                current_token_count = sum(self.count_tokens(p) for p in overlap_paras)

            current_chunk_paragraphs.append(para)
            current_token_count += para_tokens
            char_position += len(para) + 2

        # Don't forget the last chunk
        if current_chunk_paragraphs:
            chunk_text = "\n\n".join(current_chunk_paragraphs)
            chunks.append(DocumentChunk(
                content=chunk_text,
                chunk_index=len(chunks),
                total_chunks=0,
                token_count=current_token_count,
                start_char=max(0, char_position - len(chunk_text)),
                end_char=char_position,
            ))

        # Update total_chunks in all chunks
        total = len(chunks)
        for chunk in chunks:
            chunk.total_chunks = total

        logger.info(
            f"Chunked document into {total} chunks "
            f"(~{chunk_size} tokens each, {overlap*100:.0f}% overlap)"
        )

        return chunks

    def _split_into_paragraphs(self, text: str) -> List[str]:
        """Split text into paragraphs, preserving structure."""
        # Split on double newlines (paragraph breaks)
        paragraphs = re.split(r'\n\s*\n', text)
        # Filter empty paragraphs and strip whitespace
        return [p.strip() for p in paragraphs if p.strip()]

    def _chunk_large_paragraph(
        self,
        paragraph: str,
        chunk_size: int,
        overlap_tokens: int,
    ) -> List[str]:
        """
        Split a large paragraph that exceeds chunk size.

        Splits by sentences, then by arbitrary positions if needed.
        """
        # Try splitting by sentences first
        sentences = re.split(r'(?<=[.!?])\s+', paragraph)

        if len(sentences) <= 1:
            # No sentence breaks, split by character count
            return self._split_by_tokens(paragraph, chunk_size, overlap_tokens)

        chunks = []
        current_sentences: List[str] = []
        current_tokens = 0

        for sentence in sentences:
            sentence_tokens = self.count_tokens(sentence)

            if current_tokens + sentence_tokens > chunk_size and current_sentences:
                chunks.append(" ".join(current_sentences))

                # Overlap: keep last few sentences
                overlap_sents = []
                overlap_count = 0
                for s in reversed(current_sentences):
                    s_tokens = self.count_tokens(s)
                    if overlap_count + s_tokens > overlap_tokens:
                        break
                    overlap_sents.insert(0, s)
                    overlap_count += s_tokens

                current_sentences = overlap_sents
                current_tokens = overlap_count

            current_sentences.append(sentence)
            current_tokens += sentence_tokens

        if current_sentences:
            chunks.append(" ".join(current_sentences))

        return chunks

    def _split_by_tokens(
        self,
        text: str,
        chunk_size: int,
        overlap_tokens: int,
    ) -> List[str]:
        """Split text by approximate token count when no natural breaks exist."""
        # Convert token counts to character counts
        chunk_chars = chunk_size * CHARS_PER_TOKEN
        overlap_chars = overlap_tokens * CHARS_PER_TOKEN
        step_chars = chunk_chars - overlap_chars

        chunks = []
        start = 0

        while start < len(text):
            end = min(start + chunk_chars, len(text))

            # Try to find a word boundary
            if end < len(text):
                # Look back for a space
                space_pos = text.rfind(" ", start + step_chars, end)
                if space_pos > start:
                    end = space_pos

            chunks.append(text[start:end].strip())
            start = end - overlap_chars if end < len(text) else len(text)

        return [c for c in chunks if c]

    def _get_overlap_paragraphs(
        self,
        paragraphs: List[str],
        overlap_tokens: int,
    ) -> List[str]:
        """Get paragraphs from the end that fit within overlap token budget."""
        overlap_paras = []
        token_count = 0

        for para in reversed(paragraphs):
            para_tokens = self.count_tokens(para)
            if token_count + para_tokens > overlap_tokens:
                break
            overlap_paras.insert(0, para)
            token_count += para_tokens

        return overlap_paras

    def estimate_chunks_needed(
        self,
        text: str,
        chunk_size: Optional[int] = None,
        overlap: Optional[float] = None,
    ) -> int:
        """
        Estimate how many chunks will be created without actually chunking.

        Useful for progress reporting and resource planning.

        Args:
            text: Document text
            chunk_size: Target tokens per chunk
            overlap: Overlap percentage

        Returns:
            Estimated number of chunks
        """
        chunk_size = chunk_size or self.DEFAULT_CHUNK_SIZE
        overlap = overlap if overlap is not None else self.DEFAULT_OVERLAP

        total_tokens = self.count_tokens(text)

        if total_tokens <= chunk_size:
            return 1

        step_size = chunk_size * (1 - overlap)
        return max(1, int((total_tokens - chunk_size) / step_size) + 1)


# Global singleton instance
document_chunker = DocumentChunker()


def get_document_chunker() -> DocumentChunker:
    """Get the global document chunker instance."""
    return document_chunker
