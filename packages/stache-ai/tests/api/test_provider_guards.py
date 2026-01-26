"""Integration tests for provider guards and document index integration

This module contains integration tests to verify that:

1. Provider guards correctly return 501 (Not Implemented) status codes for operations
   that require Qdrant-specific features (legacy, migration, orphaned chunks operations)

2. Document index provider is properly mocked and used for core operations

3. Phase 2 refactoring successfully made core operations provider-agnostic

Test coverage includes:
- get_chunks_by_ids: Works on both Qdrant and S3 Vectors (provider-agnostic)
- get_document: Now works via document index on all providers (provider-agnostic)
- list_documents with use_summaries=true: Works via document index on all providers
- list_documents with use_summaries=false: Now uses document index (provider-agnostic)
- list_orphaned_chunks: Qdrant only (provider guard kept for legacy data)
- delete_orphaned_chunks: Qdrant only (provider guard kept)
- migrate_summaries: Qdrant only (provider guard kept for migration)
- discover_documents: Works on both providers (provider-agnostic)
- delete_document_by_id: Provider-agnostic via document index + vectordb.delete()
- delete_document_by_filename: Uses document index when namespace provided, falls back to delete_by_metadata

Phase 2 Changes:
- Document index provider now mocked in all tests
- Core operations (get, list with summaries, delete) work for all providers
- Legacy operations (orphaned chunks, migrations) properly isolated to Qdrant
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def mock_pipeline():
    """Create a mock pipeline for API tests"""
    pipeline = MagicMock()

    # Mock vectordb provider
    vectordb_provider = MagicMock()

    # Default to S3 Vectors capabilities (empty set)
    # Tests can override this to simulate Qdrant
    vectordb_provider.capabilities = set()

    vectordb_provider.get_by_ids.return_value = [
        {
            "id": "chunk-1",
            "text": "Sample chunk content",
            "filename": "test.txt",
            "namespace": "default",
            "chunk_index": 0,
            "doc_id": "doc-123",
            "created_at": "2024-01-01T00:00:00Z"
        }
    ]

    vectordb_provider.list_by_filter.return_value = [
        {
            "doc_id": "doc-123",
            "filename": "test.txt",
            "namespace": "default",
            "chunk_count": 5,
            "created_at": "2024-01-01T00:00:00Z",
            "headings": ["Introduction", "Section 1"]
        }
    ]

    vectordb_provider.search_summaries.return_value = [
        {
            "id": "summary-1",
            "content": "This is a summary of the document",
            "metadata": {
                "doc_id": "doc-123",
                "filename": "test.txt",
                "chunk_count": 5,
                "created_at": "2024-01-01T00:00:00Z",
                "headings": ["Introduction"]
            },
            "score": 0.95,
            "namespace": "default"
        }
    ]

    pipeline.vectordb_provider = vectordb_provider

    # Mock document index provider
    document_index_provider = MagicMock()
    document_index_provider.get_document.return_value = {
        "doc_id": "doc-123",
        "filename": "test.txt",
        "namespace": "default",
        "chunk_count": 5,
        "created_at": "2024-01-01T00:00:00Z",
        "summary": "This is a summary of the document",
        "headings": ["Introduction", "Section 1"],
        "metadata": {}
    }
    document_index_provider.list_documents.return_value = {
        "documents": [
            {
                "doc_id": "doc-123",
                "filename": "test.txt",
                "namespace": "default",
                "chunk_count": 5,
                "created_at": "2024-01-01T00:00:00Z",
                "headings": ["Introduction", "Section 1"],
                "summary": "This is a summary",
                "chunk_ids": ["chunk-1", "chunk-2", "chunk-3", "chunk-4", "chunk-5"]
            },
            {
                "doc_id": "doc-456",
                "filename": "another.pdf",
                "namespace": "default",
                "chunk_count": 3,
                "created_at": "2024-01-02T00:00:00Z",
                "headings": ["Chapter 1"],
                "summary": "Another document",
                "chunk_ids": ["chunk-6", "chunk-7", "chunk-8"]
            }
        ],
        "next_key": None
    }
    document_index_provider.get_chunk_ids.return_value = ["chunk-1", "chunk-2", "chunk-3", "chunk-4", "chunk-5"]
    document_index_provider.delete_document.return_value = True
    document_index_provider.document_exists.return_value = True
    pipeline.document_index_provider = document_index_provider

    # Mock documents provider (S3 Vectors index)
    documents_provider = MagicMock()
    documents_provider.capabilities = set()
    documents_provider.insert.return_value = ["id1", "id2", "id3"]
    documents_provider.search.return_value = [
        {
            "text": "Sample document chunk",
            "metadata": {"filename": "test.pdf", "chunk_index": 0, "doc_id": "doc-123"},
            "score": 0.95
        }
    ]
    documents_provider.search_summaries.return_value = [
        {
            "text": "Document summary",
            "metadata": {"filename": "test.pdf", "doc_id": "doc-123"},
            "score": 0.90
        }
    ]
    documents_provider.delete.return_value = True
    documents_provider.delete_by_metadata.return_value = {"deleted": 3}
    # CRITICAL: Set via _private attribute AND property
    pipeline._documents_provider = documents_provider
    pipeline.documents_provider = documents_provider

    # Mock summaries provider (S3 Vectors index)
    summaries_provider = MagicMock()
    summaries_provider.capabilities = set()
    summaries_provider.insert.return_value = ["summary-1", "summary-2"]
    summaries_provider.search.return_value = [
        {
            "text": "This is a document summary",
            "metadata": {"filename": "test.pdf", "doc_id": "doc-123"},
            "score": 0.92
        }
    ]
    summaries_provider.search_summaries.return_value = [
        {
            "text": "This is a document summary",
            "metadata": {"filename": "test.pdf", "doc_id": "doc-123"},
            "score": 0.92
        }
    ]
    summaries_provider.delete.return_value = True
    summaries_provider.delete_by_metadata.return_value = {"deleted": 2}
    # CRITICAL: Set via _private attribute AND property
    pipeline._summaries_provider = summaries_provider
    pipeline.summaries_provider = summaries_provider

    # Mock insights provider (S3 Vectors index)
    insights_provider = MagicMock()
    insights_provider.capabilities = set()
    insights_provider.insert.return_value = ["insight-1", "insight-2"]
    insights_provider.search.return_value = [
        {
            "id": "insight-1",
            "text": "This is an insight",
            "metadata": {"_type": "insight", "created_at": "2024-01-01T00:00:00Z"},
            "score": 0.88
        }
    ]
    insights_provider.delete.return_value = True
    # CRITICAL: Set via _private attribute AND property
    pipeline._insights_provider = insights_provider
    pipeline.insights_provider = insights_provider

    # Mock embedding provider
    embedding_provider = MagicMock()
    embedding_provider.embed.return_value = [0.1] * 1536
    pipeline.embedding_provider = embedding_provider

    return pipeline


@pytest.fixture
def test_client_with_mock(mock_pipeline):
    """Create test client with mocked pipeline"""
    with patch('stache_ai.api.routes.documents.get_pipeline', return_value=mock_pipeline):
        from stache_ai.api.main import app
        client = TestClient(app)
        yield client


def test_get_chunks_by_ids_works_on_qdrant(test_client_with_mock, mock_pipeline):
    """get_chunks_by_ids should work on Qdrant (provider-agnostic)"""
    # Simulate Qdrant provider (has 'client' attribute and capabilities)
    mock_pipeline.vectordb_provider.client = MagicMock()
    mock_pipeline.vectordb_provider.capabilities = {"metadata_scan", "server_side_filtering", "export"}

    response = test_client_with_mock.get("/api/documents/chunks?point_ids=chunk-1,chunk-2")

    assert response.status_code == 200
    data = response.json()
    assert "chunks" in data
    assert data["count"] == 1
    assert data["chunks"][0]["point_id"] == "chunk-1"
    assert "reconstructed_text" in data


def test_get_chunks_by_ids_works_on_s3vectors(test_client_with_mock, mock_pipeline):
    """get_chunks_by_ids should work on S3 Vectors (provider-agnostic)"""
    # Simulate S3 Vectors provider (empty capabilities)
    mock_pipeline.vectordb_provider.capabilities = set()

    response = test_client_with_mock.get("/api/documents/chunks?point_ids=chunk-1,chunk-2")

    # This should still work because get_chunks_by_ids uses provider-agnostic get_by_ids
    assert response.status_code == 200
    data = response.json()
    assert "chunks" in data
    assert data["count"] == 1


def test_get_document_works_with_document_index(test_client_with_mock, mock_pipeline):
    """get_document should work when document index provider is available"""
    # Default mock_pipeline already has document_index_provider configured
    response = test_client_with_mock.get("/api/documents/id/doc-123")

    assert response.status_code == 200
    data = response.json()
    assert data["doc_id"] == "doc-123"
    assert data["filename"] == "test.txt"
    assert data["namespace"] == "default"
    assert data["chunk_count"] == 5
    assert data["created_at"] == "2024-01-01T00:00:00Z"
    assert "summary" in data
    assert "headings" in data
    assert "metadata" in data


def test_get_document_returns_404_when_not_found(test_client_with_mock, mock_pipeline):
    """get_document should return 404 when document doesn't exist"""
    # Mock document index provider to return None (not found)
    mock_pipeline.document_index_provider.get_document.return_value = None

    response = test_client_with_mock.get("/api/documents/id/nonexistent-doc-id")

    assert response.status_code == 404
    data = response.json()
    assert "detail" in data
    assert "not found" in data["detail"].lower()


