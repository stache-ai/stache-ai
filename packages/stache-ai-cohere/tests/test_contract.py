"""Contract tests for stache-ai-cohere

These tests verify that the cohere provider(s) satisfy the
contract defined by the base classes.
"""

import pytest
from stache_ai.testing import EmbeddingContractTest, RerankerContractTest


class TestCohereEmbeddingsContract(EmbeddingContractTest):
    """Verify cohere embeddings provider satisfies contract."""

    @pytest.fixture
    def provider(self, test_settings):
        """Create provider instance for testing."""
        # TODO: Import and instantiate the actual provider
        # This will be implemented when the package is extracted
        pytest.skip("Provider not yet implemented")

class TestCohereRerankerContract(RerankerContractTest):
    """Verify cohere reranker provider satisfies contract."""

    @pytest.fixture
    def provider(self, test_settings):
        """Create provider instance for testing."""
        # TODO: Import and instantiate the actual provider
        # This will be implemented when the package is extracted
        pytest.skip("Provider not yet implemented")

