"""Contract tests for stache-ai-openai

These tests verify that the openai provider(s) satisfy the
contract defined by the base classes.
"""

import pytest
from stache_ai.testing import LLMContractTest, EmbeddingContractTest


class TestOpenaiLlmContract(LLMContractTest):
    """Verify openai llm provider satisfies contract."""

    @pytest.fixture
    def provider(self, test_settings):
        """Create provider instance for testing."""
        # TODO: Import and instantiate the actual provider
        # This will be implemented when the package is extracted
        pytest.skip("Provider not yet implemented")

class TestOpenaiEmbeddingsContract(EmbeddingContractTest):
    """Verify openai embeddings provider satisfies contract."""

    @pytest.fixture
    def provider(self, test_settings):
        """Create provider instance for testing."""
        # TODO: Import and instantiate the actual provider
        # This will be implemented when the package is extracted
        pytest.skip("Provider not yet implemented")

