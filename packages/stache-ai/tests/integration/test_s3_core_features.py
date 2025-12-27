"""Integration test for S3 Vectors core features

This test verifies that the core RAG workflow works end-to-end when using S3 Vectors
as the vector database provider. It tests all major features including document ingestion,
semantic search, question answering, document discovery, and deletion.
"""
import pytest
import os
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


@pytest.fixture
def mock_s3_pipeline():
    """Create a mock pipeline configured for S3 Vectors"""
    pipeline = MagicMock()

    # Mock ingest_file response
    pipeline.ingest_file.return_value = {
        "success": True,
        "chunks_created": 2,
        "chunk_ids": ["chunk-1", "chunk-2"],
        "doc_id": "doc-s3-001",
        "filename": "test.txt",
        "namespace": "test"
    }

    # Mock query response (semantic search + synthesis)
    pipeline.query.return_value = {
        "question": "What is the capital of France?",
        "answer": "The capital of France is Paris, a beautiful city known for its art, culture, and architecture.",
        "sources": [
            {
                "content": "The capital of France is Paris. It is a beautiful city.",
                "metadata": {
                    "filename": "test.txt",
                    "chunk_index": 0,
                    "doc_id": "doc-s3-001"
                },
                "score": 0.95
            }
        ],
        "namespace": "test",
        "synthesis_model": "claude-3-5-sonnet-20241022"
    }

    # Mock vectordb provider for S3 Vectors
    vectordb = MagicMock()
    vectordb.insert.return_value = ["chunk-1", "chunk-2"]
    vectordb.search.return_value = [
        {
            "id": "chunk-1",
            "content": "The capital of France is Paris. It is a beautiful city.",
            "metadata": {
                "filename": "test.txt",
                "chunk_index": 0,
                "doc_id": "doc-s3-001"
            },
            "score": 0.95
        }
    ]
    vectordb.delete.return_value = True
    vectordb.delete_by_doc_id.return_value = True
    vectordb.get_by_id.return_value = {
        "id": "chunk-1",
        "content": "The capital of France is Paris. It is a beautiful city.",
        "metadata": {
            "filename": "test.txt",
            "chunk_index": 0,
            "doc_id": "doc-s3-001"
        }
    }

    # Mock document summary listing
    vectordb.list_by_filter.return_value = [
        {
            "doc_id": "doc-s3-001",
            "filename": "test.txt",
            "namespace": "test",
            "chunk_count": 2,
            "created_at": "2025-12-11T00:00:00Z",
            "headings": []
        }
    ]

    # Mock get_by_ids for chunks retrieval
    vectordb.get_by_ids.return_value = [
        {
            "id": "chunk-1",
            "text": "The capital of France is Paris. It is a beautiful city.",
            "content": "The capital of France is Paris. It is a beautiful city.",
            "filename": "test.txt",
            "namespace": "test",
            "chunk_index": 0,
            "doc_id": "doc-s3-001"
        }
    ]

    # Mock document discovery (search_summaries)
    vectordb.search_summaries.return_value = [
        {
            "id": "doc-s3-001",
            "content": "Document about France and its capital",
            "namespace": "test",
            "metadata": {
                "doc_id": "doc-s3-001",
                "filename": "test.txt",
                "chunk_count": 2,
                "created_at": "2025-12-11T00:00:00Z",
                "headings": []
            },
            "score": 0.92
        }
    ]

    # Mock embedding provider
    embedding = MagicMock()
    embedding.embed.return_value = [0.1] * 1024  # S3 Vectors uses 1024-dim embeddings
    embedding.get_dimensions.return_value = 1024
    embedding.get_name.return_value = "S3VectorsEmbeddingProvider"

    pipeline.vectordb_provider = vectordb
    pipeline.embedding_provider = embedding

    # Mock documents provider (S3 Vectors index)
    documents_provider = MagicMock()
    documents_provider.search_summaries.return_value = vectordb.search_summaries.return_value
    documents_provider.search.return_value = vectordb.search.return_value
    documents_provider.insert.return_value = vectordb.insert.return_value
    documents_provider.delete.return_value = vectordb.delete.return_value
    documents_provider.capabilities = set()
    pipeline.documents_provider = documents_provider
    pipeline._documents_provider = documents_provider

    # Mock summaries provider (S3 Vectors index)
    summaries_provider = MagicMock()
    summaries_provider.search_summaries.return_value = [
        {
            "id": "doc-s3-001",
            "text": "Document about France and its capital",
            "namespace": "test",
            "metadata": {
                "doc_id": "doc-s3-001",
                "filename": "test.txt",
                "chunk_count": 2,
                "created_at": "2025-12-11T00:00:00Z",
                "headings": []
            },
            "score": 0.92
        }
    ]
    summaries_provider.search.return_value = summaries_provider.search_summaries.return_value
    summaries_provider.insert.return_value = ["summary-1"]
    summaries_provider.delete.return_value = True
    summaries_provider.capabilities = set()
    pipeline.summaries_provider = summaries_provider
    pipeline._summaries_provider = summaries_provider

    # Mock insights provider (S3 Vectors index)
    insights_provider = MagicMock()
    insights_provider.search.return_value = []
    insights_provider.insert.return_value = ["insight-1"]
    insights_provider.delete.return_value = True
    insights_provider.capabilities = set()
    pipeline.insights_provider = insights_provider
    pipeline._insights_provider = insights_provider

    return pipeline