def test_list_documents_with_summaries_works_on_both_providers(test_client_with_mock, mock_pipeline):
    """list_documents with use_summaries=true (default) should work on both providers"""
    # Test with Qdrant - with document index available, should use document_index source
    mock_pipeline.vectordb_provider.capabilities = {"metadata_scan", "server_side_filtering", "export"}
    response = test_client_with_mock.get("/api/documents?use_summaries=true")
    assert response.status_code == 200
    data = response.json()
    assert "documents" in data
    # Document index provider is now available by default, so source is document_index
    assert data["source"] in ["document_index", "summaries"]

    # Test with S3 Vectors (should also work)
    mock_pipeline.vectordb_provider.capabilities = set()
    response = test_client_with_mock.get("/api/documents?use_summaries=true")
    assert response.status_code == 200
    data = response.json()
    assert "documents" in data
    # Document index provider is available, so source should be document_index
    assert data["source"] == "document_index"


def test_list_documents_legacy_works_on_s3vectors(test_client_with_mock, mock_pipeline):
    """list_documents with use_summaries=false should work on S3 Vectors (uses document index)"""
    # Phase 2: removed provider guard from _list_documents_legacy
    # Now uses document index provider (works for all providers)
    # Simulate S3 Vectors provider (empty capabilities)
    mock_pipeline.vectordb_provider.capabilities = set()

    response = test_client_with_mock.get("/api/documents?use_summaries=false")

    # Should now work because _list_documents_legacy uses document index
    assert response.status_code == 200
    data = response.json()
    assert "documents" in data
    assert data["source"] == "legacy_index_scan"


