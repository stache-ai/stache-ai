"""Test updated delete route (soft delete by default)."""
import pytest
from unittest.mock import ANY, AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from stache_ai.api.main import app
from stache_ai.rag.pipeline import RAGPipeline


@pytest.fixture
def client():
    """FastAPI test client."""
    return TestClient(app)


@pytest.fixture
def mock_pipeline():
    """Mock pipeline with document index provider."""
    pipeline = MagicMock()
    pipeline.document_index_provider = MagicMock()
    # Permanent delete fires delete observers via this async method
    pipeline.notify_document_deleted = AsyncMock()
    # Routes call pipeline-level operations; bind the real implementations so
    # the mocked providers still receive the calls tests assert on.
    for name in ("soft_delete_document", "permanently_delete_document", "_hard_delete_document"):
        setattr(pipeline, name, getattr(RAGPipeline, name).__get__(pipeline))
    return pipeline


def test_soft_delete_document_default(client, mock_pipeline):
    """Test soft delete (default behavior)."""
    mock_pipeline.document_index_provider.soft_delete_document.return_value = {
        "doc_id": "doc1",
        "namespace": "default",
        "deleted_at": "2026-01-25T10:00:00Z",
        "deleted_at_ms": 1706079600000,
        "purge_after": "2026-02-24T10:00:00Z",
    }

    with patch("stache_ai.api.routes.documents.get_pipeline", return_value=mock_pipeline):
        response = client.delete("/api/documents/id/doc1?namespace=default")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "deleted"
        assert data["doc_id"] == "doc1"
        assert "deleted_at" in data
        assert "purge_after" in data
        assert "Can be restored within 30 days" in data["message"]


def test_permanent_delete_with_query_param(client, mock_pipeline):
    """Test permanent delete with ?permanent=true."""
    mock_pipeline.document_index_provider.get_chunk_ids.return_value = [
        "chunk1", "chunk2", "chunk3"
    ]

    with patch("stache_ai.api.routes.documents.get_pipeline", return_value=mock_pipeline):
        response = client.delete("/api/documents/id/doc1?namespace=default&permanent=true")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "deleted"
        assert data["chunks_deleted"] == 3
        assert "permanently deleted" in data["message"]


def test_soft_delete_calls_provider(client, mock_pipeline):
    """Test that soft delete calls the correct provider method."""
    mock_pipeline.document_index_provider.soft_delete_document.return_value = {
        "doc_id": "doc1",
        "namespace": "default",
        "deleted_at": "2026-01-25T10:00:00Z",
        "deleted_at_ms": 1706079600000,
        "purge_after": "2026-02-24T10:00:00Z",
    }

    with patch("stache_ai.api.routes.documents.get_pipeline", return_value=mock_pipeline):
        response = client.delete("/api/documents/id/doc1?namespace=default")
        assert response.status_code == 200
        mock_pipeline.document_index_provider.soft_delete_document.assert_called_once()
        call_kwargs = mock_pipeline.document_index_provider.soft_delete_document.call_args[1]
        assert call_kwargs["doc_id"] == "doc1"
        assert call_kwargs["namespace"] == "default"
        assert call_kwargs["delete_reason"] == "user_initiated"


def test_permanent_delete_calls_get_chunk_ids(client, mock_pipeline):
    """Test that permanent delete calls get_chunk_ids."""
    mock_pipeline.document_index_provider.get_chunk_ids.return_value = ["chunk1"]

    with patch("stache_ai.api.routes.documents.get_pipeline", return_value=mock_pipeline):
        response = client.delete("/api/documents/id/doc1?namespace=default&permanent=true")
        assert response.status_code == 200
        mock_pipeline.document_index_provider.get_chunk_ids.assert_called_with(
            "doc1", "default", context=ANY
        )


def test_soft_delete_document_not_found(client, mock_pipeline):
    """Test soft delete when document not found."""
    mock_pipeline.document_index_provider.soft_delete_document.side_effect = ValueError(
        "Document not found"
    )

    with patch("stache_ai.api.routes.documents.get_pipeline", return_value=mock_pipeline):
        response = client.delete("/api/documents/id/doc1?namespace=default")
        assert response.status_code == 404


def test_permanent_delete_document_not_found(client, mock_pipeline):
    """Test permanent delete when document not found."""
    mock_pipeline.document_index_provider.get_chunk_ids.return_value = []

    with patch("stache_ai.api.routes.documents.get_pipeline", return_value=mock_pipeline):
        response = client.delete("/api/documents/id/doc1?namespace=default&permanent=true")
        assert response.status_code == 404


def test_delete_no_provider(client):
    """Test delete when document index not available."""
    pipeline = MagicMock()
    pipeline.document_index_provider = None

    with patch("stache_ai.api.routes.documents.get_pipeline", return_value=pipeline):
        response = client.delete("/api/documents/id/doc1?namespace=default")
        assert response.status_code == 501
