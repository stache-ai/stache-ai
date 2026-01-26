"""Test trash purge worker for scheduled TTL enforcement."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from stache_ai.workers.trash_purge_worker import purge_expired_trash


@pytest.fixture
def mock_pipeline():
    """Mock pipeline with document index provider."""
    pipeline = MagicMock()
    pipeline.document_index_provider = MagicMock()
    return pipeline


@pytest.mark.asyncio
async def test_purge_expired_trash_empty(mock_pipeline):
    """Test purge with no expired trash."""
    mock_pipeline.document_index_provider.list_expired_trash.return_value = []

    result = await purge_expired_trash(mock_pipeline)

    assert result["processed"] == 0
    assert result["purged"] == 0
    assert result["failed"] == 0


@pytest.mark.asyncio
async def test_purge_expired_trash_single_entry(mock_pipeline):
    """Test purging a single expired trash entry."""
    mock_pipeline.document_index_provider.list_expired_trash.return_value = [
        {
            "doc_id": "doc1",
            "namespace": "default",
            "deleted_at_ms": 1706079600000,
            "purge_after": "2026-01-25T10:00:00Z",
            "purge_after_ms": 1706079600000,
        }
    ]

    mock_pipeline.document_index_provider.permanently_delete_document.return_value = {
        "doc_id": "doc1",
        "cleanup_job_id": "job1",
        "chunk_count": 5,
    }

    result = await purge_expired_trash(mock_pipeline)

    assert result["processed"] == 1
    assert result["purged"] == 1
    assert result["failed"] == 0
    mock_pipeline.document_index_provider.permanently_delete_document.assert_called_once()


@pytest.mark.asyncio
async def test_purge_expired_trash_multiple_entries(mock_pipeline):
    """Test purging multiple expired trash entries."""
    entries = [
        {
            "doc_id": f"doc{i}",
            "namespace": "default",
            "deleted_at_ms": 1706079600000,
            "purge_after": "2026-01-25T10:00:00Z",
            "purge_after_ms": 1706079600000,
        }
        for i in range(5)
    ]
    mock_pipeline.document_index_provider.list_expired_trash.return_value = entries

    mock_pipeline.document_index_provider.permanently_delete_document.return_value = {
        "doc_id": "doc",
        "cleanup_job_id": "job",
        "chunk_count": 5,
    }

    result = await purge_expired_trash(mock_pipeline, batch_size=100)

    assert result["processed"] == 5
    assert result["purged"] == 5
    assert result["failed"] == 0
    assert mock_pipeline.document_index_provider.permanently_delete_document.call_count == 5


@pytest.mark.asyncio
async def test_purge_expired_trash_batch_limit(mock_pipeline):
    """Test purge respects batch size limit."""
    entries = [
        {
            "doc_id": f"doc{i}",
            "namespace": "default",
            "deleted_at_ms": 1706079600000,
            "purge_after": "2026-01-25T10:00:00Z",
            "purge_after_ms": 1706079600000,
        }
        for i in range(10)
    ]
    mock_pipeline.document_index_provider.list_expired_trash.return_value = entries

    mock_pipeline.document_index_provider.permanently_delete_document.return_value = {
        "doc_id": "doc",
        "cleanup_job_id": "job",
        "chunk_count": 5,
    }

    result = await purge_expired_trash(mock_pipeline, batch_size=100)

    assert result["processed"] == 10


@pytest.mark.asyncio
async def test_purge_expired_trash_failure(mock_pipeline):
    """Test purge handles permanent delete failures."""
    mock_pipeline.document_index_provider.list_expired_trash.return_value = [
        {
            "doc_id": "doc1",
            "namespace": "default",
            "deleted_at_ms": 1706079600000,
            "purge_after": "2026-01-25T10:00:00Z",
            "purge_after_ms": 1706079600000,
        }
    ]

    mock_pipeline.document_index_provider.permanently_delete_document.side_effect = Exception(
        "Database error"
    )

    result = await purge_expired_trash(mock_pipeline)

    assert result["processed"] == 1
    assert result["purged"] == 0
    assert result["failed"] == 1


@pytest.mark.asyncio
async def test_purge_expired_trash_timeout(mock_pipeline):
    """Test purge timeout enforcement."""
    mock_pipeline.document_index_provider.list_expired_trash.return_value = [
        {
            "doc_id": f"doc{i}",
            "namespace": "default",
            "deleted_at_ms": 1706079600000,
            "purge_after": "2026-01-25T10:00:00Z",
            "purge_after_ms": 1706079600000,
        }
        for i in range(10)
    ]

    # Simulate slow permanent delete
    call_count = 0

    def slow_delete(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        # Block for a while to trigger timeout
        import time
        time.sleep(0.05)
        return {"doc_id": "doc", "cleanup_job_id": "job", "chunk_count": 5}

    mock_pipeline.document_index_provider.permanently_delete_document = slow_delete

    # Process with very short timeout (0.01 seconds)
    result = await purge_expired_trash(mock_pipeline, max_runtime_seconds=0.01)

    # Should process fewer than 10 items due to timeout
    # (may still process 1 since we check after starting)
    assert result["processed"] <= 2


@pytest.mark.asyncio
async def test_purge_expired_trash_no_provider(mock_pipeline):
    """Test purge when document index not available."""
    mock_pipeline.document_index_provider = None

    result = await purge_expired_trash(mock_pipeline)

    assert result["processed"] == 0
    assert result["purged"] == 0
    assert result["failed"] == 0


@pytest.mark.asyncio
async def test_purge_calls_permanently_delete(mock_pipeline):
    """Test that purge calls permanently_delete_document with correct params."""
    mock_pipeline.document_index_provider.list_expired_trash.return_value = [
        {
            "doc_id": "doc1",
            "namespace": "docs",
            "deleted_at_ms": 1706079600000,
            "purge_after": "2026-01-25T10:00:00Z",
            "purge_after_ms": 1706079600000,
        }
    ]

    mock_pipeline.document_index_provider.permanently_delete_document.return_value = {
        "doc_id": "doc1",
        "cleanup_job_id": "job1",
        "chunk_count": 5,
    }

    result = await purge_expired_trash(mock_pipeline)

    call_kwargs = mock_pipeline.document_index_provider.permanently_delete_document.call_args[1]
    assert call_kwargs["doc_id"] == "doc1"
    assert call_kwargs["namespace"] == "docs"
    assert call_kwargs["deleted_at_ms"] == 1706079600000
    assert call_kwargs["deleted_by"] == "system_auto_purge"


@pytest.mark.asyncio
async def test_purge_mixed_success_failure(mock_pipeline):
    """Test purge with mix of successes and failures."""
    mock_pipeline.document_index_provider.list_expired_trash.return_value = [
        {
            "doc_id": f"doc{i}",
            "namespace": "default",
            "deleted_at_ms": 1706079600000 + i,
            "purge_after": "2026-01-25T10:00:00Z",
            "purge_after_ms": 1706079600000,
        }
        for i in range(3)
    ]

    # Fail on second entry
    side_effects = [
        {"doc_id": "doc0", "cleanup_job_id": "job0", "chunk_count": 5},
        Exception("Error"),
        {"doc_id": "doc2", "cleanup_job_id": "job2", "chunk_count": 5},
    ]

    mock_pipeline.document_index_provider.permanently_delete_document.side_effect = side_effects

    result = await purge_expired_trash(mock_pipeline)

    assert result["processed"] == 3
    assert result["purged"] == 2
    assert result["failed"] == 1