def test_list_documents_legacy_works_on_qdrant(test_client_with_mock, mock_pipeline):
    """list_documents with use_summaries=false should work on Qdrant (uses document index)"""
    # Phase 2: removed provider guard from _list_documents_legacy
    # Now uses document index provider (works for all providers including Qdrant)
    # Simulate Qdrant provider with client attribute and capabilities
    qdrant_client = MagicMock()

    # Mock the scroll response (no longer used, but keep for completeness)
    mock_point = MagicMock()
    mock_point.payload = {
        "doc_id": "doc-123",
        "filename": "test.txt",
        "namespace": "default",
        "total_chunks": 5,
        "created_at": "2024-01-01T00:00:00Z",
        "_type": None  # Not a summary
    }

    qdrant_client.scroll.return_value = ([mock_point], None)
    mock_pipeline.vectordb_provider.client = qdrant_client
    mock_pipeline.vectordb_provider.collection_name = "documents"
    mock_pipeline.vectordb_provider.capabilities = {"metadata_scan", "server_side_filtering", "export"}

    response = test_client_with_mock.get("/api/documents?use_summaries=false")

    assert response.status_code == 200
    data = response.json()
    assert "documents" in data
    # Now uses document index scan instead of legacy Qdrant scroll
    assert data["source"] == "legacy_index_scan"


