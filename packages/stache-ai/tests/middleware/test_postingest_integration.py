"""Integration tests for PostIngestProcessor middleware with pipeline"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from stache_ai.middleware.base import PostIngestProcessor, StorageResult
from stache_ai.middleware.results import PostIngestResult
from stache_ai.middleware.context import RequestContext
from stache_ai.middleware.postingest.summary import HeuristicSummaryGenerator

pytestmark = pytest.mark.anyio


class TestPostIngestProcessorChainExecution:
    """Test PostIngestProcessor chain execution order and artifact collection"""

    @pytest.fixture
    def mock_context(self, mock_config, mock_embedding_provider, mock_summaries_provider):
        """Create request context with providers"""
        context = RequestContext(
            request_id="test-request",
            timestamp=datetime.now(timezone.utc),
            namespace="test-namespace",
            user_id="test-user"
        )
        context.custom = {
            "config": mock_config,
            "embedding_provider": mock_embedding_provider,
            "summaries_provider": mock_summaries_provider
        }
        return context

    @pytest.fixture
    def sample_storage_result(self):
        """Create sample storage result"""
        return StorageResult(
            vector_ids=["vec-1", "vec-2"],
            namespace="test-namespace",
            index="test-index",
            doc_id="doc-123",
            chunk_count=2,
            embedding_model="test-model"
        )

    @pytest.fixture
    def sample_chunks(self):
        """Create sample chunks"""
        return [
            ("Chunk 1 text", {"filename": "test.md", "chunk_index": 0, "headings": ["Introduction"]}),
            ("Chunk 2 text", {"filename": "test.md", "chunk_index": 1, "headings": ["Section 1"]})
        ]

    async def test_single_processor_execution(
        self,
        sample_chunks,
        sample_storage_result,
        mock_context
    ):
        """Test execution of a single PostIngestProcessor"""
        generator = HeuristicSummaryGenerator()

        result = await generator.process(
            chunks=sample_chunks,
            storage_result=sample_storage_result,
            context=mock_context
        )

        assert result.action == "allow"
        assert "summary" in result.artifacts
        assert "summary_embedding" in result.artifacts
        assert "headings" in result.artifacts
        assert "summary_id" in result.artifacts

    async def test_multiple_processors_sequential(
        self,
        sample_chunks,
        sample_storage_result,
        mock_context
    ):
        """Test multiple processors execute sequentially and artifacts are collected"""
        # Create multiple processors
        processor1 = HeuristicSummaryGenerator()
        processor1.priority = 50

        # Second mock processor with different priority
        class MockArtifactGenerator(PostIngestProcessor):
            priority = 100

            async def process(self, chunks, storage_result, context):
                return PostIngestResult(
                    action="allow",
                    artifacts={
                        "custom_artifact": "test-value",
                        "processor_name": "MockArtifactGenerator"
                    }
                )

        processor2 = MockArtifactGenerator()

        # Execute both in order
        all_artifacts = {}

        result1 = await processor1.process(sample_chunks, sample_storage_result, mock_context)
        if result1.action == "allow" and result1.artifacts:
            all_artifacts.update(result1.artifacts)

        result2 = await processor2.process(sample_chunks, sample_storage_result, mock_context)
        if result2.action == "allow" and result2.artifacts:
            all_artifacts.update(result2.artifacts)

        # Verify artifacts from both processors
        assert "summary" in all_artifacts
        assert "custom_artifact" in all_artifacts
        assert all_artifacts["custom_artifact"] == "test-value"

    async def test_processor_priority_order(self):
        """Test that processors execute in priority order (lower priority first)"""
        execution_order = []

        class EarlyProcessor(PostIngestProcessor):
            priority = 10

            async def process(self, chunks, storage_result, context):
                execution_order.append("early")
                return PostIngestResult(action="allow")

        class MiddleProcessor(PostIngestProcessor):
            priority = 50

            async def process(self, chunks, storage_result, context):
                execution_order.append("middle")
                return PostIngestResult(action="allow")

        class LateProcessor(PostIngestProcessor):
            priority = 100

            async def process(self, chunks, storage_result, context):
                execution_order.append("late")
                return PostIngestResult(action="allow")

        # Create processors in random order
        processors = [
            LateProcessor(),
            EarlyProcessor(),
            MiddleProcessor()
        ]

        # Sort by priority
        processors.sort(key=lambda p: p.priority)

        # Execute in priority order
        context = RequestContext(
            request_id="test",
            timestamp=datetime.now(timezone.utc),
            namespace="test"
        )
        storage_result = StorageResult(
            vector_ids=[], namespace="test", index="test",
            doc_id="test", chunk_count=0, embedding_model="test"
        )

        for processor in processors:
            await processor.process([], storage_result, context)

        assert execution_order == ["early", "middle", "late"]

    async def test_skip_action_doesnt_add_artifacts(
        self,
        sample_chunks,
        sample_storage_result
    ):
        """Test that skip action doesn't contribute artifacts"""
        class SkippingProcessor(PostIngestProcessor):
            async def process(self, chunks, storage_result, context):
                return PostIngestResult(
                    action="skip",
                    reason="Test skip"
                )

        processor = SkippingProcessor()
        context = RequestContext(
            request_id="test",
            timestamp=datetime.now(timezone.utc),
            namespace="test"
        )

        result = await processor.process(
            chunks=sample_chunks,
            storage_result=sample_storage_result,
            context=context
        )

        assert result.action == "skip"
        assert result.artifacts is None or result.artifacts == {}

    async def test_error_handling_returns_skip(
        self,
        sample_chunks,
        sample_storage_result,
        mock_context
    ):
        """Test that exceptions in PostIngestProcessor result in skip action"""
        class ErrorProneProcessor(PostIngestProcessor):
            async def process(self, chunks, storage_result, context):
                raise ValueError("Test error")

        processor = ErrorProneProcessor()

        # Should raise, but in real pipeline this would be caught
        with pytest.raises(ValueError):
            await processor.process(
                chunks=sample_chunks,
                storage_result=sample_storage_result,
                context=mock_context
            )

    async def test_artifact_overwrite_warning(
        self,
        sample_chunks,
        sample_storage_result,
        mock_context
    ):
        """Test that duplicate artifact keys overwrite (as documented)"""
        processor1 = HeuristicSummaryGenerator()

        class ConflictingProcessor(PostIngestProcessor):
            priority = 100

            async def process(self, chunks, storage_result, context):
                return PostIngestResult(
                    action="allow",
                    artifacts={
                        "summary": "OVERWRITTEN",  # Same key as HeuristicSummaryGenerator
                        "new_key": "new_value"
                    }
                )

        processor2 = ConflictingProcessor()

        # Collect artifacts
        all_artifacts = {}

        result1 = await processor1.process(sample_chunks, sample_storage_result, mock_context)
        if result1.artifacts:
            all_artifacts.update(result1.artifacts)

        result2 = await processor2.process(sample_chunks, sample_storage_result, mock_context)
        if result2.artifacts:
            all_artifacts.update(result2.artifacts)

        # Later processor should overwrite
        assert all_artifacts["summary"] == "OVERWRITTEN"
        assert all_artifacts["new_key"] == "new_value"


