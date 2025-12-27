"""Contract tests for stache-ai-mixedbread

These tests verify that the mixedbread provider(s) satisfy the
contract defined by the base classes.
"""

import pytest
from stache_ai.testing import EmbeddingContractTest


class TestMixedbreadEmbeddingsContract(EmbeddingContractTest):
    """Verify mixedbread embeddings provider satisfies contract."""

    @pytest.fixture
    def provider(self, test_settings):
        """Create provider instance for testing."""
        # TODO: Import and instantiate the actual provider
        # This will be implemented when the package is extracted
        pytest.skip("Provider not yet implemented")

