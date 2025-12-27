"""Contract tests for stache-ai-bedrock

These tests verify that the bedrock provider(s) satisfy the
contract defined by the base classes.
"""

import pytest
from stache_ai.testing import LLMContractTest, EmbeddingContractTest


class TestBedrockLlmContract(LLMContractTest):
    """Verify bedrock llm provider satisfies contract."""

    @pytest.fixture
    def provider(self, test_settings):
        """Create provider instance for testing."""
        # TODO: Import and instantiate the actual provider
        # This will be implemented when the package is extracted
        pytest.skip("Provider not yet implemented")

class TestBedrockEmbeddingsContract(EmbeddingContractTest):
    """Verify bedrock embeddings provider satisfies contract."""

    @pytest.fixture
    def provider(self, test_settings):
        """Create provider instance for testing."""
        # TODO: Import and instantiate the actual provider
        # This will be implemented when the package is extracted
        pytest.skip("Provider not yet implemented")