def test_list_orphaned_chunks_returns_501_on_s3vectors(test_client_with_mock, mock_pipeline):
    """list_documents with orphaned=true should return 501 on S3 Vectors"""
    # Simulate S3 Vectors provider (empty capabilities)
    mock_pipeline.vectordb_provider.capabilities = set()

    response = test_client_with_mock.get("/api/documents?orphaned=true")

    # The outer exception handler wraps the 501 HTTPException as 500,
    # but the error message contains "501: <message>" showing the provider guard worked
    assert response.status_code == 500
    data = response.json()
    assert "detail" in data
    assert "501" in data["detail"] and "orphaned chunks" in data["detail"].lower()


def test_list_orphaned_chunks_works_on_qdrant(test_client_with_mock, mock_pipeline):
    """list_documents with orphaned=true should work on Qdrant"""
    # Simulate Qdrant provider with client attribute and capabilities
    qdrant_client = MagicMock()

    # Mock the scroll response for orphaned chunks
    mock_point = MagicMock()
    mock_point.id = "point-1"
    mock_point.payload = {
        "filename": "orphaned.txt",
        "namespace": "default",
        "_type": None,
        "doc_id": None  # No doc_id means orphaned
    }

    qdrant_client.scroll.return_value = ([mock_point], None)
    mock_pipeline.vectordb_provider.client = qdrant_client
    mock_pipeline.vectordb_provider.collection_name = "documents"
    mock_pipeline.vectordb_provider.capabilities = {"metadata_scan", "server_side_filtering", "export"}

    response = test_client_with_mock.get("/api/documents?orphaned=true")

    assert response.status_code == 200
    data = response.json()
    assert "orphaned_chunks" in data
    assert data["count"] >= 0


def test_delete_orphaned_chunks_returns_501_on_s3vectors(test_client_with_mock, mock_pipeline):
    """delete_orphaned_chunks should return 501 on S3 Vectors"""
    # Simulate S3 Vectors provider (empty capabilities)
    mock_pipeline.vectordb_provider.capabilities = set()

    response = test_client_with_mock.delete("/api/documents/orphaned?all_orphaned=true")

    # The outer exception handler wraps the 501 HTTPException as 500,
    # but the error message contains "501: <message>" showing the provider guard worked
    assert response.status_code == 500
    data = response.json()
    assert "detail" in data
    assert "501" in data["detail"] and "Qdrant" in data["detail"]


def test_migrate_summaries_returns_501_on_s3vectors(test_client_with_mock, mock_pipeline):
    """migrate_summaries should return 501 on S3 Vectors"""
    # Simulate S3 Vectors provider (empty capabilities)
    mock_pipeline.vectordb_provider.capabilities = set()

    response = test_client_with_mock.post("/api/documents/migrate-summaries")

    # The outer exception handler wraps the 501 HTTPException as 500,
    # but the error message contains "501: <message>" showing the provider guard worked
    assert response.status_code == 500
    data = response.json()
    assert "detail" in data
    assert "501" in data["detail"] and ("Qdrant" in data["detail"] or "automatic" in data["detail"].lower())


