"""Contract tests for stache-ai-ollama

These tests verify that the ollama provider(s) satisfy the
contract defined by the base classes.
"""

import pytest
from stache_ai.testing import LLMContractTest, EmbeddingContractTest, RerankerContractTest


class TestOllamaLlmContract(LLMContractTest):
    """Verify ollama llm provider satisfies contract."""

    @pytest.fixture
    def provider(self, test_settings):
        """Create provider instance for testing."""
        # TODO: Import and instantiate the actual provider
        # This will be implemented when the package is extracted
        pytest.skip("Provider not yet implemented")

class TestOllamaEmbeddingsContract(EmbeddingContractTest):
    """Verify ollama embeddings provider satisfies contract."""

    @pytest.fixture
    def provider(self, test_settings):
        """Create provider instance for testing."""
        # TODO: Import and instantiate the actual provider
        # This will be implemented when the package is extracted
        pytest.skip("Provider not yet implemented")

class TestOllamaRerankerContract(RerankerContractTest):
    """Verify ollama reranker provider satisfies contract."""

    @pytest.fixture
    def provider(self, test_settings):
        """Create provider instance for testing."""
        # TODO: Import and instantiate the actual provider
        # This will be implemented when the package is extracted
        pytest.skip("Provider not yet implemented")

