"""Contract tests for stache-ai-dynamodb

These tests verify that the dynamodb provider(s) satisfy the
contract defined by the base classes.
"""

import pytest
from stache_ai.testing import NamespaceContractTest, DocumentIndexContractTest


class TestDynamodbNamespaceContract(NamespaceContractTest):
    """Verify dynamodb namespace provider satisfies contract."""

    @pytest.fixture
    def provider(self, test_settings):
        """Create provider instance for testing."""
        # TODO: Import and instantiate the actual provider
        # This will be implemented when the package is extracted
        pytest.skip("Provider not yet implemented")

class TestDynamodbDocument_IndexContract(DocumentIndexContractTest):
    """Verify dynamodb document_index provider satisfies contract."""

    @pytest.fixture
    def provider(self, test_settings):
        """Create provider instance for testing."""
        # TODO: Import and instantiate the actual provider
        # This will be implemented when the package is extracted
        pytest.skip("Provider not yet implemented")

