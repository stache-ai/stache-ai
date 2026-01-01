"""Chunking strategy factory with entry point discovery"""

import logging

from stache_ai.providers import plugin_loader

from .base import ChunkingStrategy

logger = logging.getLogger(__name__)


class ChunkingStrategyFactory:
    """Factory for chunking strategies with entry point discovery

    Uses the centralized plugin_loader pattern for consistency.
    Strategies are discovered via 'stache.chunking' entry point group.
    """

    _discovered: bool = False

    @classmethod
    def create(cls, name: str) -> ChunkingStrategy:
        """Create chunking strategy by name

        Args:
            name: Strategy name ('recursive', 'markdown', etc.)

        Returns:
            Chunking strategy instance

        Raises:
            ValueError: If strategy not found
        """
        cls._ensure_discovered()
        strategy_class = plugin_loader.get_provider_class('chunking', name)

        if not strategy_class:
            available = ', '.join(sorted(cls.get_available_strategies()))
            raise ValueError(
                f"Unknown chunking strategy: {name}. "
                f"Available: {available or 'none'}"
            )

        logger.info(f"Creating chunking strategy: {name}")
        return strategy_class()

    @classmethod
    def _ensure_discovered(cls):
        """Trigger discovery if not done"""
        if cls._discovered:
            return
        # Just access the providers to trigger discovery
        plugin_loader.get_providers('chunking')
        cls._discovered = True

    @classmethod
    def get_available_strategies(cls) -> list[str]:
        """Get list of available strategy names"""
        return plugin_loader.get_available_providers('chunking')

    @classmethod
    def register(cls, name: str, strategy_class: type[ChunkingStrategy]):
        """Manual registration for testing

        Note: Manually registered strategies are added to the plugin_loader cache.
        For complete test isolation, also call plugin_loader.reset() after
        resetting this factory.
        """
        plugin_loader.register_provider('chunking', name, strategy_class)

    @classmethod
    def reset(cls):
        """Reset factory state (for testing)

        Note: This only resets the discovery flag. To fully clear registered
        strategies from the cache, also call plugin_loader.reset().
        """
        cls._discovered = False
        logger.debug("ChunkingStrategyFactory discovery flag reset")
