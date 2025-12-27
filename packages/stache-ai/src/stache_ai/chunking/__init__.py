"""Chunking package - Extensible chunking strategies"""

from .base import ChunkingStrategy
from .factory import ChunkingStrategyFactory

__all__ = ['ChunkingStrategy', 'ChunkingStrategyFactory']
