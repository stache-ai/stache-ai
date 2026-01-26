"""Tests for QdrantVectorDBProvider update-related functionality"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from qdrant_client.models import ScoredPoint, Record


@pytest.fixture
def mock_settings():
    """Create mock settings for QdrantVectorDBProvider."""
    settings = Mock()
    settings.qdrant_url = "http://localhost:6333"
    settings.qdrant_api_key = None
    settings.qdrant_collection = "test_collection"
    settings.embedding_dimension = 1024
    return settings


@pytest.fixture
def mock_client():
    """Create mock Qdrant client."""
    client = MagicMock()

    # Mock get_collections to return empty list (no collection exists yet)
    mock_collections = Mock()
    mock_collections.collections = []
    client.get_collections.return_value = mock_collections

    # Mock create_collection
    client.create_collection.return_value = None

    return client


@pytest.fixture
def provider(mock_settings, mock_client):
    """Create QdrantVectorDBProvider with mocked client."""
    with patch('stache_ai_qdrant.provider.QdrantClient', return_value=mock_client):
        from stache_ai_qdrant.provider import QdrantVectorDBProvider
        provider = QdrantVectorDBProvider(mock_settings)
        return provider


def test_get_vectors_with_embeddings(provider, mock_client):
    """Test retrieving vectors with embeddings returns normalized format."""
    # Create mock points with vectors
    mock_point1 = Mock()
    mock_point1.id = "test-id-1"
    mock_point1.vector = [0.1, 0.2, 0.3]
    mock_point1.payload = {
        "text": "Test text 1",
        "namespace": "test_ns",
        "custom_field": "value1"
    }

    mock_point2 = Mock()
    mock_point2.id = "test-id-2"
    mock_point2.vector = [0.4, 0.5, 0.6]
    mock_point2.payload = {
        "text": "Test text 2",
        "namespace": "test_ns",
        "another_field": "value2"
    }

    # Mock client.retrieve to return points with vectors
    mock_client.retrieve.return_value = [mock_point1, mock_point2]

    # Call get_vectors_with_embeddings
    ids = ["test-id-1", "test-id-2"]
    results = provider.get_vectors_with_embeddings(ids)

    # Verify client.retrieve was called correctly
    mock_client.retrieve.assert_called_once_with(
        collection_name="test_collection",
        ids=ids,
        with_vectors=True,
        with_payload=True
    )

    # Verify normalized format
    assert len(results) == 2

    # First result
    assert results[0]["id"] == "test-id-1"
    assert results[0]["vector"] == [0.1, 0.2, 0.3]
    assert "metadata" in results[0]
    assert results[0]["metadata"]["namespace"] == "test_ns"
    assert results[0]["metadata"]["custom_field"] == "value1"
    # text should remain in metadata per base class contract
    assert results[0]["metadata"]["text"] == "Test text 1"

    # Second result
    assert results[1]["id"] == "test-id-2"
    assert results[1]["vector"] == [0.4, 0.5, 0.6]
    assert "metadata" in results[1]
    assert results[1]["metadata"]["namespace"] == "test_ns"
    assert results[1]["metadata"]["another_field"] == "value2"
    assert results[1]["metadata"]["text"] == "Test text 2"


def test_get_vectors_with_embeddings_namespace_filter(provider, mock_client):
    """Test namespace filtering in get_vectors_with_embeddings."""
    # Create mock points with different namespaces
    mock_point1 = Mock()
    mock_point1.id = "id-1"
    mock_point1.vector = [0.1, 0.2, 0.3]
    mock_point1.payload = {
        "text": "Text 1",
        "namespace": "namespace_a"
    }

    mock_point2 = Mock()
    mock_point2.id = "id-2"
    mock_point2.vector = [0.4, 0.5, 0.6]
    mock_point2.payload = {
        "text": "Text 2",
        "namespace": "namespace_b"
    }

    mock_client.retrieve.return_value = [mock_point1, mock_point2]

    # Call with namespace filter
    results = provider.get_vectors_with_embeddings(
        ids=["id-1", "id-2"],
        namespace="namespace_a"
    )

    # Should only return point from namespace_a
    assert len(results) == 1
    assert results[0]["id"] == "id-1"
    assert results[0]["metadata"]["namespace"] == "namespace_a"


def test_get_vectors_with_embeddings_id_format_error(provider, mock_client):
    """Test error handling when client.retrieve raises exception."""
    # Mock client.retrieve to raise an exception
    mock_client.retrieve.side_effect = Exception("Invalid ID format: expected UUID")

    # Call get_vectors_with_embeddings and expect ValueError
    with pytest.raises(ValueError) as exc_info:
        provider.get_vectors_with_embeddings(ids=["invalid-id"])

    # Verify error message mentions ID format
    error_message = str(exc_info.value)
    assert "ID" in error_message or "id" in error_message.lower()
    assert "Qdrant point IDs" in error_message


def test_get_vectors_with_embeddings_empty_ids(provider, mock_client):
    """Test get_vectors_with_embeddings with empty ID list."""
    results = provider.get_vectors_with_embeddings(ids=[])

    # Should return empty list without calling client
    assert results == []
    mock_client.retrieve.assert_not_called()


def test_max_batch_size(provider):
    """Test max_batch_size property returns correct value."""
    assert provider.max_batch_size == 1000
