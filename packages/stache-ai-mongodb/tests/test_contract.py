"""Contract tests for stache-ai-mongodb

These tests verify that the mongodb provider(s) satisfy the
contract defined by the base classes.
"""

import pytest
from stache_ai.testing import NamespaceContractTest, DocumentIndexContractTest


class TestMongodbNamespaceContract(NamespaceContractTest):
    """Verify mongodb namespace provider satisfies contract."""

    @pytest.fixture
    def provider(self, test_settings):
        """Create provider instance for testing."""
        # TODO: Import and instantiate the actual provider
        # This will be implemented when the package is extracted
        pytest.skip("Provider not yet implemented")

class TestMongodbDocument_IndexContract(DocumentIndexContractTest):
    """Verify mongodb document_index provider satisfies contract."""

    @pytest.fixture
    def provider(self, test_settings):
        """Create provider instance for testing."""
        # TODO: Import and instantiate the actual provider
        # This will be implemented when the package is extracted
        pytest.skip("Provider not yet implemented")

