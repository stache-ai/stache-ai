"""Document loaders for various file formats

Backward-compatible API. New code should use DocumentLoaderFactory directly.
"""

from .base import DocumentLoader
from .factory import DocumentLoaderFactory


# Backward-compatible function
def load_document(file_path: str, filename: str | None = None) -> str:
    """Load document and extract text (backward-compatible wrapper)"""
    return DocumentLoaderFactory.load_document(file_path, filename)


__all__ = ['DocumentLoader', 'DocumentLoaderFactory', 'load_document']
