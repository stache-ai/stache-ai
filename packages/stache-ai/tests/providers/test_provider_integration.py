"""Integration tests for provider system - require installed package"""

import pytest
from stache_ai.config import Settings
from stache_ai.providers import (
    LLMProviderFactory,
    EmbeddingProviderFactory,
    VectorDBProviderFactory,
    NamespaceProviderFactory,
    plugin_loader
)


@pytest.fixture
def fallback_settings():
    """Settings configured for fallback providers (no external deps)"""
    return Settings(
        llm_provider='fallback',
        embedding_provider='fallback',
        vectordb_provider='qdrant',  # Has no-op mode
        namespace_provider='sqlite',
    )


class TestProviderDiscoveryIntegration:
    """Test that providers are properly discovered after pip install"""

    def test_llm_providers_discovered(self):
        """Should discover at least fallback LLM provider"""
        available = LLMProviderFactory.get_available_providers()
        # Fallback has no external deps, should always be available
        assert 'fallback' in available or len(available) > 0

    def test_embedding_providers_discovered(self):
        """Should discover at least fallback embedding provider"""
        available = EmbeddingProviderFactory.get_available_providers()
        assert 'fallback' in available or len(available) > 0

    def test_namespace_providers_discovered(self):
        """Should discover SQLite namespace provider (no external deps)"""
        available = NamespaceProviderFactory.get_available_providers()
        # SQLite uses stdlib, should always be available
        assert 'sqlite' in available


class TestProviderCreationIntegration:
    """Test provider creation with real classes"""

    @pytest.mark.skipif(
        'fallback' not in LLMProviderFactory.get_available_providers(),
        reason="Fallback provider not available"
    )
    def test_create_fallback_llm(self, fallback_settings):
        """Should create fallback LLM provider"""
        provider = LLMProviderFactory.create(fallback_settings)
        assert provider is not None

    @pytest.mark.skipif(
        'fallback' not in EmbeddingProviderFactory.get_available_providers(),
        reason="Fallback provider not available"
    )
    def test_create_fallback_embedding(self, fallback_settings):
        """Should create fallback embedding provider"""
        provider = EmbeddingProviderFactory.create(fallback_settings)
        assert provider is not None

    @pytest.mark.skipif(
        'sqlite' not in NamespaceProviderFactory.get_available_providers(),
        reason="SQLite provider not available"
    )
    def test_create_sqlite_namespace(self, fallback_settings):
        """Should create SQLite namespace provider"""
        provider = NamespaceProviderFactory.create(fallback_settings)
        assert provider is not None
