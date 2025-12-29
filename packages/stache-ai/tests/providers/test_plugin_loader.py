"""Tests for the entry point based plugin loader"""

from unittest.mock import MagicMock, patch

import pytest

from stache_ai.providers import plugin_loader


class TestPluginLoaderDiscovery:
    """Test provider discovery via entry points"""

    def setup_method(self):
        """Reset loader state before each test"""
        plugin_loader.reset()

    def teardown_method(self):
        """Clean up after each test"""
        plugin_loader.reset()

    def test_discover_providers_returns_dict(self):
        """Should return dictionary even when no providers found"""
        providers = plugin_loader.discover_providers('stache.nonexistent')
        assert isinstance(providers, dict)
        assert len(providers) == 0

    def test_get_providers_caches_result(self):
        """Should cache discovery results"""
        # First call triggers discovery
        providers1 = plugin_loader.get_providers('llm')

        # Second call should return cached result
        with patch.object(plugin_loader, 'discover_providers') as mock:
            providers2 = plugin_loader.get_providers('llm')
            mock.assert_not_called()

        assert providers1 is providers2

    def test_get_provider_class_returns_none_for_unknown(self):
        """Should return None for unknown provider"""
        result = plugin_loader.get_provider_class('llm', 'nonexistent_provider')
        assert result is None

    def test_get_available_providers_returns_list(self):
        """Should return list of provider names"""
        available = plugin_loader.get_available_providers('llm')
        assert isinstance(available, list)

    def test_reset_clears_cache(self):
        """reset() should clear the provider cache"""
        # Populate cache
        plugin_loader.get_providers('llm')
        assert 'llm' in plugin_loader._provider_cache

        # Reset
        plugin_loader.reset()
        assert 'llm' not in plugin_loader._provider_cache

    @patch('importlib.metadata.entry_points')
    def test_handles_import_error_gracefully(self, mock_eps):
        """Should skip providers with missing dependencies"""
        mock_ep = MagicMock()
        mock_ep.name = 'broken_provider'
        mock_ep.load.side_effect = ImportError("Missing dependency")

        # Python 3.10+ style
        mock_eps.return_value.select.return_value = [mock_ep]

        plugin_loader.reset()
        providers = plugin_loader.discover_providers('stache.llm')

        assert 'broken_provider' not in providers

    @patch('importlib.metadata.entry_points')
    def test_handles_load_exception_gracefully(self, mock_eps):
        """Should handle unexpected exceptions during load"""
        mock_ep = MagicMock()
        mock_ep.name = 'error_provider'
        mock_ep.load.side_effect = RuntimeError("Unexpected error")

        mock_eps.return_value.select.return_value = [mock_ep]

        plugin_loader.reset()
        providers = plugin_loader.discover_providers('stache.llm')

        assert 'error_provider' not in providers


class TestPluginLoaderRegistration:
    """Test manual provider registration"""

    def setup_method(self):
        plugin_loader.reset()

    def teardown_method(self):
        """Clean up after each test"""
        plugin_loader.reset()

    def test_register_provider_adds_to_cache(self):
        """Should add provider to cache"""
        mock_class = MagicMock()
        plugin_loader.register_provider('llm', 'test', mock_class)

        result = plugin_loader.get_provider_class('llm', 'test')
        assert result is mock_class

    def test_register_provider_creates_cache_if_missing(self):
        """Should create cache entry if type not yet cached"""
        mock_class = MagicMock()
        plugin_loader.register_provider('new_type', 'test', mock_class)

        assert 'new_type' in plugin_loader._provider_cache
        assert plugin_loader._provider_cache['new_type']['test'] is mock_class


class TestPluginLoaderIntegration:
    """Integration tests - require package to be installed"""

    def setup_method(self):
        plugin_loader.reset()

    def teardown_method(self):
        """Clean up after each test"""
        plugin_loader.reset()

    @pytest.mark.skipif(
        not plugin_loader.get_provider_class('llm', 'fallback'),
        reason="Package not installed with entry points"
    )
    def test_discovers_fallback_llm_provider(self):
        """Should discover the fallback LLM provider (no external deps)"""
        provider_class = plugin_loader.get_provider_class('llm', 'fallback')
        assert provider_class is not None
        assert 'Fallback' in provider_class.__name__

    @pytest.mark.skipif(
        not plugin_loader.get_provider_class('embeddings', 'fallback'),
        reason="Package not installed with entry points"
    )
    def test_discovers_fallback_embedding_provider(self):
        """Should discover the fallback embedding provider"""
        provider_class = plugin_loader.get_provider_class('embeddings', 'fallback')
        assert provider_class is not None

    def test_load_all_populates_all_types(self):
        """load_all() should discover all provider types"""
        plugin_loader.load_all()

        # All types should be in cache (even if empty due to missing deps)
        for provider_type in plugin_loader.PROVIDER_GROUPS:
            assert provider_type in plugin_loader._provider_cache
