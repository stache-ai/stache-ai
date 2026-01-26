"""Tests for PineconeProvider update operations"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from stache_ai.config import Settings
from stache_ai_pinecone.provider import PineconeVectorDBProvider


@pytest.fixture
def mock_settings():
    """Create mock settings for Pinecone provider"""
    settings = Mock(spec=Settings)
    settings.pinecone_api_key = "test-api-key"
    settings.pinecone_index = "test-index"
    settings.pinecone_namespace = "test-namespace"
    settings.embedding_dimension = 1024
    settings.pinecone_cloud = "aws"
    settings.pinecone_region = "us-east-1"
    return settings


@pytest.fixture
def mock_pinecone_client():
    """Create mock Pinecone client"""
    with patch('stache_ai_pinecone.provider.Pinecone') as mock_pc:
        # Mock client instance
        client = MagicMock()
        mock_pc.return_value = client

        # Mock list_indexes to show index already exists
        mock_index_info = MagicMock()
        mock_index_info.name = "test-index"
        client.list_indexes.return_value = [mock_index_info]

        # Mock index instance
        mock_index = MagicMock()
        client.Index.return_value = mock_index

        yield client, mock_index


@pytest.fixture
def provider(mock_settings, mock_pinecone_client):
    """Create PineconeProvider instance with mocked dependencies"""
    client, mock_index = mock_pinecone_client
    provider = PineconeVectorDBProvider(mock_settings)
    provider.index = mock_index
    return provider


class TestGetByIds:
    """Tests for get_by_ids method"""

    def test_get_by_ids(self, provider):
        """Mock index.fetch(), verify metadata returned without vectors"""
        # Setup mock response from Pinecone fetch
        mock_response = MagicMock()
        mock_response.vectors = {
            "vec-1": MagicMock(
                id="vec-1",
                metadata={
                    "text": "First document content",
                    "source": "doc1.pdf",
                    "page": 1
                }
            ),
            "vec-2": MagicMock(
                id="vec-2",
                metadata={
                    "text": "Second document content",
                    "source": "doc2.pdf",
                    "page": 2
                }
            )
        }
        provider.index.fetch.return_value = mock_response

        # Call method
        results = provider.get_by_ids(["vec-1", "vec-2"])

        # Verify fetch called correctly
        provider.index.fetch.assert_called_once_with(
            ids=["vec-1", "vec-2"],
            namespace="test-namespace"
        )

        # Verify results format (no vectors)
        assert len(results) == 2
        assert results[0] == {
            "id": "vec-1",
            "metadata": {"text": "First document content", "source": "doc1.pdf", "page": 1}
        }
        assert results[1] == {
            "id": "vec-2",
            "metadata": {"text": "Second document content", "source": "doc2.pdf", "page": 2}
        }

        # Verify no vector field in results
        assert "vector" not in results[0]
        assert "vector" not in results[1]


class TestGetVectorsWithEmbeddings:
    """Tests for get_vectors_with_embeddings method"""

    def test_get_vectors_with_embeddings(self, provider):
        """Mock index.fetch() with vectors, verify standard format"""
        # Setup mock response with vector embeddings
        mock_response = MagicMock()
        mock_response.vectors = {
            "vec-1": MagicMock(
                id="vec-1",
                values=[0.1, 0.2, 0.3],  # Mock embedding
                metadata={
                    "text": "First document content",
                    "source": "doc1.pdf",
                    "page": 1
                }
            ),
            "vec-2": MagicMock(
                id="vec-2",
                values=[0.4, 0.5, 0.6],  # Mock embedding
                metadata={
                    "text": "Second document content",
                    "source": "doc2.pdf",
                    "page": 2
                }
            )
        }
        provider.index.fetch.return_value = mock_response

        # Call method
        results = provider.get_vectors_with_embeddings(["vec-1", "vec-2"])

        # Verify fetch called correctly
        provider.index.fetch.assert_called_once_with(
            ids=["vec-1", "vec-2"],
            namespace="test-namespace"
        )

        # Verify results format with vectors
        assert len(results) == 2
        assert results[0] == {
            "id": "vec-1",
            "vector": [0.1, 0.2, 0.3],
            "metadata": {"text": "First document content", "source": "doc1.pdf", "page": 1}
        }
        assert results[1] == {
            "id": "vec-2",
            "vector": [0.4, 0.5, 0.6],
            "metadata": {"text": "Second document content", "source": "doc2.pdf", "page": 2}
        }

    def test_get_vectors_with_embeddings_uses_default_namespace(self, provider):
        """Verify uses self.default_namespace when namespace=None (not empty string)"""
        # Setup mock response
        mock_response = MagicMock()
        mock_response.vectors = {
            "vec-1": MagicMock(
                id="vec-1",
                values=[0.1, 0.2, 0.3],
                metadata={"text": "Content", "key": "value"}
            )
        }
        provider.index.fetch.return_value = mock_response

        # Call with namespace=None (should use default_namespace)
        results = provider.get_vectors_with_embeddings(["vec-1"], namespace=None)

        # Verify default namespace was used
        provider.index.fetch.assert_called_once_with(
            ids=["vec-1"],
            namespace="test-namespace"  # Should be provider.default_namespace
        )

        # Verify it's not empty string
        call_args = provider.index.fetch.call_args
        assert call_args[1]["namespace"] == "test-namespace"
        assert call_args[1]["namespace"] != ""

        # Verify results returned
        assert len(results) == 1
        assert results[0]["id"] == "vec-1"
        assert results[0]["vector"] == [0.1, 0.2, 0.3]


class TestMaxBatchSize:
    """Tests for max_batch_size property"""

    def test_max_batch_size(self, provider):
        """Verify provider.max_batch_size == 1000"""
        assert provider.max_batch_size == 1000

        # Verify it's an integer
        assert isinstance(provider.max_batch_size, int)

        # Verify it's a property (not a method)
        assert not callable(provider.max_batch_size)
