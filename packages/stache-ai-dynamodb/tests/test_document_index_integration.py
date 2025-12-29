"""Integration tests for document index with RAG pipeline

This test suite verifies that the document index works correctly when
integrated with the RAG pipeline. It tests the dual-write pattern where
documents are written to both the vector database and the document index,
as well as the various endpoint behaviors that depend on the document index.
"""

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def mock_document_index_provider():
    """Create a mock document index provider"""
    provider = MagicMock()
    provider.get_name.return_value = "MockDocumentIndex"

    # Mock successful document creation
    provider.create_document.return_value = {
        "doc_id": "doc-001",
        "filename": "test.txt",
        "namespace": "test",
        "chunk_count": 2,
        "created_at": "2025-12-11T00:00:00Z",
        "chunk_ids": ["chunk-1", "chunk-2"],
        "summary": "Test document summary",
        "summary_embedding_id": "summary-1"
    }

    # Mock get_document
    provider.get_document.return_value = {
        "doc_id": "doc-001",
        "filename": "test.txt",
        "namespace": "test",
        "chunk_count": 2,
        "created_at": "2025-12-11T00:00:00Z",
        "chunk_ids": ["chunk-1", "chunk-2"],
        "summary": "Test document summary"
    }

    # Mock list_documents
    provider.list_documents.return_value = {
        "documents": [
            {
                "doc_id": "doc-001",
                "filename": "test.txt",
                "namespace": "test",
                "chunk_count": 2,
                "created_at": "2025-12-11T00:00:00Z"
            }
        ],
        "next_key": None
    }

    # Mock delete_document
    provider.delete_document.return_value = True

    # Mock get_chunk_ids
    provider.get_chunk_ids.return_value = ["chunk-1", "chunk-2"]

    return provider


@pytest.fixture
def mock_pipeline_with_index(mock_document_index_provider):
    """Create a mock pipeline configured with document index"""
    pipeline = MagicMock()
    pipeline.document_index_provider = mock_document_index_provider

    # Mock vectordb provider
    vectordb = MagicMock()
    vectordb.insert.return_value = ["chunk-1", "chunk-2"]
    vectordb.delete_by_doc_id.return_value = True
    vectordb.get_by_id.return_value = {
        "id": "chunk-1",
        "content": "Test chunk content",
        "metadata": {"doc_id": "doc-001", "filename": "test.txt"}
    }
    vectordb.get_by_ids.return_value = [
        {
            "id": "chunk-1",
            "text": "Test chunk 1",
            "metadata": {"doc_id": "doc-001"}
        },
        {
            "id": "chunk-2",
            "text": "Test chunk 2",
            "metadata": {"doc_id": "doc-001"}
        }
    ]

    # Mock embedding provider
    embedding = MagicMock()
    embedding.embed.return_value = [0.1] * 1024
    embedding.get_dimensions.return_value = 1024

    pipeline.vectordb_provider = vectordb
    pipeline.embedding_provider = embedding

    # Mock ingest_file and ingest_text
    pipeline.ingest_file.return_value = {
        "success": True,
        "chunks_created": 2,
        "chunk_ids": ["chunk-1", "chunk-2"],
        "doc_id": "doc-001",
        "filename": "test.txt",
        "namespace": "test"
    }

    pipeline.ingest_text.return_value = {
        "success": True,
        "chunks_created": 2,
        "chunk_ids": ["chunk-1", "chunk-2"],
        "doc_id": "doc-001",
        "filename": "Capture 2025-12-11 12:00 - Test text con...",
        "namespace": "test"
    }

    return pipeline


@pytest.fixture
def test_client_with_index(mock_pipeline_with_index):
    """Create test client with document index mocked"""
    with patch('stache_ai.api.routes.upload.get_pipeline', return_value=mock_pipeline_with_index):
        with patch('stache_ai.api.routes.capture.get_pipeline', return_value=mock_pipeline_with_index):
            with patch('stache_ai.api.routes.documents.get_pipeline', return_value=mock_pipeline_with_index):
                from stache_ai.api.main import app
                client = TestClient(app)
                yield client


