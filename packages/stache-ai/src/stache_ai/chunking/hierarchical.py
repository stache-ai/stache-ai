"""Hierarchical chunking strategy

When Docling is available, uses its document parser and HybridChunker to create
structure-aware chunks with heading context preserved in metadata.

Falls back to recursive chunking when Docling is not installed.
"""

import logging
from pathlib import Path

from .base import Chunk, ChunkingStrategy

logger = logging.getLogger(__name__)

# Check if docling is available
try:
    from docling.chunking import HybridChunker
    from docling.document_converter import DocumentConverter
    DOCLING_AVAILABLE = True
except ImportError:
    DOCLING_AVAILABLE = False
    logger.info("Docling not installed - hierarchical chunking will use recursive fallback")


class HierarchicalChunkingStrategy(ChunkingStrategy):
    """
    Hierarchical chunking using Docling's document parser.

    Features:
    - Preserves document structure (headings, sections)
    - Each chunk includes heading context in metadata
    - Uses HybridChunker for tokenization-aware splitting
    - Falls back to recursive chunking for plain text
    """

    def __init__(self, max_tokens: int = 512):
        """
        Initialize hierarchical chunker.

        Args:
            max_tokens: Maximum tokens per chunk (for HybridChunker)
        """
        self.max_tokens = max_tokens
        self._converter = None
        self._chunker = None

    @property
    def converter(self):
        """Lazy-load DocumentConverter"""
        if not DOCLING_AVAILABLE:
            return None
        if self._converter is None:
            self._converter = DocumentConverter()
        return self._converter

    @property
    def chunker(self):
        """Lazy-load HybridChunker"""
        if not DOCLING_AVAILABLE:
            return None
        if self._chunker is None:
            self._chunker = HybridChunker(
                max_tokens=self.max_tokens,
                merge_peers=True
            )
        return self._chunker

    def chunk(
        self,
        text: str,
        chunk_size: int = 2000,
        chunk_overlap: int = 200,
        **kwargs
    ) -> list[Chunk]:
        """
        Split text into hierarchical chunks.

        If file_path is provided in kwargs, uses Docling for structure-aware chunking.
        Otherwise falls back to recursive text splitting.

        Args:
            text: Input text (used as fallback if no file_path)
            chunk_size: Target size for each chunk (chars, for fallback)
            chunk_overlap: Overlap between chunks (for fallback)
            file_path: Path to source document for structure extraction

        Returns:
            List of Chunk objects with heading metadata
        """
        file_path = kwargs.get('file_path')

        if file_path and DOCLING_AVAILABLE:
            return self._chunk_with_docling(file_path)
        else:
            # Fallback to recursive chunking for plain text or when docling unavailable
            return self._chunk_text_fallback(text, chunk_size, chunk_overlap)

    def _chunk_with_docling(self, file_path: str) -> list[Chunk]:
        """
        Chunk document using Docling's structure-aware parsing.

        Args:
            file_path: Path to document file

        Returns:
            List of Chunk objects with heading context
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Document not found: {file_path}")

        logger.info(f"Processing document with Docling: {path.name}")

        try:
            # Convert document to Docling format
            result = self.converter.convert(source=str(path))
            doc = result.document

            # Apply hierarchical chunking
            chunks = []
            for i, doc_chunk in enumerate(self.chunker.chunk(dl_doc=doc)):
                # Extract heading context from metadata
                headings = []
                if hasattr(doc_chunk, 'meta') and doc_chunk.meta:
                    if hasattr(doc_chunk.meta, 'headings') and doc_chunk.meta.headings:
                        headings = list(doc_chunk.meta.headings)

                # Build heading path for display
                heading_path = " > ".join(headings) if headings else ""

                # Get document item labels if available
                doc_item_labels = []
                if hasattr(doc_chunk, 'meta') and doc_chunk.meta:
                    if hasattr(doc_chunk.meta, 'doc_items') and doc_chunk.meta.doc_items:
                        for item in doc_chunk.meta.doc_items:
                            if hasattr(item, 'label'):
                                doc_item_labels.append(str(item.label))

                chunk = Chunk(
                    text=doc_chunk.text,
                    index=i,
                    metadata={
                        'strategy': 'hierarchical',
                        'headings': headings,
                        'heading_path': heading_path,
                        'heading_level': len(headings),
                        'doc_item_labels': doc_item_labels,
                        'chunk_size': len(doc_chunk.text),
                    }
                )
                chunks.append(chunk)

            logger.info(f"Created {len(chunks)} hierarchical chunks from {path.name}")
            return chunks

        except Exception as e:
            logger.warning(f"Docling processing failed, falling back to text extraction: {e}")
            # Read file and fall back to text chunking
            text = path.read_text(encoding='utf-8', errors='replace')
            return self._chunk_text_fallback(text, 2000, 200)

    def _chunk_text_fallback(
        self,
        text: str,
        chunk_size: int,
        chunk_overlap: int
    ) -> list[Chunk]:
        """
        Fallback chunking for plain text without structure.

        Uses paragraph/sentence-based splitting similar to recursive strategy.
        """
        from .recursive import RecursiveChunkingStrategy

        recursive = RecursiveChunkingStrategy()
        chunks = recursive.chunk(text, chunk_size, chunk_overlap)

        # Add hierarchical metadata (empty since no structure)
        for chunk in chunks:
            chunk.metadata['strategy'] = 'hierarchical'
            chunk.metadata['headings'] = []
            chunk.metadata['heading_path'] = ''
            chunk.metadata['heading_level'] = 0

        return chunks


def chunk_file_hierarchically(
    file_path: str,
    max_tokens: int = 512
) -> list[Chunk]:
    """
    Convenience function to chunk a file using hierarchical strategy.

    Args:
        file_path: Path to document
        max_tokens: Max tokens per chunk

    Returns:
        List of Chunk objects
    """
    strategy = HierarchicalChunkingStrategy(max_tokens=max_tokens)
    return strategy.chunk("", file_path=file_path)