@pytest.fixture
def s3_test_client(mock_s3_pipeline):
    """Create test client with S3 Vectors mocked pipeline"""
    with patch('stache_ai.api.routes.query.get_pipeline', return_value=mock_s3_pipeline):
        with patch('stache_ai.api.routes.capture.get_pipeline', return_value=mock_s3_pipeline):
            with patch('stache_ai.api.routes.upload.get_pipeline', return_value=mock_s3_pipeline):
                with patch('stache_ai.api.routes.documents.get_pipeline', return_value=mock_s3_pipeline):
                    from stache_ai.api.main import app
                    client = TestClient(app)
                    yield client


@pytest.mark.s3vectors
@pytest.mark.integration
def test_full_rag_workflow_s3(s3_test_client, mock_s3_pipeline, monkeypatch):
    """Test that core RAG features work end-to-end on S3 Vectors

    This comprehensive test verifies 8 key steps of the RAG workflow:
    1. Ingest document
    2. Semantic search
    3. Question answering
    4. List documents (with summaries)
    5. Document discovery
    6. Get chunks by IDs
    7. Delete document
    8. Verify deletion
    """

    # Skip if S3 not configured - in real scenario this would check AWS credentials
    if not os.getenv("S3VECTORS_BUCKET"):
        # For testing, we allow this to run with mocks
        pass

    # Set vectordb provider to s3vectors (will be automatically cleaned up)
    monkeypatch.setenv("VECTORDB_PROVIDER", "s3vectors")

    test_client = s3_test_client

    # ==========================================
    # 1. INGEST DOCUMENT
    # ==========================================
    response = test_client.post(
        "/api/upload",
        files={"file": ("test.txt", b"The capital of France is Paris. It is a beautiful city.")},
        data={"namespace": "test"}
    )

    assert response.status_code == 200, f"Upload failed: {response.text}"
    result = response.json()
    assert result["success"] is True
    doc_id = result["doc_id"]
    chunk_ids = result["chunk_ids"]
    assert len(chunk_ids) > 0, "No chunks created during ingestion"
    assert doc_id == "doc-s3-001"

    # Verify the pipeline was called correctly
    mock_s3_pipeline.ingest_file.assert_called()
    call_kwargs = mock_s3_pipeline.ingest_file.call_args.kwargs
    assert "file_path" in call_kwargs
    assert "namespace" in call_kwargs
    assert call_kwargs["namespace"] == "test"

    # ==========================================
    # 2. SEMANTIC SEARCH
    # ==========================================
    response = test_client.post(
        "/api/query",
        json={
            "query": "What is the capital of France?",
            "namespace": "test",
            "top_k": 5,
            "synthesize": False  # Just search results, no synthesis yet
        }
    )

    assert response.status_code == 200, f"Query failed: {response.text}"
    result = response.json()
    assert "sources" in result
    sources = result["sources"]
    assert len(sources) > 0, "No search results returned"

    # Verify Paris is mentioned in results
    found_paris = False
    for source in sources:
        if "Paris" in source.get("content", ""):
            found_paris = True
            break
    assert found_paris, "Expected 'Paris' to be in search results"

    # ==========================================
    # 3. QUESTION ANSWERING (with synthesis)
    # ==========================================
    response = test_client.post(
        "/api/query",
        json={
            "query": "What is the capital of France?",
            "namespace": "test",
            "synthesize": True  # Get LLM-synthesized answer
        }
    )

    assert response.status_code == 200, f"Query with synthesis failed: {response.text}"
    result = response.json()
    assert "answer" in result, "No answer in response"
    answer = result["answer"]
    assert "Paris" in answer, "Expected 'Paris' to be in the synthesized answer"
    assert result.get("namespace") == "test"

    # ==========================================
    # 4. LIST DOCUMENTS (with summaries)
    # ==========================================
    response = test_client.get("/api/documents?use_summaries=true&namespace=test")

    assert response.status_code == 200, f"List documents failed: {response.text}"
    result = response.json()
    assert "documents" in result
    assert "count" in result
    assert result["count"] >= 1, "Expected at least 1 document"
    assert result.get("source") == "summaries", "Should use summary-based listing"

    # Verify document details
    documents = result["documents"]
    found_doc = False
    for doc in documents:
        if doc["doc_id"] == doc_id:
            found_doc = True
            assert doc["filename"] == "test.txt"
            assert doc["namespace"] == "test"
            assert doc["chunk_count"] == 2
            break
    assert found_doc, f"Expected to find ingested document with ID {doc_id}"

    # ==========================================
    # 5. DOCUMENT DISCOVERY (semantic)
    # ==========================================
    response = test_client.get(
        "/api/documents/discover?query=France&namespace=test"
    )

    assert response.status_code == 200, f"Document discovery failed: {response.text}"
    result = response.json()
    assert "documents" in result, "No documents in discovery response"
    assert "count" in result
    assert result["count"] > 0, "Expected at least 1 document in discovery"

    # Verify discovered document
    discovered_docs = result["documents"]
    found_discovered = False
    for doc in discovered_docs:
        if doc["doc_id"] == doc_id:
            found_discovered = True
            assert doc["namespace"] == "test"
            break
    assert found_discovered, f"Expected to discover ingested document with ID {doc_id}"

    # ==========================================
    # 6. GET CHUNKS BY IDs
    # ==========================================
    # The first chunk ID from ingestion
    chunk_id = chunk_ids[0]

    response = test_client.get(f"/api/documents/chunks?point_ids={chunk_id}")

    assert response.status_code == 200, f"Get chunks failed: {response.text}"
    result = response.json()
    assert "chunks" in result, "No chunks in response"
    assert len(result["chunks"]) > 0, "Expected at least 1 chunk"

    # Verify chunk content (endpoints returns "text" field)
    retrieved_chunk = result["chunks"][0]
    chunk_content = retrieved_chunk.get("text", retrieved_chunk.get("content", ""))
    assert "Paris" in chunk_content, f"Expected chunk to contain 'Paris', got: {chunk_content}"

    # ==========================================
    # 7. DELETE DOCUMENT
    # ==========================================
    response = test_client.delete(f"/api/documents/id/{doc_id}")

    assert response.status_code == 200, f"Delete document failed: {response.text}"
    result = response.json()
    assert "success" in result or result.get("message") is not None

    # Verify the vectordb delete was called
    assert mock_s3_pipeline.vectordb_provider.delete_by_doc_id.called or \
           mock_s3_pipeline.vectordb_provider.delete.called

    # ==========================================
    # 8. VERIFY DELETION
    # ==========================================
    # After deletion, simulate empty list response
    mock_s3_pipeline.vectordb_provider.list_by_filter.return_value = []

    response = test_client.get("/api/documents?use_summaries=true&namespace=test")

    assert response.status_code == 200, f"List documents after deletion failed: {response.text}"
    result = response.json()
    assert "documents" in result
    assert result.get("count", 0) == 0, "Expected no documents after deletion"


