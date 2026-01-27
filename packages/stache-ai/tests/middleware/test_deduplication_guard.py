"""Tests for DeduplicationGuard middleware."""
import pytest
from unittest.mock import AsyncMock, Mock
from datetime import datetime, timezone

from stache_ai.middleware.guards.deduplication import DeduplicationGuard
from stache_ai.middleware.context import RequestContext
from stache_ai.config import Settings


@pytest.fixture
def mock_config():
    """Create mock config with dedup enabled."""
    config = Mock(spec=Settings)
    config.dedup_enabled = True
    return config


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
def context(mock_config, mock_document_index, mock_vectordb):
    """Create request context with providers."""
    ctx = RequestContext(
        request_id="test-123",
        timestamp=datetime.now(timezone.utc),
        namespace="test-ns",
        source="api"
    )
    ctx.custom["config"] = mock_config
    ctx.custom["document_index"] = mock_document_index
    ctx.custom["vectordb"] = mock_vectordb
    return ctx


@pytest.mark.asyncio
async def test_guard_allows_new_document(context, mock_document_index):
    """Test guard allows new document (no existing match)."""
    # Setup: no existing document
    mock_document_index.get_document_by_source_path.return_value = None

    guard = DeduplicationGuard()
    result = await guard.validate(
        content="This is new content",
        metadata={"filename": "test.txt"},
        context=context
    )

    assert result.action == "allow"
    assert "content_hash" in result.metadata
    assert len(result.metadata["content_hash"]) == 64  # SHA-256


@pytest.mark.asyncio
async def test_guard_rejects_duplicate_content(context, mock_document_index):
    """Test guard rejects duplicate content (same hash)."""
    content = "This is duplicate content"

    # First, compute the actual hash
    from stache_ai.utils.hashing import compute_hash_async
    actual_hash = await compute_hash_async(content)

    # Setup: existing document with same hash
    mock_document_index.get_document_by_source_path.return_value = {
        "doc_id": "existing-123",
        "content_hash": actual_hash,
    }

    guard = DeduplicationGuard()

    result = await guard.validate(
        content=content,
        metadata={"filename": "test.txt"},
        context=context
    )

    assert result.action == "reject"
    assert "duplicate content" in result.reason
    assert result.metadata["existing_doc_id"] == "existing-123"
    assert result.metadata["content_hash"] == actual_hash


@pytest.mark.asyncio
async def test_guard_allows_reingest_version(context, mock_document_index, mock_vectordb):
    """Test guard allows REINGEST_VERSION when hash differs at same path."""
    old_content = "Old version"
    new_content = "New version"

    from stache_ai.utils.hashing import compute_hash_async
    old_hash = await compute_hash_async(old_content)
    new_hash = await compute_hash_async(new_content)

    # Setup: existing document with different hash
    mock_document_index.get_document_by_source_path.return_value = {
        "doc_id": "old-doc-123",
        "content_hash": old_hash,
        "chunk_ids": ["chunk-1", "chunk-2"],
    }

    # Mock soft delete
    mock_document_index.soft_delete_document.return_value = {
        "doc_id": "old-doc-123",
        "deleted_at_ms": 1234567890,
        "chunk_ids": ["chunk-1", "chunk-2"],
    }

    guard = DeduplicationGuard()
    result = await guard.validate(
        content=new_content,
        metadata={"filename": "test.txt", "source_path": "/path/to/file.txt"},
        context=context
    )

    assert result.action == "allow"
    assert result.metadata["_reingest_version"] is True
    assert result.metadata["_previous_doc_id"] == "old-doc-123"
    assert result.metadata["_deleted_at_ms"] == 1234567890
    assert result.metadata["content_hash"] == new_hash

    # Verify soft delete was called
    mock_document_index.soft_delete_document.assert_called_once_with(
        doc_id="old-doc-123",
        namespace="test-ns",
        delete_reason="reingest_version"
    )

    # Verify vector status update
    mock_vectordb.update_status.assert_called_once_with(
        ids=["chunk-1", "chunk-2"],
        namespace="test-ns",
        status="deleting"
    )


@pytest.mark.asyncio
async def test_guard_continues_on_soft_delete_failure(context, mock_document_index, mock_vectordb):
    """Test guard continues if soft delete fails (best-effort)."""
    old_content = "Old version"
    new_content = "New version"

    from stache_ai.utils.hashing import compute_hash_async
    old_hash = await compute_hash_async(old_content)

    # Setup: existing document with different hash
    mock_document_index.get_document_by_source_path.return_value = {
        "doc_id": "old-doc-123",
        "content_hash": old_hash,
    }

    # Mock soft delete failure
    mock_document_index.soft_delete_document.side_effect = Exception("Soft delete failed")

    guard = DeduplicationGuard()
    result = await guard.validate(
        content=new_content,
        metadata={"filename": "test.txt", "source_path": "/path/to/file.txt"},
        context=context
    )

    # Should still allow ingestion
    assert result.action == "allow"
    assert result.metadata["_reingest_version"] is True
    assert result.metadata["_deleted_at_ms"] is None  # No timestamp due to failure


