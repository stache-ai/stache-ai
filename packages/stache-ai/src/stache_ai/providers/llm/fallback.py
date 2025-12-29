"""Fallback LLM provider - tries primary provider first, then falls back to secondary"""

import logging
from typing import Any

from stache_ai.config import Settings
from stache_ai.providers.base import LLMProvider
from stache_ai.providers.factories import LLMProviderFactory

logger = logging.getLogger(__name__)


class FallbackLLMProvider(LLMProvider):
    """
    Fallback LLM provider that tries primary provider first,
    then falls back to secondary if primary fails.

    Uses lazy loading via factory pattern to avoid import-time dependencies.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self._primary = None
        self._secondary = None
        self._primary_name = settings.fallback_primary
        self._secondary_name = settings.fallback_secondary

        logger.info(
            f"LLM fallback configured: {self._primary_name} -> {self._secondary_name}"
        )

    @property
    def primary(self) -> LLMProvider:
        """Lazy-load primary provider"""
        if self._primary is None:
            logger.info(f"Initializing primary LLM provider: {self._primary_name}")
            # Temporarily change the setting to create the right provider
            original = self.settings.llm_provider
            self.settings.llm_provider = self._primary_name
            try:
                self._primary = LLMProviderFactory.create(self.settings)
            finally:
                self.settings.llm_provider = original
        return self._primary

    @property
    def secondary(self) -> LLMProvider:
        """Lazy-load secondary provider"""
        if self._secondary is None:
            logger.info(f"Initializing secondary LLM provider: {self._secondary_name}")
            original = self.settings.llm_provider
            self.settings.llm_provider = self._secondary_name
            try:
                self._secondary = LLMProviderFactory.create(self.settings)
            finally:
                self.settings.llm_provider = original
        return self._secondary

    def get_name(self) -> str:
        """Get provider name"""
        return f"fallback({self._primary_name}->{self._secondary_name})"

    def generate(self, prompt: str, **kwargs) -> str:
        """Generate text from prompt, with fallback"""
        try:
            return self.primary.generate(prompt, **kwargs)
        except Exception as e:
            logger.warning(f"Primary LLM provider failed: {e}, trying secondary")
            return self.secondary.generate(prompt, **kwargs)

    def generate_with_context(
        self,
        query: str,
        context: list[dict[str, Any]],
        **kwargs
    ) -> str:
        """Generate answer with context, with fallback"""
        try:
            return self.primary.generate_with_context(query, context, **kwargs)
        except Exception as e:
            logger.warning(f"Primary LLM provider failed: {e}, trying secondary")
            return self.secondary.generate_with_context(query, context, **kwargs)