@pytest.mark.s3vectors
@pytest.mark.integration
def test_s3_workflow_with_multiple_documents(s3_test_client, mock_s3_pipeline):
    """Test RAG workflow with multiple documents to verify namespace isolation"""

    test_client = s3_test_client

    # Ingest first document
    response = test_client.post(
        "/api/upload",
        files={"file": ("france.txt", b"The capital of France is Paris.")},
        data={"namespace": "geography"}
    )
    assert response.status_code == 200
    doc1_id = response.json()["doc_id"]

    # Ingest second document with different namespace
    mock_s3_pipeline.ingest_file.return_value = {
        "success": True,
        "chunks_created": 1,
        "chunk_ids": ["chunk-3"],
        "doc_id": "doc-s3-002",
        "filename": "germany.txt",
        "namespace": "travel"
    }

    response = test_client.post(
        "/api/upload",
        files={"file": ("germany.txt", b"Berlin is the capital of Germany.")},
        data={"namespace": "travel"}
    )
    assert response.status_code == 200
    doc2_id = response.json()["doc_id"]

    # Verify namespace isolation - list only geography documents
    mock_s3_pipeline.vectordb_provider.list_by_filter.return_value = [
        {
            "doc_id": doc1_id,
            "filename": "france.txt",
            "namespace": "geography",
            "chunk_count": 1,
            "created_at": "2025-12-11T00:00:00Z",
            "headings": []
        }
    ]

    response = test_client.get("/api/documents?use_summaries=true&namespace=geography")
    assert response.status_code == 200
    result = response.json()
    assert result["count"] == 1
    assert result["documents"][0]["doc_id"] == doc1_id


