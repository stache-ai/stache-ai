"""Chunking strategy factory"""

from typing import Dict, List, Type
from .base import ChunkingStrategy
import logging

logger = logging.getLogger(__name__)


class ChunkingStrategyFactory:
    """Factory for creating chunking strategies"""

    _strategies: Dict[str, Type[ChunkingStrategy]] = {}

    @classmethod
    def register(cls, name: str, strategy_class: Type[ChunkingStrategy]):
        """
        Register a chunking strategy

        Args:
            name: Strategy name (e.g., 'recursive', 'markdown')
            strategy_class: Strategy class
        """
        cls._strategies[name] = strategy_class
        logger.info(f"Registered chunking strategy: {name}")

    @classmethod
    def create(cls, name: str) -> ChunkingStrategy:
        """
        Create chunking strategy by name

        Args:
            name: Strategy name

        Returns:
            Chunking strategy instance
        """
        strategy_class = cls._strategies.get(name)

        if not strategy_class:
            available = ', '.join(cls._strategies.keys())
            raise ValueError(
                f"Unknown chunking strategy: {name}. "
                f"Available: {available}"
            )

        logger.info(f"Creating chunking strategy: {name}")
        return strategy_class()

    @classmethod
    def get_available_strategies(cls) -> List[str]:
        """Get list of available strategies"""
        return list(cls._strategies.keys())