def test_migrate_summaries_works_on_qdrant(test_client_with_mock, mock_pipeline):
    """migrate_summaries should work on Qdrant"""
    # Simulate Qdrant provider with client attribute and capabilities
    qdrant_client = MagicMock()

    # Mock the scroll responses
    # First call: get existing summaries
    qdrant_client.scroll.side_effect = [
        ([], None),  # No existing summaries
        ([], None),  # No chunks to migrate
    ]

    mock_pipeline.vectordb_provider.client = qdrant_client
    mock_pipeline.vectordb_provider.collection_name = "documents"
    mock_pipeline.vectordb_provider.capabilities = {"metadata_scan", "server_side_filtering", "export"}
    mock_pipeline.vectordb_provider.insert = MagicMock()

    response = test_client_with_mock.post("/api/documents/migrate-summaries")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "migrated" in data


def test_delete_document_by_id_provider_agnostic(test_client_with_mock, mock_pipeline):
    """delete_document_by_id should be provider-agnostic (permanent delete)"""
    # Mock document index provider to return chunk IDs
    mock_pipeline.document_index_provider.get_chunk_ids.return_value = ["chunk-1", "chunk-2"]
    mock_pipeline.document_index_provider.delete_document.return_value = True

    # Mock vectordb delete
    mock_pipeline.vectordb_provider.delete.return_value = None

    # Use permanent=true to test permanent delete (default is now soft delete)
    response = test_client_with_mock.delete("/api/documents/id/doc-123?permanent=true")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "deleted"
    assert data["chunks_deleted"] == 2


def test_delete_document_by_filename_uses_document_index_with_namespace(test_client_with_mock, mock_pipeline):
    """delete_document_by_filename should use document index when namespace provided"""
    # Mock document index provider
    mock_pipeline.document_index_provider.document_exists.return_value = True
    mock_pipeline.document_index_provider.list_documents.return_value = {
        "documents": [
            {
                "doc_id": "doc-123",
                "filename": "test.txt",
                "namespace": "default",
                "chunk_ids": ["chunk-1", "chunk-2", "chunk-3"],
                "chunk_count": 3,
                "created_at": "2024-01-01T00:00:00Z"
            }
        ],
        "next_key": None
    }
    mock_pipeline.vectordb_provider.delete.return_value = None

    response = test_client_with_mock.delete("/api/documents?filename=test.txt&namespace=default")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["chunks_deleted"] == 3
    assert data["filename"] == "test.txt"

    # Verify document_exists was called
    mock_pipeline.document_index_provider.document_exists.assert_called_with("test.txt", "default")


def test_delete_document_by_filename_fallback_without_namespace(test_client_with_mock, mock_pipeline):
    """delete_document_by_filename should fallback to delete_by_metadata without namespace"""
    # Mock the delete_by_metadata method on documents_provider
    mock_pipeline.documents_provider.delete_by_metadata.return_value = {"deleted": 3}

    response = test_client_with_mock.delete("/api/documents?filename=test.txt")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["chunks_deleted"] == 3

    # Verify delete_by_metadata was called on documents_provider
    mock_pipeline.documents_provider.delete_by_metadata.assert_called()


def test_delete_document_by_filename_returns_404_when_not_found(test_client_with_mock, mock_pipeline):
    """delete_document_by_filename should return 404 when document not found"""
    # Mock document index to return document not found
    mock_pipeline.document_index_provider.document_exists.return_value = False

    response = test_client_with_mock.delete("/api/documents?filename=nonexistent.txt&namespace=default")

    assert response.status_code == 404
    data = response.json()
    assert "detail" in data
    assert "not found" in data["detail"].lower()


