"""Text splitting for RAG (Retrieval Augmented Generation).

Splits document content into overlapping text chunks suitable for embedding
and semantic retrieval. These RAG chunks are independent of the 100KB storage
chunks used by BeezStorage.

Usage:
    from shared.client_core.rag_chunking import split_into_rag_chunks

    chunks = split_into_rag_chunks(file_content, chunk_size=800, overlap=100)
"""

from typing import List
import re


def split_into_rag_chunks(
    content: str,
    chunk_size: int = 800,
    overlap: int = 100,
    min_chunk_size: int = 50,
) -> List[str]:
    """Split text content into overlapping chunks for RAG embedding.

    Uses a paragraph-aware splitting strategy:
    1. First splits on paragraph boundaries (double newlines).
    2. If a paragraph exceeds chunk_size, splits on sentence boundaries.
    3. If a sentence exceeds chunk_size, splits on word boundaries.
    4. Adds overlap between consecutive chunks for context continuity.

    Args:
        content: The full text content to split.
        chunk_size: Target maximum characters per chunk (default 800).
        overlap: Number of characters to overlap between chunks (default 100).
        min_chunk_size: Minimum chunk size; smaller chunks are merged (default 50).

    Returns:
        List of text chunks, each approximately chunk_size characters.
    """
    if not content or not content.strip():
        return []

    content = content.strip()

    # If content fits in one chunk, return as-is
    if len(content) <= chunk_size:
        return [content]

    # Split into paragraphs first
    paragraphs = _split_paragraphs(content)

    # Build chunks by accumulating paragraphs
    raw_chunks = _accumulate_chunks(paragraphs, chunk_size)

    # Split oversized chunks on sentence/word boundaries
    split_chunks = []
    for chunk in raw_chunks:
        if len(chunk) <= chunk_size:
            split_chunks.append(chunk)
        else:
            split_chunks.extend(_split_long_chunk(chunk, chunk_size))

    # Add overlap between consecutive chunks
    overlapped = _add_overlap(split_chunks, overlap)

    # Filter out chunks that are too small
    result = [c for c in overlapped if len(c.strip()) >= min_chunk_size]

    return result if result else [content[:chunk_size]]


def _split_paragraphs(text: str) -> List[str]:
    """Split text into paragraphs on double-newline boundaries."""
    paragraphs = re.split(r'\n\s*\n', text)
    return [p.strip() for p in paragraphs if p.strip()]


def _accumulate_chunks(segments: List[str], max_size: int) -> List[str]:
    """Accumulate segments into chunks up to max_size."""
    chunks = []
    current = ""

    for segment in segments:
        if current and len(current) + len(segment) + 1 > max_size:
            chunks.append(current.strip())
            current = segment
        else:
            current = current + "\n\n" + segment if current else segment

    if current.strip():
        chunks.append(current.strip())

    return chunks


def _split_long_chunk(text: str, max_size: int) -> List[str]:
    """Split a long chunk on sentence or word boundaries."""
    # Try sentence splitting first
    sentences = re.split(r'(?<=[.!?])\s+', text)
    if len(sentences) > 1:
        chunks = _accumulate_chunks(sentences, max_size)
        result = []
        for chunk in chunks:
            if len(chunk) <= max_size:
                result.append(chunk)
            else:
                # Fall back to word splitting
                result.extend(_split_on_words(chunk, max_size))
        return result

    # No sentence boundaries found -- split on words
    return _split_on_words(text, max_size)


def _split_on_words(text: str, max_size: int) -> List[str]:
    """Split text on word boundaries to fit within max_size."""
    words = text.split()
    chunks = []
    current = ""

    for word in words:
        if current and len(current) + len(word) + 1 > max_size:
            chunks.append(current.strip())
            current = word
        else:
            current = current + " " + word if current else word

    if current.strip():
        chunks.append(current.strip())

    return chunks


def _add_overlap(chunks: List[str], overlap: int) -> List[str]:
    """Add overlap from the end of each chunk to the beginning of the next."""
    if overlap <= 0 or len(chunks) <= 1:
        return chunks

    result = [chunks[0]]

    for i in range(1, len(chunks)):
        prev = chunks[i - 1]
        # Take the last 'overlap' characters from the previous chunk
        overlap_text = prev[-overlap:] if len(prev) > overlap else prev
        # Find a clean word boundary for the overlap
        space_idx = overlap_text.find(' ')
        if space_idx > 0:
            overlap_text = overlap_text[space_idx + 1:]

        result.append(overlap_text + " " + chunks[i])

    return result


def split_binary_for_rag(
    content: bytes,
    chunk_size: int = 800,
    overlap: int = 100,
) -> List[str]:
    """Attempt to extract text from binary content and split for RAG.

    Tries UTF-8 decoding first. If the content is not text-decodable,
    returns an empty list (binary files like images can't be RAG-indexed
    via text embedding).

    Args:
        content: Raw file bytes.
        chunk_size: Target chunk size.
        overlap: Overlap between chunks.

    Returns:
        List of text chunks, or empty list if content is not text.
    """
    try:
        text = content.decode("utf-8")
        return split_into_rag_chunks(text, chunk_size=chunk_size, overlap=overlap)
    except (UnicodeDecodeError, AttributeError):
        return []
