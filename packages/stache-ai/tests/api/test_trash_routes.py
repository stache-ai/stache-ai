"""Test trash management API routes."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from stache_ai.api.main import app
from stache_ai.api.routes import trash


@pytest.fixture
def client():
    """FastAPI test client."""
    return TestClient(app)


@pytest.fixture
def mock_pipeline():
    """Mock pipeline with document index provider."""
    pipeline = MagicMock()
    pipeline.document_index_provider = MagicMock()
    return pipeline


def test_list_trash_empty(client, mock_pipeline):
    """Test listing empty trash."""
    mock_pipeline.document_index_provider.list_trash.return_value = {
        "items": [],
        "next_key": None,
        "count": 0,
    }

    with patch("stache_ai.api.routes.trash.get_pipeline", return_value=mock_pipeline):
        response = client.get("/api/trash/")
        assert response.status_code == 200
        assert response.json()["count"] == 0
        assert response.json()["items"] == []


def test_list_trash_with_items(client, mock_pipeline):
    """Test listing trash with items."""
    mock_pipeline.document_index_provider.list_trash.return_value = {
        "items": [
            {
                "doc_id": "doc1",
                "filename": "test.pdf",
                "namespace": "default",
                "deleted_at": "2026-01-25T10:00:00Z",
                "deleted_at_ms": 1706079600000,
                "purge_after": "2026-02-24T10:00:00Z",
                "purge_after_ms": 1708671600000,
                "days_until_purge": 30,
            }
        ],
        "next_key": None,
        "count": 1,
    }

    with patch("stache_ai.api.routes.trash.get_pipeline", return_value=mock_pipeline):
        response = client.get("/api/trash/")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["doc_id"] == "doc1"


def test_list_trash_with_namespace_filter(client, mock_pipeline):
    """Test listing trash with namespace filter."""
    mock_pipeline.document_index_provider.list_trash.return_value = {
        "items": [],
        "next_key": None,
        "count": 0,
    }

    with patch("stache_ai.api.routes.trash.get_pipeline", return_value=mock_pipeline):
        response = client.get("/api/trash/?namespace=docs")
        assert response.status_code == 200
        mock_pipeline.document_index_provider.list_trash.assert_called_with(
            namespace="docs",
            limit=50,
            next_key=None,
        )


def test_list_trash_no_provider(client):
    """Test listing trash when document index not available."""
    pipeline = MagicMock()
    pipeline.document_index_provider = None

    with patch("stache_ai.api.routes.trash.get_pipeline", return_value=pipeline):
        response = client.get("/api/trash/")
        assert response.status_code == 501
        assert "Document index not available" in response.json()["detail"]


def test_restore_document(client, mock_pipeline):
    """Test restoring document from trash."""
    mock_pipeline.document_index_provider.restore_document.return_value = {
        "doc_id": "doc1",
        "namespace": "default",
        "status": "active",
        "restored_at": "2026-01-25T10:30:00Z",
        "restored_at_ms": 1706081400000,
        "message": "Document restored successfully.",
    }

    with patch("stache_ai.api.routes.trash.get_pipeline", return_value=mock_pipeline):
        response = client.post(
            "/api/trash/restore",
            json={
                "doc_id": "doc1",
                "namespace": "default",
                "deleted_at_ms": 1706079600000,
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["doc_id"] == "doc1"
        assert data["status"] == "active"


def test_restore_document_not_found(client, mock_pipeline):
    """Test restoring non-existent document."""
    mock_pipeline.document_index_provider.restore_document.side_effect = ValueError(
        "Trash entry not found"
    )

    with patch("stache_ai.api.routes.trash.get_pipeline", return_value=mock_pipeline):
        response = client.post(
            "/api/trash/restore",
            json={
                "doc_id": "doc1",
                "namespace": "default",
                "deleted_at_ms": 1706079600000,
            }
        )
        assert response.status_code == 404


def test_restore_document_error(client, mock_pipeline):
    """Test restore error handling."""
    mock_pipeline.document_index_provider.restore_document.side_effect = Exception(
        "Database error"
    )

    with patch("stache_ai.api.routes.trash.get_pipeline", return_value=mock_pipeline):
        response = client.post(
            "/api/trash/restore",
            json={
                "doc_id": "doc1",
                "namespace": "default",
                "deleted_at_ms": 1706079600000,
            }
        )
        assert response.status_code == 500


def test_permanently_delete_document(client, mock_pipeline):
    """Test permanently deleting document from trash."""
    mock_pipeline.document_index_provider.permanently_delete_document.return_value = {
        "doc_id": "doc1",
        "namespace": "default",
        "chunk_count": 5,
        "cleanup_job_id": "cleanup_job_123",
    }

    with patch("stache_ai.api.routes.trash.get_pipeline", return_value=mock_pipeline):
        response = client.post(
            "/api/trash/permanent",
            json={
                "doc_id": "doc1",
                "namespace": "default",
                "deleted_at_ms": 1706079600000,
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "cleanup_pending"
        assert data["doc_id"] == "doc1"
        assert data["cleanup_job_id"] == "cleanup_job_123"


def test_permanently_delete_document_not_found(client, mock_pipeline):
    """Test permanently deleting non-existent document."""
    mock_pipeline.document_index_provider.permanently_delete_document.side_effect = ValueError(
        "Trash entry not found"
    )

    with patch("stache_ai.api.routes.trash.get_pipeline", return_value=mock_pipeline):
        response = client.post(
            "/api/trash/permanent",
            json={
                "doc_id": "doc1",
                "namespace": "default",
                "deleted_at_ms": 1706079600000,
            }
        )
        assert response.status_code == 404


def test_permanently_delete_no_provider(client):
    """Test permanently delete when document index not available."""
    pipeline = MagicMock()
    pipeline.document_index_provider = None

    with patch("stache_ai.api.routes.trash.get_pipeline", return_value=pipeline):
        response = client.post(
            "/api/trash/permanent",
            json={
                "doc_id": "doc1",
                "namespace": "default",
                "deleted_at_ms": 1706079600000,
            }
        )
        assert response.status_code == 501