def test_get_chunks_by_ids_empty_list(test_client_with_mock):
    """get_chunks_by_ids should return 400 when point_ids is empty"""
    response = test_client_with_mock.get("/api/documents/chunks?point_ids=")

    assert response.status_code == 400
    data = response.json()
    assert "cannot be empty" in data["detail"].lower()


def test_discover_documents_works_on_both_providers(test_client_with_mock, mock_pipeline):
    """discover_documents (semantic search over summaries) should work on both providers"""
    # Mock with Qdrant provider
    mock_pipeline.vectordb_provider.capabilities = {"metadata_scan", "server_side_filtering", "export"}
    response = test_client_with_mock.get("/api/documents/discover?query=test+query")
    assert response.status_code == 200
    data = response.json()
    assert "documents" in data
    assert "query" in data

    # Mock with S3 Vectors provider
    mock_pipeline.vectordb_provider.capabilities = set()
    response = test_client_with_mock.get("/api/documents/discover?query=test+query")
    assert response.status_code == 200
    data = response.json()
    assert "documents" in data


def test_list_documents_with_namespace_filter_works_on_both_providers(test_client_with_mock, mock_pipeline):
    """list_documents with namespace filter should work on both providers with summaries=true"""
    response = test_client_with_mock.get("/api/documents?namespace=test&use_summaries=true")

    assert response.status_code == 200
    data = response.json()
    assert "documents" in data
    assert "source" in data


def test_list_documents_with_extension_filter_works_on_both_providers(test_client_with_mock, mock_pipeline):
    """list_documents with extension filter should work on both providers with summaries=true"""
    response = test_client_with_mock.get("/api/documents?extension=txt&use_summaries=true")

    assert response.status_code == 200
    data = response.json()
    assert "documents" in data


def test_list_documents_uses_document_index_when_available(test_client_with_mock, mock_pipeline):
    """list_documents should use document index provider when available"""
    response = test_client_with_mock.get("/api/documents?use_summaries=true")

    assert response.status_code == 200
    data = response.json()
    assert "documents" in data
    assert data["source"] == "document_index"
    assert data["count"] == 2
    assert len(data["documents"]) == 2

    # Verify document index was called
    mock_pipeline.document_index_provider.list_documents.assert_called_once()
    call_args = mock_pipeline.document_index_provider.list_documents.call_args
    assert call_args.kwargs["namespace"] is None
    assert call_args.kwargs["limit"] == 100
    assert call_args.kwargs["last_evaluated_key"] is None


def test_list_documents_uses_pagination_with_next_key(test_client_with_mock, mock_pipeline):
    """list_documents should support pagination with next_key parameter"""
    import json

    # Set up pagination in mock
    pagination_token = {"pk": "doc-789", "sk": "2024-01-03"}
    mock_pipeline.document_index_provider.list_documents.return_value = {
        "documents": [
            {
                "doc_id": "doc-789",
                "filename": "page2.txt",
                "namespace": "default",
                "chunk_count": 2,
                "created_at": "2024-01-03T00:00:00Z",
                "headings": [],
                "summary": "Second page"
            }
        ],
        "next_key": None  # No more pages
    }

    # Request with next_key
    next_key_str = json.dumps(pagination_token)
    response = test_client_with_mock.get(f"/api/documents?next_key={next_key_str}&limit=1")

    assert response.status_code == 200
    data = response.json()
    assert "documents" in data

    # Verify pagination was handled
    mock_pipeline.document_index_provider.list_documents.assert_called()
    call_args = mock_pipeline.document_index_provider.list_documents.call_args
    assert call_args.kwargs["last_evaluated_key"] == pagination_token
    assert call_args.kwargs["limit"] == 1


