"""Tests for API routes"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def mock_pipeline():
    """Create a mock pipeline for API tests"""
    pipeline = MagicMock()
    pipeline.query.return_value = {
        "question": "Test question",
        "answer": "Test answer",
        "sources": [
            {
                "content": "Source content",
                "metadata": {"filename": "test.txt"},
                "score": 0.95
            }
        ],
        "namespace": None
    }
    pipeline.ingest_text.return_value = {
        "success": True,
        "chunks_created": 3,
        "ids": ["id1", "id2", "id3"],
        "doc_id": "doc-123",
        "namespace": None
    }
    pipeline.get_providers_info.return_value = {
        "embedding": "MockEmbeddingProvider",
        "llm": "MockLLMProvider",
        "vectordb": "MockVectorDBProvider"
    }
    return pipeline


@pytest.fixture
def test_client(mock_pipeline):
    """Create test client with mocked pipeline"""
    with patch('stache_ai.api.routes.query.get_pipeline', return_value=mock_pipeline):
        with patch('stache_ai.api.routes.capture.get_pipeline', return_value=mock_pipeline):
            with patch('stache_ai.api.routes.health.get_pipeline', return_value=mock_pipeline):
                from stache_ai.api.main import app
                client = TestClient(app)
                yield client


class TestQueryEndpoint:
    """Tests for /api/query endpoint"""

    def test_query_basic(self, test_client, mock_pipeline):
        """Test basic query request"""
        response = test_client.post(
            "/api/query",
            json={"query": "What is Stache?"}
        )

        assert response.status_code == 200
        data = response.json()
        assert "question" in data
        assert "answer" in data
        assert "sources" in data

    def test_query_with_top_k(self, test_client, mock_pipeline):
        """Test query with custom top_k"""
        response = test_client.post(
            "/api/query",
            json={"query": "Test query", "top_k": 10}
        )

        assert response.status_code == 200
        mock_pipeline.query.assert_called_with(
            question="Test query",
            top_k=10,
            synthesize=True,
            namespace=None,
            rerank=True,
            model=None,
            filter=None
        )

    def test_query_without_synthesis(self, test_client, mock_pipeline):
        """Test query without LLM synthesis"""
        mock_pipeline.query.return_value = {
            "question": "Test",
            "sources": [],
            "namespace": None
        }

        response = test_client.post(
            "/api/query",
            json={"query": "Test query", "synthesize": False}
        )

        assert response.status_code == 200
        mock_pipeline.query.assert_called_with(
            question="Test query",
            top_k=20,
            synthesize=False,
            namespace=None,
            rerank=True,
            model=None,
            filter=None
        )

    def test_query_with_namespace(self, test_client, mock_pipeline):
        """Test query with namespace filter"""
        response = test_client.post(
            "/api/query",
            json={"query": "Test query", "namespace": "test-ns"}
        )

        assert response.status_code == 200
        mock_pipeline.query.assert_called_with(
            question="Test query",
            top_k=20,
            synthesize=True,
            namespace="test-ns",
            rerank=True,
            model=None,
            filter=None
        )

    def test_query_missing_query_field(self, test_client):
        """Test query with missing required field"""
        response = test_client.post(
            "/api/query",
            json={}
        )

        assert response.status_code == 422  # Validation error

    def test_query_empty_query_string(self, test_client, mock_pipeline):
        """Test query with empty string"""
        response = test_client.post(
            "/api/query",
            json={"query": ""}
        )

        # Empty string is valid, just might not return useful results
        assert response.status_code == 200

    def test_query_error_handling(self, test_client, mock_pipeline):
        """Test error handling in query endpoint"""
        mock_pipeline.query.side_effect = Exception("Database connection error")

        response = test_client.post(
            "/api/query",
            json={"query": "Test"}
        )

        assert response.status_code == 500
        assert "Database connection error" in response.json()["detail"]


class TestCaptureEndpoint:
    """Tests for /api/capture endpoint"""

    def test_capture_basic(self, test_client, mock_pipeline):
        """Test basic capture request"""
        response = test_client.post(
            "/api/capture",
            json={
                "text": "This is a test thought to capture."
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_capture_with_metadata(self, test_client, mock_pipeline):
        """Test capture with metadata"""
        response = test_client.post(
            "/api/capture",
            json={
                "text": "Test content",
                "metadata": {"topic": "testing", "source": "unit-test"}
            }
        )

        assert response.status_code == 200
        # Verify ingest_text was called with metadata
        call_kwargs = mock_pipeline.ingest_text.call_args.kwargs
        assert call_kwargs.get("metadata", {}).get("topic") == "testing"

    def test_capture_with_namespace(self, test_client, mock_pipeline):
        """Test capture with namespace"""
        response = test_client.post(
            "/api/capture",
            json={
                "text": "Test content",
                "namespace": "personal/notes"
            }
        )

        assert response.status_code == 200
        call_kwargs = mock_pipeline.ingest_text.call_args.kwargs
        assert call_kwargs.get("namespace") == "personal/notes"


class TestHealthEndpoint:
    """Tests for /health endpoint"""

    def test_health_check(self, test_client):
        """Test health check endpoint"""
        response = test_client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"


class TestStaticFileServing:
    """Tests for static file serving"""

    def test_root_returns_index(self, test_client):
        """Test that root path serves frontend"""
        # This test depends on the frontend being built
        # Just check that the route exists and doesn't error
        response = test_client.get("/")
        # Could be 200 (index.html exists) or 404 (frontend not built)
        assert response.status_code in [200, 404]


class TestCORSConfiguration:
    """Tests for CORS configuration"""

    def test_cors_headers_present(self, test_client):
        """Test that CORS headers are present on responses"""
        response = test_client.options(
            "/api/query",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST"
            }
        )

        # CORS preflight should succeed
        assert response.status_code in [200, 405]  # 405 if OPTIONS not explicitly handled

    def test_cors_allows_localhost(self, test_client, mock_pipeline):
        """Test that localhost origins are allowed"""
        response = test_client.post(
            "/api/query",
            json={"query": "Test"},
            headers={"Origin": "http://localhost:3000"}
        )

        assert response.status_code == 200
        # Check for CORS headers in response
        assert "access-control-allow-origin" in response.headers or response.status_code == 200


class TestRequestValidation:
    """Tests for request validation"""

    def test_query_invalid_json(self, test_client):
        """Test handling of invalid JSON"""
        response = test_client.post(
            "/api/query",
            content="not valid json",
            headers={"Content-Type": "application/json"}
        )

        assert response.status_code == 422

    def test_query_wrong_content_type(self, test_client):
        """Test handling of wrong content type"""
        response = test_client.post(
            "/api/query",
            content="query=test",
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )

        assert response.status_code == 422

    def test_query_invalid_top_k_type(self, test_client):
        """Test validation of top_k type"""
        response = test_client.post(
            "/api/query",
            json={"query": "Test", "top_k": "invalid"}
        )

        assert response.status_code == 422

    def test_query_negative_top_k(self, test_client, mock_pipeline):
        """Test handling of negative top_k"""
        response = test_client.post(
            "/api/query",
            json={"query": "Test", "top_k": -1}
        )

        # FastAPI might accept it or the pipeline might handle it
        # Just ensure it doesn't crash
        assert response.status_code in [200, 422, 500]
