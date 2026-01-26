"""Tests for ReingestRecoveryProcessor middleware."""
import pytest
from unittest.mock import AsyncMock, Mock
from datetime import datetime, timezone

from stache_ai.middleware.error_processors.reingest_recovery import ReingestRecoveryProcessor
from stache_ai.middleware.context import RequestContext


@pytest.fixture
def mock_document_index():
    """Create mock document index provider."""
    return Mock()


@pytest.fixture
def mock_vectordb():
    """Create mock vectordb provider."""
    mock = Mock()
    mock.update_status = AsyncMock()
    return mock


@pytest.fixture
def context(mock_document_index, mock_vectordb):
    """Create request context with providers."""
    ctx = RequestContext(
        request_id="test-123",
        timestamp=datetime.now(timezone.utc),
        namespace="test-ns",
        source="api"
    )
    ctx.custom["document_index"] = mock_document_index
    ctx.custom["vectordb"] = mock_vectordb
    return ctx


@pytest.mark.asyncio
async def test_processor_restores_old_version_on_error(context, mock_document_index, mock_vectordb):
    """Test processor restores old document when REINGEST_VERSION fails."""
    exception = Exception("Ingestion failed")
    partial_state = {
        "metadata": {
            "_previous_doc_id": "old-doc-123",
            "_deleted_at_ms": 1234567890,
        },
        "doc_id": "new-doc-456",
        "namespace": "test-ns",
        "vectors_inserted": False,
        "chunk_ids": [],
    }

    # Mock restore response
    mock_document_index.restore_document.return_value = {
        "doc_id": "old-doc-123",
        "chunk_ids": ["chunk-1", "chunk-2", "chunk-3"],
        "chunk_count": 3,
    }

    processor = ReingestRecoveryProcessor()
    result = await processor.on_error(exception, context, partial_state)

    assert result.handled is True
    assert result.metadata["restored_doc_id"] == "old-doc-123"
    assert result.metadata["chunks_restored"] == 3

    # Verify restore was called
    mock_document_index.restore_document.assert_called_once_with(
        doc_id="old-doc-123",
        namespace="test-ns",
        deleted_at_ms=1234567890,
        restored_by="system_auto_recovery"
    )

    # Verify vector status update
    mock_vectordb.update_status.assert_called_once_with(
        ids=["chunk-1", "chunk-2", "chunk-3"],
        namespace="test-ns",
        status="active"
    )


@pytest.mark.asyncio
async def test_processor_handles_vector_restore_failure(context, mock_document_index, mock_vectordb):
    """Test processor continues if vector status update fails."""
    exception = Exception("Ingestion failed")
    partial_state = {
        "metadata": {
            "_previous_doc_id": "old-doc-123",
            "_deleted_at_ms": 1234567890,
        },
        "doc_id": "new-doc-456",
        "namespace": "test-ns",
    }

    # Mock restore response
    mock_document_index.restore_document.return_value = {
        "doc_id": "old-doc-123",
        "chunk_ids": ["chunk-1"],
        "chunk_count": 1,
    }

    # Mock vector update failure
    mock_vectordb.update_status.side_effect = Exception("Vector update failed")

    processor = ReingestRecoveryProcessor()
    result = await processor.on_error(exception, context, partial_state)

    # Should still be handled (restore succeeded)
    assert result.handled is True
    assert result.metadata["restored_doc_id"] == "old-doc-123"


@pytest.mark.asyncio
async def test_processor_returns_unhandled_for_normal_ingestion(context):
    """Test processor returns unhandled when not REINGEST_VERSION."""
    exception = Exception("Some other error")
    partial_state = {
        "metadata": {},  # No _previous_doc_id
        "doc_id": "doc-123",
        "namespace": "test-ns",
    }

    processor = ReingestRecoveryProcessor()
    result = await processor.on_error(exception, context, partial_state)

    assert result.handled is False
    assert result.metadata is None


@pytest.mark.asyncio
async def test_processor_returns_unhandled_when_no_document_index(context):
    """Test processor returns unhandled when document_index not available."""
    exception = Exception("Ingestion failed")
    partial_state = {
        "metadata": {
            "_previous_doc_id": "old-doc-123",
            "_deleted_at_ms": 1234567890,
        },
        "doc_id": "new-doc-456",
        "namespace": "test-ns",
    }

    # Remove document_index from context
    context.custom["document_index"] = None

    processor = ReingestRecoveryProcessor()
    result = await processor.on_error(exception, context, partial_state)

    assert result.handled is False


@pytest.mark.asyncio
async def test_processor_returns_unhandled_on_restore_failure(context, mock_document_index):
    """Test processor returns unhandled if restore itself fails."""
    exception = Exception("Ingestion failed")
    partial_state = {
        "metadata": {
            "_previous_doc_id": "old-doc-123",
            "_deleted_at_ms": 1234567890,
        },
        "doc_id": "new-doc-456",
        "namespace": "test-ns",
    }

    # Mock restore failure
    mock_document_index.restore_document.side_effect = Exception("Restore failed")

    processor = ReingestRecoveryProcessor()
    result = await processor.on_error(exception, context, partial_state)

    assert result.handled is False