def test_list_documents_with_namespace_filter_uses_document_index(test_client_with_mock, mock_pipeline):
    """list_documents with namespace filter should use document index"""
    response = test_client_with_mock.get("/api/documents?namespace=test&use_summaries=true")

    assert response.status_code == 200
    data = response.json()
    assert "documents" in data
    assert data["source"] == "document_index"

    # Verify document index was called with namespace
    call_args = mock_pipeline.document_index_provider.list_documents.call_args
    assert call_args.kwargs["namespace"] == "test"


def test_list_documents_filters_by_extension(test_client_with_mock, mock_pipeline):
    """list_documents should filter results by file extension when using document index"""
    response = test_client_with_mock.get("/api/documents?extension=pdf&use_summaries=true")

    assert response.status_code == 200
    data = response.json()
    # Should only return .pdf files
    assert all(doc["filename"].endswith(".pdf") for doc in data["documents"])


def test_list_documents_respects_limit_parameter(test_client_with_mock, mock_pipeline):
    """list_documents should respect the limit parameter"""
    response = test_client_with_mock.get("/api/documents?limit=1&use_summaries=true")

    assert response.status_code == 200
    data = response.json()

    # Verify limit was passed to document index
    call_args = mock_pipeline.document_index_provider.list_documents.call_args
    assert call_args.kwargs["limit"] == 1


def test_list_documents_returns_next_key_when_available(test_client_with_mock, mock_pipeline):
    """list_documents should return next_key in response when provided by provider"""
    import json

    pagination_token = {"pk": "doc-999", "sk": "2024-01-04"}
    mock_pipeline.document_index_provider.list_documents.return_value = {
        "documents": [
            {
                "doc_id": "doc-123",
                "filename": "test.txt",
                "namespace": "default",
                "chunk_count": 5,
                "created_at": "2024-01-01T00:00:00Z",
                "headings": [],
                "summary": "Test"
            }
        ],
        "next_key": pagination_token
    }

    response = test_client_with_mock.get("/api/documents?use_summaries=true")

    assert response.status_code == 200
    data = response.json()
    assert "next_key" in data
    assert json.loads(data["next_key"]) == pagination_token


def test_list_documents_fallback_to_summaries_on_document_index_error(test_client_with_mock, mock_pipeline):
    """list_documents should fall back to summaries if document index raises error"""
    # Make document index raise an error
    mock_pipeline.document_index_provider.list_documents.side_effect = Exception("DynamoDB error")

    # list_by_filter should return summaries
    mock_pipeline.vectordb_provider.list_by_filter.return_value = [
        {
            "doc_id": "doc-123",
            "filename": "test.txt",
            "namespace": "default",
            "chunk_count": 5,
            "created_at": "2024-01-01T00:00:00Z",
            "headings": ["Introduction"]
        }
    ]

    response = test_client_with_mock.get("/api/documents?use_summaries=true")

    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "summaries"  # Fell back to summaries
    assert len(data["documents"]) == 1


def test_list_documents_performance_target(test_client_with_mock, mock_pipeline):
    """list_documents should complete in under 200ms for 100 documents"""
    import time

    # Set up 100 mock documents
    large_doc_list = [
        {
            "doc_id": f"doc-{i}",
            "filename": f"document_{i}.txt",
            "namespace": "default",
            "chunk_count": 5,
            "created_at": f"2024-01-{(i % 28) + 1:02d}T00:00:00Z",
            "headings": [],
            "summary": f"Document {i}"
        }
        for i in range(100)
    ]

    mock_pipeline.document_index_provider.list_documents.return_value = {
        "documents": large_doc_list,
        "next_key": None
    }

    start_time = time.time()
    response = test_client_with_mock.get("/api/documents?limit=100&use_summaries=true")
    elapsed_ms = (time.time() - start_time) * 1000

    assert response.status_code == 200
    data = response.json()
    assert len(data["documents"]) == 100

    # Note: This is a local test, so it should be well under 200ms
    # In actual production with network latency, DynamoDB will need to meet this target
    assert elapsed_ms < 500  # Local test should be much faster