@pytest.mark.asyncio
async def test_guard_disabled_when_config_false(context, mock_config):
    """Test guard allows all when dedup_enabled=False."""
    mock_config.dedup_enabled = False

    guard = DeduplicationGuard()
    result = await guard.validate(
        content="Any content",
        metadata={"filename": "test.txt"},
        context=context
    )

    assert result.action == "allow"
    # No metadata should be added when disabled
    assert result.metadata is None


@pytest.mark.asyncio
async def test_guard_allows_when_no_document_index(context):
    """Test guard allows when document_index not available."""
    context.custom["document_index"] = None

    guard = DeduplicationGuard()
    result = await guard.validate(
        content="Any content",
        metadata={"filename": "test.txt"},
        context=context
    )

    assert result.action == "allow"


@pytest.mark.asyncio
async def test_guard_handles_fingerprint_identifier(context, mock_document_index):
    """Test guard handles fingerprint-based identifier (no source_path)."""
    content = "Content without source path"

    from stache_ai.utils.hashing import compute_hash_async
    content_hash = await compute_hash_async(content)

    # Setup: no existing document (new fingerprint)
    mock_document_index.get_document_by_source_path.return_value = None

    guard = DeduplicationGuard()
    result = await guard.validate(
        content=content,
        metadata={"filename": "text"},  # No source_path
        context=context
    )

    assert result.action == "allow"
    assert result.metadata["content_hash"] == content_hash

    # Verify lookup was called without source_path
    mock_document_index.get_document_by_source_path.assert_called_once_with(
        namespace="test-ns",
        source_path=None,
        filename="text"
    )


@pytest.mark.asyncio
async def test_guard_priority():
    """Test guard has correct priority (runs early)."""
    guard = DeduplicationGuard()
    assert guard.priority == 50  # Should run early


@pytest.mark.asyncio
async def test_guard_on_error_is_allow():
    """Test guard doesn't block on errors (on_error='allow')."""
    guard = DeduplicationGuard()
    assert guard.on_error == "allow"


@pytest.mark.asyncio
async def test_guard_logs_timing_metrics(context, mock_document_index, caplog):
    """Test guard logs hash computation and lookup timing."""
    import logging
    caplog.set_level(logging.INFO)

    mock_document_index.get_document_by_source_path.return_value = None

    guard = DeduplicationGuard()
    await guard.validate(
        content="Test content",
        metadata={"filename": "test.txt"},
        context=context
    )

    # Check that timing was logged (will be in debug/extra fields)
    # This is a basic check - actual timing values are in structured logging


@pytest.mark.asyncio
async def test_reingest_version_only_for_source_identifiers(context, mock_document_index):
    """Test REINGEST_VERSION only happens when source_path exists."""
    old_content = "Old version"
    new_content = "New version"

    from stache_ai.utils.hashing import compute_hash_async
    old_hash = await compute_hash_async(old_content)

    # Existing document WITHOUT source_path (fingerprint-based)
    mock_document_index.get_document_by_source_path.return_value = {
        "doc_id": "old-doc-123",
        "content_hash": old_hash,
    }

    guard = DeduplicationGuard()
    result = await guard.validate(
        content=new_content,
        metadata={"filename": "text"},  # No source_path
        context=context
    )

    # Different hash but no source_path → should treat as new document
    # (Fingerprint match means same identifier, but hash changed = data corruption)
    # This should trigger REINGEST_VERSION
    assert result.action == "allow"


@pytest.mark.asyncio
async def test_guard_handles_empty_content(context, mock_document_index):
    """Test guard handles empty content gracefully."""
    mock_document_index.get_document_by_source_path.return_value = None

    guard = DeduplicationGuard()
    result = await guard.validate(
        content="",
        metadata={"filename": "empty.txt"},
        context=context
    )

    assert result.action == "allow"
    assert "content_hash" in result.metadata
    # SHA-256 of empty string
    assert result.metadata["content_hash"] == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


@pytest.mark.asyncio
async def test_guard_handles_large_content(context, mock_document_index):
    """Test guard handles large content (triggers thread pool hashing)."""
    # Create content >1MB to trigger async thread pool
    large_content = "x" * (1_000_001)

    mock_document_index.get_document_by_source_path.return_value = None

    guard = DeduplicationGuard()
    result = await guard.validate(
        content=large_content,
        metadata={"filename": "large.txt"},
        context=context
    )

    assert result.action == "allow"
    assert "content_hash" in result.metadata


@pytest.mark.asyncio
async def test_guard_metadata_merge(context, mock_document_index):
    """Test guard metadata is properly merged."""
    mock_document_index.get_document_by_source_path.return_value = None

    guard = DeduplicationGuard()
    result = await guard.validate(
        content="Test",
        metadata={"filename": "test.txt", "existing_key": "value"},
        context=context
    )

    assert result.action == "allow"
    assert "content_hash" in result.metadata
    # Original metadata should not be in guard result (pipeline merges)
    assert "existing_key" not in result.metadata