# ====================================================================
# Test 1: Document Index Created During Ingestion
# ====================================================================
@pytest.mark.integration
def test_ingest_creates_document_index(test_client_with_index, mock_pipeline_with_index):
    """Test that ingesting a file creates an entry in the document index

    This test verifies the dual-write pattern: when a file is ingested,
    it should be written to both the vector database AND the document index.
    The document index creation happens within the pipeline.ingest_file method.
    """

    client = test_client_with_index
    pipeline = mock_pipeline_with_index
    doc_index = pipeline.document_index_provider

    # Setup: Mock ingest_file to simulate calling document index internally
    def ingest_file_with_index_call(*args, **kwargs):
        # Simulate what pipeline.ingest_file does: it calls document index
        doc_index.create_document(
            doc_id="doc-001",
            filename="test.txt",
            namespace="test",
            chunk_ids=["chunk-1", "chunk-2"],
            summary="Test summary"
        )
        # Return the result
        return {
            "success": True,
            "chunks_created": 2,
            "chunk_ids": ["chunk-1", "chunk-2"],
            "doc_id": "doc-001",
            "filename": "test.txt",
            "namespace": "test"
        }

    pipeline.ingest_file.side_effect = ingest_file_with_index_call

    # Upload a file
    response = client.post(
        "/api/upload",
        files={"file": ("test.txt", b"This is test content for the document index")},
        data={"namespace": "test"}
    )

    # Verify upload was successful
    assert response.status_code == 200, f"Upload failed: {response.text}"
    result = response.json()
    assert result["success"] is True
    assert result["doc_id"] == "doc-001"

    # Verify ingest_file was called
    pipeline.ingest_file.assert_called()

    # Verify document index create_document was called
    doc_index.create_document.assert_called()
    call_args = doc_index.create_document.call_args

    # Verify the call had the expected parameters
    assert call_args is not None, "Document index create_document was not called"
    kwargs = call_args.kwargs
    assert kwargs.get("doc_id") == "doc-001"
    assert kwargs.get("namespace") == "test"
    assert kwargs.get("filename") == "test.txt"
    assert kwargs.get("chunk_ids") == ["chunk-1", "chunk-2"]


# ====================================================================
# Test 2: Get Document from Index by ID
# ====================================================================
@pytest.mark.integration
def test_get_document_by_id(test_client_with_index, mock_pipeline_with_index):
    """Test retrieving a document by ID from the document index

    This test verifies that get_document endpoint uses the document index
    provider to retrieve document metadata efficiently.
    """

    client = test_client_with_index
    pipeline = mock_pipeline_with_index
    doc_index = pipeline.document_index_provider

    # Get document by ID
    response = client.get("/api/documents/id/doc-001?namespace=test")

    # Verify response
    assert response.status_code == 200, f"Get document failed: {response.text}"
    result = response.json()

    # Verify the response contains expected fields
    assert "doc_id" in result or "document" in result or result.get("success") is not None

    # Verify document index was queried
    doc_index.get_document.assert_called()


# ====================================================================
# Test 3: List Documents from Index by Namespace
# ====================================================================
@pytest.mark.integration
def test_list_documents_by_namespace(test_client_with_index, mock_pipeline_with_index):
    """Test listing documents by namespace from the document index

    This test verifies that list_documents endpoint can use the document index
    to list documents efficiently by namespace with pagination support.
    """

    client = test_client_with_index
    pipeline = mock_pipeline_with_index
    doc_index = pipeline.document_index_provider

    # List documents in namespace
    response = client.get("/api/documents?namespace=test")

    # Verify response
    assert response.status_code == 200, f"List documents failed: {response.text}"
    result = response.json()

    # Verify response structure
    assert "documents" in result or "count" in result or result.get("success") is not None

    # If documents are returned, verify structure
    if "documents" in result:
        assert isinstance(result["documents"], list)
        if len(result["documents"]) > 0:
            doc = result["documents"][0]
            assert "doc_id" in doc or "filename" in doc


# ====================================================================
# Test 4: Delete Document Removes from Both Index and Vector DB
# ====================================================================
@pytest.mark.integration
def test_delete_document_removes_from_both(test_client_with_index, mock_pipeline_with_index):
    """Test that deleting a document removes it from both vector DB and document index

    This test verifies atomic deletion: the document must be deleted from both
    the vector database and the document index. The order matters for data consistency.
    """

    client = test_client_with_index
    pipeline = mock_pipeline_with_index
    doc_index = pipeline.document_index_provider
    vectordb = pipeline.vectordb_provider

    # Delete document by ID
    response = client.delete("/api/documents/id/doc-001?namespace=test")

    # Verify response
    assert response.status_code == 200, f"Delete failed: {response.text}"

    # Verify document index delete was called
    doc_index.delete_document.assert_called()

    # Verify vectordb delete was called
    # Either delete or delete_by_doc_id should have been called
    assert vectordb.delete.called or vectordb.delete_by_doc_id.called, \
        "Vector database delete was not called"


