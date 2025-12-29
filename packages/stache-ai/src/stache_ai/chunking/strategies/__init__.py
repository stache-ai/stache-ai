"""Chunking strategies - Auto-register all strategies"""

from stache_ai.chunking.character import CharacterChunkingStrategy
from stache_ai.chunking.factory import ChunkingStrategyFactory
from stache_ai.chunking.hierarchical import HierarchicalChunkingStrategy
from stache_ai.chunking.markdown import MarkdownChunkingStrategy
from stache_ai.chunking.recursive import RecursiveChunkingStrategy
from stache_ai.chunking.semantic import SemanticChunkingStrategy
from stache_ai.chunking.transcript import TranscriptChunkingStrategy

# Register all strategies
ChunkingStrategyFactory.register('recursive', RecursiveChunkingStrategy)
ChunkingStrategyFactory.register('markdown', MarkdownChunkingStrategy)
ChunkingStrategyFactory.register('character', CharacterChunkingStrategy)
ChunkingStrategyFactory.register('semantic', SemanticChunkingStrategy)
ChunkingStrategyFactory.register('transcript', TranscriptChunkingStrategy)
ChunkingStrategyFactory.register('hierarchical', HierarchicalChunkingStrategy)

__all__ = [
    'RecursiveChunkingStrategy',
    'MarkdownChunkingStrategy',
    'CharacterChunkingStrategy',
    'SemanticChunkingStrategy',
    'TranscriptChunkingStrategy',
    'HierarchicalChunkingStrategy',
]
