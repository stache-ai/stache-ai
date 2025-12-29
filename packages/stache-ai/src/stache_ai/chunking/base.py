"""Base chunking strategy interface"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class Chunk:
    """Represents a text chunk with metadata"""
    text: str
    index: int
    metadata: dict[str, Any]


class ChunkingStrategy(ABC):
    """Abstract base class for chunking strategies"""

    @abstractmethod
    def chunk(
        self,
        text: str,
        chunk_size: int = 2000,
        chunk_overlap: int = 200,
        **kwargs
    ) -> list[Chunk]:
        """
        Split text into chunks

        Args:
            text: Input text to chunk
            chunk_size: Target size for each chunk
            chunk_overlap: Overlap between chunks
            **kwargs: Strategy-specific parameters

        Returns:
            List of Chunk objects
        """
        pass

    def get_name(self) -> str:
        """Get strategy name"""
        return self.__class__.__name__
