"""Tests for Milestone 1: Core Infrastructure."""
import pytest
import asyncio
from io import BytesIO
from stache_ai.utils.hashing import (
    compute_hash_sync,
    compute_hash_async,
    compute_file_hash_streaming,
)
from stache_ai.types import IngestionAction, IngestionResult


class TestHashing:
    """Hash utility tests."""

    def test_compute_hash_sync_string(self):
        """Test synchronous hash of string."""
        result = compute_hash_sync("hello world")
        expected = "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
        assert result == expected

    def test_compute_hash_sync_bytes(self):
        """Test synchronous hash of bytes."""
        result = compute_hash_sync(b"hello world")
        expected = "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
        assert result == expected

    @pytest.mark.asyncio
    async def test_compute_hash_async_small(self):
        """Test async hash of small content (inline)."""
        result = await compute_hash_async("hello world")
        expected = "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
        assert result == expected

    @pytest.mark.asyncio
    async def test_compute_hash_async_large(self):
        """Test async hash of large content (thread pool)."""
        content = "x" * 2_000_000  # 2MB
        result = await compute_hash_async(content)
        assert len(result) == 64  # SHA-256 hex digest

    def test_compute_file_hash_streaming(self):
        """Test streaming hash for file object."""
        file_obj = BytesIO(b"hello world")
        result = compute_file_hash_streaming(file_obj)
        expected = "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
        assert result == expected


class TestIngestionResult:
    """IngestionResult tests."""

    def test_ingest_new_result(self):
        """Test INGEST_NEW result creation."""
        result = IngestionResult(
            action=IngestionAction.INGEST_NEW,
            doc_id="doc123",
            namespace="default",
            chunks_created=5,
            reason="New document",
            content_hash="abc123",
        )
        assert result.action == IngestionAction.INGEST_NEW
        assert result.doc_id == "doc123"
        assert result.version == 1
        assert result.timestamp is not None

    def test_skip_result(self):
        """Test SKIP result creation."""
        result = IngestionResult(
            action=IngestionAction.SKIP,
            doc_id="doc123",
            namespace="default",
            chunks_created=0,
            reason="Duplicate detected",
            content_hash="abc123",
            existing_hash="abc123",
        )
        assert result.action == IngestionAction.SKIP
        assert result.existing_hash == "abc123"

    def test_reingest_version_result(self):
        """Test REINGEST_VERSION result creation."""
        result = IngestionResult(
            action=IngestionAction.REINGEST_VERSION,
            doc_id="doc456",
            namespace="default",
            chunks_created=3,
            reason="Content updated",
            content_hash="def456",
            existing_hash="abc123",
            previous_doc_id="doc123",
            version=2,
        )
        assert result.action == IngestionAction.REINGEST_VERSION
        assert result.previous_doc_id == "doc123"
        assert result.version == 2

    def test_backward_compatibility_dict_access(self):
        """Test backward compatibility with dict interface."""
        result = IngestionResult(
            action=IngestionAction.INGEST_NEW,
            doc_id="doc123",
            namespace="default",
            chunks_created=5,
            reason="New document",
            content_hash="abc123",
        )
        # Test __getitem__
        assert result["doc_id"] == "doc123"
        assert result["action"] == IngestionAction.INGEST_NEW

        # Test get()
        assert result.get("doc_id") == "doc123"
        assert result.get("nonexistent", "default") == "default"

    def test_to_dict(self):
        """Test conversion to dict for API response."""
        result = IngestionResult(
            action=IngestionAction.INGEST_NEW,
            doc_id="doc123",
            namespace="default",
            chunks_created=5,
            reason="New document",
            content_hash="abc123",
        )
        d = result.to_dict()
        assert d["action"] == "ingested_new"  # Enum value
        assert d["doc_id"] == "doc123"
        assert "timestamp" in d
