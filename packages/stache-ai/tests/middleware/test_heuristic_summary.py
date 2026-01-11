"""Unit tests for HeuristicSummaryGenerator PostIngestProcessor"""

import pytest
from unittest.mock import MagicMock
from datetime import datetime, timezone
from stache_ai.middleware.postingest.summary import HeuristicSummaryGenerator
from stache_ai.middleware.base import StorageResult
from stache_ai.middleware.context import RequestContext

pytestmark = pytest.mark.anyio


class TestHeuristicSummaryGenerator:
    """Test suite for HeuristicSummaryGenerator"""

    @pytest.fixture
    def generator(self):
        """Create generator instance"""
        return HeuristicSummaryGenerator()

    @pytest.fixture
    def context_with_providers(self, mock_config, mock_embedding_provider, mock_summaries_provider):
        """Create context with all required providers"""
        context = RequestContext(
            request_id="test-request",
            timestamp=datetime.now(timezone.utc),
            namespace="test-namespace",
            user_id="test-user",
            tenant_id="test-tenant"
        )
        context.custom = {
            "config": mock_config,
            "embedding_provider": mock_embedding_provider,
            "summaries_provider": mock_summaries_provider
        }
        return context

    async def test_summary_generation_success(
        self,
        generator,
        sample_chunks,
        mock_storage_result,
        context_with_providers
    ):
        """Test successful summary generation with all components"""
        result = await generator.process(
            chunks=sample_chunks,
            storage_result=mock_storage_result,
            context=context_with_providers
        )

        # Verify result action
        assert result.action == "allow"
        assert result.reason is None

        # Verify artifacts exist
        assert "summary" in result.artifacts
        assert "summary_embedding" in result.artifacts
        assert "headings" in result.artifacts
        assert "summary_id" in result.artifacts

        # Verify summary content
        summary = result.artifacts["summary"]
        assert "Document: test.md" in summary
        assert "Namespace: test-namespace" in summary
        assert "Headings:" in summary
        assert "Introduction" in summary
        assert "Section 1" in summary
        assert "Section 2" in summary

        # Verify headings extraction (unique only)
        headings = result.artifacts["headings"]
        assert headings == ["Introduction", "Section 1", "Section 2"]

        # Verify embedding was generated
        assert result.artifacts["summary_embedding"] == [0.1] * 1024

        # Verify summary_id is valid UUID
        import uuid
        uuid.UUID(result.artifacts["summary_id"])

    
    async def test_summary_disabled_via_config(
        self,
        generator,
        sample_chunks,
        mock_storage_result,
        context_with_providers,
        mock_config
    ):
        """Test that summary generation is skipped when disabled"""
        mock_config.enable_summary_generation = False

        result = await generator.process(
            chunks=sample_chunks,
            storage_result=mock_storage_result,
            context=context_with_providers
        )

        assert result.action == "skip"
        assert "disabled via config" in result.reason.lower()
        assert result.artifacts is None or result.artifacts == {}

    
    async def test_missing_embedding_provider(
        self,
        generator,
        sample_chunks,
        mock_storage_result,
        context_with_providers
    ):
        """Test graceful handling when embedding provider is missing"""
        context_with_providers.custom["embedding_provider"] = None

        result = await generator.process(
            chunks=sample_chunks,
            storage_result=mock_storage_result,
            context=context_with_providers
        )

        assert result.action == "skip"
        assert "providers not available" in result.reason.lower()

    
    async def test_missing_summaries_provider(
        self,
        generator,
        sample_chunks,
        mock_storage_result,
        context_with_providers
    ):
        """Test graceful handling when summaries provider is missing"""
        context_with_providers.custom["summaries_provider"] = None

        result = await generator.process(
            chunks=sample_chunks,
            storage_result=mock_storage_result,
            context=context_with_providers
        )

        assert result.action == "skip"
        assert "providers not available" in result.reason.lower()

    
    async def test_empty_chunks_handling(
        self,
        generator,
        mock_storage_result,
        context_with_providers
    ):
        """Test handling of empty chunks list"""
        result = await generator.process(
            chunks=[],
            storage_result=mock_storage_result,
            context=context_with_providers
        )

        # Should still succeed, just with minimal summary
        assert result.action == "allow"
        assert "summary" in result.artifacts
        summary = result.artifacts["summary"]
        assert "Document: unknown" in summary
        assert result.artifacts["headings"] == []

    
    async def test_chunks_without_headings(
        self,
        generator,
        mock_storage_result,
        context_with_providers
    ):
        """Test chunks without heading metadata"""
        chunks = [
            ("Plain text chunk 1", {"filename": "test.txt", "chunk_index": 0}),
            ("Plain text chunk 2", {"filename": "test.txt", "chunk_index": 1})
        ]

        result = await generator.process(
            chunks=chunks,
            storage_result=mock_storage_result,
            context=context_with_providers
        )

        assert result.action == "allow"
        assert result.artifacts["headings"] == []

        # Summary should not include "Headings:" line
        summary = result.artifacts["summary"]
        assert "Headings:" not in summary

    
    async def test_duplicate_headings_filtered(
        self,
        generator,
        mock_storage_result,
        context_with_providers
    ):
        """Test that duplicate headings are filtered out"""
        chunks = [
            ("Text 1", {"filename": "test.md", "chunk_index": 0, "headings": ["Intro", "Section A"]}),
            ("Text 2", {"filename": "test.md", "chunk_index": 1, "headings": ["Intro", "Section B"]}),
            ("Text 3", {"filename": "test.md", "chunk_index": 2, "headings": ["Section A", "Section C"]})
        ]

        result = await generator.process(
            chunks=chunks,
            storage_result=mock_storage_result,
            context=context_with_providers
        )

        # Should preserve order, but remove duplicates
        headings = result.artifacts["headings"]
        assert headings == ["Intro", "Section A", "Section B", "Section C"]

    
    async def test_content_preview_truncation(
        self,
        generator,
        mock_storage_result,
        context_with_providers
    ):
        """Test that content preview is truncated to ~1500 chars"""
        # Create chunks with lots of text
        long_text = "A" * 1000
        chunks = [
            (long_text, {"filename": "test.txt", "chunk_index": 0}),
            (long_text, {"filename": "test.txt", "chunk_index": 1}),
            (long_text, {"filename": "test.txt", "chunk_index": 2})
        ]

        result = await generator.process(
            chunks=chunks,
            storage_result=mock_storage_result,
            context=context_with_providers
        )

        summary = result.artifacts["summary"]
        # Extract content after the metadata lines
        lines = summary.split("\n")
        content_start = next(i for i, line in enumerate(lines) if line == "")
        content = "\n".join(lines[content_start:])

        # Should be truncated to ~1500 chars (plus spaces between chunks)
        assert len(content) <= 1600  # Some tolerance for spaces

    
    async def test_heading_limit_to_20(
        self,
        generator,
        mock_storage_result,
        context_with_providers
    ):
        """Test that only first 20 headings appear in summary text"""
        # Create 30 unique headings
        chunks = [
            (f"Text {i}", {"filename": "test.md", "chunk_index": i, "headings": [f"Heading {i}"]})
            for i in range(30)
        ]

        result = await generator.process(
            chunks=chunks,
            storage_result=mock_storage_result,
            context=context_with_providers
        )

        summary = result.artifacts["summary"]
        # Summary text should only include first 20 headings
        headings_line = [line for line in summary.split("\n") if line.startswith("Headings:")][0]
        assert "Heading 19" in headings_line
        assert "Heading 20" not in headings_line

        # But artifacts should include up to 50
        assert len(result.artifacts["headings"]) == 30

    
    async def test_heading_metadata_limit_to_50(
        self,
        generator,
        mock_storage_result,
        context_with_providers,
        mock_summaries_provider
    ):
        """Test that only first 50 headings stored in metadata"""
        # Create 60 unique headings
        chunks = [
            (f"Text {i}", {"filename": "test.md", "chunk_index": i, "headings": [f"Heading {i}"]})
            for i in range(60)
        ]

        result = await generator.process(
            chunks=chunks,
            storage_result=mock_storage_result,
            context=context_with_providers
        )

        # Check what was passed to summaries_provider.insert
        call_args = mock_summaries_provider.insert.call_args
        metadata = call_args.kwargs["metadatas"][0]

        assert len(metadata["headings"]) == 50

    
    async def test_metadata_preservation(
        self,
        generator,
        mock_storage_result,
        context_with_providers,
        mock_summaries_provider
    ):
        """Test that original metadata is preserved (excluding chunk-specific fields)"""
        chunks = [
            (
                "Text",
                {
                    "filename": "test.md",
                    "chunk_index": 0,
                    "created_at": "2026-01-11T00:00:00Z",
                    "source": "upload",
                    "author": "test-user",
                    "text": "should be excluded",
                    "doc_id": "should be overwritten"
                }
            )
        ]

        result = await generator.process(
            chunks=chunks,
            storage_result=mock_storage_result,
            context=context_with_providers
        )

        # Check summary metadata
        call_args = mock_summaries_provider.insert.call_args
        metadata = call_args.kwargs["metadatas"][0]

        # Should preserve custom metadata
        assert metadata["source"] == "upload"
        assert metadata["author"] == "test-user"

        # Should exclude chunk-specific fields
        assert "text" not in metadata
        assert "chunk_index" not in metadata

        # doc_id should be from storage_result, not chunk metadata
        assert metadata["doc_id"] == mock_storage_result.doc_id

    
    async def test_summaries_provider_called_correctly(
        self,
        generator,
        sample_chunks,
        mock_storage_result,
        context_with_providers,
        mock_summaries_provider
    ):
        """Test that summaries provider is called with correct arguments"""
        result = await generator.process(
            chunks=sample_chunks,
            storage_result=mock_storage_result,
            context=context_with_providers
        )

        # Verify insert was called once
        assert mock_summaries_provider.insert.call_count == 1

        # Verify call arguments
        call_args = mock_summaries_provider.insert.call_args
        assert len(call_args.kwargs["vectors"]) == 1
        assert len(call_args.kwargs["texts"]) == 1
        assert len(call_args.kwargs["metadatas"]) == 1
        assert len(call_args.kwargs["ids"]) == 1
        assert call_args.kwargs["namespace"] == "test-namespace"

        # Verify metadata structure
        metadata = call_args.kwargs["metadatas"][0]
        assert metadata["_type"] == "document_summary"
        assert metadata["doc_id"] == mock_storage_result.doc_id
        assert metadata["filename"] == "test.md"
        assert metadata["namespace"] == "test-namespace"
        assert metadata["chunk_count"] == 3

    
    async def test_embedding_provider_called_once(
        self,
        generator,
        sample_chunks,
        mock_storage_result,
        context_with_providers,
        mock_embedding_provider
    ):
        """Test that embedding provider is called exactly once with summary text"""
        result = await generator.process(
            chunks=sample_chunks,
            storage_result=mock_storage_result,
            context=context_with_providers
        )

        # Verify embed was called once
        assert mock_embedding_provider.embed.call_count == 1

        # Verify the text passed to embed matches the summary
        # embed() is called with [summary_text] (a list)
        call_args = mock_embedding_provider.embed.call_args
        embedded_texts = call_args[0][0]
        assert isinstance(embedded_texts, list)
        assert len(embedded_texts) == 1
        assert embedded_texts[0] == result.artifacts["summary"]

    
    async def test_error_handling_returns_skip(
        self,
        generator,
        sample_chunks,
        mock_storage_result,
        context_with_providers,
        mock_embedding_provider
    ):
        """Test that errors are caught and result in skip action"""
        # Make embedding provider raise an error
        mock_embedding_provider.embed.side_effect = Exception("Embedding failed")

        result = await generator.process(
            chunks=sample_chunks,
            storage_result=mock_storage_result,
            context=context_with_providers
        )

        # Should skip, not raise
        assert result.action == "skip"
        assert "failed" in result.reason.lower()
        assert "Embedding failed" in result.reason

    def test_priority_is_50(self, generator):
        """Test that priority is set to 50 (runs early)"""
        assert generator.priority == 50

    def test_on_error_is_skip(self, generator):
        """Test that on_error is set to skip (enforced by base class)"""
        assert generator.on_error == "skip"

    
    async def test_empty_headings_not_stored(
        self,
        generator,
        mock_storage_result,
        context_with_providers,
        mock_summaries_provider
    ):
        """Test that empty headings array is not stored (S3 Vectors rejects empty arrays)"""
        chunks = [
            ("Text", {"filename": "test.txt", "chunk_index": 0})
        ]

        result = await generator.process(
            chunks=chunks,
            storage_result=mock_storage_result,
            context=context_with_providers
        )

        # Check metadata passed to insert
        call_args = mock_summaries_provider.insert.call_args
        metadata = call_args.kwargs["metadatas"][0]

        # Should not have headings key if empty
        assert "headings" not in metadata

    
    async def test_summary_id_is_unique_uuid(
        self,
        generator,
        sample_chunks,
        mock_storage_result,
        context_with_providers
    ):
        """Test that summary_id is a valid, unique UUID"""
        result1 = await generator.process(
            chunks=sample_chunks,
            storage_result=mock_storage_result,
            context=context_with_providers
        )

        result2 = await generator.process(
            chunks=sample_chunks,
            storage_result=mock_storage_result,
            context=context_with_providers
        )

        import uuid
        # Both should be valid UUIDs
        uuid.UUID(result1.artifacts["summary_id"])
        uuid.UUID(result2.artifacts["summary_id"])

        # Should be different
        assert result1.artifacts["summary_id"] != result2.artifacts["summary_id"]
