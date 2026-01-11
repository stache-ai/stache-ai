"""Pytest fixtures for middleware tests"""

from unittest.mock import MagicMock, AsyncMock
import pytest

from stache_ai.middleware.base import PostIngestProcessor, StorageResult
from stache_ai.middleware.results import PostIngestResult
from stache_ai.middleware.context import RequestContext


class MockPostIngestProcessor(PostIngestProcessor):
    """Mock PostIngestProcessor for testing"""

    def __init__(self, action="allow", artifacts=None, reason=None):
        self._action = action
        self._artifacts = artifacts or {}
        self._reason = reason
        self.calls = []

    async def process(self, chunks, storage_result, context):
        """Record call and return configured result"""
        self.calls.append({
            "chunks": chunks,
            "storage_result": storage_result,
            "context": context
        })
        return PostIngestResult(
            action=self._action,
            artifacts=self._artifacts,
            reason=self._reason
        )


@pytest.fixture
def mock_postingest_processor():
    """Create a mock PostIngestProcessor for testing"""
    return MockPostIngestProcessor()


@pytest.fixture
def mock_storage_result():
    """Create a mock StorageResult for testing"""
    return StorageResult(
        vector_ids=["vec-1", "vec-2", "vec-3"],
        namespace="test-namespace",
        index="test-index",
        doc_id="doc-123",
        chunk_count=3,
        embedding_model="test-model"
    )


@pytest.fixture
def mock_embedding_provider():
    """Mock embedding provider for tests"""
    provider = MagicMock()
    # embed() returns a list of embeddings (one per input text)
    provider.embed.return_value = [[0.1] * 1024]
    provider.embed_batch.return_value = [[0.1] * 1024, [0.2] * 1024]
    provider.get_dimensions.return_value = 1024
    provider.get_name.return_value = "MockEmbeddingProvider"
    return provider


@pytest.fixture
def mock_summaries_provider():
    """Mock summaries vector provider for tests"""
    provider = MagicMock()
    provider.insert.return_value = ["summary-1"]
    provider.search.return_value = []
    provider.delete.return_value = True
    provider.get_name.return_value = "MockSummariesProvider"
    provider.capabilities = set()
    return provider


@pytest.fixture
def mock_config():
    """Mock config for tests"""
    config = MagicMock()
    config.enable_summary_generation = True
    config.chunk_size = 500
    config.chunk_overlap = 50
    return config


@pytest.fixture
def sample_chunks():
    """Sample chunks for testing"""
    return [
        (
            "# Introduction\n\nThis is the introduction to the document.",
            {
                "filename": "test.md",
                "chunk_index": 0,
                "namespace": "test-namespace",
                "created_at": "2026-01-11T00:00:00Z",
                "headings": ["Introduction"]
            }
        ),
        (
            "## Section 1\n\nThis is the first section with more content.",
            {
                "filename": "test.md",
                "chunk_index": 1,
                "namespace": "test-namespace",
                "created_at": "2026-01-11T00:00:00Z",
                "headings": ["Introduction", "Section 1"]
            }
        ),
        (
            "## Section 2\n\nThis is the second section.",
            {
                "filename": "test.md",
                "chunk_index": 2,
                "namespace": "test-namespace",
                "created_at": "2026-01-11T00:00:00Z",
                "headings": ["Introduction", "Section 2"]
            }
        )
    ]