@pytest.mark.asyncio
async def test_processor_handles_no_chunk_ids(context, mock_document_index, mock_vectordb):
    """Test processor handles case where restored doc has no chunk_ids."""
    exception = Exception("Ingestion failed")
    partial_state = {
        "metadata": {
            "_previous_doc_id": "old-doc-123",
            "_deleted_at_ms": 1234567890,
        },
        "doc_id": "new-doc-456",
        "namespace": "test-ns",
    }

    # Mock restore response with empty chunk_ids
    mock_document_index.restore_document.return_value = {
        "doc_id": "old-doc-123",
        "chunk_ids": [],
        "chunk_count": 0,
    }

    processor = ReingestRecoveryProcessor()
    result = await processor.on_error(exception, context, partial_state)

    assert result.handled is True
    # Vector update should not be called if no chunks
    mock_vectordb.update_status.assert_not_called()


@pytest.mark.asyncio
async def test_processor_handles_no_vectordb(context, mock_document_index):
    """Test processor continues when vectordb not available."""
    exception = Exception("Ingestion failed")
    partial_state = {
        "metadata": {
            "_previous_doc_id": "old-doc-123",
            "_deleted_at_ms": 1234567890,
        },
        "doc_id": "new-doc-456",
        "namespace": "test-ns",
    }

    # Mock restore response
    mock_document_index.restore_document.return_value = {
        "doc_id": "old-doc-123",
        "chunk_ids": ["chunk-1"],
        "chunk_count": 1,
    }

    # Remove vectordb from context
    context.custom["vectordb"] = None

    processor = ReingestRecoveryProcessor()
    result = await processor.on_error(exception, context, partial_state)

    # Should still succeed (vector update is best-effort)
    assert result.handled is True


@pytest.mark.asyncio
async def test_processor_priority():
    """Test processor has high priority (runs early)."""
    processor = ReingestRecoveryProcessor()
    assert processor.priority == 100


@pytest.mark.asyncio
async def test_processor_logs_restoration(context, mock_document_index, mock_vectordb, caplog):
    """Test processor logs restoration details."""
    import logging
    caplog.set_level(logging.INFO)

    exception = Exception("Ingestion failed")
    partial_state = {
        "metadata": {
            "_previous_doc_id": "old-doc-123",
            "_deleted_at_ms": 1234567890,
        },
        "doc_id": "new-doc-456",
        "namespace": "test-ns",
    }

    mock_document_index.restore_document.return_value = {
        "doc_id": "old-doc-123",
        "chunk_ids": ["chunk-1", "chunk-2"],
        "chunk_count": 2,
    }

    processor = ReingestRecoveryProcessor()
    await processor.on_error(exception, context, partial_state)

    # Check logs contain restoration info
    assert "Old version restored after REINGEST_VERSION failure" in caplog.text


@pytest.mark.asyncio
async def test_processor_preserves_original_exception(context, mock_document_index):
    """Test processor doesn't suppress exception (just performs cleanup)."""
    exception = ValueError("Original error")
    partial_state = {
        "metadata": {
            "_previous_doc_id": "old-doc-123",
            "_deleted_at_ms": 1234567890,
        },
        "doc_id": "new-doc-456",
        "namespace": "test-ns",
    }

    mock_document_index.restore_document.return_value = {
        "doc_id": "old-doc-123",
        "chunk_ids": [],
        "chunk_count": 0,
    }

    processor = ReingestRecoveryProcessor()
    result = await processor.on_error(exception, context, partial_state)

    # Processor marks as handled but does NOT suppress exception
    assert result.handled is True
    # Exception should still be raised by pipeline


@pytest.mark.asyncio
async def test_processor_handles_missing_deleted_at_ms(context, mock_document_index):
    """Test processor handles case where deleted_at_ms is missing."""
    exception = Exception("Ingestion failed")
    partial_state = {
        "metadata": {
            "_previous_doc_id": "old-doc-123",
            # Missing _deleted_at_ms
        },
        "doc_id": "new-doc-456",
        "namespace": "test-ns",
    }

    mock_document_index.restore_document.return_value = {
        "doc_id": "old-doc-123",
        "chunk_ids": [],
        "chunk_count": 0,
    }

    processor = ReingestRecoveryProcessor()
    result = await processor.on_error(exception, context, partial_state)

    assert result.handled is True

    # Verify restore was called with None for deleted_at_ms
    mock_document_index.restore_document.assert_called_once_with(
        doc_id="old-doc-123",
        namespace="test-ns",
        deleted_at_ms=None,
        restored_by="system_auto_recovery"
    )