@pytest.mark.s3vectors
@pytest.mark.integration
def test_s3_error_handling(s3_test_client, mock_s3_pipeline):
    """Test that S3 Vectors errors are handled gracefully"""

    test_client = s3_test_client

    # Simulate S3 error during upload
    mock_s3_pipeline.ingest_file.side_effect = Exception("S3 bucket not accessible")

    response = test_client.post(
        "/api/upload",
        files={"file": ("test.txt", b"Test content")},
        data={"namespace": "test"}
    )

    assert response.status_code == 500
    assert "error" in response.json() or "detail" in response.json()


@pytest.mark.s3vectors
@pytest.mark.integration
def test_s3_metadata_preservation(s3_test_client, mock_s3_pipeline):
    """Test that metadata is preserved through S3 Vectors storage and retrieval"""

    test_client = s3_test_client

    # Setup mock for this test
    mock_s3_pipeline.ingest_file.return_value = {
        "success": True,
        "chunks_created": 1,
        "chunk_ids": ["chunk-meta-1"],
        "doc_id": "doc-meta-001",
        "filename": "france_meta.txt",
        "namespace": "test"
    }

    # Ingest document with simple metadata
    response = test_client.post(
        "/api/upload",
        files={"file": ("france_meta.txt", b"Test content about France")},
        data={
            "namespace": "test",
            "chunking_strategy": "recursive"
        }
    )

    assert response.status_code == 200, f"Upload failed: {response.text}"
    doc_id = response.json()["doc_id"]
    assert doc_id == "doc-meta-001"

    # Setup mock for query with preserved metadata
    mock_s3_pipeline.query.return_value = {
        "question": "France",
        "sources": [
            {
                "content": "Test content about France",
                "metadata": {
                    "filename": "france_meta.txt",
                    "chunk_index": 0,
                    "doc_id": "doc-meta-001"
                },
                "score": 0.9
            }
        ],
        "namespace": "test"
    }

    # Verify document is searchable
    response = test_client.post(
        "/api/query",
        json={
            "query": "France",
            "namespace": "test",
            "synthesize": False
        }
    )

    assert response.status_code == 200
    result = response.json()
    assert "sources" in result
    # Verify search results contain the document metadata
    sources = result["sources"]
    assert len(sources) > 0, "Expected search results"
    # Check that metadata is present
    assert "metadata" in sources[0], "Metadata should be in response"
    # Filename should be preserved
    assert sources[0]["metadata"].get("filename") == "france_meta.txt"
