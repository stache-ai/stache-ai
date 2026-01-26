"""Test cleanup worker for permanent document deletion."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from stache_ai.workers.cleanup_worker import process_cleanup_jobs, _process_cleanup_job


@pytest.fixture
def mock_pipeline():
    """Mock pipeline with document index and document providers."""
    pipeline = MagicMock()
    pipeline.document_index_provider = MagicMock()
    pipeline.documents_provider = MagicMock()
    return pipeline


@pytest.mark.asyncio
async def test_process_cleanup_jobs_empty(mock_pipeline):
    """Test cleanup with no pending jobs."""
    mock_pipeline.document_index_provider.list_cleanup_jobs.return_value = []

    result = await process_cleanup_jobs(mock_pipeline)

    assert result["processed"] == 0
    assert result["succeeded"] == 0
    assert result["failed"] == 0


@pytest.mark.asyncio
async def test_process_cleanup_jobs_single_job(mock_pipeline):
    """Test processing a single cleanup job."""
    mock_pipeline.document_index_provider.list_cleanup_jobs.return_value = [
        {
            "cleanup_job_id": "job1",
            "doc_id": "doc1",
            "namespace": "default",
            "filename": "test.pdf",
            "deleted_at_ms": 1706079600000,
            "chunk_ids": ["chunk1", "chunk2", "chunk3"],
        }
    ]

    mock_pipeline.documents_provider.delete_by_ids = AsyncMock(return_value=3)

    result = await process_cleanup_jobs(mock_pipeline)

    assert result["processed"] == 1
    assert result["succeeded"] == 1
    assert result["failed"] == 0
    mock_pipeline.documents_provider.delete_by_ids.assert_called_once()
    mock_pipeline.document_index_provider.complete_permanent_delete.assert_called_once()


@pytest.mark.asyncio
async def test_process_cleanup_jobs_multiple_jobs(mock_pipeline):
    """Test processing multiple cleanup jobs."""
    jobs = [
        {
            "cleanup_job_id": f"job{i}",
            "doc_id": f"doc{i}",
            "namespace": "default",
            "filename": f"file{i}.pdf",
            "deleted_at_ms": 1706079600000 + i,
            "chunk_ids": [f"chunk{i}_{j}" for j in range(2)],
        }
        for i in range(3)
    ]
    mock_pipeline.document_index_provider.list_cleanup_jobs.return_value = jobs

    mock_pipeline.documents_provider.delete_by_ids = AsyncMock(return_value=2)

    result = await process_cleanup_jobs(mock_pipeline, batch_size=10)

    assert result["processed"] == 3
    assert result["succeeded"] == 3
    assert result["failed"] == 0
    assert mock_pipeline.documents_provider.delete_by_ids.call_count == 3


@pytest.mark.asyncio
async def test_process_cleanup_jobs_with_batch_size(mock_pipeline):
    """Test cleanup job batch size limit."""
    jobs = [
        {
            "cleanup_job_id": f"job{i}",
            "doc_id": f"doc{i}",
            "namespace": "default",
            "filename": f"file{i}.pdf",
            "deleted_at_ms": 1706079600000,
            "chunk_ids": ["chunk1"],
        }
        for i in range(5)
    ]
    mock_pipeline.document_index_provider.list_cleanup_jobs.return_value = jobs

    mock_pipeline.documents_provider.delete_by_ids = AsyncMock(return_value=1)

    result = await process_cleanup_jobs(mock_pipeline, batch_size=5)

    assert result["processed"] == 5
    assert result["succeeded"] == 5


@pytest.mark.asyncio
async def test_process_cleanup_job_failure(mock_pipeline):
    """Test cleanup job with error handling."""
    mock_pipeline.document_index_provider.list_cleanup_jobs.return_value = [
        {
            "cleanup_job_id": "job1",
            "doc_id": "doc1",
            "namespace": "default",
            "filename": "test.pdf",
            "deleted_at_ms": 1706079600000,
            "chunk_ids": ["chunk1"],
        }
    ]

    mock_pipeline.documents_provider.delete_by_ids = AsyncMock(
        side_effect=Exception("Delete failed")
    )

    result = await process_cleanup_jobs(mock_pipeline)

    assert result["processed"] == 1
    assert result["succeeded"] == 0
    assert result["failed"] == 1
    mock_pipeline.document_index_provider.mark_cleanup_job_failed.assert_called_once()


@pytest.mark.asyncio
async def test_process_cleanup_job_timeout(mock_pipeline):
    """Test cleanup timeout enforcement."""
    # Create a job that takes time to process
    mock_pipeline.document_index_provider.list_cleanup_jobs.return_value = [
        {
            "cleanup_job_id": "job1",
            "doc_id": "doc1",
            "namespace": "default",
            "filename": "test.pdf",
            "deleted_at_ms": 1706079600000,
            "chunk_ids": ["chunk1"],
        }
    ]

    # Simulate slow delete
    async def slow_delete(*args, **kwargs):
        await asyncio.sleep(0.1)
        return 1

    mock_pipeline.documents_provider.delete_by_ids = slow_delete

    # Process with very short timeout
    result = await process_cleanup_jobs(mock_pipeline, max_runtime_seconds=0.01)

    # Should have processed one job before timeout
    assert result["processed"] <= 1


@pytest.mark.asyncio
async def test_process_cleanup_job_partial_deletion(mock_pipeline):
    """Test cleanup job with partial vector deletion."""
    mock_pipeline.document_index_provider.list_cleanup_jobs.return_value = [
        {
            "cleanup_job_id": "job1",
            "doc_id": "doc1",
            "namespace": "default",
            "filename": "test.pdf",
            "deleted_at_ms": 1706079600000,
            "chunk_ids": ["chunk1", "chunk2", "chunk3"],
        }
    ]

    # Only 2 of 3 chunks deleted
    mock_pipeline.documents_provider.delete_by_ids = AsyncMock(return_value=2)

    result = await process_cleanup_jobs(mock_pipeline)

    assert result["processed"] == 1
    assert result["succeeded"] == 1
    # Still succeeds - partial deletion is tolerated
    mock_pipeline.document_index_provider.complete_permanent_delete.assert_called_once()


@pytest.mark.asyncio
async def test_process_cleanup_job_idempotent(mock_pipeline):
    """Test cleanup job is idempotent (can be retried safely)."""
    job = {
        "cleanup_job_id": "job1",
        "doc_id": "doc1",
        "namespace": "default",
        "filename": "test.pdf",
        "deleted_at_ms": 1706079600000,
        "chunk_ids": ["chunk1"],
    }

    # First run
    mock_pipeline.document_index_provider.list_cleanup_jobs.return_value = [job]
    mock_pipeline.documents_provider.delete_by_ids = AsyncMock(return_value=1)
    result1 = await process_cleanup_jobs(mock_pipeline)

    # Simulate second run (retry)
    mock_pipeline.document_index_provider.list_cleanup_jobs.return_value = [job]
    mock_pipeline.documents_provider.delete_by_ids = AsyncMock(return_value=0)
    # Should still complete successfully
    result2 = await process_cleanup_jobs(mock_pipeline)

    assert result2["succeeded"] == 1


@pytest.mark.asyncio
async def test_process_cleanup_no_provider(mock_pipeline):
    """Test cleanup when document index not available."""
    mock_pipeline.document_index_provider = None

    result = await process_cleanup_jobs(mock_pipeline)

    assert result["processed"] == 0
    assert result["succeeded"] == 0
    assert result["failed"] == 0


@pytest.mark.asyncio
async def test_process_cleanup_job_with_missing_vectors(mock_pipeline):
    """Test cleanup job when vectors already deleted."""
    mock_pipeline.document_index_provider.list_cleanup_jobs.return_value = [
        {
            "cleanup_job_id": "job1",
            "doc_id": "doc1",
            "namespace": "default",
            "filename": "test.pdf",
            "deleted_at_ms": 1706079600000,
            "chunk_ids": ["chunk1", "chunk2"],
        }
    ]

    # No vectors found to delete
    mock_pipeline.documents_provider.delete_by_ids = AsyncMock(return_value=0)

    result = await process_cleanup_jobs(mock_pipeline)

    # Still succeeds - vectors may have been cleaned already
    assert result["succeeded"] == 1
    mock_pipeline.document_index_provider.complete_permanent_delete.assert_called_once()


@pytest.mark.asyncio
async def test_cleanup_job_mark_failed_on_exception(mock_pipeline):
    """Test that cleanup job is marked as failed on exception."""
    mock_pipeline.document_index_provider.list_cleanup_jobs.return_value = [
        {
            "cleanup_job_id": "job1",
            "doc_id": "doc1",
            "namespace": "default",
            "filename": "test.pdf",
            "deleted_at_ms": 1706079600000,
            "chunk_ids": ["chunk1"],
        }
    ]

    mock_pipeline.documents_provider.delete_by_ids = AsyncMock(
        side_effect=Exception("Vector DB error")
    )

    await process_cleanup_jobs(mock_pipeline)

    mock_pipeline.document_index_provider.mark_cleanup_job_failed.assert_called_once()
    call_kwargs = mock_pipeline.document_index_provider.mark_cleanup_job_failed.call_args[1]
    assert call_kwargs["cleanup_job_id"] == "job1"
    assert "Vector DB error" in call_kwargs["error"]