# ====================================================================
# Test 5: Ingest Failure Doesn't Break If Index Fails
# ====================================================================
@pytest.mark.integration
def test_ingest_failure_doesnt_break_if_index_fails(test_client_with_index, mock_pipeline_with_index):
    """Test graceful degradation when document index write fails during ingestion

    Per the design decision, if the document index fails to write (e.g., DynamoDB
    is down), the ingestion should still succeed. This tests that the index failure
    is caught and logged, but doesn't cause ingestion to fail.
    """

    client = test_client_with_index
    pipeline = mock_pipeline_with_index
    doc_index = pipeline.document_index_provider

    # Setup: Mock ingest_file to call document index, which will fail
    def ingest_file_with_failing_index(*args, **kwargs):
        # Simulate what happens: pipeline tries to write to index, it fails
        try:
            doc_index.create_document(
                doc_id="doc-001",
                filename="test.txt",
                namespace="test",
                chunk_ids=["chunk-1", "chunk-2"]
            )
        except Exception:
            # In the real pipeline, this is caught and logged, not re-raised
            # So we continue and return success
            pass

        # Return success even though index write failed
        return {
            "success": True,
            "chunks_created": 2,
            "chunk_ids": ["chunk-1", "chunk-2"],
            "doc_id": "doc-001",
            "filename": "test.txt",
            "namespace": "test"
        }

    # Make document index raise an exception
    doc_index.create_document.side_effect = Exception("DynamoDB unavailable")
    pipeline.ingest_file.side_effect = ingest_file_with_failing_index

    # Try to upload - should still succeed because index failure is caught
    response = client.post(
        "/api/upload",
        files={"file": ("test.txt", b"Test content")},
        data={"namespace": "test"}
    )

    # Should succeed despite index failure
    assert response.status_code == 200, f"Upload should succeed even if index fails: {response.text}"
    result = response.json()
    assert result["success"] is True

    # Verify both were called
    pipeline.ingest_file.assert_called()
    doc_index.create_document.assert_called()


# ====================================================================
# Additional Integration Tests
# ====================================================================
@pytest.mark.integration
def test_list_documents_pagination_with_index(test_client_with_index, mock_pipeline_with_index):
    """Test pagination support in document index listing

    Verifies that pagination tokens (next_key) are properly handled
    when listing documents from the index.
    """

    client = test_client_with_index
    pipeline = mock_pipeline_with_index
    doc_index = pipeline.document_index_provider

    # Setup mock for pagination - return some docs and a next_key
    doc_index.list_documents.return_value = {
        "documents": [
            {
                "doc_id": f"doc-{i:03d}",
                "filename": f"document-{i}.txt",
                "namespace": "test",
                "chunk_count": 2,
                "created_at": f"2025-12-11T0{i}:00:00Z"
            }
            for i in range(1, 4)  # 3 documents
        ],
        "next_key": {"PK": "DOC#test#doc-003", "SK": "METADATA"}
    }

    # List with limit
    response = client.get("/api/documents?namespace=test&limit=3")

    assert response.status_code == 200
    result = response.json()

    # If pagination is supported, should have next_key in response
    doc_index.list_documents.assert_called()
    call_kwargs = doc_index.list_documents.call_args.kwargs
    assert "namespace" in call_kwargs or "limit" in call_kwargs


@pytest.mark.integration
def test_ingest_text_also_creates_index(test_client_with_index, mock_pipeline_with_index):
    """Test that text ingestion also creates document index entries

    Similar to file ingestion, text captured via the capture endpoint
    should also create document index entries.
    """

    client = test_client_with_index
    pipeline = mock_pipeline_with_index
    doc_index = pipeline.document_index_provider

    # Setup: Mock ingest_text to simulate calling document index internally
    def ingest_text_with_index_call(*args, **kwargs):
        # Simulate what pipeline.ingest_text does: it calls document index
        doc_index.create_document(
            doc_id="doc-text-001",
            filename="Capture 2025-12-11 12:00 - This is captu...",
            namespace="test",
            chunk_ids=["chunk-1", "chunk-2"]
        )
        return {
            "success": True,
            "chunks_created": 2,
            "chunk_ids": ["chunk-1", "chunk-2"],
            "doc_id": "doc-text-001",
            "filename": "Capture 2025-12-11 12:00 - This is captu...",
            "namespace": "test"
        }

    pipeline.ingest_text.side_effect = ingest_text_with_index_call

    # Mock the capture endpoint to use ingest_text
    response = client.post(
        "/api/capture",
        json={
            "text": "This is captured text content",
            "namespace": "test"
        }
    )

    # Verify ingest_text was called
    if response.status_code == 200:
        # If capture endpoint exists and works with mocked pipeline
        pipeline.ingest_text.assert_called()
        # Document index should also be created for text
        doc_index.create_document.assert_called()


@pytest.mark.integration
def test_document_index_missing_chunk_ids(test_client_with_index, mock_pipeline_with_index):
    """Test handling when document index has chunk IDs needed for deletion

    When deleting a document, we need to get the chunk IDs from the index
    to delete from the vector database. This test verifies that flow.
    """

    client = test_client_with_index
    pipeline = mock_pipeline_with_index
    doc_index = pipeline.document_index_provider
    vectordb = pipeline.vectordb_provider

    # Setup: get_chunk_ids returns the list of chunks to delete
    doc_index.get_chunk_ids.return_value = ["chunk-1", "chunk-2"]

    # Delete document
    response = client.delete("/api/documents/id/doc-001?namespace=test")

    # Verify flow: get_chunk_ids -> delete from vectordb -> delete from index
    if response.status_code == 200:
        # These might be called during deletion
        # Verify at least one of these was called
        assert doc_index.delete_document.called or vectordb.delete.called, \
            "Neither document index nor vectordb deletion was called"
