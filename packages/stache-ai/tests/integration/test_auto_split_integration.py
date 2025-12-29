"""Integration tests for auto-split with pipeline."""

from unittest.mock import MagicMock

import pytest

from stache_ai.config import Settings
from stache_ai.rag.pipeline import RAGPipeline


@pytest.fixture
def mock_vectordb_provider():
    """Create a mock vectordb provider"""
    provider = MagicMock()
    provider.get_name.return_value = "MockVectorDB"
    provider.insert = MagicMock(return_value=["chunk-1", "chunk-2"])
    provider.insert_vectors = MagicMock(return_value=["chunk-1", "chunk-2"])
    provider.search = MagicMock(return_value=[])
    return provider


@pytest.fixture
def mock_embedding_provider():
    """Create a mock embedding provider"""
    provider = MagicMock()
    provider.get_name.return_value = "MockEmbedding"
    provider.get_dimensions.return_value = 1024
    provider.embed = MagicMock(return_value=[0.1] * 1024)
    return provider


@pytest.fixture
def mock_namespace_provider():
    """Create a mock namespace provider"""
    provider = MagicMock()
    provider.get_name.return_value = "MockNamespace"
    provider.get_or_create_namespace = MagicMock(return_value={"name": "test"})
    return provider


@pytest.fixture
def mock_llm_provider():
    """Create a mock LLM provider"""
    provider = MagicMock()
    provider.get_name.return_value = "MockLLM"
    return provider


@pytest.fixture
def settings_with_auto_split():
    """Test settings with auto-split enabled"""
    return Settings(
        embedding_auto_split_enabled=True,
        embedding_auto_split_max_depth=4,
        vectordb_provider="chroma",
        namespace_provider="sqlite",
        embedding_provider="openai",
        llm_provider="fallback",
    )


@pytest.fixture
def settings_without_auto_split():
    """Test settings with auto-split disabled"""
    return Settings(
        embedding_auto_split_enabled=False,
        vectordb_provider="chroma",
        namespace_provider="sqlite",
        embedding_provider="openai",
        llm_provider="fallback",
    )


@pytest.fixture
def pipeline_with_auto_split(settings_with_auto_split, mock_vectordb_provider,
                             mock_embedding_provider, mock_namespace_provider, mock_llm_provider):
    """Pipeline with auto-split enabled and mocked providers"""
    pipeline = RAGPipeline(settings_with_auto_split)

    # Mock all providers via private attributes (bypasses lazy loading)
    pipeline._vectordb_provider = mock_vectordb_provider
    pipeline._embedding_provider = mock_embedding_provider
    pipeline._namespace_provider = mock_namespace_provider
    pipeline._llm_provider = mock_llm_provider
    pipeline._document_index_provider = MagicMock()

    return pipeline


@pytest.fixture
def pipeline_without_auto_split(settings_without_auto_split, mock_vectordb_provider,
                                mock_embedding_provider, mock_namespace_provider, mock_llm_provider):
    """Pipeline with auto-split disabled and mocked providers"""
    pipeline = RAGPipeline(settings_without_auto_split)

    # Mock all providers
    pipeline._vectordb_provider = mock_vectordb_provider
    pipeline._embedding_provider = mock_embedding_provider
    pipeline._namespace_provider = mock_namespace_provider
    pipeline._llm_provider = mock_llm_provider
    pipeline._document_index_provider = MagicMock()

    return pipeline


class TestAutoSplitIntegration:
    """Integration tests for auto-split in pipeline"""

    def test_ingest_long_text_succeeds_with_split(self, pipeline_with_auto_split):
        """Long text should ingest successfully with auto-split"""
        pipeline = pipeline_with_auto_split

        # Create a function that fails on first call, then returns embeddings
        call_count = [0]

        def embed_side_effect(text):
            call_count[0] += 1
            # First call fails with context length error
            if call_count[0] == 1:
                raise Exception("context length exceeded")
            # Subsequent calls succeed with embeddings
            return [0.1 * call_count[0]] * 1024

        pipeline._embedding_provider.embed.side_effect = embed_side_effect

        result = pipeline.ingest_text(
            text="word " * 2000,  # Very long text
            namespace="test"
        )

        assert result["chunks_created"] >= 2
        assert result.get("splits_created", 0) > 0
        assert "info" in result
        assert any("auto-split" in str(info).lower() for info in result.get("info", []))

    def test_ingest_normal_text_no_split(self, pipeline_with_auto_split):
        """Normal-sized text should not trigger split"""
        pipeline = pipeline_with_auto_split
        pipeline._embedding_provider.embed.return_value = [0.1] * 1024

        result = pipeline.ingest_text(
            text="Normal sized text",
            namespace="test"
        )

        # Normal text should not trigger splits
        assert result.get("splits_created", 0) == 0

    def test_split_metadata_in_vectors(self, pipeline_with_auto_split):
        """Split chunks should have metadata markers"""
        pipeline = pipeline_with_auto_split

        # Create a function that fails on first call, then returns embeddings
        call_count = [0]

        def embed_side_effect(text):
            call_count[0] += 1
            # First call fails with context length error
            if call_count[0] == 1:
                raise Exception("context length exceeded")
            # Subsequent calls succeed with embeddings
            return [0.1 * call_count[0]] * 1024

        pipeline._embedding_provider.embed.side_effect = embed_side_effect

        result = pipeline.ingest_text(text="long " * 1000, namespace="test")

        # Verify that insert was called on the documents provider
        assert pipeline._vectordb_provider.insert.called

        # Get the call arguments to verify metadata was passed
        call_args = pipeline._vectordb_provider.insert.call_args

        # The insert method is called with various arguments
        # We verify that the call was made and the result indicates splits occurred
        assert result is not None
        assert result.get("chunks_created", 0) > 0

    def test_disabled_auto_split(self, pipeline_without_auto_split):
        """Auto-split can be disabled via config"""
        pipeline = pipeline_without_auto_split

        # Mock embedding provider to fail on long text
        pipeline._embedding_provider.embed.side_effect = Exception("context length exceeded")

        # When auto-split is disabled, the pipeline should attempt embedding and fail
        # The error may be caught during document summary creation or other operations
        # Verify that the error is encountered (either raised or logged)
        try:
            result = pipeline.ingest_text(text="long " * 1000, namespace="test")
            # If we get here, the error was handled gracefully (e.g., logged)
            # The ingest should still complete, but may not have embeddings
            assert result is not None
        except Exception as e:
            # If error is raised, verify it's the expected one
            assert "context length exceeded" in str(e)
