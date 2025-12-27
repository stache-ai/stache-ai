"""Tests for provider factories"""

import pytest
from unittest.mock import MagicMock, patch
from stache_ai.providers import (
    LLMProviderFactory,
    EmbeddingProviderFactory,
    VectorDBProviderFactory,
    NamespaceProviderFactory,
    RerankerProviderFactory,
    DocumentIndexProviderFactory,
    plugin_loader
)
from stache_ai.config import Settings


class TestLLMProviderFactory:
    """Test LLM provider factory"""

    def setup_method(self):
        plugin_loader.reset()

    def test_create_with_registered_provider(self):
        """Should create provider when registered"""
        mock_class = MagicMock()
        mock_instance = MagicMock()
        mock_class.return_value = mock_instance

        LLMProviderFactory.register('test', mock_class)
        settings = MagicMock(spec=Settings)
        settings.llm_provider = 'test'

        result = LLMProviderFactory.create(settings)

        assert result is mock_instance
        mock_class.assert_called_once_with(settings)

    def test_create_raises_for_unknown_provider(self):
        """Should raise ValueError for unknown provider"""
        settings = MagicMock(spec=Settings)
        settings.llm_provider = 'nonexistent'

        with pytest.raises(ValueError, match="Unknown LLM provider"):
            LLMProviderFactory.create(settings)

    def test_get_available_providers(self):
        """Should return list of registered providers"""
        LLMProviderFactory.register('test1', MagicMock())
        LLMProviderFactory.register('test2', MagicMock())

        available = LLMProviderFactory.get_available_providers()

        assert 'test1' in available
        assert 'test2' in available


class TestRerankerProviderFactory:
    """Test reranker provider factory - has special cases"""

    def setup_method(self):
        plugin_loader.reset()

    def test_create_returns_none_when_disabled(self):
        """Should return None when provider is 'none'"""
        settings = MagicMock(spec=Settings)
        settings.reranker_provider = 'none'

        result = RerankerProviderFactory.create(settings)

        assert result is None

    def test_create_simple_reranker(self):
        """Should create simple reranker with threshold"""
        mock_class = MagicMock()
        RerankerProviderFactory.register('simple', mock_class)

        settings = MagicMock(spec=Settings)
        settings.reranker_provider = 'simple'
        settings.reranker_dedupe_threshold = 0.95

        RerankerProviderFactory.create(settings)

        mock_class.assert_called_once_with(dedupe_threshold=0.95)

    def test_cohere_fallback_to_simple(self):
        """Should fallback to simple when Cohere API key not set"""
        mock_simple = MagicMock()
        RerankerProviderFactory.register('simple', mock_simple)
        RerankerProviderFactory.register('cohere', MagicMock())

        settings = MagicMock(spec=Settings)
        settings.reranker_provider = 'cohere'
        settings.cohere_api_key = None
        settings.reranker_dedupe_threshold = 0.95

        RerankerProviderFactory.create(settings)

        mock_simple.assert_called_once()


class TestDocumentIndexProviderFactory:
    """Test document index provider factory"""

    def setup_method(self):
        plugin_loader.reset()

    def test_create_dynamodb_provider(self):
        """Should create DynamoDB provider"""
        mock_class = MagicMock()
        DocumentIndexProviderFactory.register('dynamodb', mock_class)

        settings = MagicMock(spec=Settings)
        settings.document_index_provider = 'dynamodb'

        DocumentIndexProviderFactory.create(settings)

        mock_class.assert_called_once_with(settings)

    def test_raises_for_unknown_provider(self):
        """Should raise ValueError for unknown provider"""
        settings = MagicMock(spec=Settings)
        settings.document_index_provider = 'postgres'

        with pytest.raises(ValueError, match="Unknown document index provider"):
            DocumentIndexProviderFactory.create(settings)
