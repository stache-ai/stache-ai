"""Contract tests for stache-ai-s3vectors

These tests verify that the s3vectors provider(s) satisfy the
contract defined by the base classes.
"""

import pytest
from stache_ai.testing import VectorDBContractTest


class TestS3VectorsVectordbContract(VectorDBContractTest):
    """Verify s3vectors vectordb provider satisfies contract."""

    @pytest.fixture
    def provider(self, test_settings):
        """Create provider instance for testing."""
        # TODO: Import and instantiate the actual provider
        # This will be implemented when the package is extracted
        pytest.skip("Provider not yet implemented")

