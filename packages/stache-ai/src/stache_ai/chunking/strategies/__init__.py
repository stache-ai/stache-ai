"""Chunking strategies - discovered via entry points

This module exists for backward compatibility imports only.
Strategies are discovered automatically via 'stache.chunking' entry points.
"""

from stache_ai.chunking.character import CharacterChunkingStrategy
from stache_ai.chunking.hierarchical import HierarchicalChunkingStrategy
from stache_ai.chunking.markdown import MarkdownChunkingStrategy
from stache_ai.chunking.recursive import RecursiveChunkingStrategy
from stache_ai.chunking.semantic import SemanticChunkingStrategy
from stache_ai.chunking.transcript import TranscriptChunkingStrategy

__all__ = [
    'RecursiveChunkingStrategy',
    'MarkdownChunkingStrategy',
    'CharacterChunkingStrategy',
    'SemanticChunkingStrategy',
    'TranscriptChunkingStrategy',
    'HierarchicalChunkingStrategy',
]