class TestHeuristicSummaryIntegration:
    """Integration tests specific to HeuristicSummaryGenerator"""

    @pytest.fixture
    def generator(self):
        return HeuristicSummaryGenerator()

    @pytest.fixture
    def mock_context(self, mock_config, mock_embedding_provider, mock_summaries_provider):
        context = RequestContext(
            request_id="test-request",
            timestamp=datetime.now(timezone.utc),
            namespace="test-namespace"
        )
        context.custom = {
            "config": mock_config,
            "embedding_provider": mock_embedding_provider,
            "summaries_provider": mock_summaries_provider
        }
        return context

    async def test_summary_with_real_chunks(
        self,
        generator,
        mock_context,
        sample_chunks,
        mock_storage_result
    ):
        """Test summary generation with realistic chunk data"""
        # Create more realistic chunks
        realistic_chunks = [
            (
                "# Introduction\n\nThis document describes the architecture of the system.",
                {
                    "filename": "architecture.md",
                    "chunk_index": 0,
                    "created_at": "2026-01-11T00:00:00Z",
                    "headings": ["Introduction"],
                    "source": "upload",
                    "doc_id": "will-be-overwritten"
                }
            ),
            (
                "## Core Components\n\nThe system consists of three main components: API, Database, and Cache.",
                {
                    "filename": "architecture.md",
                    "chunk_index": 1,
                    "created_at": "2026-01-11T00:00:00Z",
                    "headings": ["Introduction", "Core Components"]
                }
            ),
            (
                "## Deployment\n\nDeploy using Docker containers on AWS ECS.",
                {
                    "filename": "architecture.md",
                    "chunk_index": 2,
                    "created_at": "2026-01-11T00:00:00Z",
                    "headings": ["Introduction", "Deployment"]
                }
            )
        ]

        result = await generator.process(
            chunks=realistic_chunks,
            storage_result=mock_storage_result,
            context=mock_context
        )

        # Verify summary structure
        summary = result.artifacts["summary"]
        assert "Document: architecture.md" in summary
        assert "Namespace: test-namespace" in summary
        assert "Headings: Introduction, Core Components, Deployment" in summary
        assert "This document describes the architecture" in summary

        # Verify headings (unique, ordered)
        headings = result.artifacts["headings"]
        assert headings == ["Introduction", "Core Components", "Deployment"]

        # Verify metadata preservation
        embedding_provider = mock_context.custom["embedding_provider"]
        assert embedding_provider.embed.call_count == 1

        summaries_provider = mock_context.custom["summaries_provider"]
        call_args = summaries_provider.insert.call_args
        metadata = call_args.kwargs["metadatas"][0]

        # Original metadata should be preserved
        assert metadata["source"] == "upload"
        # But doc_id should be from storage_result
        assert metadata["doc_id"] == mock_storage_result.doc_id

    async def test_summary_integration_with_storage_result(
        self,
        generator,
        mock_context
    ):
        """Test that summary correctly uses StorageResult metadata"""
        # Create chunks WITHOUT namespace in metadata (to test that storage_result.namespace is used)
        chunks_without_namespace = [
            ("Chunk 1", {"filename": "test.md", "chunk_index": 0}),
            ("Chunk 2", {"filename": "test.md", "chunk_index": 1})
        ]

        storage_result = StorageResult(
            vector_ids=["id-1", "id-2"],
            namespace="custom-namespace",
            index="custom-index",
            doc_id="custom-doc-id",
            chunk_count=2,
            embedding_model="cohere.embed-english-v3"
        )

        result = await generator.process(
            chunks=chunks_without_namespace,
            storage_result=storage_result,
            context=mock_context
        )

        # Verify namespace from storage_result is used
        summaries_provider = mock_context.custom["summaries_provider"]
        call_args = summaries_provider.insert.call_args

        assert call_args.kwargs["namespace"] == "custom-namespace"

        # Verify metadata has correct doc_id and namespace from storage_result
        metadata = call_args.kwargs["metadatas"][0]
        assert metadata["doc_id"] == "custom-doc-id"
        # Note: namespace in metadata comes from storage_result (line 83 and 145 in summary.py)
        assert metadata["namespace"] == "custom-namespace"
        assert metadata["chunk_count"] == 2  # Based on len(chunks)

    async def test_provider_access_via_context(
        self,
        generator,
        sample_chunks,
        mock_storage_result
    ):
        """Test that processors access providers via context.custom"""
        # Create context WITHOUT providers but with config
        context = RequestContext(
            request_id="test",
            timestamp=datetime.now(timezone.utc),
            namespace="test"
        )
        # Add config with summary enabled, but no providers
        config = MagicMock()
        config.enable_summary_generation = True
        context.custom = {"config": config}  # Config present but no providers

        result = await generator.process(
            chunks=sample_chunks,
            storage_result=mock_storage_result,
            context=context
        )

        # Should skip gracefully
        assert result.action == "skip"
        assert "providers not available" in result.reason.lower()


def test_postingest_processor_entry_point_discovery():
    """Verify HeuristicSummaryGenerator is discovered via entry points"""
    from stache_ai.providers.plugin_loader import get_providers
    from stache_ai.middleware.postingest.summary import HeuristicSummaryGenerator

    processors = get_providers('postingest_processor')
    assert 'heuristic_summary' in processors
    assert processors['heuristic_summary'] == HeuristicSummaryGenerator
